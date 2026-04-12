# core/layers/output.py
"""
LAYER 3: OutputLayer v3.0
- Native Ollama Tool Calling via /api/chat
- Automatic tool loop (call → result → continue)
- Dynamic tool injection from MCPHub
- Streaming support with tool interrupts
"""

import json
import ast
import re
import httpx
from typing import Dict, Any, Optional, AsyncGenerator, List
from config import (
    OLLAMA_BASE,
    get_output_model,
    get_output_provider,
    get_output_tool_injection_mode,
    get_output_tool_prompt_limit,
    get_output_char_cap_interactive,
    get_output_char_cap_interactive_long,
    get_output_char_cap_interactive_analytical,
    get_output_char_cap_deep,
    get_output_char_target_interactive,
    get_output_char_target_interactive_analytical,
    get_output_char_target_deep,
    get_output_timeout_interactive_s,
    get_output_timeout_deep_s,
    get_output_stream_postcheck_mode,
)
from utils.logger import log_info, log_error, log_debug, log_warning
from utils.role_endpoint_resolver import resolve_role_endpoint
from core.llm_provider_client import complete_chat, resolve_role_provider, stream_chat
from core.persona import get_persona
from core.grounding_policy import load_grounding_policy
from core.control_contract import ControlDecision, is_interactive_tool_status
from core.output_analysis_guard import (
    build_analysis_turn_safe_fallback,
    evaluate_analysis_turn_answer,
    is_analysis_turn_guard_applicable,
)
from core.plan_runtime_bridge import (
    get_policy_final_instruction,
    get_policy_warnings,
    get_runtime_carryover_grounding_evidence,
    get_runtime_direct_response,
    get_runtime_grounding_evidence,
    get_runtime_grounding_value,
    get_runtime_tool_results,
)
from mcp_registry import get_enabled_tools
from mcp.hub import get_hub

MAX_TOOL_ITERATIONS = 5


def _is_small_model_mode() -> bool:
    """Compatibility hook used by tests and feature flags."""
    try:
        from config import get_small_model_mode
        return bool(get_small_model_mode())
    except Exception:
        return False


class OutputLayer:
    def __init__(self):
        self.ollama_base = OLLAMA_BASE

    @staticmethod
    def _skill_catalog_trace_state(
        verified_plan: Dict[str, Any],
        *,
        create: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not OutputLayer._is_skill_catalog_context_plan(verified_plan):
            return None
        if not isinstance(verified_plan, dict):
            return None
        ctx_trace = verified_plan.get("_ctx_trace")
        if not isinstance(ctx_trace, dict):
            if not create:
                return None
            ctx_trace = {}
            verified_plan["_ctx_trace"] = ctx_trace
        skill_trace = ctx_trace.get("skill_catalog")
        if not isinstance(skill_trace, dict):
            if not create:
                return None
            skill_trace = {}
            ctx_trace["skill_catalog"] = skill_trace
        return skill_trace

    @staticmethod
    def _update_skill_catalog_trace(
        verified_plan: Dict[str, Any],
        **fields: Any,
    ) -> None:
        skill_trace = OutputLayer._skill_catalog_trace_state(verified_plan, create=True)
        if not isinstance(skill_trace, dict):
            return
        for key, value in fields.items():
            if value is None:
                continue
            skill_trace[str(key)] = value

    @staticmethod
    def _normalize_semantic_text(text: str) -> str:
        raw = str(text or "").lower()
        return (
            raw.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )

    @staticmethod
    def _is_skill_catalog_context_plan(verified_plan: Dict[str, Any]) -> bool:
        if not isinstance(verified_plan, dict):
            return False
        resolution_strategy = str(
            verified_plan.get("_authoritative_resolution_strategy")
            or verified_plan.get("resolution_strategy")
            or ""
        ).strip().lower()
        return resolution_strategy == "skill_catalog_context" or bool(
            verified_plan.get("_skill_catalog_context")
        ) or bool(
            verified_plan.get("_skill_catalog_policy")
        )

    @staticmethod
    def _get_container_query_policy(verified_plan: Dict[str, Any]) -> Dict[str, Any]:
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

    @staticmethod
    def _is_container_query_contract_plan(verified_plan: Dict[str, Any]) -> bool:
        policy = OutputLayer._get_container_query_policy(verified_plan)
        return str(policy.get("query_class") or "").strip().lower() in {
            "container_inventory",
            "container_blueprint_catalog",
            "container_state_binding",
        }

    @staticmethod
    def _build_container_prompt_rules(verified_plan: Dict[str, Any]) -> List[str]:
        policy = OutputLayer._get_container_query_policy(verified_plan)
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
        prompt_lines = [
            "\n### CONTAINER-ANTWORTMODUS:",
            "Containerantworten muessen Runtime-Inventar, Blueprint-Katalog und Session-Binding sichtbar getrennt halten.",
            "Blueprint-Katalog, Runtime-Inventar und Binding niemals unmarkiert in denselben Antworttopf werfen.",
            "Statische Profile oder Taxonomie duerfen erklaeren, aber keine Live-Bindung oder Runtime-Fakten erfinden.",
        ]
        if required_tools:
            prompt_lines.append(
                "Verbindlicher Container-Contract fuer diesen Turn: Aussagen nur auf "
                f"{', '.join(f'`{tool}`' for tool in required_tools)}"
                + (" und Session-State" if query_class == "container_state_binding" else "")
                + " stuetzen."
            )
        if truth_mode:
            prompt_lines.append(f"truth_mode fuer diesen Turn: `{truth_mode}`.")

        if query_class == "container_inventory":
            prompt_lines.extend(
                [
                    "Pflichtreihenfolge: `Laufende Container`, dann `Gestoppte Container`, dann `Einordnung`.",
                    "Im Abschnitt `Laufende Container` nur aktuell laufende Container aus Runtime-Inventar nennen.",
                    "Im Abschnitt `Gestoppte Container` nur verifizierte installierte, aber nicht laufende Container nennen.",
                    "Keine Blueprints, keine Startempfehlungen und keine Capability-Liste als Hauptantwort einmischen.",
                    "Keine ungefragten Betriebsdiagnosen, keine Fehlerursachen und keine Zeitinterpretationen aus Exit-Status ableiten.",
                    "Wenn kein laufender oder gestoppter Container verifiziert ist, das explizit als Runtime-Befund sagen statt zu raten.",
                    "Blueprints nur in einem explizit markierten Zusatzblock `Verfuegbare Blueprints` nennen, wenn der User diese Ebene ausdruecklich mitfragt und dafuer belegte Blueprint-Evidence vorliegt.",
                    "Die Antwort MUSS mit dem Literal `Laufende Container:` beginnen.",
                    "\n### VERPFLICHTENDES ANTWORTGERUEST:",
                    "Laufende Container: <verifizierter Runtime-Befund zu aktuell laufenden Containern oder explizites None>.",
                    "Gestoppte Container: <verifizierter Runtime-Befund zu installierten, aber nicht laufenden Containern oder explizites None>.",
                    "Einordnung: <klare Trennung zwischen Runtime-Inventar und Blueprint-Katalog>.",
                ]
            )
        elif query_class == "container_blueprint_catalog":
            prompt_lines.extend(
                [
                    "Pflichtreihenfolge: `Verfuegbare Blueprints`, dann `Einordnung`.",
                    "Im Abschnitt `Verfuegbare Blueprints` nur startbare oder katalogisierte Blueprint-Typen nennen.",
                    "Keine Behauptung ueber aktuell laufende oder installierte Container machen, wenn dafuer nur `blueprint_list` vorliegt.",
                    "Keine Session-Bindung, keinen aktiven Container und keine Runtime-Statusaussage als Hauptantwort behaupten.",
                    "Keine zusaetzlichen Runtime-Inventar-, Running-/Stopped- oder Empty-State-Aussagen machen, wenn kein `container_list`-Beleg vorliegt.",
                    "Die Antwort MUSS mit dem Literal `Verfuegbare Blueprints:` beginnen.",
                    "\n### VERPFLICHTENDES ANTWORTGERUEST:",
                    "Verfuegbare Blueprints: <verifizierter Katalog-Befund aus Blueprint-Evidence>.",
                    "Einordnung: <klare Trennung zwischen Blueprint-Katalog und aktuellem Runtime-Inventar>.",
                ]
            )
        else:
            prompt_lines.extend(
                [
                    "Pflichtreihenfolge: `Aktiver Container`, dann `Binding/Status`, dann `Einordnung`.",
                    "Im Abschnitt `Aktiver Container` nur den verifizierten aktiven oder gebundenen Container nennen, sonst explizit `nicht verifiziert` sagen.",
                    "Im Abschnitt `Binding/Status` nur Session-Binding oder Runtime-Status des aktiven Ziels beschreiben.",
                    "Keine Blueprint-Katalog-Liste und keine generische Capability-Liste als Ersatzhauptantwort geben.",
                    "Statische Profiltexte duerfen erklaeren, aber keinen Bindungsbeweis ersetzen.",
                    "Keine Zeitspannen, Fehlerdiagnosen, Ursachenvermutungen oder impliziten Neustart-/Startempfehlungen anfuegen, wenn diese nicht explizit belegt oder angefragt sind.",
                    "Die Antwort MUSS mit dem Literal `Aktiver Container:` beginnen.",
                    "\n### VERPFLICHTENDES ANTWORTGERUEST:",
                    "Aktiver Container: <verifizierter Binding-Befund oder explizites nicht verifiziert>.",
                    "Binding/Status: <Session-Binding oder Runtime-Status des aktiven Ziels, ohne Blueprint-Katalogdrift>.",
                    "Einordnung: <klare Trennung zwischen Binding, Runtime-Inventar und Blueprint-Katalog>.",
                ]
            )
        return prompt_lines

    @staticmethod
    def _build_skill_catalog_prompt_rules(verified_plan: Dict[str, Any]) -> List[str]:
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
        installed_count = OutputLayer._to_int(ctx.get("installed_count"))
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

        prompt_lines = [
            "\n### SKILL-SEMANTIK:",
            "`list_skills` beschreibt nur installierte Runtime-Skills, nicht die komplette Fähigkeitswelt.",
            "Trenne in der Antwort Runtime-Skills, Draft Skills und Built-in Tools explizit, wenn mehr als eine Ebene gemeint ist.",
            "Built-in Tools dürfen nicht als installierte Skills formuliert werden.",
            "Session- oder System-Skills nur nennen, wenn sie im Kontext ausdrücklich belegt sind.",
            "Allgemeine Agentenfähigkeiten dürfen nicht als Skill-Liste ausgegeben werden.",
            "Vermeide anthropomorphe Metaphern oder Persona-Zusätze in faktischen Skill-Antworten.",
            "\n### SKILL-KATALOG-ANTWORTMODUS:",
            "Antworte für diesen Strategy-Typ in markierten Kurzabschnitten.",
            f"Pflichtreihenfolge: `Runtime-Skills`, dann `Einordnung`, danach optional `{followup_heading}`.",
            "Der erste Satz im Abschnitt `Runtime-Skills` muss den Runtime-Befund als autoritativen Inventar-Befund benennen.",
            "Im Abschnitt `Runtime-Skills` keine Built-in Tools, keine allgemeinen Fähigkeiten, keine Draft-Skills und keine Wunsch-/Aktionsanteile nennen.",
            "Wenn du Built-in Tools erwähnst, dann ausschließlich im explizit markierten Abschnitt `Einordnung`.",
            "Keine unmarkierte Freitext-Liste mit Fähigkeiten, Tools oder Persona-Eigenschaften anhängen.",
        ]
        if required_tools:
            prompt_lines.append(
                "Verbindlicher Skill-Catalog-Contract fuer diesen Turn: "
                f"Inventar-Aussagen nur auf {', '.join(f'`{tool}`' for tool in required_tools)} stützen."
            )
        if installed_count == 0:
            prompt_lines.append(
                "Wenn keine Runtime-Skills vorhanden sind, formuliere das explizit als Runtime-Befund, z. B. `Im Runtime-Skill-System sind aktuell keine installierten Skills vorhanden.`"
            )
        elif installed_count is not None:
            prompt_lines.append(
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
            or OutputLayer._to_int(ctx.get("draft_count")) is not None
        )
        if bool(policy.get("followup_split_required")) or "fact_then_followup" in normalized_hints:
            prompt_lines.append(
                "Wenn die User-Frage Faktinventar und Wunsch-/Brainstorming-Teil kombiniert, hat der faktische Inventarteil Vorrang."
            )
            prompt_lines.append(
                "Gib Brainstorming oder Wunsch-Skills erst nach `Runtime-Skills` und `Einordnung` in einem klar markierten Anschlussblock aus."
            )
            if followup_heading == "Wunsch-Skills":
                prompt_lines.append(
                    "Der Anschlussblock muss `Wunsch-Skills` heißen und Vorschläge klar von verifizierten Inventarfakten trennen."
                )
            else:
                prompt_lines.append(
                    "Der Anschlussblock darf nur `Wunsch-Skills` oder `Nächster Schritt` heißen und muss Vorschläge klar von verifizierten Inventarfakten trennen."
                )
        if str(policy.get("mode") or "").strip().lower() == "inventory_read_only":
            prompt_lines.append(
                "Im Modus `inventory_read_only` keine ungefragten Skill-Erstellungs-, Ausführungs- oder sonstigen Aktionsangebote anhängen."
            )
        prompt_lines.append(
            "Die Antwort MUSS mit dem Literal `Runtime-Skills:` beginnen. Kein anderer Vorspann, keine Einleitung, keine alternative Ueberschrift davor."
        )
        prompt_lines.append(
            "Wenn die Frage nach Draft-Skills fragt, antworte trotzdem zuerst mit dem Runtime-Befund im Abschnitt `Runtime-Skills` und erklaere Drafts erst danach."
        )

        answer_schema = [
            "\n### VERPFLICHTENDES ANTWORTGERUEST:",
            "Runtime-Skills: <verifizierter Runtime-Befund aus Snapshot/Tool-Ergebnis>.",
            "Einordnung: <klare Trennung zwischen Runtime-Skills, Draft-Skills und Built-in Tools>.",
        ]
        if needs_draft_explanation:
            answer_schema.append(
                "Einordnung muss bei diesem Turn explizit sagen, ob Draft-Skills verifiziert sind und warum `list_skills` sie nicht anzeigt."
            )
        if "Wunsch-Skills" in force_sections or bool(policy.get("followup_split_required")):
            answer_schema.append(
                f"{followup_heading}: <optional; Wunsch-Skills oder Vorschläge klar getrennt von Inventarfakten>."
            )
        prompt_lines.extend(answer_schema)
        return prompt_lines

    @staticmethod
    def _extract_numeric_tokens(text: str) -> List[str]:
        """
        Extract potentially factual numeric tokens.
        Filters out list markers like '1.' and keeps values with units or >=2 digits.
        """
        if not text:
            return []
        pattern = re.compile(
            r"\b\d+(?:[.,]\d+)?\s*(?:%|gb|gib|mb|mhz|ghz|tb|°c|c|b)\b|\b\d{2,}(?:[.,]\d+)?\b",
            re.IGNORECASE,
        )
        out = []
        seen = set()
        for match in pattern.finditer(text):
            token = match.group(0).strip().lower().replace(" ", "")
            if token and token not in seen:
                seen.add(token)
                out.append(token)
        return out

    @staticmethod
    def _normalize_length_hint(value: Any) -> str:
        raw = str(value or "").strip().lower()
        return raw if raw in {"short", "medium", "long"} else "medium"

    def _resolve_output_budgets(self, verified_plan: Dict[str, Any]) -> Dict[str, int]:
        response_mode = str((verified_plan or {}).get("_response_mode", "interactive")).lower()
        length_hint = self._normalize_length_hint((verified_plan or {}).get("response_length_hint"))
        dialogue_act = str((verified_plan or {}).get("dialogue_act") or "").strip().lower()
        query_signal = (verified_plan or {}).get("_query_budget") or {}
        query_type = str((query_signal or {}).get("query_type") or "").strip().lower()

        hard_cap = get_output_char_cap_deep() if response_mode == "deep" else get_output_char_cap_interactive()
        soft_target = (
            get_output_char_target_deep() if response_mode == "deep" else get_output_char_target_interactive()
        )

        if response_mode != "deep" and hard_cap > 0:
            if length_hint == "long":
                hard_cap = max(hard_cap, get_output_char_cap_interactive_long())
                soft_target = max(soft_target, int(hard_cap * 0.72))

        if length_hint == "short":
            soft_target = int(soft_target * 0.62)
        elif length_hint == "long":
            soft_target = int(soft_target * 1.30)

        # Interactive analytical answers are budgeted tighter by default to avoid
        # long generation tails in non-deep mode.
        if response_mode != "deep" and query_type == "analytical":
            hard_cap = min(hard_cap, get_output_char_cap_interactive_analytical())
            soft_target = min(soft_target, get_output_char_target_interactive_analytical())

        if hard_cap > 0:
            soft_target = min(soft_target, max(160, hard_cap - 80))
        soft_target = max(160, soft_target)

        return {
            "hard_cap": hard_cap,
            "soft_target": soft_target,
        }

    @staticmethod
    def _runtime_grounding_state(
        verified_plan: Dict[str, Any],
        execution_result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(execution_result, dict):
            existing = (verified_plan or {}).get("_execution_result")
            execution_result = existing if isinstance(existing, dict) else {}
        grounding = execution_result.get("grounding")
        if not isinstance(grounding, dict):
            grounding = {}
            execution_result["grounding"] = grounding
        if isinstance(verified_plan, dict):
            verified_plan["_execution_result"] = execution_result
        return grounding

    @staticmethod
    def _set_runtime_grounding_value(
        verified_plan: Dict[str, Any],
        execution_result: Optional[Dict[str, Any]],
        key: str,
        value: Any,
    ) -> None:
        grounding = OutputLayer._runtime_grounding_state(verified_plan, execution_result)
        grounding[str(key)] = value

    @staticmethod
    def _summarize_structured_output(output_text: str, max_lines: int = 4) -> str:
        if not output_text:
            return ""
        lines = []
        for raw in str(output_text).splitlines():
            line = str(raw or "").strip()
            if not line:
                continue
            # Skip pure separator lines (e.g. "----------------------------")
            if re.fullmatch(r"-{3,}", line):
                continue
            lines.append(line)
        if not lines:
            return ""

        # Prefer hardware-relevant lines first so GPU/VRAM details are not dropped.
        priority_patterns = [
            r"\bgpu\b",
            r"\bvram\b",
            r"\bcpu\b",
            r"\bram\b",
            r"\bspeicher\b",
            r"\bdisk\b",
        ]
        selected: List[str] = []
        for pattern in priority_patterns:
            for line in lines:
                if line in selected:
                    continue
                if re.search(pattern, line, re.IGNORECASE):
                    selected.append(line)

        for line in lines:
            if line not in selected:
                selected.append(line)

        return "; ".join(selected[:max_lines])

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _summarize_list_skills_evidence(item: Dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""

        structured = item.get("structured")
        installed_count: Optional[int] = None
        available_count: Optional[int] = None
        installed_names: List[str] = []

        if isinstance(structured, dict):
            installed_count = OutputLayer._to_int(structured.get("installed_count"))
            available_count = OutputLayer._to_int(structured.get("available_count"))
            raw_names = structured.get("installed_names")
            if isinstance(raw_names, list):
                for raw in raw_names:
                    name = str(raw or "").strip()
                    if name:
                        installed_names.append(name)

        if not installed_names or installed_count is None or available_count is None:
            facts = item.get("key_facts")
            if isinstance(facts, list):
                for raw in facts:
                    line = str(raw or "").strip()
                    if not line:
                        continue
                    low = line.lower()
                    if low.startswith("installed_count:"):
                        installed_count = OutputLayer._to_int(line.split(":", 1)[1].strip())
                    elif low.startswith("available_count:"):
                        available_count = OutputLayer._to_int(line.split(":", 1)[1].strip())
                    elif low.startswith("installed_names:"):
                        rhs = line.split(":", 1)[1].strip()
                        if rhs:
                            installed_names = [
                                part.strip()
                                for part in rhs.split(",")
                                if str(part or "").strip()
                            ]
                    else:
                        # Robust fallback: tolerate raw JSON/object payload in key_facts.
                        candidate = line
                        if ":" in line and low.startswith("list_skills"):
                            candidate = line.split(":", 1)[1].strip()
                        parsed = None
                        if candidate.startswith("{") and candidate.endswith("}"):
                            try:
                                parsed = json.loads(candidate)
                            except Exception:
                                try:
                                    parsed = ast.literal_eval(candidate)
                                except Exception:
                                    parsed = None
                        if isinstance(parsed, dict) and (
                            "installed_count" in parsed
                            or "installed" in parsed
                            or "available_count" in parsed
                        ):
                            rows = parsed.get("installed")
                            installed_rows = rows if isinstance(rows, list) else []
                            avail_rows = parsed.get("available")
                            available_rows = avail_rows if isinstance(avail_rows, list) else []
                            if installed_count is None:
                                try:
                                    installed_count = int(parsed.get("installed_count"))
                                except Exception:
                                    installed_count = len(installed_rows)
                            if available_count is None:
                                try:
                                    available_count = int(parsed.get("available_count"))
                                except Exception:
                                    available_count = len(available_rows)
                            if not installed_names:
                                for row in installed_rows:
                                    if not isinstance(row, dict):
                                        continue
                                    name = str(row.get("name") or "").strip()
                                    if name:
                                        installed_names.append(name)
                                    if len(installed_names) >= 8:
                                        break

        if installed_count is None and installed_names:
            installed_count = len(installed_names)

        if installed_count is None and available_count is None and not installed_names:
            return ""

        parts = []
        if installed_count is not None:
            if installed_names:
                shown = ", ".join(installed_names[:6])
                if installed_count > len(installed_names):
                    shown = f"{shown} (+{installed_count - len(installed_names)} weitere)"
                parts.append(f"{installed_count} installiert ({shown})")
            else:
                parts.append(f"{installed_count} installiert")
        elif installed_names:
            parts.append("installiert: " + ", ".join(installed_names[:6]))

        if available_count is not None:
            parts.append(f"{available_count} verfügbar")

        if not parts:
            return ""
        return "Runtime-Skills: " + "; ".join(parts)

    @staticmethod
    def _summarize_skill_registry_snapshot_evidence(item: Dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""

        active_count: Optional[int] = None
        draft_count: Optional[int] = None
        active_names: List[str] = []
        draft_names: List[str] = []

        structured = item.get("structured")
        if isinstance(structured, dict):
            output_text = str(structured.get("output") or structured.get("result") or "").strip()
            if output_text:
                facts = [line.strip() for line in output_text.splitlines() if line.strip()]
            else:
                facts = []
        else:
            facts = []

        raw_facts = item.get("key_facts")
        if isinstance(raw_facts, list):
            facts.extend(str(x or "").strip() for x in raw_facts if str(x or "").strip())

        for line in facts:
            low = line.lower()
            if low.startswith("active_count:"):
                active_count = OutputLayer._to_int(line.split(":", 1)[1].strip())
            elif low.startswith("draft_count:"):
                draft_count = OutputLayer._to_int(line.split(":", 1)[1].strip())
            elif low.startswith("active_names:"):
                rhs = line.split(":", 1)[1].strip()
                if rhs:
                    active_names = [part.strip() for part in rhs.split(",") if str(part or "").strip()]
            elif low.startswith("draft_names:"):
                rhs = line.split(":", 1)[1].strip()
                if rhs:
                    draft_names = [part.strip() for part in rhs.split(",") if str(part or "").strip()]

        if active_count is None and draft_count is None and not draft_names and not active_names:
            return ""

        parts = []
        if active_count is not None:
            if active_names:
                shown = ", ".join(active_names[:6])
                if active_count > len(active_names):
                    shown = f"{shown} (+{active_count - len(active_names)} weitere)"
                parts.append(f"{active_count} aktiv ({shown})")
            else:
                parts.append(f"{active_count} aktiv")
        if draft_count is not None:
            if draft_names:
                shown = ", ".join(draft_names[:6])
                if draft_count > len(draft_names):
                    shown = f"{shown} (+{draft_count - len(draft_names)} weitere)"
                parts.append(f"{draft_count} Drafts ({shown})")
            else:
                parts.append(f"{draft_count} Drafts")
        if not parts:
            return ""
        return "Skill-Registry: " + "; ".join(parts)

    @staticmethod
    def _summarize_skill_addons_evidence(item: Dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""

        selected_docs = ""
        context_lines: List[str] = []
        facts = item.get("key_facts")
        if isinstance(facts, list):
            for raw in facts:
                line = str(raw or "").strip()
                if not line:
                    continue
                low = line.lower()
                if low.startswith("selected_docs:"):
                    selected_docs = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("Skill Addon:") or line.startswith("Scope:"):
                    continue
                context_lines.append(line)

        if not context_lines:
            structured = item.get("structured")
            if isinstance(structured, dict):
                output_text = str(structured.get("output") or structured.get("result") or "").strip()
                for raw in output_text.splitlines():
                    line = str(raw or "").strip()
                    if not line or line.startswith("Skill Addon:") or line.startswith("Scope:"):
                        continue
                    if line.lower().startswith("selected_docs:"):
                        selected_docs = line.split(":", 1)[1].strip()
                        continue
                    context_lines.append(line)

        if not context_lines and not selected_docs:
            return ""

        parts: List[str] = []
        if selected_docs:
            parts.append(f"Docs: {selected_docs}")
        if context_lines:
            summary = OutputLayer._summarize_structured_output("\n".join(context_lines), max_lines=3)
            if summary:
                parts.append(summary)
        if not parts:
            return ""
        return "Skill-Semantik: " + "; ".join(parts)

    @staticmethod
    def _collect_grounding_evidence(verified_plan: Dict[str, Any], memory_data: str) -> List[Dict[str, Any]]:
        evidence: List[Dict[str, Any]] = []
        seen = set()

        def _push(item: Any) -> None:
            if not isinstance(item, dict):
                return
            tool_name = str(item.get("tool_name", "")).strip()
            ref_id = str(item.get("ref_id", "")).strip()
            status = str(item.get("status", "")).strip().lower()
            sig = (
                tool_name,
                ref_id,
                status,
                len(item.get("key_facts", []) if isinstance(item.get("key_facts"), list) else []),
            )
            if sig in seen:
                return
            seen.add(sig)
            evidence.append(item)

        from_plan = get_runtime_grounding_evidence(verified_plan)
        if isinstance(from_plan, list):
            for item in from_plan:
                _push(item)

        carryover = get_runtime_carryover_grounding_evidence(verified_plan)
        if isinstance(carryover, list):
            for item in carryover:
                _push(item)

        # Fallback: read tool_statuses from _execution_result when grounding_evidence
        # was not explicitly written (e.g. stream-path routing_block paths that only
        # call execution_result.append_tool_status without grounding_evidence_stream.append).
        exec_result = (verified_plan or {}).get("_execution_result") or {}
        for ts in exec_result.get("tool_statuses", []):
            if isinstance(ts, dict):
                _push(ts)

        # Fallback parser for tool cards embedded in memory_data.
        if memory_data:
            for line in str(memory_data).splitlines():
                stripped = line.strip()
                if not stripped.startswith("[TOOL-CARD:") or "|" not in stripped:
                    continue
                body = stripped[len("[TOOL-CARD:") :].rstrip("]").strip()
                parts = [p.strip() for p in body.split("|")]
                if len(parts) < 3:
                    continue
                status_part = parts[1].lower()
                status = "unknown"
                if " ok" in status_part or status_part.endswith("ok"):
                    status = "ok"
                elif "error" in status_part:
                    status = "error"
                elif "partial" in status_part:
                    status = "partial"
                ref_part = parts[2].lower()
                ref_id = ""
                if ref_part.startswith("ref:"):
                    ref_id = ref_part.split("ref:", 1)[1].strip()
                _push(
                    {
                        "tool_name": parts[0],
                        "status": status,
                        "ref_id": ref_id,
                        "key_facts": [],
                    }
                )
        return evidence

    @staticmethod
    def _evidence_item_has_extractable_content(item: Dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        facts = item.get("key_facts")
        if isinstance(facts, list):
            for entry in facts:
                if str(entry or "").strip():
                    return True
        structured = item.get("structured")
        if isinstance(structured, dict):
            output_text = str(
                structured.get("output") or structured.get("result") or ""
            ).strip()
            if output_text:
                return True
        metrics = item.get("metrics")
        if isinstance(metrics, dict):
            return bool(metrics)
        if isinstance(metrics, list):
            return any(
                isinstance(metric, dict)
                and str(metric.get("key") or metric.get("name") or "").strip()
                for metric in metrics
            )
        return False

    @staticmethod
    def _summarize_evidence_item(item: Dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""
        tool = str(item.get("tool_name", "tool")).strip()
        fact = ""
        if tool == "list_skills":
            fact = OutputLayer._summarize_list_skills_evidence(item)
        elif tool == "skill_registry_snapshot":
            fact = OutputLayer._summarize_skill_registry_snapshot_evidence(item)
        elif tool == "skill_addons":
            fact = OutputLayer._summarize_skill_addons_evidence(item)
        structured = item.get("structured")
        if isinstance(structured, dict):
            # Skills use "result"; other tools may use "output"
            output_text = str(
                structured.get("output") or structured.get("result") or ""
            ).strip()
            if output_text:
                fact = OutputLayer._summarize_structured_output(output_text, max_lines=4)
            if not fact:
                err_text = str(
                    structured.get("error")
                    or structured.get("message")
                    or structured.get("reason")
                    or ""
                ).strip()
                if err_text:
                    fact = OutputLayer._summarize_structured_output(err_text, max_lines=4)
        if not fact:
            metrics = item.get("metrics")
            if isinstance(metrics, dict) and metrics:
                fact = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:4])
            elif isinstance(metrics, list):
                chunks = []
                for metric in metrics[:4]:
                    if not isinstance(metric, dict):
                        continue
                    key = str(metric.get("key") or metric.get("name") or "").strip()
                    if not key:
                        continue
                    chunks.append(f"{key}={metric.get('value')}{metric.get('unit') or ''}")
                if chunks:
                    fact = ", ".join(chunks)
        if not fact:
            facts = item.get("key_facts")
            if isinstance(facts, list) and facts:
                fact = OutputLayer._summarize_structured_output(
                    "\n".join(str(f or "").strip() for f in facts[:8] if str(f or "").strip()),
                    max_lines=4,
                )
                if fact.startswith("{") and fact.endswith("}"):
                    try:
                        parsed_fact = json.loads(fact)
                        if isinstance(parsed_fact, dict):
                            out_text = str(
                                parsed_fact.get("output")
                                or parsed_fact.get("result")
                                or parsed_fact.get("error")
                                or parsed_fact.get("message")
                                or ""
                            ).strip()
                            if out_text:
                                fact = OutputLayer._summarize_structured_output(out_text, max_lines=4)
                    except Exception:
                        pass
        if not fact:
            fact = str(item.get("reason") or "").strip()
        return fact

    @staticmethod
    def _collect_skill_catalog_fact_lines(item: Dict[str, Any]) -> List[str]:
        if not isinstance(item, dict):
            return []

        lines: List[str] = []
        key_facts = item.get("key_facts")
        if isinstance(key_facts, list):
            lines.extend(str(raw or "").strip() for raw in key_facts if str(raw or "").strip())

        structured = item.get("structured")
        if isinstance(structured, dict):
            output_text = str(structured.get("output") or structured.get("result") or "").strip()
            if output_text:
                lines.extend(str(raw or "").strip() for raw in output_text.splitlines() if str(raw or "").strip())
        return lines

    @staticmethod
    def _extract_skill_catalog_snapshot(
        verified_plan: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        ctx = (
            verified_plan.get("_skill_catalog_context")
            if isinstance(verified_plan, dict)
            else {}
        )
        ctx = ctx if isinstance(ctx, dict) else {}
        snapshot = {
            "installed_count": OutputLayer._to_int(ctx.get("installed_count")),
            "draft_count": None,
            "available_count": OutputLayer._to_int(ctx.get("available_count")),
            "installed_names": [],
            "draft_names": [],
            "selected_docs": str(ctx.get("selected_docs") or "").strip(),
            "session_skills_verified": bool(ctx.get("session_skills_verified")),
            "draft_inventory_verified": False,
        }

        for item in evidence:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name") or "").strip()
            status = str(item.get("status") or "").strip().lower()
            structured = item.get("structured")
            if tool_name == "list_skills" and isinstance(structured, dict):
                if snapshot["installed_count"] is None:
                    snapshot["installed_count"] = OutputLayer._to_int(structured.get("installed_count"))
                if snapshot["available_count"] is None:
                    snapshot["available_count"] = OutputLayer._to_int(structured.get("available_count"))
                raw_names = structured.get("installed_names")
                if isinstance(raw_names, list) and not snapshot["installed_names"]:
                    snapshot["installed_names"] = [
                        str(raw or "").strip()
                        for raw in raw_names
                        if str(raw or "").strip()
                    ][:8]
            elif tool_name == "list_draft_skills" and status == "ok" and isinstance(structured, dict):
                snapshot["draft_inventory_verified"] = True
                if snapshot["draft_count"] is None:
                    snapshot["draft_count"] = OutputLayer._to_int(structured.get("draft_count"))
                raw_names = structured.get("draft_names")
                if isinstance(raw_names, list) and not snapshot["draft_names"]:
                    snapshot["draft_names"] = [
                        str(raw or "").strip()
                        for raw in raw_names
                        if str(raw or "").strip()
                    ][:8]

            for line in OutputLayer._collect_skill_catalog_fact_lines(item):
                low = line.lower()
                if tool_name == "list_skills":
                    if low.startswith("installed_count:") and snapshot["installed_count"] is None:
                        snapshot["installed_count"] = OutputLayer._to_int(line.split(":", 1)[1].strip())
                    elif low.startswith("available_count:") and snapshot["available_count"] is None:
                        snapshot["available_count"] = OutputLayer._to_int(line.split(":", 1)[1].strip())
                    elif low.startswith("installed_names:") and not snapshot["installed_names"]:
                        rhs = line.split(":", 1)[1].strip()
                        if rhs:
                            snapshot["installed_names"] = [
                                part.strip() for part in rhs.split(",") if str(part or "").strip()
                            ][:8]
                elif tool_name == "list_draft_skills" and status == "ok":
                    snapshot["draft_inventory_verified"] = True
                    if low.startswith("draft_count:") and snapshot["draft_count"] is None:
                        snapshot["draft_count"] = OutputLayer._to_int(line.split(":", 1)[1].strip())
                    elif low.startswith("draft_names:") and not snapshot["draft_names"]:
                        rhs = line.split(":", 1)[1].strip()
                        if rhs:
                            snapshot["draft_names"] = [
                                part.strip() for part in rhs.split(",") if str(part or "").strip()
                            ][:8]
                elif tool_name not in {"skill_addons"}:
                    normalized = OutputLayer._normalize_semantic_text(line)
                    if "session-skill" in normalized or "system-skill" in normalized:
                        snapshot["session_skills_verified"] = True
        return snapshot

    @staticmethod
    def _build_skill_catalog_safe_fallback(
        verified_plan: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> str:
        snapshot = OutputLayer._extract_skill_catalog_snapshot(verified_plan, evidence)
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
        followup_heading = (
            "Wunsch-Skills"
            if "Wunsch-Skills" in force_sections
            else "Nächster Schritt"
        )

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

    @staticmethod
    def _extract_container_contract_snapshot(
        verified_plan: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        policy = OutputLayer._get_container_query_policy(verified_plan)
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

    @staticmethod
    def _build_container_safe_fallback(
        verified_plan: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> str:
        snapshot = OutputLayer._extract_container_contract_snapshot(verified_plan, evidence)
        query_class = str(snapshot.get("query_class") or "").strip().lower()
        containers = list(snapshot.get("containers") or [])
        blueprints = list(snapshot.get("blueprints") or [])
        binding_present = snapshot.get("binding_present")
        active_container = snapshot.get("active_container") if isinstance(snapshot.get("active_container"), dict) else {}

        if query_class == "container_inventory":
            running = [row for row in containers if str(row.get("state") or row.get("status") or "").strip().lower() == "running"]
            stopped = [row for row in containers if row not in running]
            if running:
                running_line = "Laufende Container: " + ", ".join(
                    str(row.get("blueprint_id") or row.get("name") or "unbekannt").strip()
                    for row in running[:6]
                    if str(row.get("blueprint_id") or row.get("name") or "").strip()
                ) + "."
            else:
                running_line = "Laufende Container: Keine laufenden Container verifiziert."
            if stopped:
                stopped_line = "Gestoppte Container: " + ", ".join(
                    str(row.get("blueprint_id") or row.get("name") or "unbekannt").strip()
                    for row in stopped[:8]
                    if str(row.get("blueprint_id") or row.get("name") or "").strip()
                ) + "."
            else:
                stopped_line = "Gestoppte Container: Keine gestoppten Container verifiziert."
            return (
                running_line
                + "\n"
                + stopped_line
                + "\nEinordnung: Das ist ein Runtime-Inventar-Befund und keine Blueprint-Liste."
            )

        if query_class == "container_blueprint_catalog":
            if blueprints:
                catalog_line = "Verfuegbare Blueprints: " + ", ".join(
                    str(row.get("name") or row.get("id") or "unbekannt").strip()
                    for row in blueprints[:8]
                    if str(row.get("name") or row.get("id") or "").strip()
                ) + "."
            else:
                catalog_line = "Verfuegbare Blueprints: Keine Blueprints verifiziert."
            return (
                catalog_line
                + "\nEinordnung: Das ist ein Blueprint-Katalog-Befund; daraus folgt keine Aussage ueber aktuell laufende oder installierte Container."
            )

        if query_class == "container_state_binding":
            active_label = str(
                active_container.get("blueprint_id")
                or active_container.get("name")
                or active_container.get("container_id")
                or ""
            ).strip()
            active_line = "Aktiver Container: nicht verifiziert."
            if active_label:
                active_line = f"Aktiver Container: {active_label}."
            elif binding_present is True:
                active_line = "Aktiver Container: Ein aktives Binding ist verifiziert, aber ohne belastbaren Containernamen im Snapshot."
            running = [row for row in containers if str(row.get("state") or row.get("status") or "").strip().lower() == "running"]
            active_status = str(active_container.get("status") or "").strip().lower()
            if active_label and binding_present is True:
                binding_line = (
                    f"Binding/Status: Ein aktives Session-Binding auf {active_label} ist verifiziert; "
                    f"Runtime-Status: {active_status or 'unbekannt'}."
                )
            elif active_label:
                binding_line = (
                    f"Binding/Status: Runtime-Status des aktiven Ziels {active_label}: "
                    f"{active_status or 'unbekannt'}."
                )
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
            return (
                active_line
                + "\n"
                + binding_line
                + "\nEinordnung: Binding, Runtime-Inventar und Blueprint-Katalog bleiben getrennt."
            )

        return ""

    @staticmethod
    def _locate_skill_catalog_sections(answer: str) -> Dict[str, int]:
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

    @staticmethod
    def _evaluate_skill_catalog_semantic_leakage(
        answer: str,
        verified_plan: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not OutputLayer._is_skill_catalog_context_plan(verified_plan):
            return {"violated": False}

        answer_text = str(answer or "").strip()
        if not answer_text:
            return {"violated": False}

        answer_lower = answer_text.lower()
        normalized = OutputLayer._normalize_semantic_text(answer_text)
        sections = OutputLayer._locate_skill_catalog_sections(answer_text)
        runtime_idx = sections.get("runtime_skills", -1)
        einordnung_idx = sections.get("einordnung", -1)
        followup_idx = min(
            [idx for idx in [sections.get("next_step", -1), sections.get("wish_skills", -1)] if idx >= 0],
            default=-1,
        )
        verified_session_evidence = bool(
            OutputLayer._extract_skill_catalog_snapshot(verified_plan, evidence).get("session_skills_verified")
        )
        skill_snapshot = OutputLayer._extract_skill_catalog_snapshot(verified_plan, evidence)
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
                return {
                    "violated": True,
                    "reason": "free_self_description",
                    "details": pattern,
                }

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
            classification_normalized = OutputLayer._normalize_semantic_text(classification_text)
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
                    return {
                        "violated": True,
                        "reason": "unsolicited_action_offer",
                        "details": pattern,
                    }

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
                r"haette gerne",
                r"hätte gerne",
                r"haettest du gerne",
                r"hättest du gerne",
                r"wuensche",
                r"wünsche",
                r"wuensch",
                r"wünsch",
                r"waere hilfreich",
                r"wäre hilfreich",
                r"priorisieren",
                r"fehlen wuerde",
                r"fehlen würde",
            ]
            if any(re.search(pattern, answer_text, re.IGNORECASE) for pattern in brainstorming_patterns):
                if followup_idx < 0:
                    return {
                        "violated": True,
                        "reason": "followup_not_split",
                        "details": "brainstorm content without marked follow-up section",
                    }

        return {"violated": False}

    @staticmethod
    def _evaluate_container_contract_leakage(
        answer: str,
        verified_plan: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not OutputLayer._is_container_query_contract_plan(verified_plan):
            return {"violated": False}

        answer_text = str(answer or "").strip()
        if not answer_text:
            return {"violated": False}

        snapshot = OutputLayer._extract_container_contract_snapshot(verified_plan, evidence)
        query_class = str(snapshot.get("query_class") or "").strip().lower()
        answer_norm = OutputLayer._normalize_semantic_text(answer_text)
        tool_names = {
            str((item or {}).get("tool_name") or "").strip().lower()
            for item in evidence
            if isinstance(item, dict)
        }

        if query_class == "container_blueprint_catalog" and "container_list" not in tool_names:
            runtime_markers = (
                "laufende container",
                "running container",
                "running containers",
                "gestoppte container",
                "stopped container",
                "stopped containers",
                "aktiver container",
                "session-binding",
                "session binding",
                "runtime-inventar: leer",
                "keine laufenden container",
            )
            if any(marker in answer_norm for marker in runtime_markers):
                return {
                    "violated": True,
                    "reason": "blueprint_runtime_leakage",
                }

        if query_class == "container_state_binding":
            unsupported_action_markers = (
                "frage gerne",
                "wenn du willst",
                "starte ",
                "start-instruktion",
                "manuelle container-start",
                "neu starten",
            )
            if any(marker in answer_norm for marker in unsupported_action_markers):
                return {
                    "violated": True,
                    "reason": "binding_action_leakage",
                }
            unsupported_time_markers = (
                " vor etwa ",
                " seit ",
                " tage",
                " tagen",
                " stunden",
                " minuten",
            )
            normalized_padded = f" {answer_norm} "
            if any(marker in normalized_padded for marker in unsupported_time_markers):
                return {
                    "violated": True,
                    "reason": "binding_time_leakage",
                }
            allowed_binding_ids = set()
            active_container = snapshot.get("active_container") if isinstance(snapshot.get("active_container"), dict) else {}
            for candidate in (
                active_container.get("blueprint_id"),
                active_container.get("name"),
                active_container.get("container_id"),
            ):
                normalized = OutputLayer._normalize_semantic_text(str(candidate or "").strip())
                if normalized:
                    allowed_binding_ids.add(normalized)
            for row in containers:
                if not isinstance(row, dict):
                    continue
                for candidate in (
                    row.get("blueprint_id"),
                    row.get("name"),
                    row.get("container_id"),
                ):
                    normalized = OutputLayer._normalize_semantic_text(str(candidate or "").strip())
                    if normalized:
                        allowed_binding_ids.add(normalized)
            answer_ids = {
                OutputLayer._normalize_semantic_text(match.group(0))
                for match in re.finditer(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", answer_norm)
            }
            ignored_binding_ids = {
                "session-binding",
                "container-state",
                "runtime-status",
            }
            leaked_ids = sorted(
                candidate
                for candidate in answer_ids
                if candidate
                and candidate not in ignored_binding_ids
                and candidate not in allowed_binding_ids
            )
            if leaked_ids:
                return {
                    "violated": True,
                    "reason": "binding_profile_leakage",
                    "details": ", ".join(leaked_ids[:4]),
                }

        return {"violated": False}

    @staticmethod
    def _build_grounding_fallback(
        evidence: List[Dict[str, Any]],
        *,
        mode: str = "explicit_uncertainty",
    ) -> str:
        mode = str(mode or "explicit_uncertainty").strip().lower()
        usable = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).strip().lower() != "ok":
                continue
            tool = str(item.get("tool_name", "tool")).strip()
            fact = OutputLayer._summarize_evidence_item(item)
            if fact:
                usable.append((tool, fact))
            if len(usable) >= 3:
                break

        if mode == "summarize_evidence" and usable:
            lines = [f"- {tool}: {fact}" for tool, fact in usable]
            return "Verifizierte Ergebnisse:\n" + "\n".join(lines)

        if usable:
            lines = [f"- {tool}: {fact}" for tool, fact in usable]
            return (
                "Ich kann nur verifizierte Fakten aus den Tool-Ergebnissen ausgeben.\n"
                + "\n".join(lines)
                + "\nNicht belegbare Zusatzangaben lasse ich weg."
            )

        return (
            "Ich habe aktuell keinen verifizierten Tool-Nachweis für eine belastbare Faktenantwort. "
            "Bitte Tool-Abfrage erneut ausführen."
        )

    @staticmethod
    def _build_tool_failure_fallback(evidence: List[Dict[str, Any]]) -> str:
        issues = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).strip().lower()
            if status not in {"error", "skip", "partial", "unavailable", "routing_block"}:
                continue
            if status == "routing_block":
                continue
            tool = str(item.get("tool_name", "tool")).strip()
            fact = OutputLayer._summarize_evidence_item(item)
            if not fact:
                continue
            issues.append((tool, status, fact))
            if len(issues) >= 3:
                break

        if not issues:
            return (
                "Tool-Ausführung war nicht erfolgreich, aber die Fehlermeldung ist unvollständig. "
                "Bitte Anfrage mit denselben Parametern erneut ausführen."
            )

        lines = [f"- {tool} [{status}]: {fact}" for tool, status, fact in issues]
        return (
            "Tool-Ausführung fehlgeschlagen:\n"
            + "\n".join(lines)
            + "\nBitte Parameter korrigieren oder den vorgeschlagenen sicheren Fallback bestätigen."
        )

    def _grounding_precheck(
        self,
        verified_plan: Dict[str, Any],
        memory_data: str,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        policy = load_grounding_policy()
        output_cfg = (policy or {}).get("output") or {}
        is_fact_query = bool((verified_plan or {}).get("is_fact_query", False))
        conversation_mode = str((verified_plan or {}).get("conversation_mode") or "").strip().lower()
        is_conversational_mode = conversation_mode == "conversational"
        has_tool_usage = bool(str(get_runtime_tool_results(verified_plan) or "").strip())
        has_tool_suggestions = bool(self._extract_selected_tool_names(verified_plan))
        evidence = self._collect_grounding_evidence(verified_plan, memory_data)

        allowed = output_cfg.get("allowed_evidence_statuses", ["ok"])
        allowed_statuses = {
            str(x).strip().lower()
            for x in (allowed if isinstance(allowed, list) else ["ok"])
            if str(x).strip()
        } or {"ok"}
        min_successful = int(output_cfg.get("min_successful_evidence", 1) or 1)
        successful = 0
        successful_extractable = 0
        for item in evidence:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).strip().lower()
            if status in allowed_statuses:
                successful += 1
                if self._evidence_item_has_extractable_content(item):
                    successful_extractable += 1

        require_evidence = bool(
            (
                is_fact_query
                and bool(output_cfg.get("enforce_evidence_for_fact_query", True))
                and (has_tool_usage or has_tool_suggestions)
            )
            or (has_tool_usage and bool(output_cfg.get("enforce_evidence_when_tools_used", True)))
            or (
                has_tool_suggestions
                and not is_conversational_mode
                and bool(output_cfg.get("enforce_evidence_when_tools_suggested", True))
            )
        )

        self._set_runtime_grounding_value(
            verified_plan, execution_result, "missing_evidence", False
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "violation_detected", False
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "fallback_used", False
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "repair_attempted", False
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "repair_used", False
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "analysis_guard_evaluation", {}
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "analysis_guard_violation", {}
        )
        self._set_runtime_grounding_value(
            verified_plan,
            execution_result,
            "successful_evidence",
            successful_extractable
        )
        self._set_runtime_grounding_value(
            verified_plan,
            execution_result,
            "successful_evidence_status_only",
            successful
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "evidence_total", len(evidence)
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "hybrid_mode", False
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "block_reason", ""
        )
        self._set_runtime_grounding_value(
            verified_plan, execution_result, "tool_execution_failed", False
        )
        if self._is_skill_catalog_context_plan(verified_plan):
            skill_ctx = verified_plan.get("_skill_catalog_context")
            skill_ctx = skill_ctx if isinstance(skill_ctx, dict) else {}
            selected_doc_ids = list(skill_ctx.get("selected_doc_ids") or [])
            if not selected_doc_ids and str(skill_ctx.get("selected_docs") or "").strip():
                selected_doc_ids = [
                    part.strip()
                    for part in str(skill_ctx.get("selected_docs") or "").split(",")
                    if str(part or "").strip()
                ]
            self._update_skill_catalog_trace(
                verified_plan,
                selected_hints=list(verified_plan.get("strategy_hints") or []),
                selected_docs=selected_doc_ids,
                strict_mode="answer_schema+semantic_postcheck",
                postcheck="pending",
            )

        # A2 Fix: routing/gate blocks (blueprint gate, policy gate) are NOT tech failures.
        # When a gate block has already generated its own user-facing message (e.g. RÜCKFRAGE),
        # grounding must not pile on with a spurious missing_evidence_fallback.
        # Gate blocks set _blueprint_gate_blocked=True in the plan.
        _gate_blocked = bool((verified_plan or {}).get("_blueprint_gate_blocked"))
        if _gate_blocked and require_evidence and successful_extractable < min_successful:
            return {
                "blocked": False,
                "blocked_reason": "routing_gate_block",
                "mode": "pass",
                "response": "",
                "evidence": evidence,
                "is_fact_query": is_fact_query,
                "has_tool_usage": has_tool_usage,
                "verified_plan": verified_plan,
                "policy": output_cfg,
            }

        # Interaktive Container-/Approval-/Routing-Zustände sind keine Tech-Failures.
        # Wenn Evidence nur aus ok + interaktiven Zuständen besteht, muss der Output
        # durchlaufen statt in einen generischen Grounding-Fallback zu kippen.
        _interactive_statuses = [
            str((e or {}).get("status") or "").strip().lower()
            for e in (evidence or [])
            if isinstance(e, dict) and is_interactive_tool_status((e or {}).get("status"))
        ]
        _all_failed_are_interactive = bool(_interactive_statuses) and all(
            str((e or {}).get("status") or "").strip().lower() == "ok"
            or is_interactive_tool_status((e or {}).get("status"))
            for e in (evidence or [])
            if isinstance(e, dict)
        )
        if _all_failed_are_interactive and require_evidence and successful_extractable < min_successful:
            blocked_reason = "routing_block"
            if "needs_clarification" in _interactive_statuses:
                blocked_reason = "needs_clarification"
            elif "pending_approval" in _interactive_statuses:
                blocked_reason = "pending_approval"
            return {
                "blocked": False,
                "blocked_reason": blocked_reason,
                "mode": "pass",
                "response": "",
                "evidence": evidence,
                "is_fact_query": is_fact_query,
                "has_tool_usage": has_tool_usage,
                "verified_plan": verified_plan,
                "policy": output_cfg,
            }

        if require_evidence and successful_extractable < min_successful:
            self._set_runtime_grounding_value(
                verified_plan, execution_result, "missing_evidence", True
            )
            has_tool_failures = any(
                str((item or {}).get("status", "")).strip().lower() in {"error", "skip", "partial", "unavailable"}
                for item in evidence
                if isinstance(item, dict)
            )
            if has_tool_failures and successful_extractable == 0:
                self._set_runtime_grounding_value(
                    verified_plan,
                    execution_result,
                    "tool_execution_failed",
                    True
                )
                self._set_runtime_grounding_value(
                    verified_plan,
                    execution_result,
                    "block_reason",
                    "tool_execution_failed"
                )
                return {
                    "blocked": False,
                    "blocked_reason": "tool_execution_failed",
                    "mode": "tool_execution_failed_fallback",
                    "response": self._build_tool_failure_fallback(evidence),
                    "evidence": evidence,
                    "is_fact_query": is_fact_query,
                    "has_tool_usage": has_tool_usage,
                    "verified_plan": verified_plan,
                    "policy": output_cfg,
                }
            fallback_mode = str(output_cfg.get("fallback_mode", "explicit_uncertainty"))
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "block_reason",
                "missing_evidence"
            )
            return {
                "blocked": False,
                "blocked_reason": "missing_evidence",
                "mode": "missing_evidence_fallback",
                "response": self._build_grounding_fallback(evidence, mode=fallback_mode),
                "evidence": evidence,
                "is_fact_query": is_fact_query,
                "has_tool_usage": has_tool_usage,
                "verified_plan": verified_plan,
                "policy": output_cfg,
            }

        strict_mode = str(output_cfg.get("fact_query_response_mode", "model")).strip().lower()
        if is_fact_query and has_tool_usage and strict_mode == "evidence_summary":
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "block_reason",
                "evidence_summary_mode"
            )
            return {
                "blocked": False,
                "blocked_reason": "evidence_summary_mode",
                "mode": "evidence_summary_fallback",
                "response": self._build_grounding_fallback(evidence, mode="summarize_evidence"),
                "evidence": evidence,
                "is_fact_query": is_fact_query,
                "has_tool_usage": has_tool_usage,
                "verified_plan": verified_plan,
                "policy": output_cfg,
            }
        if strict_mode in {"hybrid", "hybrid_model"}:
            self._set_runtime_grounding_value(
                verified_plan, execution_result, "hybrid_mode", True
            )

        return {
            "blocked": False,
            "mode": "pass",
            "response": "",
            "evidence": evidence,
            "is_fact_query": is_fact_query,
            "has_tool_usage": has_tool_usage,
            "verified_plan": verified_plan,
            "policy": output_cfg,
        }

    def _attempt_grounding_repair_once(
        self,
        *,
        verified_plan: Dict[str, Any],
        execution_result: Optional[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        output_cfg: Dict[str, Any],
        reason: str,
    ) -> str:
        if not bool(output_cfg.get("enable_postcheck_repair_once", True)):
            return ""
        if not isinstance(verified_plan, dict):
            return ""
        if bool(
            get_runtime_grounding_value(
                verified_plan,
                key="repair_attempted",
                default=False,
            )
        ):
            return ""

        self._set_runtime_grounding_value(
            verified_plan, execution_result, "repair_attempted", True
        )
        if self._is_container_query_contract_plan(verified_plan):
            repaired = self._build_container_safe_fallback(verified_plan, evidence)
            repaired_text = str(repaired or "").strip()
            if repaired_text:
                self._set_runtime_grounding_value(
                    verified_plan, execution_result, "repair_used", True
                )
                log_warning(
                    "[OutputLayer] Container postcheck repair used: "
                    f"reason={reason}"
                )
                return repaired_text
        repaired = self._build_grounding_fallback(evidence, mode="summarize_evidence")
        repaired_text = str(repaired or "").strip()
        if not repaired_text:
            return ""
        if "keinen verifizierten tool-nachweis" in repaired_text.lower():
            return ""

        self._set_runtime_grounding_value(
            verified_plan, execution_result, "repair_used", True
        )
        log_warning(
            "[OutputLayer] Grounding postcheck repair used: "
            f"reason={reason} mode=summarize_evidence"
        )
        return repaired_text

    def _grounding_postcheck(
        self,
        answer: str,
        verified_plan: Dict[str, Any],
        precheck: Dict[str, Any],
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not answer:
            return answer
        output_cfg = (precheck or {}).get("policy") or {}
        evidence = (precheck or {}).get("evidence") or []
        is_fact_query = bool((precheck or {}).get("is_fact_query", False))

        evidence_text_parts = self._collect_evidence_text_parts(evidence)
        evidence_blob = "\n".join(evidence_text_parts)
        fallback_mode = str(output_cfg.get("fallback_mode", "explicit_uncertainty"))
        analysis_guard_result = evaluate_analysis_turn_answer(
            answer,
            verified_plan=verified_plan,
            output_cfg=output_cfg,
            user_text=str(
                get_runtime_grounding_value(
                    verified_plan,
                    key="analysis_guard_user_text",
                    default="",
                )
                or ""
            ),
            memory_data_present=bool(
                get_runtime_grounding_value(
                    verified_plan,
                    key="analysis_guard_memory_present",
                    default=False,
                )
            ),
            evidence_text=evidence_blob,
            has_tool_usage=bool((precheck or {}).get("has_tool_usage", False)),
            is_fact_query=is_fact_query,
        )
        self._set_runtime_grounding_value(
            verified_plan,
            execution_result,
            "analysis_guard_evaluation",
            analysis_guard_result,
        )
        if analysis_guard_result.get("applicable") or str(verified_plan.get("_loop_trace_mode") or "").strip():
            log_info(
                "[OutputLayer] Analysis turn guard evaluated: "
                f"applicable={bool(analysis_guard_result.get('applicable'))} "
                f"trigger={analysis_guard_result.get('trigger_source') or 'none'} "
                f"skipped_reason={analysis_guard_result.get('skipped_reason') or 'none'} "
                f"violated={bool(analysis_guard_result.get('violated'))} "
                f"checked_chars={int(analysis_guard_result.get('checked_chars') or 0)}"
            )
        if analysis_guard_result.get("violated"):
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "violation_detected",
                True,
            )
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "fallback_used",
                True,
            )
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "repair_attempted",
                True,
            )
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "repair_used",
                True,
            )
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "analysis_guard_violation",
                analysis_guard_result,
            )
            log_warning(
                "[OutputLayer] Analysis turn guard repair used: "
                f"reasons={analysis_guard_result.get('reasons')}"
            )
            return build_analysis_turn_safe_fallback(
                verified_plan,
                user_text=str(
                    get_runtime_grounding_value(
                        verified_plan,
                        key="analysis_guard_user_text",
                        default="",
                    )
                    or ""
                ),
                reasons=list(analysis_guard_result.get("reasons") or []),
            )
        if not (is_fact_query and evidence):
            return answer

        # Strict-Mode: evidence vorhanden, aber kein extrahierbarer Content
        _strict_no_content = bool(evidence and not evidence_text_parts)
        if _strict_no_content:
            log_warning(
                "[OutputLayer] Grounding postcheck strict mode: "
                f"fact_query evidence present but no extractable content; "
                f"tools={[e.get('tool_name') for e in evidence]}"
            )
        if self._is_skill_catalog_context_plan(verified_plan):
            skill_ctx = verified_plan.get("_skill_catalog_context")
            skill_ctx = skill_ctx if isinstance(skill_ctx, dict) else {}
            selected_doc_ids = list(skill_ctx.get("selected_doc_ids") or [])
            if not selected_doc_ids and str(skill_ctx.get("selected_docs") or "").strip():
                selected_doc_ids = [
                    part.strip()
                    for part in str(skill_ctx.get("selected_docs") or "").split(",")
                    if str(part or "").strip()
                ]
            self._update_skill_catalog_trace(
                verified_plan,
                selected_hints=list(verified_plan.get("strategy_hints") or []),
                selected_docs=selected_doc_ids,
                strict_mode="answer_schema+semantic_postcheck",
            )

        if bool(output_cfg.get("forbid_new_numeric_claims", True)):
            answer_nums = set(self._extract_numeric_tokens(answer))
            evidence_nums = set(self._extract_numeric_tokens(evidence_blob))
            unknown = sorted(tok for tok in answer_nums if tok not in evidence_nums)
            if unknown:
                self._set_runtime_grounding_value(
                    verified_plan,
                    execution_result,
                    "violation_detected",
                    True
                )
                self._set_runtime_grounding_value(
                    verified_plan,
                    execution_result,
                    "fallback_used",
                    True
                )
                log_warning(
                    f"[OutputLayer] Grounding postcheck fallback: unknown numeric claims={unknown[:6]}"
                )
                repaired = self._attempt_grounding_repair_once(
                    verified_plan=verified_plan,
                    execution_result=execution_result,
                    evidence=evidence,
                    output_cfg=output_cfg,
                    reason="unknown_numeric_claims",
                )
                if repaired:
                    return repaired
                return self._build_grounding_fallback(evidence, mode=fallback_mode)

        skill_catalog_result = self._evaluate_skill_catalog_semantic_leakage(
            answer=answer,
            verified_plan=verified_plan,
            evidence=evidence,
        )
        if skill_catalog_result.get("violated"):
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "violation_detected",
                True
            )
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "fallback_used",
                True
            )
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "skill_catalog_violation",
                skill_catalog_result
            )
            self._update_skill_catalog_trace(
                verified_plan,
                postcheck=f"repaired:{skill_catalog_result.get('reason')}",
            )
            repaired = self._build_skill_catalog_safe_fallback(verified_plan, evidence)
            repaired_text = str(repaired or "").strip()
            if repaired_text:
                self._set_runtime_grounding_value(
                    verified_plan, execution_result, "repair_attempted", True
                )
                self._set_runtime_grounding_value(
                    verified_plan, execution_result, "repair_used", True
                )
                log_warning(
                    "[OutputLayer] Skill catalog postcheck repair used: "
                    f"reason={skill_catalog_result.get('reason')}"
                )
                return repaired_text
            self._update_skill_catalog_trace(
                verified_plan,
                postcheck="fallback_summary",
            )
            return self._build_grounding_fallback(evidence, mode="summarize_evidence")

        container_result = self._evaluate_container_contract_leakage(
            answer=answer,
            verified_plan=verified_plan,
            evidence=evidence,
        )
        if container_result.get("violated"):
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "violation_detected",
                True
            )
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "fallback_used",
                True
            )
            repaired = self._build_container_safe_fallback(verified_plan, evidence)
            repaired_text = str(repaired or "").strip()
            if repaired_text:
                self._set_runtime_grounding_value(
                    verified_plan, execution_result, "repair_attempted", True
                )
                self._set_runtime_grounding_value(
                    verified_plan, execution_result, "repair_used", True
                )
                log_warning(
                    "[OutputLayer] Container contract repair used: "
                    f"reason={container_result.get('reason')}"
                )
                return repaired_text
            return self._build_grounding_fallback(evidence, mode="summarize_evidence")

        qualitative_guard = output_cfg.get("qualitative_claim_guard", {})
        if bool(output_cfg.get("forbid_unverified_qualitative_claims", True)):
            _effective_guard = dict(qualitative_guard)
            if _strict_no_content:
                # Bei leerem Evidence-Blob: kein sentence_violations-Requirement,
                # niedrigere overall-Schwelle
                _effective_guard["min_assertive_sentence_violations"] = 0
                _effective_guard["max_overall_novelty_ratio"] = 0.5
            qualitative_result = self._evaluate_qualitative_grounding(
                answer=answer,
                evidence_blob=evidence_blob,
                guard_cfg=_effective_guard,
            )
            if qualitative_result.get("violated"):
                self._set_runtime_grounding_value(
                    verified_plan,
                    execution_result,
                    "violation_detected",
                    True
                )
                self._set_runtime_grounding_value(
                    verified_plan,
                    execution_result,
                    "fallback_used",
                    True
                )
                self._set_runtime_grounding_value(
                    verified_plan,
                    execution_result,
                    "qualitative_violation",
                    qualitative_result
                )
                log_warning(
                    "[OutputLayer] Grounding postcheck fallback: "
                    f"qualitative novelty ratio={qualitative_result.get('overall_novelty_ratio')}"
                )
                repaired = self._attempt_grounding_repair_once(
                    verified_plan=verified_plan,
                    execution_result=execution_result,
                    evidence=evidence,
                    output_cfg=output_cfg,
                    reason="qualitative_novelty",
                )
                if repaired:
                    return repaired
                return self._build_grounding_fallback(evidence, mode=fallback_mode)

        if self._is_skill_catalog_context_plan(verified_plan):
            self._update_skill_catalog_trace(
                verified_plan,
                postcheck="passed",
            )
        return answer

    @staticmethod
    def _resolve_stream_postcheck_mode(precheck_policy: Dict[str, Any]) -> str:
        mode = str((precheck_policy or {}).get("stream_postcheck_mode", "")).strip().lower()
        if mode in {"tail_repair", "buffered", "off"}:
            return mode
        return str(get_output_stream_postcheck_mode() or "tail_repair").strip().lower()

    @classmethod
    def _should_buffer_stream_postcheck(
        cls,
        verified_plan: Dict[str, Any],
        precheck_policy: Dict[str, Any],
        *,
        postcheck_enabled: bool,
    ) -> bool:
        if not postcheck_enabled:
            return False
        if bool((verified_plan or {}).get("_task_loop_step_runtime")):
            return False
        mode = cls._resolve_stream_postcheck_mode(precheck_policy)
        if mode == "off":
            return False
        if mode == "buffered":
            return True
        # skill_catalog_context and strict container contracts keep repair
        # invisible to the user while still preserving postcheck/trace observability.
        return (
            cls._is_skill_catalog_context_plan(verified_plan)
            or cls._is_container_query_contract_plan(verified_plan)
            or is_analysis_turn_guard_applicable(
                verified_plan,
                output_cfg=precheck_policy,
                has_tool_usage=bool(str(get_runtime_tool_results(verified_plan) or "").strip()),
                is_fact_query=bool(verified_plan.get("is_fact_query", False)),
            )
        )

    def _stream_postcheck_enabled(self, precheck: Dict[str, Any]) -> bool:
        policy = (precheck or {}).get("policy") or {}
        if self._resolve_stream_postcheck_mode(policy) == "off":
            return False
        if is_analysis_turn_guard_applicable(
            (precheck or {}).get("verified_plan") or {},
            output_cfg=policy,
            has_tool_usage=bool((precheck or {}).get("has_tool_usage", False)),
            is_fact_query=bool((precheck or {}).get("is_fact_query", False)),
        ):
            return True
        return bool(
            precheck.get("is_fact_query")
            and (
                bool(policy.get("forbid_new_numeric_claims", True))
                or bool(policy.get("forbid_unverified_qualitative_claims", True))
            )
        )

    @staticmethod
    def _extract_word_tokens(text: str, min_len: int) -> List[str]:
        if not text:
            return []
        pattern = re.compile(r"[a-zA-Z0-9äöüÄÖÜß_-]+")
        out: List[str] = []
        for raw in pattern.findall(str(text)):
            token = str(raw).strip().lower()
            if len(token) < min_len:
                continue
            if token.isdigit():
                continue
            out.append(token)
        return out

    def _collect_evidence_text_parts(self, evidence: List[Dict[str, Any]]) -> List[str]:
        evidence_text_parts: List[str] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            facts = item.get("key_facts")
            if isinstance(facts, list):
                evidence_text_parts.extend(str(x) for x in facts if str(x).strip())
            metrics = item.get("metrics")
            if isinstance(metrics, dict):
                evidence_text_parts.extend(str(v) for v in metrics.values())
            elif isinstance(metrics, list):
                for metric in metrics:
                    if not isinstance(metric, dict):
                        continue
                    val = metric.get("value")
                    unit = metric.get("unit")
                    if val is not None:
                        evidence_text_parts.append(f"{val}{unit or ''}")
            structured = item.get("structured")
            if isinstance(structured, dict):
                for val in structured.values():
                    if isinstance(val, (str, int, float)):
                        evidence_text_parts.append(str(val))
        return evidence_text_parts

    def _evaluate_qualitative_grounding(
        self,
        *,
        answer: str,
        evidence_blob: str,
        guard_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        cfg = guard_cfg if isinstance(guard_cfg, dict) else {}
        min_len = max(2, int(cfg.get("min_token_length", 5) or 5))
        max_overall_ratio = float(cfg.get("max_overall_novelty_ratio", 0.72) or 0.72)
        max_sentence_ratio = float(cfg.get("max_sentence_novelty_ratio", 0.82) or 0.82)
        min_sentence_tokens = max(1, int(cfg.get("min_sentence_tokens", 4) or 4))
        min_sentence_violations = max(
            0, int(cfg.get("min_assertive_sentence_violations", 1) or 0)
        )
        assertive_cues = [
            str(cue).strip().lower()
            for cue in cfg.get("assertive_cues", [])
            if str(cue).strip()
        ]
        ignored = {
            str(tok).strip().lower()
            for tok in cfg.get("ignored_tokens", [])
            if str(tok).strip()
        }

        evidence_tokens = {
            tok
            for tok in self._extract_word_tokens(evidence_blob, min_len=min_len)
            if tok not in ignored
        }
        answer_tokens = [
            tok
            for tok in self._extract_word_tokens(answer, min_len=min_len)
            if tok not in ignored
        ]
        answer_unique = sorted(set(answer_tokens))
        if not answer_unique:
            return {"violated": False, "overall_novelty_ratio": 0.0, "sentence_violations": 0}

        novelty = [tok for tok in answer_unique if tok not in evidence_tokens]
        overall_ratio = len(novelty) / max(1, len(answer_unique))

        sentence_violations = 0
        for sentence in re.split(r"[.!?;\n]+", answer):
            sentence_text = sentence.strip()
            if not sentence_text:
                continue
            sentence_lower = sentence_text.lower()
            if assertive_cues and not any(
                re.search(rf"\b{re.escape(cue)}\b", sentence_lower) for cue in assertive_cues
            ):
                continue
            sentence_tokens = [
                tok
                for tok in self._extract_word_tokens(sentence_text, min_len=min_len)
                if tok not in ignored
            ]
            sentence_unique = sorted(set(sentence_tokens))
            if len(sentence_unique) < min_sentence_tokens:
                continue
            sentence_novelty = [tok for tok in sentence_unique if tok not in evidence_tokens]
            sentence_ratio = len(sentence_novelty) / max(1, len(sentence_unique))
            if sentence_ratio > max_sentence_ratio:
                sentence_violations += 1

        violated = bool(
            overall_ratio > max_overall_ratio
            and sentence_violations >= min_sentence_violations
        )
        return {
            "violated": violated,
            "overall_novelty_ratio": round(overall_ratio, 4),
            "sentence_violations": sentence_violations,
            "novel_tokens_sample": novelty[:8],
        }

    def _get_ollama_tools(self) -> List[Dict]:
        """Baut Ollama-native Tool-Definitionen aus MCPHub."""
        hub = get_hub()
        hub.initialize()
        tool_defs = hub.list_tools()

        ollama_tools = []
        for tool_def in tool_defs:
            name = tool_def.get("name", "")
            desc = tool_def.get("description", "")
            input_schema = tool_def.get("inputSchema", {})

            if not name:
                continue

            # Convert MCP format → Ollama format
            ollama_tool = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": input_schema if input_schema else {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
            ollama_tools.append(ollama_tool)

        log_debug(f"[OutputLayer] {len(ollama_tools)} tools prepared for Ollama")
        return ollama_tools

    def build_system_prompt(
        self, 
        verified_plan: Dict[str, Any], 
        memory_data: str,
        memory_required_but_missing: bool = False,
        needs_chat_history: bool = False
    ) -> str:
        """Baut den System-Prompt mit Persona und Kontext."""
        persona = get_persona()
        prompt_parts = []
        
        # Persona-Basis mit dynamischen Tools
        available_tools = self._resolve_tools_for_prompt(verified_plan)
        dynamic_context = {"tools": available_tools} if available_tools else None
        prompt_parts.append(persona.build_system_prompt(dynamic_context=dynamic_context))
        
        # Anti-Halluzination
        if memory_required_but_missing:
            prompt_parts.append("\n### ANTI-HALLUZINATION:")
            prompt_parts.append(
                "Die angefragte Information wurde explizit im Gedächtnis gesucht "
                "und wurde NICHT gefunden."
            )
            prompt_parts.append(
                "Du kennst die Antwort NICHT. "
                "Sage klar: 'Das habe ich nicht gespeichert' oder 'Das weiß ich leider nicht.' "
                "NIEMALS raten. NIEMALS Namen, Zahlen oder Fakten erfinden — "
                "auch nicht als Beispiel, Platzhalter oder Schätzung."
            )
        
        # Chat-History Hinweis
        if needs_chat_history:
            prompt_parts.append("\n### CHAT-HISTORY:")
            prompt_parts.append("Beantworte basierend auf der bisherigen Konversation.")
        
        # Control-Layer Anweisung
        instruction = get_policy_final_instruction(verified_plan)
        if instruction:
            prompt_parts.append(f"\n### ANWEISUNG:\n{instruction}")
        
        # Memory-Daten
        if memory_data:
            prompt_parts.append(f"\n### FAKTEN AUS DEM GEDÄCHTNIS:\n{memory_data}")
            prompt_parts.append("NUTZE diese Fakten!")

        # Output grounding rules (policy-driven; only for factual/tool-backed turns)
        is_fact_query = bool(verified_plan.get("is_fact_query", False))
        has_tool_usage = bool(str(get_runtime_tool_results(verified_plan) or "").strip())
        if is_fact_query or has_tool_usage:
            prompt_parts.append("\n### OUTPUT-GROUNDING:")
            prompt_parts.append("Nutze nur belegbare Fakten aus Kontext und Tool-Cards.")
            prompt_parts.append("Wenn ein Fakt nicht belegt ist, markiere ihn als 'nicht verifiziert'.")
            prompt_parts.append("Keine neuen Zahlen/Specs ohne expliziten Nachweis.")
            prompt_parts.append("Tools wurden bereits ausgeführt. Gib KEINE neuen Tool-Aufrufe aus.")
            prompt_parts.append("Gib niemals [TOOL-CALL]-Blöcke, JSON-Toolcalls oder Kommando-Pläne aus.")
            prompt_parts.append("Antworte stattdessen direkt mit Ergebnis, Befund oder klarer Lücke.")
            if bool(
                get_runtime_grounding_value(
                    verified_plan,
                    key="hybrid_mode",
                    default=False,
                )
            ):
                prompt_parts.append("Antwort darf natürlich formuliert sein, muss aber vollständig evidenzgebunden bleiben.")
        elif is_analysis_turn_guard_applicable(
            verified_plan,
            output_cfg=load_grounding_policy().get("output") or {},
            has_tool_usage=has_tool_usage,
            is_fact_query=is_fact_query,
        ):
            prompt_parts.append("\n### ANALYSE-GUARD:")
            prompt_parts.append("Behandle diese Antwort als konzeptionelle Analyse ohne Runtime-Nachweise.")
            prompt_parts.append("Behaupte keine Gedaechtnis-, Hardware-, VRAM/RAM-, Container-, Blueprint- oder Systemstatus-Fakten, sofern sie nicht explizit im Kontext stehen.")
            prompt_parts.append("Markiere unbelegte Punkte klar als 'nicht verifiziert'.")
            prompt_parts.append("Erfinde keine abgeschlossenen Checks, Systempruefungen oder bereits erledigten Schritte.")
            prompt_parts.append("Wenn nur ein sicherer Zwischenstand moeglich ist, sage das direkt.")

        if self._is_container_query_contract_plan(verified_plan):
            prompt_parts.extend(self._build_container_prompt_rules(verified_plan))

        if self._is_skill_catalog_context_plan(verified_plan):
            prompt_parts.extend(self._build_skill_catalog_prompt_rules(verified_plan))
        
        # Warnungen
        warnings = get_policy_warnings(verified_plan)
        if warnings:
            prompt_parts.append("\n### WARNUNGEN:")
            for w in warnings:
                prompt_parts.append(f"- {w}")

        # Runtime mode hint
        response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
        budgets = self._resolve_output_budgets(verified_plan)
        soft_target = budgets["soft_target"]
        hard_cap = budgets["hard_cap"]
        length_hint = self._normalize_length_hint(verified_plan.get("response_length_hint"))
        dialogue_act = str(verified_plan.get("dialogue_act") or "").strip().lower()
        response_tone = str(verified_plan.get("response_tone") or "").strip().lower()
        try:
            tone_confidence = float(verified_plan.get("tone_confidence") or 0.0)
        except Exception:
            tone_confidence = 0.0

        if response_mode != "deep":
            prompt_parts.append("\n### ANTWORT-BUDGET:")
            prompt_parts.append(
                f"Ziel (weich): ca. {soft_target} Zeichen. "
                f"Harte Grenze: {hard_cap if hard_cap > 0 else 'deaktiviert'} Zeichen."
            )
            prompt_parts.append("Priorisiere klare Antworten; bei Bedarf lieber in 2 kurzen Schritten antworten.")
        else:
            prompt_parts.append("\n### ANTWORT-BUDGET:")
            prompt_parts.append(
                f"Deep-Modus Ziel (weich): ca. {soft_target} Zeichen. "
                f"Harte Grenze: {hard_cap if hard_cap > 0 else 'deaktiviert'} Zeichen."
            )
        
        # Sequential Thinking Ergebnisse
        sequential_result = verified_plan.get("_sequential_result")
        if sequential_result and sequential_result.get("success"):
            prompt_parts.append("\n### VORAB-ANALYSE (Sequential Thinking):")
            full_response = sequential_result.get("full_response", "")
            if full_response and not full_response.startswith("[Ollama Error"):
                prompt_parts.append(full_response[:4000])
            else:
                steps = sequential_result.get("steps", [])
                for step in steps[:10]:
                    step_num = step.get("step", "?")
                    title = step.get("title", "")
                    thought = step.get("thought", "")[:500]
                    prompt_parts.append(f"**Step {step_num}: {title}**")
                    prompt_parts.append(thought)
            prompt_parts.append("\nFASSE diese Analyse zusammen und formuliere eine klare Antwort.")
        
        # Stil
        style = verified_plan.get("suggested_response_style", "")
        if style:
            prompt_parts.append(f"\n### STIL: Antworte {style}.")

        # Dialogue act / tone guidance (hybrid signal)
        if dialogue_act or response_tone:
            prompt_parts.append("\n### DIALOG-FÜHRUNG:")
            if dialogue_act:
                prompt_parts.append(f"- dialogue_act: {dialogue_act}")
            if response_tone:
                prompt_parts.append(f"- response_tone: {response_tone}")
            prompt_parts.append(f"- response_length_hint: {length_hint}")
            prompt_parts.append(f"- tone_confidence: {tone_confidence:.2f}")

            if response_tone == "mirror_user":
                prompt_parts.append("Spiegle Ton und Energie des Users, ohne künstlich zu wirken.")
            elif response_tone == "warm":
                prompt_parts.append("Antworte warm, zugewandt und direkt.")
            elif response_tone == "formal":
                prompt_parts.append("Antworte sachlich-formal und präzise.")
            else:
                prompt_parts.append("Antworte neutral, klar und kooperativ.")

            if dialogue_act in {"ack", "feedback"} and response_mode != "deep":
                prompt_parts.append("Bei Bestätigung/Feedback: kurz antworten (1-3 Sätze), keine Bulletpoints.")
            elif dialogue_act == "smalltalk":
                prompt_parts.append(
                    "Bei Smalltalk: keine erfundenen persönlichen Erlebnisse oder Nutzergeschichten behaupten."
                )
                prompt_parts.append(
                    "Wenn nach deinem \"Tag\" gefragt wird, transparent als Assistenzsystem ohne menschlichen Alltag antworten."
                )
            elif length_hint == "short":
                prompt_parts.append("Halte die Antwort kurz.")
            elif length_hint == "long":
                prompt_parts.append("Antwort darf ausführlicher sein, aber strukturiert bleiben.")
        
        return "\n".join(prompt_parts)

    @staticmethod
    def _extract_selected_tool_names(verified_plan: Dict[str, Any]) -> List[str]:
        """
        Extract selected tool names from verified plan metadata.
        """
        raw = []
        if isinstance(verified_plan, dict):
            raw = (
                verified_plan.get("_selected_tools_for_prompt")
                or verified_plan.get("suggested_tools")
                or []
            )

        names: List[str] = []
        seen = set()
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("tool") or item.get("name") or "").strip()
            else:
                name = str(item).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def _resolve_tools_for_prompt(self, verified_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolve tool list injected into Output system prompt.
        """
        mode = get_output_tool_injection_mode()
        limit = get_output_tool_prompt_limit()
        all_tools = get_enabled_tools()

        if mode == "none":
            return []
        if mode == "all":
            return all_tools[:limit]

        # selected (default): only tools chosen for the current request.
        selected_names = self._extract_selected_tool_names(verified_plan)
        if not selected_names:
            return []

        selected = []
        by_name = {t.get("name"): t for t in all_tools if t.get("name")}
        for name in selected_names:
            item = by_name.get(name)
            if item:
                selected.append(item)
            else:
                selected.append({
                    "name": name,
                    "mcp": "unknown",
                    "description": "Selected for current request",
                })
            if len(selected) >= limit:
                break
        return selected
    
    def _build_messages(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        memory_required_but_missing: bool = False,
        chat_history: list = None
    ) -> List[Dict[str, str]]:
        """Baut Messages-Array für /api/chat (statt prompt für /api/generate)."""
        
        needs_chat_history = verified_plan.get("needs_chat_history", False)
        system_prompt = self.build_system_prompt(
            verified_plan, memory_data, memory_required_but_missing,
            needs_chat_history=needs_chat_history
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Chat-History einbauen
        if chat_history and len(chat_history) > 1:
            history_to_show = chat_history[-11:-1] if len(chat_history) > 11 else chat_history[:-1]
            for msg in history_to_show:
                role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                content = msg.content
                if role == "user":
                    messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    messages.append({"role": "assistant", "content": content})
        
        # Aktuelle User-Nachricht — single-truth: no duplicate tool/protocol injection here.
        messages.append({"role": "user", "content": user_text})

        return messages
    
    # ═══════════════════════════════════════════════════════════
    # ASYNC STREAMING WITH TOOL LOOP
    # ═══════════════════════════════════════════════════════════
    async def generate_stream(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = None,
        memory_required_but_missing: bool = False,
        chat_history: list = None,
        control_decision: Optional[ControlDecision] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Generiert Antwort als Stream MIT nativem Tool Calling.
        
        Flow:
        1. Sende Messages + Tools an Ollama /api/chat
        2. Wenn Modell Tool aufruft: execute via MCPHub
        3. Injiziere Ergebnis als tool-message
        4. Wiederhole bis Text-Antwort kommt (max MAX_TOOL_ITERATIONS)
        5. Streame die Text-Antwort zum Frontend
        """
        direct_response = get_runtime_direct_response(verified_plan)
        if direct_response:
            log_info("[OutputLayer] Direct response short-circuit (tool-backed)")
            yield direct_response
            return

        model = (model or "").strip() or get_output_model()
        response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
        budgets = self._resolve_output_budgets(verified_plan)
        char_cap = int(budgets["hard_cap"])
        soft_target = int(budgets["soft_target"])
        verified_plan["_length_policy"] = {
            "response_mode": response_mode,
            "hard_cap": char_cap,
            "soft_target": soft_target,
            "length_hint": self._normalize_length_hint(verified_plan.get("response_length_hint")),
        }
        timeout_s = verified_plan.get("_output_time_budget_s")
        if timeout_s is None:
            timeout_s = (
                get_output_timeout_deep_s()
                if response_mode == "deep"
                else get_output_timeout_interactive_s()
            )
        try:
            timeout_s = float(timeout_s)
        except Exception:
            timeout_s = float(get_output_timeout_interactive_s())
        timeout_s = max(5.0, min(300.0, timeout_s))
        messages = self._build_messages(
            user_text, verified_plan, memory_data,
            memory_required_but_missing, chat_history
        )
        self._set_runtime_grounding_value(
            verified_plan,
            execution_result,
            "analysis_guard_user_text",
            user_text,
        )
        self._set_runtime_grounding_value(
            verified_plan,
            execution_result,
            "analysis_guard_memory_present",
            bool(str(memory_data or "").strip()),
        )
        precheck = self._grounding_precheck(verified_plan, memory_data, execution_result=execution_result)
        if str(precheck.get("mode", "")).strip().lower() in {
            "tool_execution_failed_fallback",
            "missing_evidence_fallback",
            "evidence_summary_fallback",
        }:
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "fallback_used",
                True
            )
            yield str(precheck.get("response") or "")
            return
        postcheck_policy = precheck.get("policy") or {}
        postcheck_enabled = self._stream_postcheck_enabled(precheck)
        # Legacy mode keeps full buffering; skill_catalog_context also buffers
        # so repaired grounding does not leak as a visible correction block.
        buffer_for_postcheck = self._should_buffer_stream_postcheck(
            verified_plan,
            postcheck_policy,
            postcheck_enabled=postcheck_enabled,
        )

        # Observability parity with sync path.
        ctx_trace = verified_plan.get("_ctx_trace", {}) if isinstance(verified_plan, dict) else {}
        mode = ctx_trace.get("mode", "unknown")
        context_sources = ctx_trace.get("context_sources", [])
        retrieval_count = ctx_trace.get("retrieval_count", 0)
        payload_chars = len(memory_data or "")
        log_info(
            f"[CTX-FINAL] mode={mode} context_sources={context_sources} "
            f"payload_chars={payload_chars} retrieval_count={retrieval_count}"
        )
        
        # === Tool-Ergebnisse sind bereits im memory_data/verified_plan vom Orchestrator ===
        # === Kein Tool Loop nötig — Orchestrator hat Tools schon ausgeführt ===
        
        provider = resolve_role_provider("output", default=get_output_provider())
        try:
            endpoint = self.ollama_base
            if provider == "ollama":
                route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
                log_info(
                    f"[Routing] role=output provider=ollama requested_target={route['requested_target']} "
                    f"effective_target={route['effective_target'] or 'none'} "
                    f"fallback={bool(route['fallback_reason'])} "
                    f"fallback_reason={route['fallback_reason'] or 'none'} "
                    f"endpoint_source={route['endpoint_source']}"
                )
                if route["hard_error"]:
                    yield "Entschuldigung, Output-Compute ist aktuell nicht verfügbar."
                    return
                endpoint = route["endpoint"] or self.ollama_base
            else:
                log_info(f"[Routing] role=output provider={provider} endpoint=cloud")

            # === STREAMING RESPONSE via /api/chat ===
            log_debug(f"[OutputLayer] Streaming response provider={provider} model={model}...")
            total_chars = 0
            truncated = False
            buffered_chunks: List[str] = []
            postcheck_chunks: List[str] = []

            async for chunk in stream_chat(
                provider=provider,
                model=model,
                messages=messages,
                timeout_s=timeout_s,
                ollama_endpoint=endpoint,
            ):
                if not chunk:
                    continue
                if char_cap > 0 and total_chars >= char_cap:
                    truncated = True
                    break
                if char_cap > 0 and total_chars + len(chunk) > char_cap:
                    keep = max(0, char_cap - total_chars)
                    if keep > 0:
                        _chunk_out = chunk[:keep]
                        if postcheck_enabled:
                            postcheck_chunks.append(_chunk_out)
                        if buffer_for_postcheck:
                            buffered_chunks.append(_chunk_out)
                        else:
                            yield _chunk_out
                        total_chars += keep
                    truncated = True
                    break
                total_chars += len(chunk)
                if postcheck_enabled:
                    postcheck_chunks.append(chunk)
                if buffer_for_postcheck:
                    buffered_chunks.append(chunk)
                else:
                    yield chunk

            if truncated:
                trunc_note = (
                    "\n\n[Antwort gekürzt: Interaktiv-Budget erreicht. "
                    "Wenn du willst, führe ich direkt fort.]"
                    if response_mode != "deep"
                    else "\n\n[Antwort gekürzt: Deep-Mode Output-Budget erreicht.]"
                )
                if buffer_for_postcheck:
                    buffered_chunks.append(trunc_note)
                else:
                    yield trunc_note

            if postcheck_enabled:
                merged = "".join(postcheck_chunks)
                checked = self._grounding_postcheck(
                    merged,
                    verified_plan,
                    precheck,
                    execution_result=execution_result,
                )
                changed = checked != merged
                if changed and not bool(
                    get_runtime_grounding_value(
                        verified_plan,
                        key="repair_used",
                        default=False,
                    )
                ):
                    self._set_runtime_grounding_value(
                        verified_plan,
                        execution_result,
                        "fallback_used",
                        True
                    )

                if buffer_for_postcheck:
                    if changed:
                        yield checked
                    else:
                        for part in buffered_chunks:
                            yield part
                elif changed:
                    # Stream-first behavior: preserve low TTFT, append correction only when needed.
                    yield "\n\n[Grounding-Korrektur]\n"
                    yield checked
            
            log_info(
                f"[OutputLayer] Streamed {total_chars} chars "
                f"(cap_hit={truncated}, soft_target={soft_target}, hard_cap={char_cap})"
            )
                
        except httpx.TimeoutException:
            log_error(f"[OutputLayer] Stream Timeout nach {timeout_s:.0f}s")
            yield "Entschuldigung, die Anfrage hat zu lange gedauert."
        except httpx.HTTPStatusError as e:
            log_error(f"[OutputLayer] Stream HTTP Error: {e.response.status_code}")
            yield f"Entschuldigung, Server-Fehler: {e.response.status_code}"
        except (httpx.ReadError, httpx.RemoteProtocolError) as e:
            log_error(f"[OutputLayer] Stream disconnected: {e}")
            yield "Verbindung zum Model wurde unterbrochen. Bitte Anfrage erneut senden."
        except httpx.ConnectError as e:
            log_error(f"[OutputLayer] Connection Error: {e}")
            yield "Entschuldigung, konnte keine Verbindung zum Model herstellen."
        except Exception as e:
            log_error(f"[OutputLayer] Error: {type(e).__name__}: {e}")
            yield f"Entschuldigung, es gab einen Fehler: {str(e)}"
    
    async def _chat_check_tools(
        self, 
        model: str, 
        messages: List[Dict], 
        tools: List[Dict]
    ) -> Optional[Dict]:
        """
        NON-STREAMING /api/chat call um zu prüfen ob Tool-Calls kommen.
        Returns: {"content": "...", "tool_calls": [...]} oder None
        """
        if not tools:
            return None
        
        try:
            provider = resolve_role_provider("output", default=get_output_provider())
            endpoint = self.ollama_base
            if provider == "ollama":
                route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
                if route["hard_error"]:
                    log_error(
                        f"[Routing] role=output hard_error=true code={route['error_code']} "
                        f"requested_target={route['requested_target']}"
                    )
                    return None
                endpoint = route["endpoint"] or self.ollama_base

            # Non-Ollama providers are currently text-only in Output.
            tool_payload = tools if provider == "ollama" else []
            result = await complete_chat(
                provider=provider,
                model=model,
                messages=messages,
                timeout_s=90.0,
                ollama_endpoint=endpoint,
                tools=tool_payload,
            )
            tool_calls = result.get("tool_calls", []) if isinstance(result, dict) else []
            content = result.get("content", "") if isinstance(result, dict) else ""
            
            if tool_calls:
                return {"content": content, "tool_calls": tool_calls}
            
            return None  # Keine Tool-Calls → Text-Antwort
            
        except Exception as e:
            log_error(f"[OutputLayer] Tool check failed: {e}")
            return None
    
    # ═══════════════════════════════════════════════════════════
    # LEGACY: _build_full_prompt für Backward-Kompatibilität
    # ═══════════════════════════════════════════════════════════
    def _build_full_prompt(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        memory_required_but_missing: bool = False,
        chat_history: list = None
    ) -> str:
        """Legacy prompt builder für /api/generate Kompatibilität."""
        needs_chat_history = verified_plan.get("needs_chat_history", False)
        system_prompt = self.build_system_prompt(
            verified_plan, memory_data, memory_required_but_missing,
            needs_chat_history=needs_chat_history
        )
        prompt_parts = [system_prompt]
        
        if chat_history and len(chat_history) > 1:
            prompt_parts.append("\n\n### BISHERIGE KONVERSATION:")
            history_to_show = chat_history[-11:-1] if len(chat_history) > 11 else chat_history[:-1]
            for msg in history_to_show:
                role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                if role == "user":
                    prompt_parts.append(f"USER: {msg.content}")
                elif role == "assistant":
                    prompt_parts.append(f"ASSISTANT: {msg.content}")
        
        prompt_parts.append(f"\n\n### USER:\n{user_text}")
        prompt_parts.append("\n\n### DEINE ANTWORT:")
        return "\n".join(prompt_parts)
    
    # ═══════════════════════════════════════════════════════════
    # SYNC STREAMING (Legacy SSE-Kompatibilität)
    # ═══════════════════════════════════════════════════════════
    def generate_stream_sync(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = None,
        memory_required_but_missing: bool = False,
        chat_history: list = None,
        control_decision: Optional[ControlDecision] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ):
        """Synchroner Stream Generator. ACHTUNG: Blockiert! Nur in ThreadPool."""
        model = (model or "").strip() or get_output_model()
        provider = resolve_role_provider("output", default=get_output_provider())
        response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
        budgets = self._resolve_output_budgets(verified_plan)
        char_cap = int(budgets["hard_cap"])
        soft_target = int(budgets["soft_target"])
        verified_plan["_length_policy"] = {
            "response_mode": response_mode,
            "hard_cap": char_cap,
            "soft_target": soft_target,
            "length_hint": self._normalize_length_hint(verified_plan.get("response_length_hint")),
        }
        timeout_s = verified_plan.get("_output_time_budget_s")
        if timeout_s is None:
            timeout_s = (
                get_output_timeout_deep_s()
                if response_mode == "deep"
                else get_output_timeout_interactive_s()
            )
        try:
            timeout_s = float(timeout_s)
        except Exception:
            timeout_s = float(get_output_timeout_interactive_s())
        timeout_s = max(5.0, min(300.0, timeout_s))
        precheck = self._grounding_precheck(verified_plan, memory_data, execution_result=execution_result)
        if str(precheck.get("mode", "")).strip().lower() in {
            "tool_execution_failed_fallback",
            "missing_evidence_fallback",
            "evidence_summary_fallback",
        }:
            self._set_runtime_grounding_value(
                verified_plan,
                execution_result,
                "fallback_used",
                True
            )
            yield str(precheck.get("response") or "")
            return
        if provider != "ollama":
            log_warning(
                f"[OutputLayer] Sync stream path only supports ollama right now "
                f"(provider={provider}, model={model})"
            )
            yield (
                "Cloud-Provider ist aktiv. Dieser Legacy-Sync-Stream ist nur für Ollama verfügbar. "
                "Bitte nutze den normalen Streaming-Chatpfad."
            )
            return
        postcheck_policy = precheck.get("policy") or {}
        postcheck_enabled = self._stream_postcheck_enabled(precheck)
        buffer_for_postcheck = self._should_buffer_stream_postcheck(
            verified_plan,
            postcheck_policy,
            postcheck_enabled=postcheck_enabled,
        )
        full_prompt = self._build_full_prompt(
            user_text, verified_plan, memory_data,
            memory_required_but_missing, chat_history
        )

        # Observability parity with async path.
        ctx_trace = verified_plan.get("_ctx_trace", {}) if isinstance(verified_plan, dict) else {}
        mode = ctx_trace.get("mode", "unknown")
        context_sources = ctx_trace.get("context_sources", [])
        retrieval_count = ctx_trace.get("retrieval_count", 0)
        payload_chars = len(memory_data or "")
        log_info(
            f"[CTX-FINAL] mode={mode} context_sources={context_sources} "
            f"payload_chars={payload_chars} retrieval_count={retrieval_count}"
        )
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": True,
            "keep_alive": "5m",
        }
        
        try:
            route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
            log_info(
                f"[Routing] role=output requested_target={route['requested_target']} "
                f"effective_target={route['effective_target'] or 'none'} "
                f"fallback={bool(route['fallback_reason'])} "
                f"fallback_reason={route['fallback_reason'] or 'none'} "
                f"endpoint_source={route['endpoint_source']}"
            )
            if route["hard_error"]:
                yield "Fehler: Output-Compute nicht verfuegbar."
                return
            endpoint = route["endpoint"] or self.ollama_base

            log_debug(f"[OutputLayer] Sync streaming with {model}...")
            total_chars = 0
            truncated = False
            buffered_chunks: List[str] = []
            postcheck_chunks: List[str] = []
            
            with httpx.Client(timeout=timeout_s) as client:
                with client.stream(
                    "POST",
                    f"{endpoint}/api/generate",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                chunk = data.get("response", "")
                                if chunk:
                                    if char_cap > 0 and total_chars >= char_cap:
                                        truncated = True
                                        break
                                    if char_cap > 0 and total_chars + len(chunk) > char_cap:
                                        keep = max(0, char_cap - total_chars)
                                        if keep > 0:
                                            _chunk_out = chunk[:keep]
                                            if postcheck_enabled:
                                                postcheck_chunks.append(_chunk_out)
                                            if buffer_for_postcheck:
                                                buffered_chunks.append(_chunk_out)
                                            else:
                                                yield _chunk_out
                                            total_chars += keep
                                        truncated = True
                                        break
                                    total_chars += len(chunk)
                                    if postcheck_enabled:
                                        postcheck_chunks.append(chunk)
                                    if buffer_for_postcheck:
                                        buffered_chunks.append(chunk)
                                    else:
                                        yield chunk
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue

            if truncated:
                trunc_note = (
                    "\n\n[Antwort gekürzt: Interaktiv-Budget erreicht. "
                    "Wenn du willst, führe ich direkt fort.]"
                    if response_mode != "deep"
                    else "\n\n[Antwort gekürzt: Deep-Mode Output-Budget erreicht.]"
                )
                if buffer_for_postcheck:
                    buffered_chunks.append(trunc_note)
                else:
                    yield trunc_note

            if postcheck_enabled:
                merged = "".join(postcheck_chunks)
                checked = self._grounding_postcheck(
                    merged,
                    verified_plan,
                    precheck,
                    execution_result=execution_result,
                )
                changed = checked != merged
                if changed and not bool(
                    get_runtime_grounding_value(
                        verified_plan,
                        key="repair_used",
                        default=False,
                    )
                ):
                    self._set_runtime_grounding_value(
                        verified_plan,
                        execution_result,
                        "fallback_used",
                        True
                    )

                if buffer_for_postcheck:
                    if changed:
                        yield checked
                    else:
                        for part in buffered_chunks:
                            yield part
                elif changed:
                    yield "\n\n[Grounding-Korrektur]\n"
                    yield checked
            
            log_info(
                f"[OutputLayer] Sync streamed {total_chars} chars "
                f"(cap_hit={truncated}, soft_target={soft_target}, hard_cap={char_cap})"
            )
            
        except Exception as e:
            log_error(f"[OutputLayer] Sync stream error: {e}")
            yield f"Fehler: {str(e)}"

    async def generate(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = '',
        model: str = None,
        memory_required_but_missing: bool = False,
        chat_history: list = None,
        control_decision: Optional[ControlDecision] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Non-streaming generate (sammelt alle chunks)."""
        result = []
        async for chunk in self.generate_stream(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=memory_data,
            model=model,
            memory_required_but_missing=memory_required_but_missing,
            chat_history=chat_history,
            control_decision=control_decision,
            execution_result=execution_result,
        ):
            result.append(chunk)
        return ''.join(result)
