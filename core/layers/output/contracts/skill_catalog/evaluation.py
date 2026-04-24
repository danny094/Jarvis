"""
core.layers.output.contracts.skill_catalog.evaluation
=======================================================
Prompt-Regeln, Postcheck und Safe-Fallback für Skill-Catalog-Turns.

  build_skill_catalog_prompt_rules  → Instruktionen für das LLM
  locate_skill_catalog_sections     → Findet Sektionen in der Antwort
  evaluate_skill_catalog_semantic_leakage → Prüft Kontrakt-Invarianten
  build_skill_catalog_safe_fallback → Baut sichere Fallback-Antwort
"""
import re
from typing import Any, Dict, List

from intelligence_modules.prompt_manager import load_prompt

from core.layers.output.analysis.qualitative import normalize_semantic_text, to_int
from core.layers.output.contracts.skill_catalog.snapshot import extract_skill_catalog_snapshot
from core.layers.output.contracts.skill_catalog.trace import is_skill_catalog_context_plan


def build_skill_catalog_prompt_rules(verified_plan: Dict[str, Any]) -> List[str]:
    """
    Baut die Prompt-Regeln für Skill-Catalog-Turns.
    Gibt eine Liste von Prompt-Zeilen zurück die in build_system_prompt() eingefügt werden.
    """
    ctx = (
        verified_plan.get("_skill_catalog_context")
        if isinstance(verified_plan, dict)
        else {}
    )
    ctx = ctx if isinstance(ctx, dict) else {}
    policy = (
        verified_plan.get("_skill_catalog_policy")
        if isinstance(verified_plan, dict)
        else {}
    )
    policy = policy if isinstance(policy, dict) else {}
    installed_count = to_int(ctx.get("installed_count"))
    required_tools = [
        str(tool or "").strip()
        for tool in list(policy.get("required_tools") or [])
        if str(tool or "").strip()
    ]
    force_sections = [
        str(section or "").strip()
        for section in list(policy.get("force_sections") or [])
        if str(section or "").strip()
    ]
    if not force_sections:
        force_sections = ["Runtime-Skills", "Einordnung"]
    followup_heading = (
        "Wunsch-Skills"
        if "Wunsch-Skills" in force_sections
        else "Nächster Schritt"
    )

    required_tools_line = ""
    if required_tools:
        required_tools_line = (
            "Verbindlicher Skill-Catalog-Contract fuer diesen Turn: "
            f"Inventar-Aussagen nur auf {', '.join(f'`{tool}`' for tool in required_tools)} stützen."
        )
    installed_count_line = ""
    if installed_count == 0:
        installed_count_line = (
            "Wenn keine Runtime-Skills vorhanden sind, formuliere das explizit als Runtime-Befund, z. B. `Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.`"
        )
    elif installed_count is not None:
        installed_count_line = (
            f"Der Runtime-Befund muss sich auf den verifizierten Snapshot beziehen: aktuell {installed_count} installierte Runtime-Skills."
        )

    strategy_hints = verified_plan.get("strategy_hints") if isinstance(verified_plan, dict) else []
    normalized_hints = {
        str(hint or "").strip().lower()
        for hint in (strategy_hints if isinstance(strategy_hints, list) else [])
        if str(hint or "").strip()
    }
    needs_draft_explanation = bool(policy.get("draft_explanation_required")) or bool(
        "draft_skills" in normalized_hints
        or "tools_vs_skills" in normalized_hints
        or to_int(ctx.get("draft_count")) is not None
    )
    followup_split_lines: List[str] = []
    followup_split_required = bool(policy.get("followup_split_required")) or "fact_then_followup" in normalized_hints
    if followup_split_required:
        followup_split_lines.append(
            "Wenn die User-Frage Faktinventar und Wunsch-/Brainstorming-Teil kombiniert, hat der faktische Inventarteil Vorrang."
        )
        followup_split_lines.append(
            "Gib Brainstorming oder Wunsch-Skills erst nach `Runtime-Skills` und `Einordnung` in einem klar markierten Anschlussblock aus."
        )
        if followup_heading == "Wunsch-Skills":
            followup_split_lines.append(
                "Der Anschlussblock muss `Wunsch-Skills` heißen und Vorschläge klar von verifizierten Inventarfakten trennen."
            )
        else:
            followup_split_lines.append(
                "Der Anschlussblock darf nur `Wunsch-Skills` oder `Nächster Schritt` heißen und muss Vorschläge klar von verifizierten Inventarfakten trennen."
            )
    inventory_read_only_line = ""
    if str(policy.get("mode") or "").strip().lower() == "inventory_read_only":
        inventory_read_only_line = (
            "Im Modus `inventory_read_only` keine ungefragten Skill-Erstellungs-, Ausführungs- oder sonstigen Aktionsangebote anhängen."
        )

    draft_schema_line = ""
    if needs_draft_explanation:
        draft_schema_line = (
            "Einordnung muss bei diesem Turn explizit sagen, ob Draft-Skills verifiziert sind und warum `list_skills` sie nicht anzeigt."
        )
    followup_schema_line = ""
    if "Wunsch-Skills" in force_sections or bool(policy.get("followup_split_required")):
        followup_schema_line = (
            f"{followup_heading}: <optional; Wunsch-Skills oder Vorschläge klar getrennt von Inventarfakten>."
        )
    rendered = load_prompt(
        "contracts",
        "skill_catalog",
        followup_heading=followup_heading,
        required_tools_line=required_tools_line,
        installed_count_line=installed_count_line,
        followup_split_lines="\n".join(followup_split_lines),
        inventory_read_only_line=inventory_read_only_line,
        draft_schema_line=draft_schema_line,
        followup_schema_line=followup_schema_line,
    )
    return [line for line in rendered.splitlines() if line.strip()]


def locate_skill_catalog_sections(answer: str) -> Dict[str, int]:
    """
    Findet die Positionen der Pflicht-Sektionen in der LLM-Antwort.
    Gibt Dict mit Schlüsseln: runtime_skills, einordnung, next_step, wish_skills.
    """
    text = str(answer or "")
    patterns = {
        "runtime_skills": r"(^|\n)\s*(?:#{1,6}\s*)?runtime[- ]skills\b\s*:?",
        "einordnung": r"(^|\n)\s*(?:#{1,6}\s*)?einordnung\b\s*:?",
        "next_step": r"(^|\n)\s*(?:#{1,6}\s*)?(?:naechster|nächster)\s+schritt\b\s*:?",
        "wish_skills": r"(^|\n)\s*(?:#{1,6}\s*)?wunsch[- ]skills\b\s*:?",
    }
    hits: Dict[str, int] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            hits[key] = match.start()
    return hits


def evaluate_skill_catalog_semantic_leakage(
    answer: str,
    verified_plan: Dict[str, Any],
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Prüft ob die LLM-Antwort Kontrakt-Invarianten verletzt.

    Geprüfte Verletzungstypen:
      missing_runtime_section          → Runtime-Skills: Sektion fehlt
      free_self_description            → anthropomorphe Selbstbeschreibung
      unverified_session_system_skills → Session-/System-Skills ohne Evidence
      runtime_tool_category_leakage   → Built-in Tools vor Einordnung-Sektion
      built_in_capability_style_drift  → capability-style in tools_vs_skills-Turn
      unsolicited_action_offer         → unaufgeforderte Skill-Aktionsangebote
      draft_claim_without_inventory    → Draft-Behauptung ohne list_draft_skills
      followup_not_split               → Brainstorming ohne markierten Folge-Block
    """
    if not is_skill_catalog_context_plan(verified_plan):
        return {"violated": False}

    answer_text = str(answer or "").strip()
    if not answer_text:
        return {"violated": False}

    answer_lower = answer_text.lower()
    normalized = normalize_semantic_text(answer_text)
    sections = locate_skill_catalog_sections(answer_text)
    runtime_idx = sections.get("runtime_skills", -1)
    einordnung_idx = sections.get("einordnung", -1)
    followup_idx = min(
        [idx for idx in [sections.get("next_step", -1), sections.get("wish_skills", -1)] if idx >= 0],
        default=-1,
    )
    skill_snapshot = extract_skill_catalog_snapshot(verified_plan, evidence)
    verified_session_evidence = bool(skill_snapshot.get("session_skills_verified"))
    draft_inventory_verified = bool(skill_snapshot.get("draft_inventory_verified"))
    strategy_hints = verified_plan.get("strategy_hints") if isinstance(verified_plan, dict) else []
    normalized_hints = {
        str(hint or "").strip().lower()
        for hint in (strategy_hints if isinstance(strategy_hints, list) else [])
        if str(hint or "").strip()
    }

    if runtime_idx < 0:
        return {
            "violated": True,
            "reason": "missing_runtime_section",
            "details": "runtime section missing",
        }

    free_persona_patterns = [
        r"ich habe trotzdem grundlegende faehigkeiten",
        r"grundlegende faehigkeiten",
        r"eigenes denken",
        r"mein koerper",
        r"\bich kann denken\b",
    ]
    for pattern in free_persona_patterns:
        if re.search(pattern, normalized):
            return {"violated": True, "reason": "free_self_description", "details": pattern}

    session_patterns = [
        r"session-skills?",
        r"system-skills?",
        r"session-/system-skills?",
        r"skill\.md",
        r"codex-skills?",
    ]
    if not verified_session_evidence:
        for pattern in session_patterns:
            if re.search(pattern, normalized):
                return {
                    "violated": True,
                    "reason": "unverified_session_system_skills",
                    "details": pattern,
                }

    tool_markers = [
        r"\bbuilt-?in\b",
        r"\btools?\b",
        r"\bmcp\b",
        r"\bmemory\b",
        r"skill-erstellung",
        r"faehigkeiten",
    ]
    for pattern in tool_markers:
        match = re.search(pattern, normalized)
        if not match:
            continue
        marker_pos = answer_lower.find(match.group(0).lower())
        if einordnung_idx < 0 or (marker_pos >= 0 and marker_pos < einordnung_idx):
            return {
                "violated": True,
                "reason": "runtime_tool_category_leakage",
                "details": match.group(0),
            }

    if "tools_vs_skills" in normalized_hints and einordnung_idx >= 0:
        section_end = followup_idx if followup_idx > einordnung_idx else len(answer_text)
        classification_text = answer_text[einordnung_idx:section_end]
        classification_normalized = normalize_semantic_text(classification_text)
        has_built_in_boundary = bool(
            re.search(r"\bbuilt-?in\b", classification_normalized)
            or re.search(r"\btools?\b", classification_normalized)
        )
        capability_style_examples = bool(
            re.search(r"\b(zum beispiel|beispielsweise|etwa)\b", classification_normalized)
        )
        core_ability_framing = bool(
            re.search(
                r"basis-infrastruktur|kernfaehig|direkt in meiner|gehoeren zu meinen",
                classification_normalized,
            )
        )
        if has_built_in_boundary and capability_style_examples and core_ability_framing:
            return {
                "violated": True,
                "reason": "built_in_capability_style_drift",
                "details": "capability-style built-in/self description in tools-vs-skills turn",
            }

    policy = (
        verified_plan.get("_skill_catalog_policy")
        if isinstance(verified_plan, dict)
        else {}
    )
    policy = policy if isinstance(policy, dict) else {}
    if str(policy.get("mode") or "").strip().lower() == "inventory_read_only":
        action_offer_patterns = [
            r"moechtest du[, ]+dass ich",
            r"möchtest du[, ]+dass ich",
            r"soll ich (?:einen|einen speziellen|einen neuen)?\s*skill",
            r"ich kann (?:dir |auch )?(?:einen|einen speziellen|einen neuen)?\s*skill (?:entwickeln|erstellen|bauen|schreiben)",
            r"(?:einen|einen speziellen|einen neuen)?\s*skill (?:entwickeln|erstellen|bauen|schreiben)",
            r"hast du eine konkrete aufgabe im sinn",
            r"wenn du willst[, ]+",
        ]
        for pattern in action_offer_patterns:
            if re.search(pattern, normalized):
                return {"violated": True, "reason": "unsolicited_action_offer", "details": pattern}

    if not draft_inventory_verified:
        has_draft_reference = bool(
            re.search(r"draft[- ]skills?", normalized)
            or re.search(r"\bdrafts?\b", normalized)
        )
        draft_state_claim = bool(
            re.search(
                r"draft[- ]skills?\s+sind aktuell|keine\s+draft[- ]skills?|draft[- ]skills?:|verifiziert|verfuegbar|vorhanden|explizit",
                normalized,
            )
        )
        if has_draft_reference and draft_state_claim:
            return {
                "violated": True,
                "reason": "draft_claim_without_inventory_evidence",
                "details": "draft state claim without list_draft_skills evidence",
            }

    if "fact_then_followup" in normalized_hints:
        brainstorming_patterns = [
            r"haette gerne", r"hätte gerne", r"haettest du gerne", r"hättest du gerne",
            r"wuensche", r"wünsche", r"wuensch", r"wünsch",
            r"waere hilfreich", r"wäre hilfreich",
            r"priorisieren", r"fehlen wuerde", r"fehlen würde",
        ]
        if any(re.search(p, answer_text, re.IGNORECASE) for p in brainstorming_patterns):
            if followup_idx < 0:
                return {
                    "violated": True,
                    "reason": "followup_not_split",
                    "details": "brainstorm content without marked follow-up section",
                }

    return {"violated": False}


def build_skill_catalog_safe_fallback(
    verified_plan: Dict[str, Any],
    evidence: List[Dict[str, Any]],
) -> str:
    """
    Baut eine sichere, kontrakt-konforme Fallback-Antwort
    wenn evaluate_skill_catalog_semantic_leakage eine Verletzung meldet.
    """
    snapshot = extract_skill_catalog_snapshot(verified_plan, evidence)
    policy = (
        verified_plan.get("_skill_catalog_policy")
        if isinstance(verified_plan, dict)
        else {}
    )
    policy = policy if isinstance(policy, dict) else {}
    installed_count = snapshot.get("installed_count")
    draft_count = snapshot.get("draft_count")
    installed_names = snapshot.get("installed_names") or []
    draft_names = snapshot.get("draft_names") or []
    draft_inventory_verified = bool(snapshot.get("draft_inventory_verified"))
    force_sections = [
        str(section or "").strip()
        for section in list(policy.get("force_sections") or [])
        if str(section or "").strip()
    ]
    followup_heading = "Wunsch-Skills" if "Wunsch-Skills" in force_sections else "Nächster Schritt"

    if installed_count == 0:
        runtime_line = "Runtime-Skills: Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden."
    elif isinstance(installed_count, int) and installed_count > 0:
        runtime_line = (
            f"Runtime-Skills: Im Runtime-Skill-System sind aktuell {installed_count} installierte Skills vorhanden."
        )
        if installed_names:
            runtime_line = runtime_line[:-1] + f": {', '.join(installed_names[:6])}."
    else:
        runtime_line = "Runtime-Skills: Der Runtime-Skill-Befund liegt verifiziert vor, aber ohne belastbare Zaehlung im Snapshot."

    classification_parts = [
        "Das bezieht sich nur auf installierte Runtime-Skills.",
        "Built-in Tools und allgemeine Systemfaehigkeiten sind davon getrennt und werden nicht als installierte Skills gezaehlt.",
    ]
    if draft_inventory_verified and isinstance(draft_count, int):
        if draft_count == 0:
            classification_parts.append("Zusaetzlich sind aktuell keine Draft-Skills verifiziert.")
        elif draft_names:
            classification_parts.append(
                f"Getrennt davon sind aktuell {draft_count} Draft-Skills verifiziert: {', '.join(draft_names[:6])}."
            )
        else:
            classification_parts.append(
                f"Getrennt davon sind aktuell {draft_count} Draft-Skills verifiziert."
            )

    strategy_hints = verified_plan.get("strategy_hints") if isinstance(verified_plan, dict) else []
    normalized_hints = {
        str(hint or "").strip().lower()
        for hint in (strategy_hints if isinstance(strategy_hints, list) else [])
        if str(hint or "").strip()
    }
    if (
        draft_inventory_verified
        or "draft_skills" in normalized_hints
        or "tools_vs_skills" in normalized_hints
    ):
        if draft_inventory_verified:
            classification_parts.append(
                "`list_skills` zeigt nur installierte Runtime-Skills; Draft-Skills werden dort deshalb nicht aufgefuehrt."
            )
        else:
            classification_parts.append(
                "`list_skills` zeigt nur installierte Runtime-Skills; ob Draft-Skills in diesem Turn verifiziert vorhanden sind, ist ohne `list_draft_skills`-Evidence nicht belegt."
            )

    response = runtime_line + "\nEinordnung: " + " ".join(classification_parts)
    if "fact_then_followup" in normalized_hints:
        response += (
            f"\n{followup_heading}: Wenn du Wunsch-Skills priorisieren willst, "
            "nenne einen konkreten Use-Case; dann trenne ich Inventar und gewünschte Erweiterungen sauber."
        )
    return response
