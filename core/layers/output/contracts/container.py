"""
core.layers.output.contracts.container
========================================
Container-Query-Kontrakt.

Drei Query-Klassen mit je eigenen Prompt-Regeln und Postcheck-Invarianten:
  container_inventory        → Laufende / gestoppte Container
  container_blueprint_catalog → Verfügbare Blueprints
  container_state_binding    → Aktiver Container + Session-Binding
"""
import re
from typing import Any, Dict, List

from intelligence_modules.prompt_manager import load_prompt

from core.layers.output.analysis.qualitative import normalize_semantic_text


def get_container_query_policy(verified_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Liest _container_query_policy aus dem Plan oder leitet query_class
    aus resolution_strategy ab.
    """
    if not isinstance(verified_plan, dict):
        return {}
    policy = (
        verified_plan.get("_container_query_policy")
        if isinstance(verified_plan.get("_container_query_policy"), dict)
        else {}
    )
    if policy:
        return policy
    strategy = str(
        verified_plan.get("_authoritative_resolution_strategy")
        or verified_plan.get("resolution_strategy")
        or ""
    ).strip().lower()
    if strategy in {
        "container_inventory",
        "container_blueprint_catalog",
        "container_state_binding",
    }:
        return {"query_class": strategy}
    return {}


def is_container_query_contract_plan(verified_plan: Dict[str, Any]) -> bool:
    """Prüft ob der Plan einer der 3 Container-Kontrakt-Klassen gehört."""
    policy = get_container_query_policy(verified_plan)
    return str(policy.get("query_class") or "").strip().lower() in {
        "container_inventory",
        "container_blueprint_catalog",
        "container_state_binding",
    }


def build_container_prompt_rules(verified_plan: Dict[str, Any]) -> List[str]:
    """
    Baut Prompt-Regeln für Container-Turns je nach query_class.
    Gibt leere Liste zurück wenn kein Container-Kontrakt-Plan.
    """
    policy = get_container_query_policy(verified_plan)
    query_class = str(policy.get("query_class") or "").strip().lower()
    if query_class not in {
        "container_inventory",
        "container_blueprint_catalog",
        "container_state_binding",
    }:
        return []

    required_tools = [
        str(tool or "").strip()
        for tool in list(policy.get("required_tools") or [])
        if str(tool or "").strip()
    ]
    truth_mode = str(policy.get("truth_mode") or "").strip().lower()
    required_tools_line = ""
    if required_tools:
        required_tools_line = (
            "Verbindlicher Container-Contract fuer diesen Turn: Aussagen nur auf "
            f"{', '.join(f'`{tool}`' for tool in required_tools)}"
            + (" und Session-State" if query_class == "container_state_binding" else "")
            + " stuetzen."
        )
    truth_mode_line = ""
    if truth_mode:
        truth_mode_line = f"truth_mode fuer diesen Turn: `{truth_mode}`."

    rendered = load_prompt(
        "contracts",
        query_class,
        required_tools_line=required_tools_line,
        truth_mode_line=truth_mode_line,
    )
    return [line for line in rendered.splitlines() if line.strip()]


def extract_container_contract_snapshot(
    verified_plan: Dict[str, Any],
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Baut einen Container-Snapshot aus Evidence:
    containers, blueprints, binding_present, active_container, query_class.
    """
    policy = get_container_query_policy(verified_plan)
    snapshot: Dict[str, Any] = {
        "query_class": str(policy.get("query_class") or "").strip().lower(),
        "truth_mode": str(policy.get("truth_mode") or "").strip().lower(),
        "containers": [],
        "blueprints": [],
        "binding_present": None,
        "active_container": {},
    }
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip().lower()
        status = str(item.get("status") or "").strip().lower()
        structured = item.get("structured")
        if status != "ok" or not isinstance(structured, dict):
            continue
        if tool_name == "container_list":
            rows = structured.get("containers")
            if isinstance(rows, list) and not snapshot["containers"]:
                snapshot["containers"] = [row for row in rows if isinstance(row, dict)]
        elif tool_name == "container_inspect":
            if not snapshot["active_container"] and str(structured.get("container_id") or "").strip():
                snapshot["active_container"] = {
                    "container_id": str(structured.get("container_id") or "").strip(),
                    "name": str(structured.get("name") or "").strip(),
                    "blueprint_id": str(structured.get("blueprint_id") or "").strip(),
                    "status": str(structured.get("status") or "").strip(),
                    "running": bool(structured.get("running")),
                }
        elif tool_name == "blueprint_list":
            rows = structured.get("blueprints")
            if isinstance(rows, list) and not snapshot["blueprints"]:
                snapshot["blueprints"] = [row for row in rows if isinstance(row, dict)]
        elif tool_name == "conversation_state":
            binding_present = structured.get("binding_present")
            if isinstance(binding_present, bool):
                snapshot["binding_present"] = binding_present
    return snapshot


def build_container_safe_fallback(
    verified_plan: Dict[str, Any],
    evidence: List[Dict[str, Any]],
) -> str:
    """
    Baut eine sichere, kontrakt-konforme Fallback-Antwort
    wenn evaluate_container_contract_leakage eine Verletzung meldet.
    """
    snapshot = extract_container_contract_snapshot(verified_plan, evidence)
    query_class = str(snapshot.get("query_class") or "").strip().lower()
    containers = list(snapshot.get("containers") or [])
    blueprints = list(snapshot.get("blueprints") or [])
    binding_present = snapshot.get("binding_present")
    active_container = snapshot.get("active_container") if isinstance(snapshot.get("active_container"), dict) else {}

    if query_class == "container_inventory":
        running = [row for row in containers if str(row.get("state") or row.get("status") or "").strip().lower() == "running"]
        stopped = [row for row in containers if row not in running]
        running_line = (
            "Laufende Container: " + ", ".join(
                str(row.get("blueprint_id") or row.get("name") or "unbekannt").strip()
                for row in running[:6]
                if str(row.get("blueprint_id") or row.get("name") or "").strip()
            ) + "."
            if running else "Laufende Container: Keine laufenden Container verifiziert."
        )
        stopped_line = (
            "Gestoppte Container: " + ", ".join(
                str(row.get("blueprint_id") or row.get("name") or "unbekannt").strip()
                for row in stopped[:8]
                if str(row.get("blueprint_id") or row.get("name") or "").strip()
            ) + "."
            if stopped else "Gestoppte Container: Keine gestoppten Container verifiziert."
        )
        return running_line + "\n" + stopped_line + "\nEinordnung: Das ist ein Runtime-Inventar-Befund und keine Blueprint-Liste."

    if query_class == "container_blueprint_catalog":
        catalog_line = (
            "Verfuegbare Blueprints: " + ", ".join(
                str(row.get("name") or row.get("id") or "unbekannt").strip()
                for row in blueprints[:8]
                if str(row.get("name") or row.get("id") or "").strip()
            ) + "."
            if blueprints else "Verfuegbare Blueprints: Keine Blueprints verifiziert."
        )
        return catalog_line + "\nEinordnung: Das ist ein Blueprint-Katalog-Befund; daraus folgt keine Aussage ueber aktuell laufende oder installierte Container."

    if query_class == "container_state_binding":
        active_label = str(
            active_container.get("blueprint_id")
            or active_container.get("name")
            or active_container.get("container_id")
            or ""
        ).strip()
        if active_label:
            active_line = f"Aktiver Container: {active_label}."
        elif binding_present is True:
            active_line = "Aktiver Container: Ein aktives Binding ist verifiziert, aber ohne belastbaren Containernamen im Snapshot."
        else:
            active_line = "Aktiver Container: nicht verifiziert."
        running = [row for row in containers if str(row.get("state") or row.get("status") or "").strip().lower() == "running"]
        active_status = str(active_container.get("status") or "").strip().lower()
        if active_label and binding_present is True:
            binding_line = (
                f"Binding/Status: Ein aktives Session-Binding auf {active_label} ist verifiziert; "
                f"Runtime-Status: {active_status or 'unbekannt'}."
            )
        elif active_label:
            binding_line = f"Binding/Status: Runtime-Status des aktiven Ziels {active_label}: {active_status or 'unbekannt'}."
        elif binding_present is False and not running:
            binding_line = "Binding/Status: Fuer diesen Check ist kein aktives Session-Binding verifiziert; laufende TRION-managed Container sind derzeit nicht belegt."
        elif running:
            binding_line = "Binding/Status: Laufende TRION-managed Container: " + ", ".join(
                str(row.get("blueprint_id") or row.get("name") or "unbekannt").strip()
                for row in running[:6]
                if str(row.get("blueprint_id") or row.get("name") or "").strip()
            ) + "."
        else:
            binding_line = "Binding/Status: Fuer diesen Check liegt kein belastbarer Binding-/Status-Befund vor."
        return active_line + "\n" + binding_line + "\nEinordnung: Binding, Runtime-Inventar und Blueprint-Katalog bleiben getrennt."

    return ""


def evaluate_container_contract_leakage(
    answer: str,
    verified_plan: Dict[str, Any],
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Prüft ob die LLM-Antwort Container-Kontrakt-Invarianten verletzt.

    Geprüfte Verletzungstypen:
      blueprint_runtime_leakage  → Runtime-Aussagen in Blueprint-Catalog-Turn
      binding_action_leakage     → Aktionsangebote in State-Binding-Turn
      binding_time_leakage       → Zeitangaben in State-Binding-Turn
      binding_profile_leakage    → Unbekannte Container-IDs in State-Binding-Turn
    """
    if not is_container_query_contract_plan(verified_plan):
        return {"violated": False}

    answer_text = str(answer or "").strip()
    if not answer_text:
        return {"violated": False}

    snapshot = extract_container_contract_snapshot(verified_plan, evidence)
    query_class = str(snapshot.get("query_class") or "").strip().lower()
    answer_norm = normalize_semantic_text(answer_text)
    tool_names = {
        str((item or {}).get("tool_name") or "").strip().lower()
        for item in evidence
        if isinstance(item, dict)
    }

    if query_class == "container_blueprint_catalog" and "container_list" not in tool_names:
        runtime_markers = (
            "laufende container", "running container", "running containers",
            "gestoppte container", "stopped container", "stopped containers",
            "aktiver container", "session-binding", "session binding",
            "runtime-inventar: leer", "keine laufenden container",
        )
        if any(marker in answer_norm for marker in runtime_markers):
            return {"violated": True, "reason": "blueprint_runtime_leakage"}

    if query_class == "container_state_binding":
        unsupported_action_markers = (
            "frage gerne", "wenn du willst", "starte ",
            "start-instruktion", "manuelle container-start", "neu starten",
        )
        if any(marker in answer_norm for marker in unsupported_action_markers):
            return {"violated": True, "reason": "binding_action_leakage"}

        unsupported_time_markers = (
            " vor etwa ", " seit ", " tage", " tagen", " stunden", " minuten",
        )
        if any(marker in f" {answer_norm} " for marker in unsupported_time_markers):
            return {"violated": True, "reason": "binding_time_leakage"}

        containers = list(snapshot.get("containers") or [])
        active_container = snapshot.get("active_container") if isinstance(snapshot.get("active_container"), dict) else {}
        allowed_binding_ids = set()
        for candidate in (
            active_container.get("blueprint_id"),
            active_container.get("name"),
            active_container.get("container_id"),
        ):
            normalized = normalize_semantic_text(str(candidate or "").strip())
            if normalized:
                allowed_binding_ids.add(normalized)
        for row in containers:
            if not isinstance(row, dict):
                continue
            for candidate in (row.get("blueprint_id"), row.get("name"), row.get("container_id")):
                normalized = normalize_semantic_text(str(candidate or "").strip())
                if normalized:
                    allowed_binding_ids.add(normalized)

        answer_ids = {
            normalize_semantic_text(match.group(0))
            for match in re.finditer(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", answer_norm)
        }
        ignored_binding_ids = {"session-binding", "container-state", "runtime-status"}
        leaked_ids = sorted(
            c for c in answer_ids
            if c and c not in ignored_binding_ids and c not in allowed_binding_ids
        )
        if leaked_ids:
            return {
                "violated": True,
                "reason": "binding_profile_leakage",
                "details": ", ".join(leaked_ids[:4]),
            }

    return {"violated": False}
