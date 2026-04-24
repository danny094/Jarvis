"""
core.layers.output.generation.async_stream
============================================
Async Streaming Generation — Haupt-Ausgabepfad.

generate_stream  → AsyncGenerator: chunk-weiser Stream mit Grounding-Postcheck
generate         → str: sammelt alle Chunks (non-streaming Wrapper)
"""
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from utils.logger import log_debug, log_error, log_info
from utils.role_endpoint_resolver import resolve_role_endpoint
from core.llm_provider_client import resolve_role_provider, stream_chat
from core.plan_runtime_bridge import get_runtime_direct_response, get_runtime_grounding_value
from core.control_contract import ControlDecision
from config import (
    get_output_model,
    get_output_provider,
    get_output_timeout_interactive_s,
    get_output_timeout_deep_s,
)
from core.task_loop.runtime_policy import task_loop_output_timeout_override
from core.layers.output.prompt.budget import normalize_length_hint, resolve_output_budgets
from core.layers.output.prompt.system_prompt import build_messages
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


async def generate_stream(
    ollama_base: str,
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
    Generiert Antwort als Async-Stream.
    Tool-Ergebnisse werden vom Orchestrator vor diesem Aufruf in
    memory_data/verified_plan injiziert — kein Tool-Loop hier.
    """
    direct_response = get_runtime_direct_response(verified_plan)
    if direct_response:
        log_info("[OutputLayer] Direct response short-circuit (tool-backed)")
        yield direct_response
        return

    model = (model or "").strip() or get_output_model()
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

    messages = build_messages(
        user_text, verified_plan, memory_data,
        memory_required_but_missing, chat_history,
    )
    set_runtime_grounding_value(verified_plan, execution_result, "analysis_guard_user_text", user_text)
    set_runtime_grounding_value(
        verified_plan, execution_result,
        "analysis_guard_memory_present", bool(str(memory_data or "").strip()),
    )

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

    postcheck_policy = precheck.get("policy") or {}
    postcheck_enabled = stream_postcheck_enabled(precheck)
    buffer_for_postcheck = should_buffer_stream_postcheck(
        verified_plan, postcheck_policy, postcheck_enabled=postcheck_enabled,
    )

    # Observability parity with sync path.
    ctx_trace = verified_plan.get("_ctx_trace", {}) if isinstance(verified_plan, dict) else {}
    log_info(
        f"[CTX-FINAL] mode={ctx_trace.get('mode', 'unknown')} "
        f"context_sources={ctx_trace.get('context_sources', [])} "
        f"payload_chars={len(memory_data or '')} "
        f"retrieval_count={ctx_trace.get('retrieval_count', 0)}"
    )

    provider = resolve_role_provider("output", default=get_output_provider())
    try:
        endpoint = ollama_base
        if provider == "ollama":
            route = resolve_role_endpoint("output", default_endpoint=ollama_base)
            log_info(
                f"[Routing] role=output provider=ollama "
                f"requested_target={route['requested_target']} "
                f"effective_target={route['effective_target'] or 'none'} "
                f"fallback={bool(route['fallback_reason'])} "
                f"fallback_reason={route['fallback_reason'] or 'none'} "
                f"endpoint_source={route['endpoint_source']}"
            )
            if route["hard_error"]:
                yield output_notice("output_error_compute_unavailable")
                return
            endpoint = route["endpoint"] or ollama_base
        else:
            log_info(f"[Routing] role=output provider={provider} endpoint=cloud")

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
                # Stream-first: TTFT bleibt niedrig, Korrektur wird angehängt.
                yield output_grounding_correction_marker()
                yield checked

        log_info(
            f"[OutputLayer] Streamed {total_chars} chars "
            f"(cap_hit={truncated}, soft_target={soft_target}, hard_cap={char_cap})"
        )

    except httpx.TimeoutException:
        log_error(f"[OutputLayer] Stream Timeout nach {timeout_s:.0f}s")
        yield output_notice("output_error_timeout")
    except httpx.HTTPStatusError as e:
        log_error(f"[OutputLayer] Stream HTTP Error: {e.response.status_code}")
        yield output_notice("output_error_server", status_code=e.response.status_code)
    except (httpx.ReadError, httpx.RemoteProtocolError) as e:
        log_error(f"[OutputLayer] Stream disconnected: {e}")
        yield output_notice("output_error_disconnected")
    except httpx.ConnectError as e:
        log_error(f"[OutputLayer] Connection Error: {e}")
        yield output_notice("output_error_connect")
    except Exception as e:
        log_error(f"[OutputLayer] Error: {type(e).__name__}: {e}")
        yield output_notice("output_error_generic", error=str(e))


async def generate(
    ollama_base: str,
    user_text: str,
    verified_plan: Dict[str, Any],
    memory_data: str = "",
    model: str = None,
    memory_required_but_missing: bool = False,
    chat_history: list = None,
    control_decision: Optional[ControlDecision] = None,
    execution_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Non-streaming generate — sammelt alle Stream-Chunks."""
    result = []
    async for chunk in generate_stream(
        ollama_base=ollama_base,
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
    return "".join(result)
