"""
Deterministic domain router for CRONJOB vs SKILL vs CONTAINER vs GENERIC.

Design goals:
- no LLM prompt dependency
- hard lexical rules first
- optional embedding refinement for ambiguous turns
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import (
    OLLAMA_BASE,
    get_domain_router_embedding_enable,
    get_domain_router_lock_min_confidence,
    get_embedding_model,
)
from utils.logger import log_debug
from utils.role_endpoint_resolver import resolve_role_endpoint


class DomainRouterHybridClassifier:
    _PROTOTYPES = {
        "cronjob": "Erstelle einen Cronjob der mich jede Stunde erinnert und den Jobstatus prüft.",
        "skill": "Erstelle einen neuen Skill, schreibe Code und führe den Skill aus.",
        "container": "Starte einen Container aus einem Blueprint und gib mir IP und Port.",
        "generic": "Beantworte eine normale Frage ohne Tool-Aktion.",
    }

    _CRON_MARKERS = (
        "cron",
        "cronjob",
        "cronjobs",
        "schedule",
        "zeitplan",
        "zeitgesteuert",
        "erinner mich",
        "erinnere mich",
        "jede minute",
        "jede stunde",
        "taeglich",
        "täglich",
        "wöchentlich",
        "woechentlich",
    )
    _SKILL_MARKERS = (
        "skill",
        "skills",
        "create_skill",
        "run_skill",
        "autonomous_skill_task",
        "funktion bauen",
        "funktion erstellen",
        "code schreiben",
    )
    _CONTAINER_MARKERS = (
        "container",
        "container manager",
        "container commander",
        "blueprint",
        "deploy",
        "start container",
        "starte container",
        "stop container",
        "stoppe container",
        "docker",
        "image",
        "steam-headless",
        "sunshine",
        "gpu",
        "nvidia runtime",
        "mount",
        "volume",
        "port",
        "ports",
        "host server",
        "host-server",
        "ip adresse",
        "ip-adresse",
        "ip address",
    )

    _CRON_EXPR_RE = re.compile(r"(?<!\S)([\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+)(?!\S)")
    _HEX_ID_RE = re.compile(r"\b[a-f0-9]{12}\b", re.IGNORECASE)

    _ONE_SHOT_MARKERS = (
        "einmalig",
        "nur einmal",
        "einmal",
        "one-time",
        "one time",
        "once",
    )
    _RECURRING_MARKERS = (
        "jede",
        "taeglich",
        "täglich",
        "woechentlich",
        "wöchentlich",
        "monatlich",
        "jaehrlich",
        "jährlich",
        "stuendlich",
        "stündlich",
        "every day",
        "every week",
        "every month",
        "every hour",
        "every minute",
    )
    _CRON_CREATE_VERBS = (
        "erstelle",
        "erstell",
        "anlege",
        "anleg",
        "create",
        "setze auf",
        "schedule",
        "richte ein",
        "einrichten",
    )
    _CRON_META_PATTERNS = (
        "wie fühlst du",
        "wie fuehlst du",
        "wie geht es dir",
        "wie geht's",
        "wie gehts",
        "jetzt wo du",
        "nun da du",
        "was denkst du",
        "was hältst du",
        "was haeltst du",
    )
    _TOOL_TAG_RE = re.compile(
        r"\{(?:tool|domain)\s*[:=]\s*(cronjob|skill|container|mcp_call)\s*\}",
        re.IGNORECASE,
    )
    _TOOL_TAG_SHORT_RE = re.compile(
        r"\{(cronjob|skill|container|mcp_call)\}",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._embed_timeout_s = 1.5
        self._proto_cache: Dict[str, List[float]] = {}
        self._proto_ts = 0.0
        self._proto_ttl_s = 6 * 60 * 60

    @classmethod
    def _extract_tool_domain_tag(cls, text: str) -> str:
        raw = str(text or "")
        m = cls._TOOL_TAG_RE.search(raw)
        if not m:
            m = cls._TOOL_TAG_SHORT_RE.search(raw)
        if not m:
            return ""
        return str(m.group(1) or "").strip().upper()

    @staticmethod
    def _contains(text: str, phrase: str) -> bool:
        raw = str(text or "")
        token = str(phrase or "").strip()
        if not raw or not token:
            return False
        if " " in token or "-" in token or "/" in token:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
            return re.search(pattern, raw) is not None
        return re.search(rf"\b{re.escape(token)}\b", raw) is not None

    @staticmethod
    def _looks_like_math_query(text: str) -> bool:
        lower = str(text or "").lower()
        if not lower:
            return False
        if re.search(r"\b\d+\s*(?:[\+\-\*/]|x|×)\s*\d+\b", lower):
            return True
        return any(
            marker in lower
            for marker in (
                "rechne",
                "berechne",
                "calculate",
                "multipliziere",
                "addiere",
                "subtrahiere",
                "dividiere",
            )
        )

    @staticmethod
    def _looks_like_definition_query(text: str) -> bool:
        lower = str(text or "").lower()
        if not lower:
            return False
        return any(
            marker in lower
            for marker in (
                "was ist",
                "erklär mir",
                "erklaer mir",
                "erkläre mir",
                "explain",
                "erkläre kurz",
                "erklaere kurz",
            )
        )

    @staticmethod
    def _looks_like_creative_prompt(text: str) -> bool:
        lower = str(text or "").lower()
        if not lower:
            return False
        creative_markers = (
            "gedicht",
            "poem",
            "haiku",
            "reim",
            "song",
            "lied",
            "story",
            "geschichte",
            "kreativ",
            "schreibe mir ein gedicht",
            "schreib mir ein gedicht",
            "write me a poem",
            "write a poem",
        )
        return any(marker in lower for marker in creative_markers)

    @staticmethod
    def _cos(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na <= 0.0 or nb <= 0.0:
            return 0.0
        return dot / (math.sqrt(na) * math.sqrt(nb))

    async def _embed(self, text: str) -> Optional[List[float]]:
        route = resolve_role_endpoint("embedding", default_endpoint=OLLAMA_BASE)
        if route.get("hard_error"):
            return None
        endpoint = route.get("endpoint") or OLLAMA_BASE
        payload = {"model": get_embedding_model(), "prompt": text}
        try:
            async with httpx.AsyncClient(timeout=self._embed_timeout_s) as client:
                resp = await client.post(f"{endpoint}/api/embeddings", json=payload)
                resp.raise_for_status()
                data = resp.json()
            vec = data.get("embedding")
            if isinstance(vec, list) and vec:
                return [float(v) for v in vec]
        except Exception as exc:
            log_debug(f"[DomainRouter] embedding unavailable: {type(exc).__name__}: {exc}")
        return None

    async def _ensure_prototypes(self) -> bool:
        now = time.time()
        if self._proto_cache and (now - self._proto_ts) < self._proto_ttl_s:
            return True
        cache: Dict[str, List[float]] = {}
        for label, text in self._PROTOTYPES.items():
            vec = await self._embed(text)
            if vec:
                cache[label] = vec
        if not cache:
            return False
        self._proto_cache = cache
        self._proto_ts = now
        return True

    @classmethod
    def _extract_cron_expression(cls, lower: str) -> str:
        m = cls._CRON_EXPR_RE.search(lower or "")
        if not m:
            return ""
        return str(m.group(1) or "").strip()

    @classmethod
    def _infer_cron_expression(cls, lower: str) -> str:
        explicit = cls._extract_cron_expression(lower)
        if explicit:
            return explicit

        m = re.search(r"(?:jede|alle)\s+(\d{1,3})\s*(?:min|minuten|minute)\b", lower)
        if m:
            n = max(1, min(59, int(m.group(1))))
            return f"*/{n} * * * *"
        m = re.search(r"(?:in|nach)\s+(\d{1,3})\s*(?:min|minuten|minute)\b", lower)
        if m:
            n = max(1, min(59, int(m.group(1))))
            return f"*/{n} * * * *"
        m = re.search(r"(?:einmal|once)\s+in\s+(\d{1,3})\s*(?:min|minuten|minute)\b", lower)
        if m:
            n = max(1, min(59, int(m.group(1))))
            return f"*/{n} * * * *"

        if "jede minute" in lower or "jede min" in lower or "every minute" in lower:
            return "*/1 * * * *"
        if "jede stunde" in lower or "every hour" in lower:
            return "0 * * * *"

        m = re.search(r"(?:täglich|taeglich|daily)\s*(?:um|at)?\s*(\d{1,2})[:.](\d{2})", lower)
        if m:
            hour = max(0, min(23, int(m.group(1))))
            minute = max(0, min(59, int(m.group(2))))
            return f"{minute} {hour} * * *"

        return ""

    @classmethod
    def _infer_schedule_hint(cls, lower: str) -> Tuple[str, str]:
        text = str(lower or "")
        if not text:
            return "unknown", ""

        has_one_shot = any(marker in text for marker in cls._ONE_SHOT_MARKERS)
        has_recurring = any(marker in text for marker in cls._RECURRING_MARKERS)
        has_recurring = has_recurring or bool(
            re.search(r"(?:jede|alle)\s+\d{1,3}\s*(?:sek|sekunden|s|min|minuten|minute|h|std|stunden|stunde|tag|tage)\b", text)
        )
        has_explicit_cron = bool(cls._extract_cron_expression(text))
        if has_explicit_cron:
            has_recurring = True

        one_shot_at = cls._infer_one_shot_datetime_hint(text)
        if one_shot_at and not has_recurring:
            return "one_shot", one_shot_at
        if has_recurring and not has_one_shot:
            return "recurring", ""
        if has_one_shot and not has_recurring:
            return ("one_shot", one_shot_at) if one_shot_at else ("one_shot", "")
        if has_one_shot and has_recurring:
            # Conflicting hints -> keep deterministic recurring to avoid accidental one-shot loss.
            return "recurring", ""
        return "unknown", ""

    @classmethod
    def _infer_one_shot_datetime_hint(cls, lower: str) -> str:
        text = str(lower or "").strip()
        if not text:
            return ""
        now = datetime.now(timezone.utc)

        rel = re.search(
            r"(?:in|nach)\s+(\d{1,4}|einer|einem|ein|one)\s*"
            r"(sek|sekunde|sekunden|seconds?|s|min|minute|minuten|minutes?|h|std|stunde|stunden|hours?|tage?|days?)\b",
            text,
        )
        if rel:
            amount_raw = str(rel.group(1) or "").strip()
            if amount_raw in {"einer", "einem", "ein", "one"}:
                amount = 1
            else:
                amount = max(1, int(amount_raw))
            unit = str(rel.group(2) or "").strip().lower()
            if unit.startswith(("sek", "s")):
                delta = timedelta(seconds=amount)
            elif unit.startswith(("h", "std", "stun")):
                delta = timedelta(hours=amount)
            elif unit.startswith(("tag", "day")):
                delta = timedelta(days=amount)
            else:
                delta = timedelta(minutes=amount)
            run_at = now + delta
            # Scheduler works minute-granular; always round up to the next minute boundary.
            # This prevents near-past run_at values for phrases like "in 1 minute"
            # when pipeline latency consumes the remaining seconds in the current minute.
            run_at = (run_at + timedelta(minutes=1)).replace(second=0, microsecond=0)
            return run_at.isoformat().replace("+00:00", "Z")

        abs_today = re.search(r"(?:heute|today)\s*(?:um|at)?\s*(\d{1,2})[:.](\d{2})\b", text)
        if abs_today:
            hour = max(0, min(23, int(abs_today.group(1))))
            minute = max(0, min(59, int(abs_today.group(2))))
            run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_at <= now:
                run_at = run_at + timedelta(days=1)
            return run_at.isoformat().replace("+00:00", "Z")
        abs_today_hour = re.search(r"(?:heute|today)\s*(?:um|at)?\s*(\d{1,2})\s*uhr\b", text)
        if abs_today_hour:
            hour = max(0, min(23, int(abs_today_hour.group(1))))
            run_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if run_at <= now:
                run_at = run_at + timedelta(days=1)
            return run_at.isoformat().replace("+00:00", "Z")

        abs_tomorrow = re.search(r"(?:morgen|tomorrow)\s*(?:um|at)?\s*(\d{1,2})[:.](\d{2})\b", text)
        if abs_tomorrow:
            hour = max(0, min(23, int(abs_tomorrow.group(1))))
            minute = max(0, min(59, int(abs_tomorrow.group(2))))
            run_at = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return run_at.isoformat().replace("+00:00", "Z")
        abs_tomorrow_hour = re.search(r"(?:morgen|tomorrow)\s*(?:um|at)?\s*(\d{1,2})\s*uhr\b", text)
        if abs_tomorrow_hour:
            hour = max(0, min(23, int(abs_tomorrow_hour.group(1))))
            run_at = (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
            return run_at.isoformat().replace("+00:00", "Z")

        abs_date = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:um|at)?\s*(\d{1,2})[:.](\d{2})\b", text)
        if abs_date:
            try:
                day = datetime.fromisoformat(abs_date.group(1)).date()
                hour = max(0, min(23, int(abs_date.group(2))))
                minute = max(0, min(59, int(abs_date.group(3))))
                run_at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
                if run_at <= now:
                    return ""
                return run_at.isoformat().replace("+00:00", "Z")
            except Exception:
                return ""

        return ""

    @classmethod
    def _has_cron_schedule_signal(cls, lower: str) -> bool:
        text = str(lower or "")
        if not text:
            return False
        if cls._extract_cron_expression(text):
            return True
        mode, one_shot_at = cls._infer_schedule_hint(text)
        if mode in {"one_shot", "recurring"}:
            return True
        if one_shot_at:
            return True
        if re.search(
            r"(?:in|nach|um|at)\s+\d{1,4}\s*(?:sek|sekunden|s|min|minuten|minute|h|std|stunden|stunde)\b",
            text,
        ):
            return True
        if re.search(r"(?:heute|today|morgen|tomorrow)\s*(?:um|at)?\s*\d{1,2}(?:[:.]\d{2})?\s*uhr?\b", text):
            return True
        return False

    @classmethod
    def _is_meta_cron_query(cls, lower: str) -> bool:
        text = str(lower or "")
        if not text:
            return False
        if "cron" not in text and "cronjob" not in text and "zeitplan" not in text:
            return False
        if cls._has_cron_schedule_signal(text):
            return False

        if any(marker in text for marker in cls._CRON_META_PATTERNS):
            return True

        has_capability_phrase = (
            re.search(r"\b(kannst|koenntest|can you|can)\b", text) is not None
            and any(verb in text for verb in cls._CRON_CREATE_VERBS)
        )
        if has_capability_phrase:
            return True

        return False

    @classmethod
    def _is_cron_create_request(cls, lower: str) -> bool:
        text = str(lower or "")
        if not text:
            return False
        if cls._is_meta_cron_query(text):
            return False
        has_create_verb = any(verb in text for verb in cls._CRON_CREATE_VERBS)
        if not has_create_verb:
            return False
        return cls._has_cron_schedule_signal(text)

    @classmethod
    def _infer_cron_operation(cls, lower: str) -> str:
        if not lower:
            return "unknown"
        if cls._is_meta_cron_query(lower):
            return "status"
        # Intent verbs first: avoid false "status" routing when objective text contains
        # terms like "status summary" during a create request.
        if cls._is_cron_create_request(lower):
            return "create"
        if any(x in lower for x in ("run now", "jetzt ausführen", "jetzt starten", "sofort ausführen")):
            return "run_now"
        if any(x in lower for x in ("pause", "pausieren")):
            return "pause"
        if any(x in lower for x in ("resume", "fortsetzen", "weiterführen", "weiterfuehren")):
            return "resume"
        if any(x in lower for x in ("lösch", "loesch", "delete", "entfern", "remove")) and "cron" in lower:
            return "delete"
        if any(x in lower for x in ("liste", "list", "zeige jobs", "jobs anzeigen")) and "cron" in lower:
            return "list"
        if "queue" in lower or "warteschlange" in lower:
            return "queue"
        if "status" in lower:
            return "status"
        if any(x in lower for x in ("validier", "validate")) and "cron" in lower:
            return "validate"
        if any(x in lower for x in ("update", "ändere", "aendere", "edit")) and "cron" in lower:
            return "update"
        if cls._has_cron_schedule_signal(lower):
            return "create"
        if "cron" in lower:
            return "status"
        return "unknown"

    @classmethod
    def _infer_container_operation(cls, lower: str) -> str:
        if not lower:
            return "unknown"
        if any(x in lower for x in ("host server", "host-server", "ip adresse", "ip-adresse", "ip address")) and any(
            v in lower for v in ("find", "finden", "ermittel", "heraus", "auslesen", "zeige", "gib", "lookup", "check")
        ):
            return "exec"
        if any(x in lower for x in ("erstell", "create", "neues blueprint", "new blueprint", "blueprint anlegen")):
            if "blueprint" in lower or "image" in lower:
                return "create_blueprint"
        if any(x in lower for x in ("start", "starte", "deploy", "hochfahren", "launch")) and any(
            t in lower for t in ("container", "blueprint", "steam-headless", "sunshine")
        ):
            return "deploy"
        if any(x in lower for x in ("stop", "stoppe", "beende", "kill")) and "container" in lower:
            return "stop"
        if any(x in lower for x in ("logs", "log", "ausgabe")) and "container" in lower:
            return "logs"
        if any(x in lower for x in ("status", "stats", "auslastung", "health")) and "container" in lower:
            return "status"
        if any(x in lower for x in ("liste", "list", "zeig")) and any(t in lower for t in ("container", "blueprint", "ports")):
            return "list"
        if any(x in lower for x in ("exec", "ausführen", "ausfuehren", "run command", "befehl")) and "container" in lower:
            return "exec"
        return "unknown"

    @classmethod
    def _rule_scores(
        cls,
        user_text: str,
        selected_tools: Optional[List[Any]],
    ) -> Tuple[float, float, float, Dict[str, Any]]:
        lower = (user_text or "").lower()
        cron_score = 0.0
        skill_score = 0.0
        container_score = 0.0
        reasons: List[str] = []

        for marker in cls._CRON_MARKERS:
            if cls._contains(lower, marker):
                cron_score += 1.25
                reasons.append(f"cron:{marker}")
        if re.search(r"\bcronjobs?\b", lower) or "zeitplan" in lower or "schedule" in lower:
            cron_score += 1.0
            reasons.append("cron:context_word")

        for marker in cls._SKILL_MARKERS:
            if cls._contains(lower, marker):
                skill_score += 1.25
                reasons.append(f"skill:{marker}")
        for marker in cls._CONTAINER_MARKERS:
            if cls._contains(lower, marker):
                container_score += 1.1
                reasons.append(f"container:{marker}")

        cron_expr = cls._extract_cron_expression(lower)
        if cron_expr:
            cron_score += 2.5
            reasons.append("cron:expr")

        if re.search(r"(?:jede|alle)\s+\d{1,3}\s*(?:min|minuten|minute|h|stunden|stunde)\b", lower):
            cron_score += 1.8
            reasons.append("cron:interval")

        if re.search(r"\b(skill|skills)\b", lower):
            skill_score += 1.0
            reasons.append("skill:word")

        if any(w in lower for w in ("code", "python", "funktion", "script")) and "cron" not in lower:
            skill_score += 0.8
            reasons.append("skill:code_context")

        if any(w in lower for w in ("erinner", "remind")):
            cron_score += 1.0
            reasons.append("cron:reminder")
        if cls._has_cron_schedule_signal(lower):
            cron_score += 1.1
            reasons.append("cron:schedule_signal")
            if re.search(
                r"\b(erstell|create|sende|send|erinner|erinnerung|report|zusammenfassung|soll|prüf|pruef|überprüf|ueberpruef|gib)\b",
                lower,
            ):
                cron_score += 1.2
                reasons.append("cron:schedule_task_signal")
        if any(w in lower for w in ("container", "blueprint", "docker")):
            container_score += 0.8
            reasons.append("container:core_word")
        if any(w in lower for w in ("gpu", "nvidia", "sunshine", "steam-headless")):
            container_score += 1.0
            reasons.append("container:runtime_context")

        for item in selected_tools or []:
            if isinstance(item, dict):
                name = str(item.get("tool") or item.get("name") or "").strip().lower()
            else:
                name = str(item or "").strip().lower()
            if not name:
                continue
            if name.startswith("autonomy_cron_") or name == "cron_reference_links_list":
                cron_score += 1.5
                reasons.append(f"cron:selector:{name}")
            if name in {"create_skill", "run_skill", "autonomous_skill_task"}:
                skill_score += 1.5
                reasons.append(f"skill:selector:{name}")
            if name in {
                "request_container",
                "stop_container",
                "exec_in_container",
                "container_logs",
                "container_stats",
                "container_list",
                "container_inspect",
                "blueprint_list",
                "blueprint_get",
                "blueprint_create",
                "storage_scope_list",
                "storage_scope_upsert",
                "list_used_ports",
                "find_free_port",
                "check_port",
                "list_blueprint_ports",
            }:
                container_score += 1.5
                reasons.append(f"container:selector:{name}")

        return (
            cron_score,
            skill_score,
            container_score,
            {"reasons": reasons, "cron_expression_hint": cls._infer_cron_expression(lower)},
        )

    async def classify(
        self,
        user_text: str,
        *,
        selected_tools: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        lower = (user_text or "").lower()
        tagged_domain = self._extract_tool_domain_tag(lower)
        if tagged_domain:
            if tagged_domain == "CRONJOB":
                schedule_mode_hint, one_shot_at_hint = self._infer_schedule_hint(lower)
                return {
                    "domain_tag": "CRONJOB",
                    "domain_locked": True,
                    "confidence": 0.99,
                    "source": "tool_tag",
                    "operation": self._infer_cron_operation(lower),
                    "cron_expression_hint": self._infer_cron_expression(lower),
                    "schedule_mode_hint": schedule_mode_hint,
                    "one_shot_at_hint": one_shot_at_hint,
                    "cron_job_id_hint": "",
                    "rule_cron_score": 0.0,
                    "rule_skill_score": 0.0,
                    "rule_container_score": 0.0,
                    "reason": "tool_tag:cronjob",
                }
            if tagged_domain == "SKILL":
                return {
                    "domain_tag": "SKILL",
                    "domain_locked": True,
                    "confidence": 0.99,
                    "source": "tool_tag",
                    "operation": "unknown",
                    "cron_expression_hint": "",
                    "schedule_mode_hint": "unknown",
                    "one_shot_at_hint": "",
                    "cron_job_id_hint": "",
                    "rule_cron_score": 0.0,
                    "rule_skill_score": 0.0,
                    "rule_container_score": 0.0,
                    "reason": "tool_tag:skill",
                }
            if tagged_domain == "CONTAINER":
                return {
                    "domain_tag": "CONTAINER",
                    "domain_locked": True,
                    "confidence": 0.99,
                    "source": "tool_tag",
                    "operation": self._infer_container_operation(lower),
                    "cron_expression_hint": "",
                    "schedule_mode_hint": "unknown",
                    "one_shot_at_hint": "",
                    "cron_job_id_hint": "",
                    "rule_cron_score": 0.0,
                    "rule_skill_score": 0.0,
                    "rule_container_score": 0.0,
                    "reason": "tool_tag:container",
                }
            if tagged_domain == "MCP_CALL":
                return {
                    "domain_tag": "MCP_CALL",
                    "domain_locked": False,
                    "confidence": 0.99,
                    "source": "tool_tag",
                    "operation": "tool_call",
                    "cron_expression_hint": "",
                    "schedule_mode_hint": "unknown",
                    "one_shot_at_hint": "",
                    "cron_job_id_hint": "",
                    "rule_cron_score": 0.0,
                    "rule_skill_score": 0.0,
                    "rule_container_score": 0.0,
                    "reason": "tool_tag:mcp_call",
                }

        cron_score, skill_score, container_score, meta = self._rule_scores(user_text, selected_tools)

        domain = "generic"
        source = "rules"
        confidence = 0.55

        if cron_score >= 2.0 and cron_score >= (skill_score + 0.9) and cron_score >= (container_score + 0.9):
            domain = "cronjob"
            confidence = min(0.95, 0.70 + min(0.24, cron_score * 0.05))
        elif skill_score >= 2.0 and skill_score >= (cron_score + 0.9) and skill_score >= (container_score + 0.9):
            domain = "skill"
            confidence = min(0.95, 0.70 + min(0.24, skill_score * 0.05))
        elif container_score >= 2.0 and container_score >= (cron_score + 0.9) and container_score >= (skill_score + 0.9):
            domain = "container"
            confidence = min(0.95, 0.70 + min(0.24, container_score * 0.05))
        else:
            if self._looks_like_math_query(user_text):
                domain = "generic"
                source = "rules_math_guard"
                confidence = 0.9
            elif self._looks_like_definition_query(user_text) and not any(
                tok in lower
                for tok in ("cronjob", "cronjobs", "skill", "skills", "container", "docker", "blueprint")
            ):
                domain = "generic"
                source = "rules_definition_guard"
                confidence = 0.88
            elif self._looks_like_creative_prompt(user_text) and not any(
                tok in lower
                for tok in ("cronjob", "cronjobs", "skill", "skills", "container", "docker", "blueprint")
            ):
                domain = "generic"
                source = "rules_creative_guard"
                confidence = 0.88
            # ambiguous/low-signal path
            elif get_domain_router_embedding_enable() and await self._ensure_prototypes():
                text_vec = await self._embed(user_text)
                if text_vec:
                    sims: Dict[str, float] = {}
                    for label, vec in self._proto_cache.items():
                        sims[label] = self._cos(text_vec, vec)
                    ranked = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)
                    if ranked:
                        best_label, best_sim = ranked[0]
                        second = ranked[1][1] if len(ranked) > 1 else 0.0
                        margin = max(0.0, best_sim - second)
                        if best_label in {"cronjob", "skill", "container"} and best_sim >= 0.31 and margin >= 0.015:
                            domain = best_label
                            confidence = min(0.92, 0.60 + best_sim * 0.60 + margin * 0.45)
                            source = "embedding_hybrid"
                            meta["embedding_similarity"] = round(best_sim, 4)
                            meta["embedding_margin"] = round(margin, 4)

        lock_threshold = float(get_domain_router_lock_min_confidence())
        domain_tag = domain.upper()
        operation = "unknown"
        if domain == "cronjob":
            operation = self._infer_cron_operation(lower)
        elif domain == "container":
            operation = self._infer_container_operation(lower)
        cron_expr_hint = str(meta.get("cron_expression_hint") or "")
        schedule_mode_hint = "unknown"
        one_shot_at_hint = ""
        if domain == "cronjob":
            schedule_mode_hint, one_shot_at_hint = self._infer_schedule_hint(lower)
        cron_job_id_hint = ""
        if domain == "cronjob":
            m = self._HEX_ID_RE.search(lower)
            if m:
                cron_job_id_hint = str(m.group(0)).lower()

        return {
            "domain_tag": domain_tag,
            "domain_locked": bool(domain in {"cronjob", "skill", "container"} and confidence >= lock_threshold),
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "source": source,
            "operation": operation,
            "cron_expression_hint": cron_expr_hint,
            "schedule_mode_hint": schedule_mode_hint,
            "one_shot_at_hint": one_shot_at_hint,
            "cron_job_id_hint": cron_job_id_hint,
            "rule_cron_score": round(float(cron_score), 3),
            "rule_skill_score": round(float(skill_score), 3),
            "rule_container_score": round(float(container_score), 3),
            "reason": ", ".join(meta.get("reasons", [])[:8]),
        }
