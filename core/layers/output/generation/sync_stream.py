"""
core.layers.output.generation.sync_stream
===========================================
Sync Streaming Generation — Legacy SSE-Kompatibilität.

generate_stream_sync  → sync Generator: nur Ollama /api/generate
ACHTUNG: Blockiert den aufrufenden Thread — nur in ThreadPool verwenden.
"""
import json
from typing import Any, Dict, List, Optional

import httpx

from utils.logger import log_debug, log_error, log_info, log_warning
from utils.role_endpoint_resolver import resolve_role_endpoint
from core.llm_provider_client import resolve_role_provider
from core.plan_runtime_bridge import get_runtime_grounding_value
from core.control_contract import ControlDecision
from config import (
    get_output_model,
    get_output_provider,
    get_output_timeout_interactive_s,
    get_output_timeout_deep_s,
)
from core.task_loop.runtime_policy import task_loop_output_timeout_override
from core.layers.output.prompt.budget import normalize_length_hint, resolve_output_budgets
from core.layers.output.prompt.system_prompt import build_full_prompt
from core.layers.output.grounding.precheck import grounding_precheck
from core.layers.output.grounding.postcheck import grounding_postcheck
from core.layers.output.grounding.stream import (
    should_buffer_stream_postcheck,
    stream_postcheck_enabled,
)
from core.layers.output.grounding.state import set_runtime_grounding_value
from core.layers.output.prompt.tool_injection import extract_selected_tool_names
from core.layers.output.prompt.notices import (
    output_grounding_correction_marker,
    output_notice,
    output_truncation_note,
)


def generate_stream_sync(
    ollama_base: str,
    user_text: str,
    verified_plan: Dict[str, Any],
    memory_data: str = "",
    model: str = None,
    memory_required_but_missing: bool = False,
    chat_history: list = None,
    control_decision: Optional[ControlDecision] = None,
    execution_result: Optional[Dict[str, Any]] = None,
):
    """
    Synchroner Stream-Generator via Ollama /api/generate.
    ACHTUNG: Blockiert — nur in ThreadPool verwenden!
    """
    model = (model or "").strip() or get_output_model()
    provider = resolve_role_provider("output", default=get_output_provider())
    response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
    budgets = resolve_output_budgets(verified_plan)
    char_cap = int(budgets["hard_cap"])
    soft_target = int(budgets["soft_target"])
    verified_plan["_length_policy"] = {
        "response_mode": response_mode,
        "hard_cap": char_cap,
        "soft_target": soft_target,
        "length_hint": normalize_length_hint(verified_plan.get("response_length_hint")),
    }

    timeout_s = task_loop_output_timeout_override(verified_plan)
    if timeout_s is None:
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

    precheck = grounding_precheck(
        verified_plan, memory_data,
        extract_selected_tool_names,
        execution_result=execution_result,
    )
    if str(precheck.get("mode", "")).strip().lower() in {
        "tool_execution_failed_fallback",
        "missing_evidence_fallback",
        "evidence_summary_fallback",
    }:
        set_runtime_grounding_value(verified_plan, execution_result, "fallback_used", True)
        yield str(precheck.get("response") or "")
        return

    if provider != "ollama":
        log_warning(
            f"[OutputLayer] Sync stream path only supports ollama right now "
            f"(provider={provider}, model={model})"
        )
        yield output_notice("output_sync_cloud_provider")
        return

    postcheck_policy = precheck.get("policy") or {}
    postcheck_enabled = stream_postcheck_enabled(precheck)
    buffer_for_postcheck = should_buffer_stream_postcheck(
        verified_plan, postcheck_policy, postcheck_enabled=postcheck_enabled,
    )
    full_prompt = build_full_prompt(
        user_text, verified_plan, memory_data,
        memory_required_but_missing, chat_history,
    )

    # Observability parity with async path.
    ctx_trace = verified_plan.get("_ctx_trace", {}) if isinstance(verified_plan, dict) else {}
    log_info(
        f"[CTX-FINAL] mode={ctx_trace.get('mode', 'unknown')} "
        f"context_sources={ctx_trace.get('context_sources', [])} "
        f"payload_chars={len(memory_data or '')} "
        f"retrieval_count={ctx_trace.get('retrieval_count', 0)}"
    )

    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": True,
        "keep_alive": "5m",
    }

    try:
        route = resolve_role_endpoint("output", default_endpoint=ollama_base)
        log_info(
            f"[Routing] role=output requested_target={route['requested_target']} "
            f"effective_target={route['effective_target'] or 'none'} "
            f"fallback={bool(route['fallback_reason'])} "
            f"fallback_reason={route['fallback_reason'] or 'none'} "
            f"endpoint_source={route['endpoint_source']}"
        )
        if route["hard_error"]:
            yield output_notice("output_error_sync_compute_unavailable")
            return
        endpoint = route["endpoint"] or ollama_base

        log_debug(f"[OutputLayer] Sync streaming with {model}...")
        total_chars = 0
        truncated = False
        buffered_chunks: List[str] = []
        postcheck_chunks: List[str] = []

        with httpx.Client(timeout=timeout_s) as client:
            with client.stream("POST", f"{endpoint}/api/generate", json=payload) as response:
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
            trunc_note = output_truncation_note(response_mode)
            if buffer_for_postcheck:
                buffered_chunks.append(trunc_note)
            else:
                yield trunc_note

        if postcheck_enabled:
            merged = "".join(postcheck_chunks)
            checked = grounding_postcheck(
                merged, verified_plan, precheck, execution_result=execution_result,
            )
            changed = checked != merged
            if changed and not bool(
                get_runtime_grounding_value(verified_plan, key="repair_used", default=False)
            ):
                set_runtime_grounding_value(verified_plan, execution_result, "fallback_used", True)

            if buffer_for_postcheck:
                if changed:
                    yield checked
                else:
                    for part in buffered_chunks:
                        yield part
            elif changed:
                yield output_grounding_correction_marker()
                yield checked

        log_info(
            f"[OutputLayer] Sync streamed {total_chars} chars "
            f"(cap_hit={truncated}, soft_target={soft_target}, hard_cap={char_cap})"
        )

    except Exception as e:
        log_error(f"[OutputLayer] Sync stream error: {e}")
        yield output_notice("output_error_sync_generic", error=str(e))
