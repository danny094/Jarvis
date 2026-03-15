"""
Lightweight query preclassification for autonomy budgeting.

Purpose:
- classify request type early (factual / analytical / conversational / action)
- provide response/tool budget hints before expensive planning/tool execution
- optionally refine low-confidence lexical results with embeddings
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from config import (
    OLLAMA_BASE,
    get_embedding_model,
    get_query_budget_embedding_enable,
)
from utils.logger import log_debug
from utils.role_endpoint_resolver import resolve_role_endpoint


class QueryBudgetHybridClassifier:
    _QUERY_TYPES = ("factual", "analytical", "conversational", "action")

    _QUERY_PROTOTYPES = {
        "factual": "Was habe ich dir gerade gemerkt? Antworte kurz.",
        "analytical": "Analysiere die Pipeline in mehreren Schritten und begründe die Ursachen.",
        "conversational": "Hey wie geht es dir heute?",
        "action": "Starte einen Container und führe den Befehl aus.",
    }

    _FACTUAL_TOKENS = {
        "gemerkt",
        "gemerke",
        "erinnere",
        "erinnerst",
        "recall",
        "remember",
        "fakt",
        "status",
        "letzte",
        "zuletzt",
        "was habe ich",
        "was weisst du",
        "was weißt du",
    }
    _ANALYTICAL_TOKENS = {
        "analysiere",
        "analyse",
        "ursache",
        "pipeline",
        "warum",
        "vergleich",
        "tradeoff",
        "bottleneck",
        "engpass",
        "optimieren",
        "strategie",
    }
    _CONVERSATIONAL_TOKENS = {
        "hi",
        "hey",
        "hallo",
        "wie geht",
        "wie fuehl",
        "wie fühl",
        "gefuehl",
        "gefühl",
        "gefuehle",
        "gefühle",
        "glaubst",
        "meinst",
        "ich finde",
        "smalltalk",
        "danke",
        "cool",
        "super",
        "nice",
    }
    _ACTION_TOKENS = {
        "starte",
        "start",
        "run",
        "führe",
        "fuehre",
        "execute",
        "erstelle",
        "create",
        "build",
        "deploy",
        "container",
        "skill",
        "tool",
    }
    _EXPLICIT_DEEP_MARKERS = (
        "/deep",
        "deep analysis",
        "schritt für schritt",
        "schritt fuer schritt",
        "detailliert",
        "ausführlich",
        "ausfuehrlich",
    )
    _TOOL_TAG_RE = re.compile(
        r"\{(?:tool|domain)\s*[:=]\s*(cronjob|skill|container|mcp_call)\s*\}",
        re.IGNORECASE,
    )
    _TOOL_TAG_SHORT_RE = re.compile(
        r"\{(cronjob|skill|container|mcp_call)\}",
        re.IGNORECASE,
    )

    def __init__(self):
        self._prototype_cache: Dict[str, List[float]] = {}
        self._prototype_cache_ts = 0.0
        self._prototype_lock = asyncio.Lock()
        self._prototype_cache_ttl_s = 6 * 60 * 60
        self._embed_timeout_s = 1.8

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-zA-Z0-9äöüÄÖÜß_:-]+", (text or "").lower())

    @staticmethod
    def _contains_any_phrase(text: str, phrases: List[str]) -> bool:
        lower = (text or "").lower()
        return any(p in lower for p in phrases)

    @staticmethod
    def _has_recall_signal(text: str) -> bool:
        lower = str(text or "").lower()
        return any(
            phrase in lower
            for phrase in (
                "was habe ich",
                "was weißt du",
                "was weisst du",
                "weisst du noch",
                "weißt du noch",
                "remember",
                "recall",
                "erinner",
                "gemerkt",
            )
        )

    @staticmethod
    def _has_conversational_meta_signal(text: str) -> bool:
        lower = str(text or "").lower()
        return any(
            phrase in lower
            for phrase in (
                "wie geht es dir",
                "wie geht's",
                "wie gehts",
                "wie fühl",
                "wie fuehl",
                "gefühl",
                "gefuehl",
                "gefühle",
                "gefuehle",
                "glaubst du",
                "meinst du",
                "ich finde",
            )
        )

    @classmethod
    def _allow_embedding_override(
        cls,
        *,
        text: str,
        lexical_type: str,
        refined_type: str,
    ) -> bool:
        if lexical_type == refined_type:
            return True
        if lexical_type == "conversational" and refined_type == "factual":
            # Keep smalltalk/meta-feelings prompts stable even if embedding drifts.
            if cls._has_conversational_meta_signal(text) and not cls._has_recall_signal(text):
                return False
        if lexical_type == "action" and refined_type == "factual":
            # Keep explicit cron operation/create requests stable against embedding drift.
            if cls._has_cron_context(text) and (
                cls._has_cron_operation_verb(text)
                or cls._has_cron_create_verb(text)
                or cls._has_cron_schedule_signal(text)
            ):
                return False
        return True

    @staticmethod
    def _has_cron_context(text: str) -> bool:
        lower = str(text or "").lower()
        return any(tok in lower for tok in ("cron", "cronjob", "schedule", "zeitplan"))

    @staticmethod
    def _has_container_context(text: str) -> bool:
        lower = str(text or "").lower()
        return any(
            tok in lower
            for tok in (
                "container",
                "container manager",
                "blueprint",
                "docker",
                "port",
                "ports",
                "volume",
                "sunshine",
                "steam-headless",
            )
        )

    @staticmethod
    def _has_container_operation_verb(text: str) -> bool:
        lower = str(text or "").lower()
        return any(
            tok in lower
            for tok in (
                "start",
                "starte",
                "deploy",
                "stop",
                "stoppe",
                "logs",
                "log",
                "status",
                "stats",
                "liste",
                "list",
                "exec",
                "ausführen",
                "ausfuehren",
                "befehl",
                "run command",
            )
        )

    @staticmethod
    def _has_host_runtime_lookup_intent(text: str) -> bool:
        lower = str(text or "").lower()
        if not lower:
            return False
        has_target = any(
            tok in lower
            for tok in (
                "host server",
                "host-server",
                "server",
                "host",
                "ip adresse",
                "ip-adresse",
                "ip address",
            )
        )
        if not has_target:
            return False
        return any(
            tok in lower
            for tok in (
                "find",
                "finden",
                "ermittel",
                "heraus",
                "auslesen",
                "check",
                "prüf",
                "pruef",
                "zeige",
                "gib",
            )
        )

    @staticmethod
    def _has_cron_create_verb(text: str) -> bool:
        lower = str(text or "").lower()
        return any(tok in lower for tok in ("erstell", "anleg", "create", "schedule", "einricht"))

    @staticmethod
    def _has_cron_operation_verb(text: str) -> bool:
        lower = str(text or "").lower()
        return any(
            tok in lower
            for tok in (
                "jetzt ausführen",
                "jetzt ausfuehren",
                "run now",
                "sofort ausführen",
                "sofort ausfuehren",
                "pausier",
                "pause",
                "fortsetz",
                "resume",
                "weiterführ",
                "weiterfuehr",
                "lösch",
                "loesch",
                "delete",
                "entfern",
                "remove",
                "liste",
                "list",
                "warteschlange",
                "queue",
                "ändere",
                "aendere",
                "update",
                "validier",
                "validate",
                "status",
            )
        )

    @staticmethod
    def _has_cron_schedule_signal(text: str) -> bool:
        lower = str(text or "").lower()
        if any(tok in lower for tok in ("einmalig", "one-time", "one time", "once", "jede ", "alle ")):
            return True
        if re.search(r"(?:in|nach)\s+(\d{1,4}|ein|einer|einem|one)\s*(?:sek|min|minute|minuten|h|std|stunde|stunden)\b", lower):
            return True
        if re.search(r"\b[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\b", lower):
            return True
        return False

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
    def _signal_from_tool_tag(tag: str, text: str) -> Dict[str, Any]:
        label = str(tag or "").strip().upper()
        lower = str(text or "").lower()
        if label == "CRONJOB":
            tool_hint = (
                "autonomy_cron_create_job"
                if any(k in lower for k in ("erstelle", "create", "anlege", "schedule", "einrichten"))
                else "autonomy_cron_status"
            )
            return {
                "query_type": "action",
                "intent_hint": "cron_action",
                "complexity_signal": "medium",
                "response_budget": "medium",
                "tool_hint": tool_hint,
                "skip_thinking_candidate": False,
                "confidence": 0.99,
                "source": "tool_tag",
                "embedding_similarity": 0.0,
                "tool_tag": label,
            }
        if label == "SKILL":
            return {
                "query_type": "action",
                "intent_hint": "skill_action",
                "complexity_signal": "medium",
                "response_budget": "medium",
                "tool_hint": "run_skill",
                "skip_thinking_candidate": False,
                "confidence": 0.99,
                "source": "tool_tag",
                "embedding_similarity": 0.0,
                "tool_tag": label,
            }
        if label == "CONTAINER":
            return {
                "query_type": "action",
                "intent_hint": "container_action",
                "complexity_signal": "medium",
                "response_budget": "medium",
                "tool_hint": "request_container",
                "skip_thinking_candidate": False,
                "confidence": 0.99,
                "source": "tool_tag",
                "embedding_similarity": 0.0,
                "tool_tag": label,
            }
        if label == "MCP_CALL":
            return {
                "query_type": "action",
                "intent_hint": "mcp_call",
                "complexity_signal": "medium",
                "response_budget": "medium",
                "tool_hint": "",
                "skip_thinking_candidate": False,
                "confidence": 0.99,
                "source": "tool_tag",
                "embedding_similarity": 0.0,
                "tool_tag": label,
            }
        return {}

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for x, y in zip(a, b):
            dot += x * y
            norm_a += x * x
            norm_b += y * y
        if norm_a <= 0.0 or norm_b <= 0.0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    async def _embed_text(self, text: str) -> Optional[List[float]]:
        route = resolve_role_endpoint("embedding", default_endpoint=OLLAMA_BASE)
        if route.get("hard_error"):
            return None
        endpoint = route.get("endpoint") or OLLAMA_BASE
        payload = {
            "model": get_embedding_model(),
            "prompt": text,
        }
        try:
            async with httpx.AsyncClient(timeout=self._embed_timeout_s) as client:
                resp = await client.post(f"{endpoint}/api/embeddings", json=payload)
                resp.raise_for_status()
                data = resp.json()
            vec = data.get("embedding")
            if isinstance(vec, list) and vec:
                return [float(v) for v in vec]
        except Exception as e:
            log_debug(f"[QueryBudget] Embedding unavailable: {type(e).__name__}: {e}")
        return None

    async def _ensure_prototype_vectors(self) -> bool:
        now = time.time()
        if self._prototype_cache and (now - self._prototype_cache_ts) < self._prototype_cache_ttl_s:
            return True
        async with self._prototype_lock:
            now = time.time()
            if self._prototype_cache and (now - self._prototype_cache_ts) < self._prototype_cache_ttl_s:
                return True
            cache: Dict[str, List[float]] = {}
            for key, text in self._QUERY_PROTOTYPES.items():
                vec = await self._embed_text(text)
                if vec:
                    cache[key] = vec
            if not cache:
                return False
            self._prototype_cache = cache
            self._prototype_cache_ts = now
            return True

    def _lexical_classify(
        self,
        user_text: str,
        selected_tools: Optional[List[Any]] = None,
        tone_signal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = (user_text or "").strip()
        lower = text.lower()
        tokens = self._tokenize(text)
        token_set = set(tokens)

        tool_names: List[str] = []
        for item in selected_tools or []:
            if isinstance(item, dict):
                name = str(item.get("tool") or item.get("name") or "").strip().lower()
            else:
                name = str(item or "").strip().lower()
            if name:
                tool_names.append(name)

        def _hits(vocab: set) -> int:
            total = len(token_set.intersection(vocab))
            for phrase in vocab:
                if " " in phrase and phrase in lower:
                    total += 1
            return total

        factual_hits = _hits(self._FACTUAL_TOKENS)
        analytical_hits = _hits(self._ANALYTICAL_TOKENS)
        conversational_hits = _hits(self._CONVERSATIONAL_TOKENS)
        action_hits = _hits(self._ACTION_TOKENS)

        recall_like = factual_hits > 0 or any(
            phrase in lower
            for phrase in (
                "was habe ich",
                "was weißt du",
                "was weisst du",
                "weisst du noch",
                "weißt du noch",
                "remember",
                "recall",
                "erinner",
                "gemerkt",
            )
        )

        if any(name in {"memory_graph_search", "memory_search"} for name in tool_names):
            factual_hits += 2 if recall_like else 0.35
        if any(name in {"analyze", "think"} for name in tool_names):
            analytical_hits += 2
        if any(name in {"run_skill", "request_container", "exec_in_container"} for name in tool_names):
            action_hits += 2

        tone_act = str((tone_signal or {}).get("dialogue_act") or "").strip().lower()
        if tone_act == "smalltalk":
            conversational_hits += 2
        elif tone_act == "analysis":
            analytical_hits += 1
        elif tone_act in {"ack", "feedback"}:
            conversational_hits += 1

        scores = {
            "factual": 0.25 + 0.70 * factual_hits,
            "analytical": 0.20 + 0.75 * analytical_hits,
            "conversational": 0.20 + 0.70 * conversational_hits,
            "action": 0.20 + 0.72 * action_hits,
        }

        if "?" in text and factual_hits > 0:
            scores["factual"] += 0.25
        if "?" in text and analytical_hits > 0:
            scores["analytical"] += 0.15
        if len(text) <= 80 and conversational_hits > 0:
            scores["conversational"] += 0.2
        if any(w in lower for w in ("schritt", "step", "5 punkten", "detailliert")):
            scores["analytical"] += 0.35
        if any(w in lower for w in ("bitte", "mach", "starte")) and action_hits > 0:
            scores["action"] += 0.22

        host_runtime_lookup = self._has_host_runtime_lookup_intent(lower)
        if host_runtime_lookup:
            # Host/IP runtime lookups are execution/tooling requests, not memory fact recall.
            scores["action"] += 1.20
        if ("nutze" in lower or "benutze" in lower or "use" in lower) and "tool" in lower:
            scores["action"] += 0.45

        has_explicit_action_verb = any(
            tok in lower
            for tok in (
                "erstell",
                "create",
                "starte",
                "start ",
                " run ",
                "führe",
                "fuehre",
                "execute",
                "deploy",
                "pausier",
                "fortsetz",
                "weiterführ",
                "weiterfuehr",
                "lösch",
                "loesch",
                "delete",
                "list",
                "liste",
                "status",
                "update",
                "validier",
                "validate",
                "stop ",
                "stoppe",
            )
        )
        definition_like = bool(re.search(r"\bwas\s+ist\b", lower)) or "erklär mir" in lower or "erklaer mir" in lower
        capability_like = lower.startswith("kannst du") or lower.startswith("can you")
        if (definition_like or capability_like) and not has_explicit_action_verb and not host_runtime_lookup:
            scores["factual"] += 0.95
            scores["action"] = max(0.0, scores["action"] - 0.55)

        cron_context = self._has_cron_context(lower)
        container_context = self._has_container_context(lower)
        container_operation_verb = self._has_container_operation_verb(lower)
        cron_create_verb = self._has_cron_create_verb(lower)
        cron_operation_verb = self._has_cron_operation_verb(lower)
        cron_schedule_signal = self._has_cron_schedule_signal(lower)
        if cron_context and cron_create_verb and cron_schedule_signal:
            # Untagged cron-create prompts with schedule hints should route to action.
            scores["action"] += 1.15
        elif cron_context and cron_operation_verb:
            # Cron operation requests (pause/resume/delete/list/update/validate/run_now) are actions.
            scores["action"] += 1.15
        elif cron_context and cron_create_verb:
            scores["action"] += 0.35
        if container_context and container_operation_verb:
            scores["action"] += 1.05

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_label = ranked[0][0]
        best_score = float(ranked[0][1])
        second_score = float(ranked[1][1]) if len(ranked) > 1 else 0.0
        spread = max(0.0, best_score - second_score)
        confidence = min(0.97, 0.52 + min(0.35, spread * 0.18) + min(0.10, best_score * 0.04))

        return {
            "query_type": best_label,
            "confidence": round(confidence, 3),
            "scores": scores,
            "source": "lexical",
        }

    async def _embedding_refine(self, text: str) -> Optional[Dict[str, Any]]:
        if not get_query_budget_embedding_enable():
            return None
        ok = await self._ensure_prototype_vectors()
        if not ok:
            return None
        text_vec = await self._embed_text(text)
        if not text_vec:
            return None

        sims: Dict[str, float] = {}
        for key in self._QUERY_TYPES:
            proto = self._prototype_cache.get(key)
            if not proto:
                continue
            sims[key] = self._cosine_similarity(text_vec, proto)
        if not sims:
            return None
        best = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)[0]
        return {
            "query_type": best[0],
            "similarity": float(best[1]),
            "scores": sims,
        }

    @staticmethod
    def _derive_intent(query_type: str, text: str) -> str:
        lower = (text or "").lower()
        if query_type == "factual":
            if any(k in lower for k in ("gemerkt", "erinner", "recall", "remember")):
                return "recall"
            return "fact_lookup"
        if query_type == "analytical":
            return "deep_analysis"
        if query_type == "conversational":
            return "small_talk"
        if "container" in lower:
            return "container_action"
        if "skill" in lower:
            return "skill_action"
        return "action_request"

    @staticmethod
    def _derive_tool_hint(intent_hint: str) -> str:
        mapping = {
            "recall": "memory_graph_search",
            "fact_lookup": "memory_search",
            "deep_analysis": "analyze",
            "container_action": "request_container",
            "skill_action": "run_skill",
        }
        return mapping.get(intent_hint, "")

    @staticmethod
    def _derive_complexity(query_type: str, text: str) -> str:
        lower = (text or "").lower()
        if query_type == "analytical":
            if any(k in lower for k in ("mehrere", "mehrschritt", "5 punkten", "tradeoff", "ursache")):
                return "high"
            return "medium"
        if query_type == "action":
            return "medium" if any(k in lower for k in ("pipeline", "orchestr", "mehrere")) else "low"
        if len(lower) <= 120:
            return "low"
        return "medium"

    @staticmethod
    def _derive_response_budget(query_type: str, complexity: str, text: str) -> str:
        lower = (text or "").lower()
        if query_type in {"conversational"}:
            return "short"
        if query_type == "factual":
            return "short" if complexity == "low" else "medium"
        if query_type == "analytical":
            if complexity == "high" and any(m in lower for m in QueryBudgetHybridClassifier._EXPLICIT_DEEP_MARKERS):
                return "long"
            return "medium"
        return "medium"

    # Keywords that signal container/env/tool intent even without a hyphenated ID.
    # "starte einen Ubuntu Container" has no hyphen but must not skip ThinkingLayer.
    _CONTAINER_ENV_MARKERS = frozenset({
        "ubuntu", "debian", "alpine", "python", "node", "nodejs", "java", "golang",
        "linux", "container", "blueprint", "image", "umgebung", "environment", "env",
        "setup", "einrichten", "aufsetzen", "installier", "install",
        "starte", "start", "deploy", "run", "erstelle", "create", "build",
    })

    @staticmethod
    def _derive_skip_thinking_candidate(
        query_type: str,
        complexity: str,
        text: str,
    ) -> bool:
        import re as _re
        lower = (text or "").lower()
        if any(m in lower for m in QueryBudgetHybridClassifier._EXPLICIT_DEEP_MARKERS):
            return False
        # Action tokens already defined on the class cover most intent signals.
        if any(t in lower for t in QueryBudgetHybridClassifier._ACTION_TOKENS):
            return False
        # Container/environment keywords without a hyphenated ID (e.g. "starte Ubuntu Container").
        if any(m in lower for m in QueryBudgetHybridClassifier._CONTAINER_ENV_MARKERS):
            return False
        # Blueprint/skill IDs are hyphenated multi-word identifiers (e.g. "gaming-station",
        # "trion-home", "my-python-skill"). A query mentioning one likely needs ThinkingLayer
        # for blueprint routing or skill lookup — never safe to lobotomize.
        if _re.search(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", lower):
            return False
        return query_type in {"factual", "conversational"} and complexity == "low"

    async def classify(
        self,
        user_text: str,
        *,
        selected_tools: Optional[List[Any]] = None,
        tone_signal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = str(user_text or "").strip()
        if not text:
            return {
                "query_type": "conversational",
                "intent_hint": "small_talk",
                "complexity_signal": "low",
                "response_budget": "short",
                "tool_hint": "",
                "skip_thinking_candidate": True,
                "confidence": 0.5,
                "source": "fallback",
            }

        tag = self._extract_tool_domain_tag(text)
        if tag:
            tagged = self._signal_from_tool_tag(tag, text)
            if tagged:
                return tagged

        lexical = self._lexical_classify(
            text,
            selected_tools=selected_tools,
            tone_signal=tone_signal,
        )
        final_query_type = str(lexical.get("query_type") or "factual")
        confidence = float(lexical.get("confidence", 0.55) or 0.55)
        source = "lexical"
        embedding_sim = 0.0

        if confidence < 0.78:
            refined = await self._embedding_refine(text)
            if refined:
                refined_type = str(refined.get("query_type") or final_query_type)
                embedding_sim = float(refined.get("similarity", 0.0) or 0.0)
                if embedding_sim >= 0.34:
                    if self._allow_embedding_override(
                        text=text,
                        lexical_type=final_query_type,
                        refined_type=refined_type,
                    ):
                        final_query_type = refined_type
                        confidence = max(confidence, min(0.92, 0.58 + embedding_sim))
                        source = "embedding_hybrid"

        intent_hint = self._derive_intent(final_query_type, text)
        complexity = self._derive_complexity(final_query_type, text)
        response_budget = self._derive_response_budget(final_query_type, complexity, text)
        tool_hint = self._derive_tool_hint(intent_hint)
        skip_thinking_candidate = self._derive_skip_thinking_candidate(
            final_query_type, complexity, text
        )

        return {
            "query_type": final_query_type,
            "intent_hint": intent_hint,
            "complexity_signal": complexity,
            "response_budget": response_budget,
            "tool_hint": tool_hint,
            "skip_thinking_candidate": bool(skip_thinking_candidate),
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "source": source,
            "embedding_similarity": round(embedding_sim, 4),
        }
