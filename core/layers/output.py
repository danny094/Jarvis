# core/layers/output.py
"""
LAYER 3: OutputLayer v3.0
- Native Ollama Tool Calling via /api/chat
- Automatic tool loop (call → result → continue)
- Dynamic tool injection from MCPHub
- Streaming support with tool interrupts
"""

import json
import re
import httpx
from typing import Dict, Any, Optional, AsyncGenerator, List
from config import (
    OLLAMA_BASE,
    get_output_model,
    get_output_tool_injection_mode,
    get_output_tool_prompt_limit,
    get_output_char_cap_interactive,
    get_output_char_cap_interactive_long,
    get_output_char_cap_deep,
    get_output_char_target_interactive,
    get_output_char_target_deep,
    get_output_timeout_interactive_s,
    get_output_timeout_deep_s,
)
from utils.logger import log_info, log_error, log_debug, log_warning
from utils.role_endpoint_resolver import resolve_role_endpoint
from core.persona import get_persona
from core.grounding_policy import load_grounding_policy
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

        hard_cap = get_output_char_cap_deep() if response_mode == "deep" else get_output_char_cap_interactive()
        soft_target = (
            get_output_char_target_deep() if response_mode == "deep" else get_output_char_target_interactive()
        )

        if response_mode != "deep" and hard_cap > 0:
            if length_hint == "long" or dialogue_act == "analysis":
                hard_cap = max(hard_cap, get_output_char_cap_interactive_long())
                soft_target = max(soft_target, int(hard_cap * 0.72))

        if length_hint == "short":
            soft_target = int(soft_target * 0.62)
        elif length_hint == "long":
            soft_target = int(soft_target * 1.30)

        if hard_cap > 0:
            soft_target = min(soft_target, max(160, hard_cap - 80))
        soft_target = max(160, soft_target)

        return {
            "hard_cap": hard_cap,
            "soft_target": soft_target,
        }

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
        return "Skills: " + "; ".join(parts)

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

        from_plan = (verified_plan or {}).get("_grounding_evidence") or []
        if isinstance(from_plan, list):
            for item in from_plan:
                _push(item)

        carryover = (verified_plan or {}).get("_carryover_grounding_evidence") or []
        if isinstance(carryover, list):
            for item in carryover:
                _push(item)

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
            fact = ""
            if tool == "list_skills":
                fact = OutputLayer._summarize_list_skills_evidence(item)
            structured = item.get("structured")
            if isinstance(structured, dict):
                # Skills use "result"; other tools may use "output"
                output_text = str(
                    structured.get("output") or structured.get("result") or ""
                ).strip()
                if output_text:
                    fact = OutputLayer._summarize_structured_output(output_text, max_lines=4)
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
                                    parsed_fact.get("output") or parsed_fact.get("result") or ""
                                ).strip()
                                if out_text:
                                    fact = OutputLayer._summarize_structured_output(out_text, max_lines=4)
                        except Exception:
                            pass
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

    def _grounding_precheck(
        self,
        verified_plan: Dict[str, Any],
        memory_data: str,
    ) -> Dict[str, Any]:
        policy = load_grounding_policy()
        output_cfg = (policy or {}).get("output") or {}
        is_fact_query = bool((verified_plan or {}).get("is_fact_query", False))
        has_tool_usage = bool(str((verified_plan or {}).get("_tool_results", "") or "").strip())
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
                and bool(output_cfg.get("enforce_evidence_when_tools_suggested", True))
            )
        )

        verified_plan["_grounding_missing_evidence"] = False
        verified_plan["_grounding_violation_detected"] = False
        verified_plan["_grounded_fallback_used"] = False
        verified_plan["_grounding_repair_attempted"] = False
        verified_plan["_grounding_repair_used"] = False
        verified_plan["_grounding_successful_evidence"] = successful_extractable
        verified_plan["_grounding_successful_evidence_status_only"] = successful
        verified_plan["_grounding_evidence_total"] = len(evidence)
        verified_plan["_grounding_hybrid_mode"] = False

        if require_evidence and successful_extractable < min_successful:
            verified_plan["_grounding_missing_evidence"] = True
            fallback_mode = str(output_cfg.get("fallback_mode", "explicit_uncertainty"))
            return {
                "blocked": True,
                "response": self._build_grounding_fallback(evidence, mode=fallback_mode),
                "evidence": evidence,
                "is_fact_query": is_fact_query,
                "policy": output_cfg,
            }

        strict_mode = str(output_cfg.get("fact_query_response_mode", "model")).strip().lower()
        if is_fact_query and has_tool_usage and strict_mode == "evidence_summary":
            return {
                "blocked": True,
                "response": self._build_grounding_fallback(evidence, mode="summarize_evidence"),
                "evidence": evidence,
                "is_fact_query": is_fact_query,
                "policy": output_cfg,
            }
        if strict_mode in {"hybrid", "hybrid_model"}:
            verified_plan["_grounding_hybrid_mode"] = True

        return {
            "blocked": False,
            "response": "",
            "evidence": evidence,
            "is_fact_query": is_fact_query,
            "policy": output_cfg,
        }

    def _attempt_grounding_repair_once(
        self,
        *,
        verified_plan: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        output_cfg: Dict[str, Any],
        reason: str,
    ) -> str:
        if not bool(output_cfg.get("enable_postcheck_repair_once", True)):
            return ""
        if not isinstance(verified_plan, dict):
            return ""
        if verified_plan.get("_grounding_repair_attempted"):
            return ""

        verified_plan["_grounding_repair_attempted"] = True
        repaired = self._build_grounding_fallback(evidence, mode="summarize_evidence")
        repaired_text = str(repaired or "").strip()
        if not repaired_text:
            return ""
        if "keinen verifizierten tool-nachweis" in repaired_text.lower():
            return ""

        verified_plan["_grounding_repair_used"] = True
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
    ) -> str:
        if not answer:
            return answer
        output_cfg = (precheck or {}).get("policy") or {}
        evidence = (precheck or {}).get("evidence") or []
        is_fact_query = bool((precheck or {}).get("is_fact_query", False))
        if not (is_fact_query and evidence):
            return answer

        evidence_text_parts = self._collect_evidence_text_parts(evidence)
        evidence_blob = "\n".join(evidence_text_parts)
        fallback_mode = str(output_cfg.get("fallback_mode", "explicit_uncertainty"))

        # Strict-Mode: evidence vorhanden, aber kein extrahierbarer Content
        _strict_no_content = bool(evidence and not evidence_text_parts)
        if _strict_no_content:
            log_warning(
                "[OutputLayer] Grounding postcheck strict mode: "
                f"fact_query evidence present but no extractable content; "
                f"tools={[e.get('tool_name') for e in evidence]}"
            )

        if bool(output_cfg.get("forbid_new_numeric_claims", True)):
            answer_nums = set(self._extract_numeric_tokens(answer))
            evidence_nums = set(self._extract_numeric_tokens(evidence_blob))
            unknown = sorted(tok for tok in answer_nums if tok not in evidence_nums)
            if unknown:
                verified_plan["_grounding_violation_detected"] = True
                verified_plan["_grounded_fallback_used"] = True
                log_warning(
                    f"[OutputLayer] Grounding postcheck fallback: unknown numeric claims={unknown[:6]}"
                )
                repaired = self._attempt_grounding_repair_once(
                    verified_plan=verified_plan,
                    evidence=evidence,
                    output_cfg=output_cfg,
                    reason="unknown_numeric_claims",
                )
                if repaired:
                    return repaired
                return self._build_grounding_fallback(evidence, mode=fallback_mode)

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
                verified_plan["_grounding_violation_detected"] = True
                verified_plan["_grounded_fallback_used"] = True
                verified_plan["_grounding_qualitative_violation"] = qualitative_result
                log_warning(
                    "[OutputLayer] Grounding postcheck fallback: "
                    f"qualitative novelty ratio={qualitative_result.get('overall_novelty_ratio')}"
                )
                repaired = self._attempt_grounding_repair_once(
                    verified_plan=verified_plan,
                    evidence=evidence,
                    output_cfg=output_cfg,
                    reason="qualitative_novelty",
                )
                if repaired:
                    return repaired
                return self._build_grounding_fallback(evidence, mode=fallback_mode)

        return answer

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

    def _build_system_prompt(
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
            prompt_parts.append("Diese Info ist NICHT gespeichert. ERFINDE NICHTS.")
            prompt_parts.append("Sage: 'Das habe ich leider nicht gespeichert.'")
        
        # Chat-History Hinweis
        if needs_chat_history:
            prompt_parts.append("\n### CHAT-HISTORY:")
            prompt_parts.append("Beantworte basierend auf der bisherigen Konversation.")
        
        # Control-Layer Anweisung
        instruction = verified_plan.get("_final_instruction", "")
        if instruction:
            prompt_parts.append(f"\n### ANWEISUNG:\n{instruction}")
        
        # Memory-Daten
        if memory_data:
            prompt_parts.append(f"\n### FAKTEN AUS DEM GEDÄCHTNIS:\n{memory_data}")
            prompt_parts.append("NUTZE diese Fakten!")

        # Output grounding rules (policy-driven; only for factual/tool-backed turns)
        is_fact_query = bool(verified_plan.get("is_fact_query", False))
        has_tool_usage = bool(str(verified_plan.get("_tool_results", "") or "").strip())
        if is_fact_query or has_tool_usage:
            prompt_parts.append("\n### OUTPUT-GROUNDING:")
            prompt_parts.append("Nutze nur belegbare Fakten aus Kontext und Tool-Cards.")
            prompt_parts.append("Wenn ein Fakt nicht belegt ist, markiere ihn als 'nicht verifiziert'.")
            prompt_parts.append("Keine neuen Zahlen/Specs ohne expliziten Nachweis.")
            if bool(verified_plan.get("_grounding_hybrid_mode")):
                prompt_parts.append("Antwort darf natürlich formuliert sein, muss aber vollständig evidenzgebunden bleiben.")
        
        # Warnungen
        warnings = verified_plan.get("_warnings", [])
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
        system_prompt = self._build_system_prompt(
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
        chat_history: list = None
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
        precheck = self._grounding_precheck(verified_plan, memory_data)
        if precheck.get("blocked"):
            verified_plan["_grounded_fallback_used"] = True
            yield str(precheck.get("response") or "")
            return
        postcheck_policy = precheck.get("policy") or {}
        buffer_for_postcheck = bool(
            precheck.get("is_fact_query")
            and (
                bool(postcheck_policy.get("forbid_new_numeric_claims", True))
                or bool(postcheck_policy.get("forbid_unverified_qualitative_claims", True))
            )
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
                yield "Entschuldigung, Output-Compute ist aktuell nicht verfügbar."
                return
            endpoint = route["endpoint"] or self.ollama_base

            # === STREAMING RESPONSE via /api/chat ===
            log_debug(f"[OutputLayer] Streaming response with {model}...")
            total_chars = 0
            truncated = False
            buffered_chunks: List[str] = []
            
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                # Final request: stream=true, KEINE tools (erzwingt Text-Antwort)
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": "5m",
                }
                
                async with client.stream(
                    "POST",
                    f"{endpoint}/api/chat",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                msg = data.get("message", {})
                                chunk = msg.get("content", "")
                                if chunk:
                                    if char_cap > 0 and total_chars >= char_cap:
                                        truncated = True
                                        break
                                    if char_cap > 0 and total_chars + len(chunk) > char_cap:
                                        keep = max(0, char_cap - total_chars)
                                        if keep > 0:
                                            if buffer_for_postcheck:
                                                buffered_chunks.append(chunk[:keep])
                                            else:
                                                yield chunk[:keep]
                                            total_chars += keep
                                        truncated = True
                                        break
                                    total_chars += len(chunk)
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

            if buffer_for_postcheck:
                merged = "".join(buffered_chunks)
                checked = self._grounding_postcheck(merged, verified_plan, precheck)
                if checked != merged and not bool(verified_plan.get("_grounding_repair_used")):
                    verified_plan["_grounded_fallback_used"] = True
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
        
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "keep_alive": "5m",
        }
        
        try:
            route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
            if route["hard_error"]:
                log_error(
                    f"[Routing] role=output hard_error=true code={route['error_code']} "
                    f"requested_target={route['requested_target']}"
                )
                return None
            endpoint = route["endpoint"] or self.ollama_base

            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{endpoint}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
            
            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            content = msg.get("content", "")
            
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
        system_prompt = self._build_system_prompt(
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
        chat_history: list = None
    ):
        """Synchroner Stream Generator. ACHTUNG: Blockiert! Nur in ThreadPool."""
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
        precheck = self._grounding_precheck(verified_plan, memory_data)
        if precheck.get("blocked"):
            verified_plan["_grounded_fallback_used"] = True
            yield str(precheck.get("response") or "")
            return
        postcheck_policy = precheck.get("policy") or {}
        buffer_for_postcheck = bool(
            precheck.get("is_fact_query")
            and (
                bool(postcheck_policy.get("forbid_new_numeric_claims", True))
                or bool(postcheck_policy.get("forbid_unverified_qualitative_claims", True))
            )
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
                                            if buffer_for_postcheck:
                                                buffered_chunks.append(chunk[:keep])
                                            else:
                                                yield chunk[:keep]
                                            total_chars += keep
                                        truncated = True
                                        break
                                    total_chars += len(chunk)
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

            if buffer_for_postcheck:
                merged = "".join(buffered_chunks)
                checked = self._grounding_postcheck(merged, verified_plan, precheck)
                if checked != merged and not bool(verified_plan.get("_grounding_repair_used")):
                    verified_plan["_grounded_fallback_used"] = True
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
        chat_history: list = None
    ) -> str:
        """Non-streaming generate (sammelt alle chunks)."""
        result = []
        async for chunk in self.generate_stream(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=memory_data,
            model=model,
            memory_required_but_missing=memory_required_but_missing,
            chat_history=chat_history
        ):
            result.append(chunk)
        return ''.join(result)
