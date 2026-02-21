"""
Tool Intelligence - Reflection Loop (Phase 4)

Autonomous problem-solving: wenn Round 1 Fehler hat,
analysiert dieser Loop was schiefging und versucht es
mit alternativen Tools / Ansätzen (max 1 extra Runde).

Loop-Schutz (3-fach):
  1. Max 1 Reflection-Runde pro Request
  2. Error-Fingerprint: gleicher Fehler in Runde 2 → Abbruch
  3. Seen-Tools: gleiche Tool+Args nie zweimal
"""

import re
import json
import hashlib
from typing import Dict, Any, List, Optional
from utils.logger import log_info, log_warn


# ──────────────────────────────────────────────────────────────
# ALTERNATIVE-TOOL RULES
# Wenn Tool X mit Fehler Y scheitert → versuche Z
# ──────────────────────────────────────────────────────────────
ALTERNATIVE_RULES: List[Dict] = [
    {
        "failed_tool": "home_read",
        "error_pattern": "Is a directory",
        "alternatives": [{"tool": "home_list", "args_from": "same_path"}],
        "reason": "Pfad ist ein Verzeichnis → Listing statt Lesen",
    },
    {
        "failed_tool": "home_read",
        "error_pattern": "No such file or directory",
        "alternatives": [{"tool": "home_list", "args_from": "parent_path"}],
        "reason": "Datei nicht gefunden → Verzeichnis listen",
    },
    {
        "failed_tool": "create_skill",
        "error_pattern": "required",
        "alternatives": [{"tool": "validate_skill_code", "args_from": "code_only"}],
        "reason": "Skill-Parameter unvollständig → erst validieren",
    },
    {
        "failed_tool": "exec_in_container",
        "error_pattern": "",
        "alternatives": [{"tool": "container_stats", "args_from": "container_id"}],
        "reason": "Container-Ausführung fehlgeschlagen → Status prüfen",
    },
    {
        "failed_tool": "memory_search",
        "error_pattern": "",
        "alternatives": [{"tool": "memory_graph_search", "args_from": "same_query"}],
        "reason": "Normale Suche leer → Graph-Suche versuchen",
    },
]


def _fingerprint(tool_name: str, error_msg: str) -> str:
    """Kompakter Fingerprint aus Tool + Fehler-Kern."""
    key = f"{tool_name}::{error_msg[:80]}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


def _extract_errors_from_context(tool_context: str) -> List[Dict]:
    """Extrahiert fehlgeschlagene Tools + Fehlermeldungen aus tool_context."""
    errors = []
    pattern = re.compile(
        r"### TOOL-FEHLER \(([^)]+)\):\n(.*?)(?=\n###|\Z)", re.DOTALL
    )
    for match in pattern.finditer(tool_context):
        tool_name = match.group(1).strip()
        error_msg = match.group(2).strip()[:200]
        errors.append({"tool": tool_name, "error": error_msg})
    return errors


def _build_alternative_args(rule: Dict, original_args: Dict, user_text: str) -> Dict:
    """Baut Args für das Alternative-Tool basierend auf der Regel."""
    strategy = rule["alternatives"][0].get("args_from", "")

    if strategy == "same_path":
        return {"path": original_args.get("path", ".")}
    elif strategy == "parent_path":
        path = original_args.get("path", ".")
        parts = path.rsplit("/", 1)
        return {"path": parts[0] if len(parts) > 1 else "."}
    elif strategy == "code_only":
        return {"code": original_args.get("code", "")}
    elif strategy == "container_id":
        return {"container_id": original_args.get("container_id", "")}
    elif strategy == "same_query":
        return {"query": original_args.get("query", user_text[:100])}
    return {}


class ReflectionLoop:
    """
    Analysiert Fehler aus Runde 1 und plant eine Retry-Runde.

    Sicherheits-Mechanismen:
      - max 1 Aktivierung pro Request (_used Flag)
      - Error-Fingerprints verhindern Schleifen
      - Seen-Tools verhindern identische Wiederholungen
    """

    def __init__(self):
        self._seen_fingerprints: set = set()
        self._seen_tool_calls: set = set()
        self._used: bool = False

    def register_round1_tool(self, tool_name: str, tool_args: Dict):
        """Registriert einen Round-1-Aufruf als 'bereits gesehen'."""
        key = f"{tool_name}::{json.dumps(tool_args, sort_keys=True, default=str)}"
        self._seen_tool_calls.add(hashlib.md5(key.encode()).hexdigest()[:8])

    def plan_retry(
        self,
        tool_context: str,
        user_text: str,
        round1_tool_args: Dict[str, Dict],
    ) -> List[Dict[str, Any]]:
        """
        Plant Retry-Aufrufe basierend auf Fehlern in tool_context.

        Returns:
            Liste von {"tool": str, "args": dict, "reason": str, "original_error": str}
            Leere Liste = nichts zu tun / Loop-Schutz aktiv
        """
        if self._used:
            log_warn("[ReflectionLoop] Bereits aktiviert → überspringe (Loop-Schutz)")
            return []

        self._used = True

        errors = _extract_errors_from_context(tool_context)
        if not errors:
            log_info("[ReflectionLoop] Keine Fehler → keine Retry-Runde nötig")
            return []

        log_info(f"[ReflectionLoop] {len(errors)} Fehler → suche Alternativen")

        plan: List[Dict] = []
        for err in errors:
            failed_tool = err["tool"]
            error_msg = err["error"]
            fp = _fingerprint(failed_tool, error_msg)

            # Loop-Schutz 2: gleicher Fehler-Fingerprint schon gesehen?
            if fp in self._seen_fingerprints:
                log_warn(f"[ReflectionLoop] Fingerprint {fp} bereits gesehen → überspringe")
                continue
            self._seen_fingerprints.add(fp)

            rule = self._find_rule(failed_tool, error_msg)
            if not rule:
                log_info(f"[ReflectionLoop] Keine Regel für '{failed_tool}' → überspringe")
                continue

            orig_args = round1_tool_args.get(failed_tool, {})
            alt_tool = rule["alternatives"][0]["tool"]
            alt_args = _build_alternative_args(rule, orig_args, user_text)

            # Loop-Schutz 3: gleiche Tool+Args schon versucht?
            call_key = f"{alt_tool}::{json.dumps(alt_args, sort_keys=True, default=str)}"
            call_fp = hashlib.md5(call_key.encode()).hexdigest()[:8]
            if call_fp in self._seen_tool_calls:
                log_warn(f"[ReflectionLoop] {alt_tool}({alt_args}) bereits versucht → überspringe")
                continue

            plan.append({
                "tool": alt_tool,
                "args": alt_args,
                "reason": rule["reason"],
                "original_error": f"{failed_tool}: {error_msg[:80]}",
            })
            log_info(f"[ReflectionLoop] {failed_tool} → {alt_tool}({alt_args}) | {rule['reason']}")

        return plan

    def _find_rule(self, tool_name: str, error_msg: str) -> Optional[Dict]:
        """Findet die erste passende Regel für Tool + Fehlermuster."""
        for rule in ALTERNATIVE_RULES:
            if rule["failed_tool"] != tool_name:
                continue
            pattern = rule.get("error_pattern", "")
            if not pattern or pattern.lower() in error_msg.lower():
                return rule
        return None
