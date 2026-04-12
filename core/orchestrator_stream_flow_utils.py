import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, AsyncGenerator, List, Optional, Tuple


def _extract_blueprint_hint_from_history(messages: Optional[List[dict]], current_user_text: str) -> str:
    """
    A3 Fix: extract a blueprint name from recent chat history.
    See orchestrator_sync_flow_utils._extract_blueprint_hint_from_history for full docs.
    """
    if not messages:
        return ""
    current_lower = current_user_text.lower()
    pattern = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")
    skip = {"follow-up", "step-by-step", "well-known", "real-time", "up-to-date", "built-in"}
    for msg in reversed(messages[-6:]):
        content = str(msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "") or "")
        matches = pattern.findall(content.lower())
        for candidate in matches:
            if candidate in skip or len(candidate) < 5 or candidate in current_lower:
                continue
            return candidate
    return ""

from core.control_contract import (
    DoneReason,
    control_decision_from_plan,
    execution_result_from_plan,
    persist_control_decision,
    persist_execution_result,
    tool_allowed_by_control_decision,
)
from core.plan_runtime_bridge import (
    append_runtime_tool_results,
    get_runtime_grounding_evidence,
    get_runtime_grounding_value,
    get_runtime_tool_confidence,
    set_runtime_direct_response,
    set_runtime_grounding_evidence,
    set_runtime_successful_tool_runs,
    set_runtime_tool_confidence,
    set_runtime_tool_failure,
    set_runtime_tool_results,
)
from core.loop_trace import (
    build_loop_trace_completed_event,
    build_loop_trace_correction_event,
    build_loop_trace_plan_normalized_event,
    build_loop_trace_started_event,
    build_loop_trace_step_started_event,
    is_internal_loop_analysis_prompt,
)
from core.host_runtime_policy import (
    build_direct_host_runtime_response,
    build_host_runtime_blueprint_create_args,
    build_host_runtime_failure_response,
    build_host_runtime_exec_args,
    extract_blueprint_id_from_create_result,
)
from core.tool_hub_runtime import get_initialized_hub_safe


def _build_thinking_ui_payload(plan: Optional[Dict[str, Any]], **overrides: Any) -> Dict[str, Any]:
    """Expose a compact, UI-safe thinking summary without leaking raw internals."""
    base = dict(plan or {})
    ctx_trace = base.get("_ctx_trace") if isinstance(base.get("_ctx_trace"), dict) else {}
    skill_trace = ctx_trace.get("skill_catalog") if isinstance(ctx_trace.get("skill_catalog"), dict) else {}
    thinking_tools = list(base.get("_thinking_suggested_tools") or base.get("suggested_tools") or [])
    final_execution_tools = list(base.get("_final_execution_tools") or [])
    skill_route = base.get("_skill_catalog_tool_route") if isinstance(base.get("_skill_catalog_tool_route"), dict) else {}
    payload: Dict[str, Any] = {
        "intent": base.get("intent", "unknown"),
        "needs_memory": bool(base.get("needs_memory", False)),
        "memory_keys": list(base.get("memory_keys") or []),
        "needs_chat_history": bool(base.get("needs_chat_history", False)),
        "is_fact_query": bool(base.get("is_fact_query", False)),
        "suggested_tools": thinking_tools,
        "thinking_suggested_tools": thinking_tools,
        "final_execution_tools": final_execution_tools,
        "hallucination_risk": base.get("hallucination_risk", "medium"),
        "needs_sequential_thinking": bool(base.get("needs_sequential_thinking", False)),
        "response_length_hint": base.get("response_length_hint"),
        "resolution_strategy": (
            base.get("resolution_strategy")
            or base.get("_authoritative_resolution_strategy")
        ),
        "strategy_hints": list(base.get("strategy_hints") or []),
        "cached": bool(base.get("cached", False)),
        "skipped": bool(base.get("skipped", False)),
        "reason": base.get("reason"),
        "source": base.get("source"),
        "skill_catalog_hints": list(skill_trace.get("selected_hints") or []),
        "skill_catalog_docs": list(skill_trace.get("selected_docs") or []),
        "skill_catalog_strict_mode": skill_trace.get("strict_mode"),
        "skill_catalog_postcheck": skill_trace.get("postcheck"),
        "skill_catalog_thinking_tools": list(skill_trace.get("thinking_suggested_tools") or thinking_tools),
        "skill_catalog_final_execution_tools": list(skill_trace.get("final_execution_tools") or final_execution_tools),
        "skill_catalog_tool_route": skill_trace.get("tool_route_status") or skill_route.get("status"),
        "skill_catalog_tool_route_reason": skill_trace.get("tool_route_reason") or skill_route.get("reason"),
        "skill_catalog_policy_mode": skill_trace.get("policy_mode"),
        "skill_catalog_required_tools": list(skill_trace.get("required_tools") or []),
        "skill_catalog_force_sections": list(skill_trace.get("force_sections") or []),
        "loop_trace_mode": base.get("_loop_trace_mode"),
        "loop_trace_reason": (
            (base.get("_loop_trace_normalization") or {}).get("reason")
            if isinstance(base.get("_loop_trace_normalization"), dict)
            else None
        ),
        "loop_trace_corrections": (
            list((base.get("_loop_trace_normalization") or {}).get("corrections") or [])
            if isinstance(base.get("_loop_trace_normalization"), dict)
            else []
        ),
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}

async def process_stream_with_events(
    orch: Any,
    request: Any,
    *,
    intent_system_available: bool,
    enable_chunking: bool,
    chunking_threshold: int,
    get_master_settings_fn: Any,
    thinking_plan_cache: Any,
    sequential_result_cache: Any,
    soften_control_deny_fn: Any,
    skill_creation_intent_cls: Any,
    intent_origin_cls: Any,
    get_intent_store_fn: Any,
    log_info_fn: Any,
    log_warn_fn: Any,
    log_error_fn: Any,
    log_debug_fn: Any,
    log_warning_fn: Any,
) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
    """
    Phase 3: Native event-rich streaming (ported from bridge.py).
    
    Features:
    - Intent confirmation check
    - Chunking for large inputs
    - Live streaming thinking
    - Sequential thinking events  
    - Control layer with skill confirmation
    - Output streaming
    - Memory save
    """
    import time
    from config import ENABLE_CONTROL_LAYER, SKIP_CONTROL_ON_LOW_RISK
    
    _t0 = time.time()
    log_info_fn("[Orchestrator] process_stream_with_events (Phase 3)")
    
    # [NEW] Lifecycle Start
    req_id_str = f"stream-{int(time.time()*1000)}"
    _stream_lifecycle_user_text = str(request.get_last_user_message() or "")
    orch.lifecycle.start_task(
        req_id_str,
        {"user_text": _stream_lifecycle_user_text, "conversation_id": request.conversation_id},
    )
    
    user_text = str(request.get_last_user_message() or "")
    conversation_id = request.conversation_id
    forced_response_mode = orch._requested_response_mode(request)
    request_retrieval_cache: Dict[str, Any] = {}
    tone_signal = await orch._classify_tone_signal(user_text, request.messages)
    _emit_loop_trace = is_internal_loop_analysis_prompt(user_text)
    _loop_trace_started_emitted = False
    
    # ═══════════════════════════════════════════════════
    # STEP 0: INTENT CONFIRMATION
    # ═══════════════════════════════════════════════════
    if intent_system_available:
        try:
            result = await orch._check_pending_confirmation(user_text, conversation_id)
            if result:
                yield (result.content, False, {"type": "content"})
                ws_done = orch._save_workspace_entry(
                    conversation_id,
                    orch._build_done_workspace_summary("confirmation_executed"),
                    "chat_done",
                    "orchestrator",
                )
                if ws_done:
                    yield ("", False, ws_done)
                yield ("", True, {"done_reason": "confirmation_executed"})
                return
        except Exception as e:
            log_info_fn(f"[Orchestrator] Intent check skipped: {e}")

    from core.orchestrator_modules.task_loop import is_task_loop_request, stream_task_loop_events
    if is_task_loop_request(user_text, request):
        orch.lifecycle.finish_task(req_id_str, {"task_loop": True, "stream": True})
        orch._post_task_processing()
        async for event in stream_task_loop_events(
            orch,
            request,
            user_text,
            conversation_id,
            log_info_fn=log_info_fn,
            log_warn_fn=log_warn_fn,
            tone_signal=tone_signal,
        ):
            yield event
        return
    
    # ═══════════════════════════════════════════════════
    # STEP 0.5: CHUNKING (large inputs)
    # ═══════════════════════════════════════════════════
    chunking_context = None
    
    try:
        from utils.chunker import needs_chunking, count_tokens
        if enable_chunking and needs_chunking(user_text, chunking_threshold):
            log_info_fn(f"[Orchestrator] Chunking: {count_tokens(user_text)} tokens")
            async for event in orch._process_chunked_stream(user_text, conversation_id, request):
                chunk_text, is_done, metadata = event
                yield event
                if metadata.get("type") == "chunking_done":
                    chunking_context = {
                        "aggregated_summary": metadata.get("aggregated_summary", ""),
                        "thinking_result": metadata.get("thinking_result", {}),
                    }
    except Exception as e:
        log_info_fn(f"[Orchestrator] Chunking skipped: {e}")
    
    # ═══════════════════════════════════════════════════
    # STEP 0.8: CONTEXT COMPRESSION (Rolling Summary)
    # ═══════════════════════════════════════════════════
    try:
        from core.context_compressor import get_compressor, estimate_protocol_tokens
        from utils.settings import settings as _settings
        _compression_enabled = _settings.get("CONTEXT_COMPRESSION_ENABLED", True)
        if _compression_enabled:
            _token_est = estimate_protocol_tokens()
            _compression_threshold = _settings.get("COMPRESSION_THRESHOLD", 100000)
            if _token_est >= _compression_threshold:
                _compression_mode = _settings.get("CONTEXT_COMPRESSION_MODE", "sync")
                log_info_fn(f"[Orchestrator] Context compression triggered ({_token_est} tokens, mode={_compression_mode})")
                yield ("", False, {
                    "type": "compression_start",
                    "token_count": _token_est,
                    "mode": _compression_mode,
                })
                if _compression_mode == "sync":
                    _did_compress, _phase = await get_compressor().check_and_compress()
                    yield ("", False, {
                        "type": "compression_done",
                        "phase": _phase,
                        "async": False,
                    })
                else:
                    # Async: Hintergrund-Task, Pipeline läuft sofort weiter
                    asyncio.create_task(get_compressor().check_and_compress())
                    yield ("", False, {
                        "type": "compression_done",
                        "phase": "async_started",
                        "async": True,
                    })
    except Exception as _ce:
        log_warn_fn(f"[Orchestrator] Context compression skipped: {_ce}")

    # ═══════════════════════════════════════════════════
    # STEP 1: THINKING LAYER (STREAMING)
    # ═══════════════════════════════════════════════════
    log_info_fn(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 1 THINKING")
    
    thinking_plan = {}
    _thinking_skill_ctx = ""       # Pre-fetched for ThinkingLayer
    _stream_prefetch_mode = "off"  # Tracks prefetch mode for trace
    query_budget_signal: Dict[str, Any] = {}
    domain_route_signal: Dict[str, Any] = {}

    if chunking_context and chunking_context.get("thinking_result"):
        log_info_fn("[Orchestrator] Layer 1 SKIPPED (using chunking result)")
        thinking_plan = chunking_context["thinking_result"]
        thinking_plan = orch._ensure_dialogue_controls(
            thinking_plan,
            tone_signal,
            user_text=user_text,
            selected_tools=[],
        )
        yield ("", False, {
            "type": "thinking_done",
            "thinking": _build_thinking_ui_payload(thinking_plan, source="chunking"),
            "source": "chunking",
        })
    else:
        log_info_fn("[Orchestrator] === LAYER 1: THINKING (STREAMING) ===")
        
        # Layer 0: Tool Selection
        from core.orchestrator_pipeline_stages import run_tool_selection_stage
        selected_tools, query_budget_signal, domain_route_signal, _last_assistant_msg = (
            await run_tool_selection_stage(
                orch, user_text, request, forced_response_mode, tone_signal, log_info_fn
            )
        )
        if selected_tools:
            yield ("", False, {"type": "tool_selection", "tools": selected_tools})

        # Check if we should skip ThinkingLayer
        skip_thinking = False
        if request.source_adapter == "master_orchestrator":
            settings = get_master_settings_fn()
            skip_thinking = not settings.get("use_thinking_layer", False)
            
            if skip_thinking:
                log_info_fn("[Pipeline] Skipping ThinkingLayer for Master (ThinkingLayer=OFF in settings)")
                thinking_plan = orch.thinking._default_plan()
                thinking_plan = orch._ensure_dialogue_controls(
                    thinking_plan,
                    tone_signal,
                    user_text=user_text,
                    selected_tools=selected_tools,
                )
                yield ("", False, {
                    "type": "thinking_done",
                    "thinking": _build_thinking_ui_payload(
                        thinking_plan,
                        intent="Master orchestrator action",
                        needs_memory=False,
                        skipped=True,
                        reason="Master has own planning + ThinkingLayer disabled in settings",
                        source="master_skip",
                    ),
                })
        if (
            not skip_thinking
            and orch._should_skip_thinking_from_query_budget(
                query_budget_signal,
                user_text=user_text,
                forced_mode=forced_response_mode,
            )
        ):
            skip_thinking = True
            log_info_fn("[Pipeline] Skipping ThinkingLayer via QueryBudget signal [stream]")
            thinking_plan = orch.thinking._default_plan()
            thinking_plan = orch._ensure_dialogue_controls(
                thinking_plan,
                tone_signal,
                user_text=user_text,
                selected_tools=selected_tools,
            )
            yield ("", False, {
                "type": "thinking_done",
                "thinking": _build_thinking_ui_payload(
                    thinking_plan,
                    intent="query_budget_fast_path",
                    needs_memory=False,
                    skipped=True,
                    reason="query_budget_skip_candidate",
                    source="query_budget",
                ),
            })
        
        if not skip_thinking:
            # ── ThinkingLayer Cache-Check ──
            # Kurze Inputs (< 5 Wörter) sind vollständig kontextabhängig ("ja bitte",
            # "ok", "nein") — niemals cachen, da der gleiche Text in verschiedenen
            # Gesprächssituationen komplett unterschiedliche Tools erfordert.
            _is_short_input = len(user_text.split()) < 5
            _cached_plan = None if _is_short_input else thinking_plan_cache.get(user_text)
            if _is_short_input:
                log_info_fn("[Orchestrator] ThinkingLayer Cache SKIP: short input is context-dependent")
            if _cached_plan:
                thinking_plan = _cached_plan
                thinking_plan = orch._ensure_dialogue_controls(
                    thinking_plan,
                    tone_signal,
                    user_text=user_text,
                    selected_tools=selected_tools,
                )
                # Touch TTL on hit so repeated turns don't expire mid-benchmark.
                thinking_plan_cache.set(user_text, thinking_plan)
                log_info_fn(f"[Orchestrator] CACHE HIT ThinkingLayer: intent='{thinking_plan.get('intent')}'")
                yield ("", False, {
                    "type": "thinking_done",
                    "thinking": _build_thinking_ui_payload(
                        thinking_plan,
                        cached=True,
                        source="cache",
                    ),
                })
            else:
                # STEP 0.5: Skill-Graph Pre-Fetch — policy-gated (stream path)
                _thinking_skill_ctx, _stream_prefetch_mode = orch._maybe_prefetch_skills(
                    user_text, selected_tools
                )
                if _thinking_skill_ctx:
                    log_info_fn(f"[Orchestrator] Skill-Context für ThinkingLayer vorbereitet mode={_stream_prefetch_mode}")

                # Variante A: Kontext-Anreicherung für extrem kurze Inputs.
                # DeepSeek soll "ja bitte. [Kontext: Möchtest du den Blueprint starten?]"
                # sehen — nicht nur "ja bitte" — damit suggested_tools korrekt gesetzt wird.
                _thinking_user_text = user_text
                if _last_assistant_msg and len(user_text.split()) < 5:
                    _ctx_snippet = _last_assistant_msg.strip()[-200:]
                    _thinking_user_text = f"{user_text}. [Kontext: {_ctx_snippet}]"
                    log_info_fn("[Orchestrator] A-Enrichment: ThinkingLayer user_text angereichert [stream]")

                async for chunk, is_done, plan in orch.thinking.analyze_stream(
                    _thinking_user_text,
                    memory_context=_thinking_skill_ctx,
                    available_tools=selected_tools,
                    tone_signal=tone_signal,
                ):
                    if not is_done:
                        yield ("", False, {
                            "type": "thinking_stream",
                            "chunk": chunk,
                            "thinking_chunk": chunk,
                        })
                    else:
                        thinking_plan = plan
                        thinking_plan = orch._ensure_dialogue_controls(
                            thinking_plan,
                            tone_signal,
                            user_text=user_text,
                            selected_tools=selected_tools,
                        )
                        thinking_plan["_trace_skills_prefetch"] = bool(_thinking_skill_ctx)
                        thinking_plan["_trace_skills_prefetch_mode"] = _stream_prefetch_mode
                        # Im Cache speichern für spätere Aufrufe
                        thinking_plan_cache.set(user_text, thinking_plan)
                        log_info_fn(f"[Orchestrator] ThinkingLayer plan cached prefetch={_stream_prefetch_mode}")
                yield ("", False, {
                    "type": "thinking_done",
                    "thinking": _build_thinking_ui_payload(
                        thinking_plan,
                        source="live",
                    ),
                })
    if _emit_loop_trace:
        yield ("", False, build_loop_trace_started_event(user_text, thinking_plan))
        _loop_trace_started_emitted = True
    # ═══════════════════════════════════════════════════
    # PLAN FINALIZATION + RESPONSE MODE
    # ═══════════════════════════════════════════════════
    from core.orchestrator_pipeline_stages import run_plan_finalization
    thinking_plan, response_mode_stream = run_plan_finalization(
        orch, user_text, request, thinking_plan, selected_tools,
        query_budget_signal, domain_route_signal, forced_response_mode,
        conversation_id, log_info_fn,
    )
    log_info_fn(f"[Orchestrator] response_mode={response_mode_stream} (stream)")
    _loop_trace_normalized = build_loop_trace_plan_normalized_event(thinking_plan)
    if _loop_trace_normalized:
        _emit_loop_trace = True
        if not _loop_trace_started_emitted:
            yield ("", False, build_loop_trace_started_event(user_text, thinking_plan))
            _loop_trace_started_emitted = True
    if _loop_trace_normalized:
        yield ("", False, _loop_trace_normalized)
    yield ("", False, {"type": "response_mode", "mode": response_mode_stream})
    
    # ═══════════════════════════════════════════════════
    # WORKSPACE: Save thinking observations
    # ═══════════════════════════════════════════════════
    obs_text = orch._extract_workspace_observations(thinking_plan)
    if obs_text:
        ws_event = orch._save_workspace_entry(
            conversation_id, obs_text, "observation", "thinking"
        )
        if ws_event:
            yield ("", False, ws_event)

    # ═══════════════════════════════════════════════════
    # STEP 1.5: CONTEXT RETRIEVAL (unified helper)
    # ═══════════════════════════════════════════════════
    from config import get_small_model_mode as _get_smm_stream
    _smm_stream = _get_smm_stream()
    full_context, ctx_trace_stream, mem_res = orch.build_effective_context(
        user_text=user_text,
        conv_id=conversation_id,
        small_model_mode=_smm_stream,
        cleanup_payload=thinking_plan,
        debug_flags={
            # Prefer trace stored in plan (works for both cache-hit and fresh run).
            # _thinking_skill_ctx is empty on cache-hit so must not be used as sole source.
            "skills_prefetch_used": thinking_plan.get("_trace_skills_prefetch", bool(_thinking_skill_ctx)),
            "skills_prefetch_mode": thinking_plan.get("_trace_skills_prefetch_mode", "off" if _smm_stream else "full"),
            "detection_rules_used": thinking_plan.get("_trace_detection_rules_mode", "false"),
        },
        request_cache=request_retrieval_cache,
    )
    memory_used = ctx_trace_stream.get("memory_used", False)
    # NOTE: context_text_chars = background context only (NOW/RULES/NEXT, capped).
    # tool_context is appended separately and is NOT included here.
    log_info_fn(
        f"[CTX] mode={'small' if ctx_trace_stream['small_model_mode'] else 'full'} "
        f"context_text_chars={ctx_trace_stream['context_chars']} retrieval={ctx_trace_stream['retrieval_count']} "
        f"src={','.join(ctx_trace_stream['context_sources'])}"
    )
    
    # ═══════════════════════════════════════════════════
    # STEP 1.6–1.8: PRE-CONTROL GATES (Hardware, Skill Dedup, Container)
    # ═══════════════════════════════════════════════════
    from core.orchestrator_pipeline_stages import run_pre_control_gates
    _skill_gate_result, _hardware_gate_msg = run_pre_control_gates(
        orch, user_text, thinking_plan, request, log_info_fn, log_warn_fn
    )

    # Stream-only: yield UI-notification events based on gate results
    if _hardware_gate_msg:
        ws_warn = orch._save_workspace_entry(
            conversation_id,
            "hardware_gate_triggered=true | authority=control | reason=hardware_self_protection",
            "observation",
            "orchestrator",
        )
        if ws_warn:
            yield ("", False, ws_warn)
        yield ("", False, {"type": "hardware_gate_signal", "reason": "hardware_self_protection"})

    if _skill_gate_result:
        if _skill_gate_result.get("blocked"):
            yield ("", False, {
                "type": "skill_blocked",
                "reason": _skill_gate_result["reason"],
            })
        elif _skill_gate_result.get("routed"):
            yield ("", False, {
                "type": "skill_routed",
                "skill_name": _skill_gate_result["skill_name"],
                "score": _skill_gate_result["score"],
            })

    # ═══════════════════════════════════════════════════
    # STEP 1.75: SEQUENTIAL THINKING (STREAMING)
    # ═══════════════════════════════════════════════════
    if thinking_plan.get('needs_sequential_thinking') or thinking_plan.get('sequential_thinking_required'):
        log_info_fn("[Orchestrator] Sequential Thinking detected")
        if _emit_loop_trace:
            yield ("", False, build_loop_trace_step_started_event(
                phase="sequential_thinking",
                summary="Sequential analysis gestartet",
                details={
                    "complexity": thinking_plan.get("sequential_complexity", 0),
                    "reasoning_type": thinking_plan.get("reasoning_type"),
                },
            ))
        try:
            sequential_input = user_text
            if chunking_context and chunking_context.get("aggregated_summary"):
                sequential_input = f"User: {thinking_plan.get('intent')}\n{chunking_context['aggregated_summary']}"

            # ── Sequential Cache-Check ──
            _seq_cache_key = f"{sequential_input}|{thinking_plan.get('intent', '')}"
            _cached_seq = sequential_result_cache.get(_seq_cache_key)
            if _cached_seq:
                log_info_fn("[Orchestrator] CACHE HIT Sequential Thinking")
                thinking_plan["_sequential_result"] = _cached_seq
                _cached_event = {
                    "type": "sequential_done",
                    "task_id": "cached",
                    "steps": _cached_seq.get("steps", []),
                    "summary": _cached_seq.get("summary", ""),
                    "cached": True,
                }
                _ws_seq_cached = orch._persist_sequential_workspace_event(conversation_id, _cached_event)
                if _ws_seq_cached:
                    yield ("", False, _ws_seq_cached)
                yield ("", False, _cached_event)
            else:
                _seq_steps_collected = []
                from config import get_sequential_timeout_s
                _seq_timeout_s = float(get_sequential_timeout_s())
                try:
                    async with asyncio.timeout(_seq_timeout_s):
                        async for event in orch.control._check_sequential_thinking_stream(
                            user_text=sequential_input,
                            thinking_plan=thinking_plan
                        ):
                            # Sammle Steps für Cache
                            if event.get("type") == "sequential_step":
                                _step_payload = event.get("step")
                                if not isinstance(_step_payload, dict):
                                    _step_payload = {
                                        "step": event.get("step_number") or event.get("step_num") or event.get("step") or len(_seq_steps_collected) + 1,
                                        "title": event.get("title", ""),
                                        "thought": event.get("thought", "") or event.get("content", ""),
                                    }
                                _seq_steps_collected.append(_step_payload)
                            elif event.get("type") == "sequential_done":
                                # Im Cache speichern
                                _seq_result = {
                                    "steps": _seq_steps_collected,
                                    "summary": event.get("summary", ""),
                                }
                                thinking_plan["_sequential_result"] = _seq_result
                                sequential_result_cache.set(_seq_cache_key, _seq_result)
                                log_info_fn(f"[Orchestrator] Sequential result cached ({len(_seq_steps_collected)} steps)")
                            _ws_seq = orch._persist_sequential_workspace_event(conversation_id, event)
                            if _ws_seq:
                                yield ("", False, _ws_seq)
                            yield ("", False, event)
                except TimeoutError:
                    thinking_plan["_sequential_timed_out"] = True
                    log_warn_fn(f"[Orchestrator] Sequential stream timeout after {_seq_timeout_s:.0f}s")
                    _timeout_event = {
                        "type": "sequential_error",
                        "task_id": "timeout",
                        "error": f"timeout_after_{int(_seq_timeout_s)}s",
                    }
                    _ws_seq_timeout = orch._persist_sequential_workspace_event(conversation_id, _timeout_event)
                    if _ws_seq_timeout:
                        yield ("", False, _ws_seq_timeout)
                    yield ("", False, _timeout_event)
        except Exception as e:
            log_info_fn(f"[Orchestrator] Sequential error: {e}")
    
    # ═══════════════════════════════════════════════════
    # STEP 2: CONTROL LAYER
    # ═══════════════════════════════════════════════════
    log_info_fn(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 2 CONTROL")
    
    skip_control, _skip_reason_stream = orch._should_skip_control_layer(user_text, thinking_plan)
    if skip_control:
        log_info_fn(f"[Orchestrator] Layer 2 SKIPPED ({_skip_reason_stream})")
    else:
        log_info_fn(f"[Orchestrator] Layer 2 CONTROL REQUIRED ({_skip_reason_stream})")
    
    if skip_control:
        verified_plan = thinking_plan.copy()
        verified_plan["_skipped"] = True
        verified_plan["_skip_reason"] = str(_skip_reason_stream or "low_risk_skip")
        verification = {
            "approved": True,
            "hard_block": False,
            "decision_class": "allow",
            "block_reason_code": "",
            "reason": "control_skipped",
            "corrections": {},
            "warnings": [],
            "final_instruction": "",
        }
    else:
        log_info_fn("[Orchestrator] === LAYER 2: CONTROL ===")
        verification = await orch.control.verify(
            user_text,
            thinking_plan,
            full_context,
            response_mode=response_mode_stream,
        )
        verified_plan = orch.control.apply_corrections(thinking_plan, verification)
        # Skill Confirmation Handling (stream parity with sync path)
        if verification.get("_needs_skill_confirmation") and intent_system_available:
            skill_name = verification.get("_skill_name", "unknown")
            log_info_fn(f"[Orchestrator] Creating skill_creation_intent_cls for '{skill_name}' (stream)")
            intent = skill_creation_intent_cls(
                skill_name=skill_name,
                origin=intent_origin_cls.USER,
                reason=verification.get("_cim_decision", {}).get("pattern_id", "control_layer"),
                user_text=user_text,
                conversation_id=conversation_id,
                thinking_plan=thinking_plan,
                complexity=thinking_plan.get("sequential_complexity", 5),
            )
            store = get_intent_store_fn()
            store.add(intent)
            verified_plan["_pending_intent"] = intent.to_dict()
            log_info_fn(f"[Orchestrator] Intent {intent.id[:8]} added to verified_plan (stream)")

            # B4: Auto-create bypass (stream-Parität mit sync-Pfad)
            from config import get_skill_auto_create_on_low_risk
            if (
                get_skill_auto_create_on_low_risk()
                and thinking_plan.get("hallucination_risk") == "low"
                and not verified_plan["_pending_intent"].get("needs_package_install", False)
            ):
                _bypassed_skill = verified_plan["_pending_intent"].get("skill_name", "?")
                del verified_plan["_pending_intent"]
                verified_plan["_auto_create_bypass"] = True
                log_info_fn(
                    f"[Orchestrator] Auto-create bypass: skill={_bypassed_skill} "
                    f"(low_risk, no_packages, SKILL_AUTO_CREATE_ON_LOW_RISK=true) [stream]"
                )

    control_decision = control_decision_from_plan(verified_plan, default_approved=False)
    if not verified_plan.get("_control_decision"):
        control_decision = control_decision_from_plan(
            {"_control_decision": verification},
            default_approved=False,
        )
    if not verified_plan.get("_control_decision"):
        persist_control_decision(verified_plan, control_decision)
    if not verified_plan.get("_execution_result"):
        persist_execution_result(verified_plan, execution_result_from_plan(verified_plan))

    log_info_fn(f"[Orchestrator] Control approved={verification.get('approved')}")

    # ── Stream extra-lookup — gated by retrieval budget (Commit 4 parity) ──
    # Mirror of sync path (core/orchestrator.py:1848): budget check before each lookup.
    if verification.get("corrections", {}).get("memory_keys"):
        from config import get_control_corrections_memory_keys_max
        _extra_limit_stream = get_control_corrections_memory_keys_max()
        _raw_extra_keys_stream = verification["corrections"]["memory_keys"] or []
        if not isinstance(_raw_extra_keys_stream, (list, tuple)):
            _raw_extra_keys_stream = []
        _seen_extra_stream = set()
        _extra_keys_stream = []
        for _key_raw in _raw_extra_keys_stream:
            _nk_stream = str(_key_raw or "").strip()
            if not _nk_stream or _nk_stream in _seen_extra_stream:
                continue
            _extra_keys_stream.append(_nk_stream)
            _seen_extra_stream.add(_nk_stream)
            if len(_extra_keys_stream) >= _extra_limit_stream:
                break
        if _extra_limit_stream == 0:
            _extra_keys_stream = []
        if len(_raw_extra_keys_stream) > len(_extra_keys_stream):
            log_info_fn(
                f"[CTX] stream extra-lookup keys capped: kept={len(_extra_keys_stream)} "
                f"dropped={len(_raw_extra_keys_stream) - len(_extra_keys_stream)} "
                f"limit={_extra_limit_stream}"
            )
        _policy_stream = orch._compute_retrieval_policy(thinking_plan, verified_plan)
        _budget_stream = _policy_stream["max_retrievals"]
        for _key in _extra_keys_stream:
            if _key not in thinking_plan.get("memory_keys", []):
                if ctx_trace_stream["retrieval_count"] >= _budget_stream:
                    log_info_fn(
                        f"[CTX] stream extra-lookup skipped (budget exhausted): "
                        f"key='{_key}' count={ctx_trace_stream['retrieval_count']} max={_budget_stream}"
                    )
                    continue
                log_info_fn(f"[Orchestrator-Control-Stream] Extra memory lookup: {_key}")
                _extra_text_s, _extra_trace_s, _extra_res_s = orch.build_effective_context(
                    user_text=_key,
                    conv_id=conversation_id,
                    small_model_mode=_smm_stream,
                    cleanup_payload={"needs_memory": True, "memory_keys": [_key]},
                    include_blocks={"compact": False, "system_tools": False, "memory_data": True},
                    request_cache=request_retrieval_cache,
                )
                if _extra_text_s:
                    full_context = orch._append_context_block(
                        full_context, "\n" + _extra_text_s, "jit_memory", ctx_trace_stream
                    )
                    memory_used = True
                    ctx_trace_stream["retrieval_count"] += 1
                    log_info_fn(
                        f"[CTX] stream extra-lookup key='{_key}' "
                        f"chars={_extra_trace_s['context_chars']} "
                        f"src={','.join(_extra_trace_s['context_sources'])}"
                    )

    # ── ControlLayer Tool-Decision: Args via Function Calling ──
    _control_tool_decisions = await orch._collect_control_tool_decisions(
        user_text,
        verified_plan,
        control_decision=control_decision,
        stream=True,
    )
    persist_control_decision(verified_plan, control_decision)
    
    # Control is the only hard-block authority.
    if orch._is_control_hard_block_decision(verification):
        log_info_fn("[Orchestrator] Request blocked by ControlLayer gate")
        reason = verification.get("reason", "Safety policy violation")
        warnings = verification.get("warnings", [])
        msg = reason
        if warnings:
            msg += f"\n\n_{', '.join(warnings)}_"
        _control_summary = orch._build_control_workspace_summary(
            verification,
            skipped=skip_control,
            skip_reason=_skip_reason_stream,
        )
        ws_ctrl_block = orch._save_workspace_entry(
            conversation_id,
            _control_summary,
            "control_decision",
            "control",
        )
        if ws_ctrl_block:
            yield ("", False, ws_ctrl_block)
        # Als normaler Content-Chunk yielden — dann done
        yield (msg, False, {"type": "content"})
        ws_done = orch._save_workspace_entry(
            conversation_id,
            orch._build_done_workspace_summary("blocked"),
            "chat_done",
            "orchestrator",
        )
        if ws_done:
            yield ("", False, ws_done)
        yield ("", True, {"done_reason": "blocked"})
        return
    if verification.get("approved") == False:
        soften_control_deny_fn(verification)
        control_decision = control_decision_from_plan(
            {"_control_decision": verification},
            default_approved=False,
        )
        persist_control_decision(verified_plan, control_decision)
        log_warning_fn("[Orchestrator] Soft control deny converted to warning (stream path)")

    yield (
        "",
        False,
        {
            "type": "control",
            "approved": bool(control_decision.approved),
            "decision_class": str(control_decision.decision_class or "").strip(),
            "reason": str(control_decision.reason or "").strip(),
            "warnings": [str(w) for w in control_decision.warnings],
            "tools_allowed": [str(t) for t in control_decision.tools_allowed],
            "skipped": skip_control,
        },
    )

    # ═══════════════════════════════════════════════════
    # LOOP ENGINE TRIGGER CHECK
    # Kein extra LLM-Call — ThinkingLayer berechnet
    # sequential_complexity/needs_sequential sowieso.
    # ═══════════════════════════════════════════════════
    _loop_complexity = thinking_plan.get("sequential_complexity", 0)
    _loop_sequential = thinking_plan.get("needs_sequential_thinking", False)
    # Lese suggested_tools aus thinking_plan (vor CIM-Übersteuerung)
    _raw_suggested = thinking_plan.get("suggested_tools") or verified_plan.get("suggested_tools") or []
    _loop_tools_count = len(_raw_suggested)
    # autonomous_skill_task braucht keinen LoopEngine — hat eigene Pipeline
    _autonomous_task = "autonomous_skill_task" in _raw_suggested
    from config import get_loop_engine_trigger_complexity, get_loop_engine_min_tools
    _loop_complexity_threshold = int(get_loop_engine_trigger_complexity())
    _loop_min_tools = int(get_loop_engine_min_tools())
    _loop_candidate = (
        _loop_complexity >= _loop_complexity_threshold
        or (_loop_sequential and _loop_tools_count >= 2)
    )
    use_loop_engine = (
        not _autonomous_task
        and response_mode_stream == "deep"
        and _loop_tools_count >= _loop_min_tools
        and _loop_candidate
    )
    # ── Phase 1.5 Commit 4: LoopEngine guard in small-model-mode ──
    # LoopEngine prompt grows unbounded across iterations — incompatible with small-model budget.
    if use_loop_engine and _smm_stream:
        use_loop_engine = False
        log_info_fn("[Orchestrator] LoopEngine SKIP — small-model-mode (unbounded prompt growth risk)")
    if use_loop_engine:
        log_info_fn(
            "[Orchestrator] LoopEngine trigger: "
            f"complexity={_loop_complexity}/{_loop_complexity_threshold}, "
            f"sequential={_loop_sequential}, tools={_loop_tools_count}/{_loop_min_tools}, "
            f"response_mode={response_mode_stream}"
        )
    elif _autonomous_task:
        log_info_fn(f"[Orchestrator] LoopEngine SKIP — autonomous_skill_task hat eigene Pipeline")
    elif response_mode_stream != "deep":
        log_info_fn("[Orchestrator] LoopEngine SKIP — response_mode!=deep")

    # WORKSPACE: persist central control decision + optional detail payload.
    _control_summary = orch._build_control_workspace_summary(
        verification,
        skipped=skip_control,
        skip_reason=_skip_reason_stream,
    )
    ws_ctrl = orch._save_workspace_entry(
        conversation_id,
        _control_summary,
        "control_decision",
        "control",
    )
    if ws_ctrl:
        yield ("", False, ws_ctrl)

    if not skip_control:
        corrections = verification.get("corrections", {})
        warnings = verification.get("warnings", [])
        if corrections or warnings:
            ctrl_parts = []
            if warnings:
                ctrl_parts.append(f"**Warnings:** {', '.join(str(w) for w in warnings)}")
            if corrections:
                ctrl_parts.append(f"**Corrections:** {json.dumps(corrections, ensure_ascii=False)[:300]}")
            ws_event = orch._save_workspace_entry(
                conversation_id, "\n".join(ctrl_parts), "observation", "control"
            )
            if ws_event:
                yield ("", False, ws_event)

    # Skill confirmation
    if verified_plan.get("_pending_intent"):
        pending = verified_plan["_pending_intent"]
        yield (f"🛠️ Möchtest du den Skill **{pending.get('skill_name')}** erstellen? (Ja/Nein)", False, {"type": "content"})
        ws_done = orch._save_workspace_entry(
            conversation_id,
            orch._build_done_workspace_summary("confirmation_pending"),
            "chat_done",
            "orchestrator",
        )
        if ws_done:
            yield ("", False, ws_done)
        yield (
            "",
            True,
            {
                "type": "confirmation_pending",
                "intent_id": pending.get("id"),
                "done_reason": "confirmation_pending",
            },
        )
        return
    
    if orch._is_control_hard_block_decision(verification):
        # Keep message visible to user before terminal done event.
        yield (verification.get("message", "Nicht genehmigt"), False, {"type": "content"})
        ws_done = orch._save_workspace_entry(
            conversation_id,
            orch._build_done_workspace_summary("blocked"),
            "chat_done",
            "orchestrator",
        )
        if ws_done:
            yield ("", False, ws_done)
        yield ("", True, {"type": "error", "done_reason": "blocked"})
        return
    
    # ═══════════════════════════════════════════════════
    # STEP 2.5: TOOL EXECUTION
    # ═══════════════════════════════════════════════════
    tool_context = ""
    grounding_evidence_stream: List[Dict[str, Any]] = []
    successful_tool_runs_stream: List[Dict[str, Any]] = []
    _carry_grounding = get_runtime_grounding_evidence(verified_plan)
    if isinstance(_carry_grounding, list):
        grounding_evidence_stream.extend(_carry_grounding or [])

    suggested_tools = orch._resolve_execution_suggested_tools(
        user_text,
        verified_plan,
        _control_tool_decisions,
        control_decision=control_decision,
        stream=True,
        enable_skill_trigger_router=True,
        conversation_id=conversation_id,
        chat_history=request.messages,
    )
    execution_result_stream = execution_result_from_plan(verified_plan)
    stream_direct_cron_response = ""
    stream_direct_host_runtime_response = ""
    stream_direct_host_runtime_failure_response = ""
    host_runtime_lookup = bool(verified_plan.get("_host_runtime_chain_applied"))
    host_runtime_bootstrap_attempted = False
    host_runtime_blueprint_fallback_attempted = False
    host_runtime_created_blueprint_id = ""
    host_runtime_last_failure_reason = ""
    host_runtime_exec_succeeded = False

    if suggested_tools:
        log_info_fn(f"[TIMING] T+{time.time()-_t0:.2f}s: TOOL EXECUTION")
        log_info_fn(f"[Orchestrator] === TOOL EXECUTION: {suggested_tools} ===")
        # Normalisierte dict-Specs für Frontend zu lesbaren Namen konvertieren
        _tool_names_display = [t["tool"] if isinstance(t, dict) and "tool" in t else str(t) for t in suggested_tools]
        yield ("", False, {"type": "tool_start", "tools": _tool_names_display})

        tool_hub = get_initialized_hub_safe(log_warn_fn=log_warn_fn)
        if tool_hub is None:
            _hub_reason = "tool_hub_unavailable"
            for _spec in suggested_tools:
                _tool_name = (
                    _spec.get("tool")
                    if isinstance(_spec, dict) and "tool" in _spec
                    else str(_spec)
                )
                _tool_name = str(_tool_name or "").strip()
                if not _tool_name:
                    continue
                tool_context += (
                    f"\n[{_tool_name}]: FEHLER: MCP Hub nicht verfügbar "
                    f"({_hub_reason}). Tool-Ausführung übersprungen."
                )
                yield ("", False, {
                    "type": "tool_result",
                    "tool": _tool_name,
                    "success": False,
                    "error": _hub_reason,
                    "skipped": True,
                })
                grounding_evidence_stream.append({
                    "tool_name": _tool_name,
                    "status": "error",
                    "reason": _hub_reason,
                })
                execution_result_stream.append_tool_status(
                    tool_name=_tool_name,
                    status="error",
                    reason=_hub_reason,
                )
            set_runtime_tool_failure(verified_plan, True)
            suggested_tools = []

        _last_container_id = None
        _container_state = orch._get_recent_container_state(conversation_id)
        _known_last_container_id = ""
        if isinstance(_container_state, dict):
            _known_last_container_id = str(_container_state.get("last_active_container_id", "")).strip()

        # Fast Lane Executor für home_* Tools
        _STREAM_FAST_LANE_TOOLS = {"home_read", "home_write", "home_list"}
        try:
            from core.tools.fast_lane.executor import get_fast_lane_executor
            _stream_fast_lane = get_fast_lane_executor()
        except ImportError:
            _stream_fast_lane = None

        # Reflection Loop: initialisieren + Round-1-Args verfolgen
        from core.tool_intelligence import ReflectionLoop
        _reflection = ReflectionLoop()
        _round1_args: Dict[str, Dict] = {}
        _tool_queue = list(suggested_tools or [])
        _tool_idx = 0
        while _tool_idx < len(_tool_queue):
            tool_spec = _tool_queue[_tool_idx]
            _tool_idx += 1
            # Handle normalisierte Specs: {"tool": "run_skill", "args": {...}}
            if isinstance(tool_spec, dict) and "tool" in tool_spec:
                tool_name = tool_spec["tool"]
                tool_args = tool_spec.get("args", {})
            else:
                tool_name = tool_spec
                # ControlLayer entscheidet Args (Function Calling) — Fallback: heuristic
                # IMPORTANT: {} is falsy → same logic as sync path (_cd.get() or _build_tool_args)
                tool_args = _control_tool_decisions.get(tool_name) or orch._build_tool_args(tool_name, user_text, verified_plan=verified_plan)
                if tool_name in _control_tool_decisions and _control_tool_decisions[tool_name]:
                    log_debug_fn(f"[Orchestrator] Using ControlLayer args for {tool_name}")
                # autonomous_skill_task: Intent aus ThinkingLayer injizieren
                if tool_name == "autonomous_skill_task":
                    tool_args["intent"] = thinking_plan.get("intent", user_text)
                    # complexity=3: User will explizit Skill erstellen → immer unter AUTO_CREATE_THRESHOLD
                    tool_args["complexity"] = 3
                    tool_args["thinking_plan"] = {
                        "intent": thinking_plan.get("intent", ""),
                        "reasoning": thinking_plan.get("reasoning", ""),
                        "sequential_complexity": thinking_plan.get("sequential_complexity", 3),
                    }
            if tool_name == "request_container" and bool(verified_plan.get("_trion_home_start_fast_path")):
                tool_name = "home_start"
                tool_args = {}
            if not tool_allowed_by_control_decision(control_decision, tool_name):
                _deny_reason = "control_tool_not_allowed"
                execution_result_stream.append_tool_status(
                    tool_name=str(tool_name),
                    status="routing_block",
                    reason=_deny_reason,
                )
                grounding_evidence_stream.append({
                    "tool_name": str(tool_name),
                    "status": "routing_block",
                    "reason": _deny_reason,
                })
                yield ("", False, {
                    "type": "tool_result",
                    "tool": str(tool_name),
                    "success": False,
                    "error": _deny_reason,
                    "skipped": True,
                })
                continue
            if host_runtime_lookup:
                if tool_name == "exec_in_container":
                    _existing_cid = "PENDING"
                    if isinstance(tool_args, dict):
                        _existing_cid = str(tool_args.get("container_id") or "PENDING")
                    tool_args = build_host_runtime_exec_args(container_id=_existing_cid)
                elif tool_name == "blueprint_create" and host_runtime_blueprint_fallback_attempted:
                    tool_args = build_host_runtime_blueprint_create_args(user_text=user_text)
            try:
                _round1_args[tool_name] = tool_args
                _reflection.register_round1_tool(tool_name, tool_args)

                # Temporal guard: Protokoll ist die Quelle, kein Graph-Fallback nötig
                if tool_name == "memory_graph_search" and thinking_plan.get("time_reference"):
                    log_info_fn(f"[Orchestrator-Stream] Blocking memory_graph_search — time_reference={thinking_plan['time_reference']}, protocol is source")
                    continue

                # Write-guard: home_write nur wenn ThinkingLayer es explizit vorgeschlagen hat
                if tool_name == "home_write" and "home_write" not in thinking_plan.get("suggested_tools", []):
                    log_info_fn("[Orchestrator-Stream] Blocking home_write — not in ThinkingLayer suggested_tools (ControlLayer hallucination)")
                    continue

                # Fail-closed: bei Skill-Router-Ausfall keine Skill-Ausführung zulassen.
                if tool_name in {"autonomous_skill_task", "create_skill", "run_skill"} and thinking_plan.get("_skill_gate_blocked"):
                    _skill_reason = thinking_plan.get("_skill_gate_reason", "skill_router_unavailable")
                    log_warn_fn(f"[Orchestrator-Stream] Tool unavailable {tool_name} — reason={_skill_reason}")
                    tool_context += (
                        f"\n[{tool_name}]: FEHLER: Skill-Router nicht verfügbar ({_skill_reason}). "
                        "Tool kann in dieser Runtime nicht ausgeführt werden."
                    )
                    yield ("", False, {
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": False,
                        "error": _skill_reason,
                        "skipped": True,
                    })
                    grounding_evidence_stream.append({
                        "tool_name": tool_name,
                        "status": "routing_block",
                        "reason": _skill_reason,
                    })
                    execution_result_stream.append_tool_status(
                        tool_name=str(tool_name),
                        status="routing_block",
                        reason=str(_skill_reason),
                    )
                    continue

                # Blueprint Gate + Router (Stream):
                # Handles both: pre-planned gate (Step 1.8) AND keyword-fallback path (JIT check).
                if tool_name == "request_container":
                    if host_runtime_lookup and host_runtime_created_blueprint_id:
                        tool_args["blueprint_id"] = host_runtime_created_blueprint_id
                        tool_args["session_id"] = conversation_id or ""
                        tool_args["conversation_id"] = conversation_id or ""
                        log_info_fn(
                            "[Orchestrator-Stream] Host-runtime fallback blueprint injected: "
                            f"{host_runtime_created_blueprint_id}"
                        )
                    elif thinking_plan.get("_blueprint_gate_blocked"):
                        # Gate was set at Step 1.8 (no match OR suggest-zone) — block
                        log_info_fn("[Orchestrator-Stream] Blocking request_container — Blueprint Gate (pre-planned)")
                        _suggest_data = thinking_plan.get("_blueprint_suggest")
                        if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                            host_runtime_blueprint_fallback_attempted = True
                            host_runtime_last_failure_reason = "request_container_blocked:no_blueprint_match"
                            tool_context += (
                                "\n[request_container]: FEHLER: Kein passender Blueprint im Router-Match. "
                                "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                            )
                            _tool_queue[_tool_idx:_tool_idx] = [
                                "blueprint_create",
                                "request_container",
                                "exec_in_container",
                            ]
                            continue
                        if _suggest_data:
                            _cands = ", ".join(f"{c['id']} ({c['score']:.2f})" for c in _suggest_data.get("candidates", []))
                            # Soft-Guidance: kein Hard-Block, sondern natives Tool-Ergebnis das den
                            # LLM über die Klärungsanfrage informiert — kein grounding_missing_evidence.
                            _clarification_msg = (
                                f"Mehrere Blueprints passen auf die Anfrage, aber keiner ist eindeutig. "
                                f"Mögliche Kandidaten: {_cands}. "
                                "Bitte den Nutzer, einen dieser Blueprints auszuwählen."
                            )
                            tool_context += f"\n[request_container]: {_clarification_msg}"
                            execution_result_stream.append_tool_status(
                                tool_name="request_container",
                                status="needs_clarification",
                                reason=_clarification_msg,
                            )
                        else:
                            tool_context += "\n[request_container]: FEHLER: Kein passender Blueprint gefunden. Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                            execution_result_stream.append_tool_status(
                                tool_name="request_container",
                                status="routing_block",
                                reason="no_blueprint_match",
                            )
                        host_runtime_last_failure_reason = "request_container_blocked:no_blueprint_match"
                        continue
                    elif "_blueprint_router" in thinking_plan:
                        _bp_id = thinking_plan["_blueprint_router"]["blueprint_id"]
                        tool_args["blueprint_id"] = _bp_id  # Always inject — no fallback override allowed
                        tool_args["session_id"] = conversation_id or ""
                        tool_args["conversation_id"] = conversation_id or ""
                        log_info_fn(f"[Orchestrator-Stream] blueprint_id injected: {_bp_id}")
                    else:
                        # Keyword-fallback path: JIT router check
                        # Short-Input Bypass context: "ja bitte" hat keine Blueprint-Keywords
                        # → _last_assistant_msg als Fallback-Text verwenden wenn user_text < 5 Wörter
                        _jit_text = user_text
                        if len(user_text.split()) < 5 and _last_assistant_msg:
                            _jit_text = f"{user_text} {_last_assistant_msg}"
                        try:
                            _jit_d = orch._route_blueprint_request(_jit_text, thinking_plan)
                            if _jit_d and _jit_d.get("blocked"):
                                _jit_reason = _jit_d.get("reason", "blueprint_router_unavailable")
                                log_warn_fn(f"[Orchestrator-Stream] JIT router blocked request_container — reason={_jit_reason}")
                                if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                                    host_runtime_blueprint_fallback_attempted = True
                                    host_runtime_last_failure_reason = f"request_container_blocked:{_jit_reason}"
                                    tool_context += (
                                        "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. "
                                        "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                                    )
                                    _tool_queue[_tool_idx:_tool_idx] = [
                                        "blueprint_create",
                                        "request_container",
                                        "exec_in_container",
                                    ]
                                    continue
                                host_runtime_last_failure_reason = f"request_container_blocked:{_jit_reason}"
                                tool_context += "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. Kein Freestyle-Container erlaubt."
                                execution_result_stream.append_tool_status(
                                    tool_name="request_container",
                                    status="routing_block",
                                    reason=str(_jit_reason),
                                )
                                continue
                            elif _jit_d and not _jit_d.get("suggest"):
                                tool_args["blueprint_id"] = _jit_d["blueprint_id"]
                                tool_args["session_id"] = conversation_id or ""
                                tool_args["conversation_id"] = conversation_id or ""
                                log_info_fn(f"[Orchestrator-Stream] JIT blueprint_id: {_jit_d['blueprint_id']} (score={_jit_d['score']:.2f})")
                            elif _jit_d and _jit_d.get("suggest"):
                                _jit_cands = ", ".join(f"{c['id']} ({c['score']:.2f})" for c in _jit_d["candidates"])
                                if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                                    host_runtime_blueprint_fallback_attempted = True
                                    host_runtime_last_failure_reason = "request_container_suggest:needs_manual_selection"
                                    tool_context += (
                                        "\n[request_container]: Router ist unklar (Suggest-Zone). "
                                        "Host-Runtime-Fallback startet deterministisch mit blueprint_create."
                                    )
                                    _tool_queue[_tool_idx:_tool_idx] = [
                                        "blueprint_create",
                                        "request_container",
                                        "exec_in_container",
                                    ]
                                    continue
                                log_info_fn(f"[Orchestrator-Stream] JIT suggest: {_jit_cands} — Rückfrage nötig")
                                tool_context += f"\n[request_container]: RÜCKFRAGE: Welchen Blueprint soll ich starten? Meinst du: {_jit_cands}? Bitte präzisiere."
                                execution_result_stream.append_tool_status(
                                    tool_name="request_container",
                                    status="routing_block",
                                    reason="jit_suggest_requires_selection",
                                )
                                continue
                            else:
                                log_info_fn("[Orchestrator-Stream] JIT Blueprint Gate: kein Match — blocking")
                                if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                                    host_runtime_blueprint_fallback_attempted = True
                                    host_runtime_last_failure_reason = "request_container_blocked:no_jit_match"
                                    tool_context += (
                                        "\n[request_container]: Kein Router-Match gefunden. "
                                        "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                                    )
                                    _tool_queue[_tool_idx:_tool_idx] = [
                                        "blueprint_create",
                                        "request_container",
                                        "exec_in_container",
                                    ]
                                    continue
                                host_runtime_last_failure_reason = "request_container_blocked:no_jit_match"
                                tool_context += "\n[request_container]: FEHLER: Kein passender Blueprint gefunden. Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                                execution_result_stream.append_tool_status(
                                    tool_name="request_container",
                                    status="routing_block",
                                    reason="no_jit_match",
                                )
                                continue
                        except Exception as _jit_e:
                            if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                                host_runtime_blueprint_fallback_attempted = True
                                host_runtime_last_failure_reason = f"request_container_jit_error:{_jit_e}"
                                tool_context += (
                                    "\n[request_container]: FEHLER: Blueprint-Router Laufzeitfehler. "
                                    "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                                )
                                _tool_queue[_tool_idx:_tool_idx] = [
                                    "blueprint_create",
                                    "request_container",
                                    "exec_in_container",
                                ]
                                continue
                            host_runtime_last_failure_reason = f"request_container_jit_error:{_jit_e}"
                            log_warn_fn(f"[Orchestrator-Stream] JIT router error: {_jit_e} — blocking request_container (no freestyle fallback)")
                            tool_context += "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. Kein Freestyle-Container erlaubt."
                            execution_result_stream.append_tool_status(
                                tool_name="request_container",
                                status="error",
                                reason=f"jit_router_error:{_jit_e}",
                            )
                            continue

                # Chain: inject container_id from previous request_container
                if _last_container_id and tool_args.get("container_id") == "PENDING":
                    tool_args["container_id"] = _last_container_id
                elif _known_last_container_id and tool_args.get("container_id") == "PENDING":
                    tool_args["container_id"] = _known_last_container_id
                elif tool_args.get("container_id") == "PENDING":
                    _resolve_reason = "no_pending_resolution_attempted"
                    if orch._tool_requires_container_id(tool_name):
                        _preferred_ids = [
                            _last_container_id,
                            _known_last_container_id,
                            (_container_state or {}).get("home_container_id", ""),
                            (_container_state or {}).get("last_active_container_id", ""),
                        ]
                        _resolved_id, _resolve_reason = await orch._resolve_pending_container_id_async(
                            tool_hub,
                            conversation_id or "",
                            preferred_ids=[str(v or "").strip() for v in _preferred_ids if str(v or "").strip()],
                            history_len=len(request.messages),
                        )
                        if _resolved_id:
                            tool_args["container_id"] = _resolved_id
                            _last_container_id = _resolved_id
                            _known_last_container_id = _resolved_id
                            log_info_fn(
                                f"[Orchestrator-Stream] Auto-resolved container_id for {tool_name}: {_resolved_id[:12]}"
                            )

                    if tool_args.get("container_id") == "PENDING":
                        if host_runtime_lookup and tool_name == "exec_in_container" and not host_runtime_bootstrap_attempted:
                            host_runtime_bootstrap_attempted = True
                            host_runtime_last_failure_reason = f"exec_missing_container:{_resolve_reason}"
                            tool_context += (
                                "\n[exec_in_container]: Keine aktive container_id gefunden. "
                                "Host-Runtime-Fallback startet: request_container -> exec_in_container."
                            )
                            _tool_queue[_tool_idx:_tool_idx] = ["request_container", "exec_in_container"]
                            continue
                        _skip_reason = f"missing_container_id:auto_resolve_failed:{_resolve_reason}"
                        log_warn_fn(f"[Orchestrator-Stream] Skipping {tool_name} - {_skip_reason}")
                        tool_context += f"\n### TOOL-SKIP ({tool_name}): {_skip_reason}\n"
                        yield ("", False, {
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": False,
                            "error": _skip_reason,
                            "skipped": True,
                        })
                        grounding_evidence_stream.append({
                            "tool_name": tool_name,
                            "status": "skip",
                            "reason": _skip_reason,
                        })
                        continue

                _valid, tool_args, _arg_reason = orch._validate_tool_args(
                    tool_hub, tool_name, tool_args, user_text
                )
                if not _valid:
                    log_warn_fn(f"[Orchestrator-Stream] Skipping {tool_name} due to invalid args: {_arg_reason}")
                    if host_runtime_lookup and tool_name in {"exec_in_container", "request_container", "blueprint_create"}:
                        host_runtime_last_failure_reason = f"{tool_name}_invalid_args:{_arg_reason}"
                    tool_context += f"\n### TOOL-SKIP ({tool_name}): {_arg_reason}\n"
                    yield ("", False, {
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": False,
                        "error": _arg_reason,
                        "skipped": True,
                    })
                    grounding_evidence_stream.append({
                        "tool_name": tool_name,
                        "status": "unavailable",
                        "reason": _arg_reason,
                    })
                    execution_result_stream.append_tool_status(
                        tool_name=str(tool_name),
                        status="unavailable",
                        reason=str(_arg_reason),
                    )
                    continue
                orch._bind_cron_conversation_id(tool_name, tool_args, conversation_id)

                # ── Fast Lane: home_read/write/list nativ ausführen ──
                if tool_name in _STREAM_FAST_LANE_TOOLS and _stream_fast_lane:
                    try:
                        log_info_fn(f"[Orchestrator-Stream] Fast Lane ⚡ {tool_name}")
                        fl_result = _stream_fast_lane.execute(tool_name, tool_args)
                        formatted, success, meta = orch._format_tool_result(fl_result, tool_name)
                        # ── Commit 2 stream parity: Card + Full Payload ──
                        _fl_status = "ok" if success else "error"
                        _card, _ref = orch._build_tool_result_card(
                            tool_name, formatted.strip(), _fl_status, conversation_id
                        )
                        tool_context += _card
                        grounding_evidence_stream.append(
                            orch._build_grounding_evidence_entry(
                                tool_name=tool_name,
                                raw_result=formatted.strip(),
                                status=_fl_status,
                                ref_id=_ref,
                            )
                        )
                        if success:
                            successful_tool_runs_stream.append({
                                "tool_name": str(tool_name),
                                "args": orch._sanitize_tool_args_for_state(tool_args),
                            })
                            execution_result_stream.append_tool_status(
                                tool_name=str(tool_name),
                                status="ok",
                                reason="fast_lane",
                            )
                        else:
                            execution_result_stream.append_tool_status(
                                tool_name=str(tool_name),
                                status="error",
                                reason="fast_lane_error",
                            )
                        yield ("", False, {"type": "tool_result", "tool": tool_name, "success": success, "execution_mode": "fast_lane"})
                        # HOME AUTO-EXPAND: home_list → auto-read files (same as MCP path)
                        if tool_name == "home_list" and success and hasattr(fl_result, 'content') and isinstance(fl_result.content, list):
                            _list_base = tool_args.get("path", ".").strip("/")
                            if _list_base in (".", "", "/trion-home"):
                                _list_base = ""
                            _files_read = 0
                            for _item in fl_result.content:
                                if _files_read >= 5:
                                    break
                                if _item.endswith("/"):
                                    _subdir = (_list_base + "/" if _list_base else "") + _item.rstrip("/")
                                    try:
                                        _sr = _stream_fast_lane.execute("home_list", {"path": _subdir})
                                        _si = _sr.content if hasattr(_sr, 'content') else []
                                        if isinstance(_si, list):
                                            tool_context += f"\n### INHALT VON {_subdir}/:\n{json.dumps(_si, ensure_ascii=False)}\n"
                                            for _si_item in _si:
                                                if _files_read >= 5:
                                                    break
                                                if not _si_item.endswith("/"):
                                                    _fp = f"{_subdir}/{_si_item}"
                                                    try:
                                                        _fc = _stream_fast_lane.execute("home_read", {"path": _fp})
                                                        _fcc = _fc.content if hasattr(_fc, 'content') else ""
                                                        if _fcc:
                                                            tool_context += f"\n### DATEI-INHALT ({_fp}):\n{_fcc}\n"
                                                            _files_read += 1
                                                    except Exception:
                                                        pass
                                    except Exception:
                                        pass
                                else:
                                    _fp = (_list_base + "/" if _list_base else "") + _item
                                    try:
                                        _fc = _stream_fast_lane.execute("home_read", {"path": _fp})
                                        _fcc = _fc.content if hasattr(_fc, 'content') else ""
                                        if _fcc:
                                            tool_context += f"\n### DATEI-INHALT ({_fp}):\n{_fcc}\n"
                                            _files_read += 1
                                    except Exception:
                                        pass
                            if _files_read > 0:
                                log_info_fn(f"[Orchestrator-Stream] FL home auto-expand: {_files_read} file(s)")
                        continue
                    except Exception as _fl_e:
                        log_warning_fn(f"[Orchestrator-Stream] Fast Lane failed for {tool_name}, falling back: {_fl_e}")
                        # Fall through to MCP

                # ── Container Verify-Step (Phase 1: fail-only) ──
                if tool_name == "exec_in_container" and tool_args.get("container_id"):
                    cid = tool_args["container_id"]
                    if cid != _last_container_id:  # Skip verify for freshly started containers
                        if not orch._verify_container_running(cid):
                            log_warn_fn(f"[Orchestrator-Verify] Container {cid[:12]} NOT running — aborting exec")
                            stop_event = json.dumps({
                                "container_id": cid,
                                "stopped_at": datetime.utcnow().isoformat() + "Z",
                                "reason": "verify_failed",
                                "session_id": conversation_id or "",
                            }, ensure_ascii=False)
                            ws_ev = orch._save_workspace_entry(
                                "_container_events", stop_event, "container_stopped", "orchestrator"
                            )
                            if ws_ev:
                                yield ("", False, ws_ev)
                            tool_context += f"\n### VERIFY-FEHLER ({tool_name}): Container {cid[:12]} ist nicht mehr aktiv.\n"
                            yield ("", False, {"type": "tool_result", "tool": tool_name, "success": False, "error": "container_not_running"})
                            grounding_evidence_stream.append({
                                "tool_name": tool_name,
                                "status": "error",
                                "reason": "container_not_running",
                            })
                            execution_result_stream.append_tool_status(
                                tool_name=str(tool_name),
                                status="error",
                                reason="container_not_running",
                            )
                            continue

                log_info_fn(f"[Orchestrator] Calling tool: {tool_name}({tool_args})")
                if hasattr(tool_hub, "call_tool_async"):
                    result = await tool_hub.call_tool_async(tool_name, tool_args)
                else:
                    result = await asyncio.to_thread(tool_hub.call_tool, tool_name, tool_args)

                # ── Clarification Intercept (autonomous_skill_task) ──
                # Wenn Skill-Erstellung eine Frage stellt — NICHT als TOOL-FEHLER behandeln
                if isinstance(result, dict) and result.get("needs_clarification"):
                    question    = result.get("question", "")
                    orig_intent = result.get("original_intent", user_text)
                    log_info_fn(f"[Orchestrator] Skill gap detected — asking user for clarification")

                    # 1. Intent für Resume speichern
                    if intent_system_available:
                        try:
                            store = get_intent_store_fn()
                            intent_obj = store.create(
                                conversation_id=conversation_id,
                                user_text=orig_intent,
                                skill_name="pending_skill_creation",
                                reason=orig_intent,
                            )
                            intent_obj.intent_type = "skill_clarification"
                            intent_obj.thinking_plan = thinking_plan
                        except Exception as _e:
                            log_warn_fn(f"[Orchestrator] Intent store failed: {_e}")

                    # 2. Workspace: Pending-State sichern
                    ws_content = (
                        f"**⏸️ Pending Skill:** {orig_intent}\n"
                        f"**Status:** Wartet auf Nutzer-Antwort\n"
                        f"**Frage:** {question}"
                    )
                    ws_ev = orch._save_workspace_entry(
                        conversation_id, ws_content, "pending_skill", "orchestrator"
                    )
                    if ws_ev:
                        yield ("", False, ws_ev)

                    # 3. Frage in tool_context (OutputLayer formuliert freundlich)
                    tool_context += f"\n### KLÄRUNG BENÖTIGT:\n{question}\n"
                    tool_context += "\nStelle diese Frage freundlich an den User.\n"
                    continue  # nächstes Tool

                # Track container_id from deploy result
                if tool_name == "request_container" and isinstance(result, dict):
                    _last_container_id = result.get("container_id", "") or result.get("container", {}).get("container_id", "")
                    _known_last_container_id = _last_container_id or _known_last_container_id
                if tool_name == "blueprint_create":
                    _created_bp = extract_blueprint_id_from_create_result(result)
                    if _created_bp:
                        host_runtime_created_blueprint_id = _created_bp
                        log_info_fn(f"[Orchestrator-Stream] Host-runtime blueprint created: {_created_bp}")
                    elif host_runtime_lookup:
                        host_runtime_last_failure_reason = "blueprint_create_missing_id"

                orch._update_container_state_from_tool_result(
                    conversation_id,
                    tool_name,
                    tool_args,
                    result,
                    history_len=len(request.messages),
                )

                result_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
                # ╔════════════════════════════════════════════════════════════╗
                # ║  PHASE 3: TOOL INTELLIGENCE (Refactored Stream)           ║
                # ╚════════════════════════════════════════════════════════════╝
                
                intelligence_result = orch.tool_intelligence.handle_tool_result(
                    tool_name=tool_name,
                    result=result,
                    tool_args=tool_args,
                    tool_hub=tool_hub  # NEW: Pass hub for retry
                )
                
                # Check if auto-retry succeeded
                retry_result = intelligence_result.get('retry_result')
                if retry_result and retry_result.get('success'):
                    # ✅ AUTO-RETRY SUCCEEDED!
                    log_info_fn(f"[AutoRetry] Success on attempt {retry_result['attempts']}!")
                    result = retry_result['result']
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    retry_info = (
                        f"Auto-Retry OK (fix={retry_result['fix_applied']}, "
                        f"attempt={retry_result['attempts']}/2)\n{result_str}"
                    )
                    # ── Commit 2 stream parity: Card + Full Payload ──
                    _card, _ref = orch._build_tool_result_card(
                        tool_name, retry_info, "ok", conversation_id
                    )
                    tool_context += _card
                    grounding_evidence_stream.append(
                        orch._build_grounding_evidence_entry(
                            tool_name=tool_name,
                            raw_result=retry_info,
                            status="ok",
                            ref_id=_ref,
                        )
                    )
                    successful_tool_runs_stream.append({
                        "tool_name": str(tool_name),
                        "args": orch._sanitize_tool_args_for_state(tool_args),
                    })
                    execution_result_stream.append_tool_status(
                        tool_name=str(tool_name),
                        status="ok",
                        reason="retry_success",
                    )
                    if tool_name == "autonomy_cron_create_job":
                        _direct_msg = orch._build_direct_cron_create_response(
                            result=result,
                            tool_args=tool_args,
                            conversation_id=conversation_id,
                        )
                        if _direct_msg:
                            stream_direct_cron_response = _direct_msg
                    _host_direct_msg_retry = build_direct_host_runtime_response(tool_name, tool_args, result)
                    if _host_direct_msg_retry:
                        stream_direct_host_runtime_response = _host_direct_msg_retry
                        host_runtime_exec_succeeded = True
                    yield ("", False, {
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": True,
                        "retry_success": True,
                        "attempts": retry_result['attempts']
                    })

                elif intelligence_result['is_error']:
                    # Error (retry failed or not attempted)
                    error_msg = intelligence_result['error_msg']
                    solutions = intelligence_result.get('solutions', '')
                    if host_runtime_lookup and tool_name in {"exec_in_container", "request_container", "blueprint_create"}:
                        host_runtime_last_failure_reason = f"{tool_name}_error:{error_msg}"

                    # ── HOME READ RECOVERY: "Is a directory" → auto-expand ──
                    if tool_name == "home_read" and "Is a directory" in error_msg:
                        dir_path = tool_args.get("path", ".")
                        log_info_fn(f"[Orchestrator] home_read got directory '{dir_path}' → auto-expanding")
                        try:
                            from core.tools.fast_lane.executor import FastLaneExecutor
                            fl = FastLaneExecutor()
                            sub_result = fl.execute("home_list", {"path": dir_path})
                            sub_items = sub_result.content if hasattr(sub_result, 'content') else sub_result
                            if isinstance(sub_items, list):
                                tool_context += f"\n### INHALT VON {dir_path}/:\n{json.dumps(sub_items, ensure_ascii=False)}\n"
                                files_read = 0
                                for sub_item in sub_items:
                                    if files_read >= 5:
                                        break
                                    if sub_item.endswith("/"):
                                        continue
                                    fp = sub_item if dir_path in (".", "") else f"{dir_path}/{sub_item}"
                                    try:
                                        fc = fl.execute("home_read", {"path": fp})
                                        fc_content = fc.content if hasattr(fc, 'content') else fc
                                        if fc_content:
                                            tool_context += f"\n### DATEI-INHALT ({fp}):\n{fc_content}\n"
                                            files_read += 1
                                    except Exception:
                                        pass
                                log_info_fn(f"[Orchestrator] home_read recovery: read {files_read} file(s) from {dir_path}/")
                                execution_result_stream.append_tool_status(
                                    tool_name=str(tool_name),
                                    status="ok",
                                    reason="home_read_recovery",
                                )
                                yield ("", False, {"type": "tool_result", "tool": tool_name, "success": True})
                                continue
                        except Exception as expand_err:
                            log_warn_fn(f"[Orchestrator] home_read recovery failed: {expand_err}")

                    log_warn_fn(f"[Orchestrator] Tool {tool_name} FAILED: {error_msg}")
                    _err_detail = error_msg + (f"\n{solutions}" if solutions else "")
                    if retry_result:
                        _err_detail += f"\nAuto-Retry: {retry_result.get('reason', '')}"
                    # ── Commit 2 stream parity: Error Card + Full Payload ──
                    _card, _ref = orch._build_tool_result_card(
                        tool_name, _err_detail, "error", conversation_id
                    )
                    tool_context += f"\n### TOOL-FEHLER ({tool_name}):\n"
                    tool_context += _card
                    grounding_evidence_stream.append(
                        orch._build_grounding_evidence_entry(
                            tool_name=tool_name,
                            raw_result=_err_detail,
                            status="error",
                            ref_id=_ref,
                        )
                    )
                    execution_result_stream.append_tool_status(
                        tool_name=str(tool_name),
                        status="error",
                        reason=str(error_msg),
                    )
                    yield ("", False, {
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": False,
                        "error": error_msg,
                        "retry_attempted": retry_result is not None
                    })
                else:
                    # TOOL SUCCESS (no error, no retry needed)
                    # ── Fix #12A: detect pending_approval for request_container ──
                    _result_status_raw = str(
                        (result if isinstance(result, dict) else {}).get("status") or ""
                    ).strip().lower()
                    _is_pending_approval = (
                        tool_name == "request_container"
                        and _result_status_raw == "pending_approval"
                    )
                    _evidence_status = "pending_approval" if _is_pending_approval else "ok"
                    # ── Commit 2 stream parity: Card + Full Payload ──
                    _card, _ref = orch._build_tool_result_card(
                        tool_name, result_str, "ok", conversation_id
                    )
                    tool_context += _card
                    grounding_evidence_stream.append(
                        orch._build_grounding_evidence_entry(
                            tool_name=tool_name,
                            raw_result=result_str,
                            status=_evidence_status,
                            ref_id=_ref,
                        )
                    )
                    successful_tool_runs_stream.append({
                        "tool_name": str(tool_name),
                        "args": orch._sanitize_tool_args_for_state(tool_args),
                    })
                    execution_result_stream.append_tool_status(
                        tool_name=str(tool_name),
                        status="ok",
                        reason="tool_ok",
                    )
                    if tool_name == "autonomy_cron_create_job":
                        _direct_msg = orch._build_direct_cron_create_response(
                            result=result,
                            tool_args=tool_args,
                            conversation_id=conversation_id,
                        )
                        if _direct_msg:
                            stream_direct_cron_response = _direct_msg
                    _host_direct_msg = build_direct_host_runtime_response(tool_name, tool_args, result)
                    if _host_direct_msg:
                        stream_direct_host_runtime_response = _host_direct_msg
                        host_runtime_exec_succeeded = True
                    log_info_fn(f"[Orchestrator] Tool {tool_name} OK: {len(result_str)} chars ref={_ref}")
                    yield ("", False, {"type": "tool_result", "tool": tool_name, "success": True})

                    # ── HOME AUTO-EXPAND: home_list → auto-read files ──
                    _home_list_content = result.content if hasattr(result, 'content') else result
                    if tool_name == "home_list" and isinstance(_home_list_content, list):
                        try:
                            from core.tools.fast_lane.executor import FastLaneExecutor
                            fl = FastLaneExecutor()
                            files_read = 0
                            _list_base = tool_args.get("path", ".").strip("/")
                            if _list_base in (".", "", "/trion-home"):
                                _list_base = ""
                            for item in _home_list_content:
                                if files_read >= 5:
                                    break
                                if item.endswith("/"):
                                    subdir = (_list_base + "/" if _list_base else "") + item.rstrip("/")
                                    try:
                                        sub_result = fl.execute("home_list", {"path": subdir})
                                        sub_items = sub_result.content if hasattr(sub_result, 'content') else sub_result
                                        if isinstance(sub_items, list):
                                            tool_context += f"\n### INHALT VON {subdir}/:\n{json.dumps(sub_items, ensure_ascii=False)}\n"
                                            for sub_item in sub_items:
                                                if files_read >= 5:
                                                    break
                                                if not sub_item.endswith("/"):
                                                    file_path = f"{subdir}/{sub_item}"
                                                    try:
                                                        fc = fl.execute("home_read", {"path": file_path})
                                                        fc_content = fc.content if hasattr(fc, 'content') else fc
                                                        tool_context += f"\n### DATEI-INHALT ({file_path}):\n{fc_content}\n"
                                                        files_read += 1
                                                    except Exception:
                                                        pass
                                    except Exception:
                                        pass
                                else:
                                    file_path = (_list_base + "/" if _list_base else "") + item
                                    try:
                                        fc = fl.execute("home_read", {"path": file_path})
                                        fc_content = fc.content if hasattr(fc, 'content') else fc
                                        if fc_content:
                                            tool_context += f"\n### DATEI-INHALT ({file_path}):\n{fc_content}\n"
                                            files_read += 1
                                    except Exception:
                                        pass
                            if files_read > 0:
                                log_info_fn(f"[Orchestrator] Home auto-expand: read {files_read} file(s)")
                        except Exception as e:
                            log_warn_fn(f"[Orchestrator] Home auto-expand failed: {e}")

                # ── Container Session Tracking (stream path) ──
                container_evt = orch._build_container_event_content(
                    tool_name, result, user_text, tool_args,
                    session_id=conversation_id or "",
                )
                if container_evt:
                    ws_ev = orch._save_container_event("_container_events", container_evt)
                    if ws_ev:
                        yield ("", False, ws_ev)
                    log_info_fn(f"[Orchestrator] Container event: {container_evt['event_type']}")

            except Exception as e:
                log_error_fn(f"[Orchestrator] Tool {tool_name} failed: {e}")
                if host_runtime_lookup and tool_name in {"exec_in_container", "request_container", "blueprint_create"}:
                    host_runtime_last_failure_reason = f"{tool_name}_exception:{e}"
                tool_context += f"\n### TOOL-FEHLER ({tool_name}): {str(e)}\n"
                yield ("", False, {"type": "tool_result", "tool": tool_name, "success": False, "error": str(e)})
                grounding_evidence_stream.append({
                    "tool_name": tool_name,
                    "status": "error",
                    "reason": str(e),
                })
                execution_result_stream.append_tool_status(
                    tool_name=str(tool_name),
                    status="error",
                    reason=str(e),
                )

    # ═══════════════════════════════════════════════════
    # STEP 2.5: REFLECTION LOOP (Round 2, max 1x)
    # ═══════════════════════════════════════════════════
    _stream_has_failure = bool(tool_context and "TOOL-FEHLER" in tool_context)
    if _stream_has_failure:
        # ── Failure-compact via entry-point (Gap D closed, stream path) ──
        _fail_block_stream = orch._build_failure_compact_block(
            conversation_id, len(full_context), _smm_stream
        )
        if _fail_block_stream:
            log_info_fn(f"[CTX] failure-compact injected chars={len(_fail_block_stream)} (via entry-point, stream path)")
            # Prepend to tool_context so it flows into reflection/output.
            # Source registered here; chars are NOT counted here to avoid double-counting:
            # the full tool_context (incl. this block) is measured once at the tool_ctx append below.
            tool_context = _fail_block_stream + tool_context
            ctx_trace_stream["context_sources"].append("failure_ctx")

    if tool_context and "TOOL-FEHLER" in tool_context:
        retry_plan = _reflection.plan_retry(
            tool_context=tool_context,
            user_text=user_text,
            round1_tool_args=_round1_args,
        )
        if retry_plan:
            log_info_fn(f"[ReflectionLoop] === ROUND 2: {len(retry_plan)} alternative(s) ===")
            yield ("", False, {"type": "reflection_start", "count": len(retry_plan)})
            for step in retry_plan:
                alt_tool = step["tool"]
                alt_args = step["args"]
                try:
                    log_info_fn(f"[ReflectionLoop] Versuche: {alt_tool}({alt_args}) | {step['reason']}")
                    if hasattr(tool_hub, "call_tool_async"):
                        alt_result = await tool_hub.call_tool_async(alt_tool, alt_args)
                    else:
                        alt_result = await asyncio.to_thread(tool_hub.call_tool, alt_tool, alt_args)
                    alt_str = json.dumps(alt_result, ensure_ascii=False, default=str) if isinstance(alt_result, (dict, list)) else str(alt_result)
                    # Extract content if ToolResult
                    if hasattr(alt_result, 'content') and alt_result.content is not None:
                        alt_str = json.dumps(alt_result.content, ensure_ascii=False, default=str) if isinstance(alt_result.content, (dict, list)) else str(alt_result.content)
                    tool_context += (
                        f"\n### 🔄 REFLECTION ({alt_tool}):\n"
                        f"**Grund:** {step['reason']}\n"
                        f"**Wegen:** {step['original_error']}\n"
                        f"**Ergebnis:** {alt_str}\n"
                    )
                    log_info_fn(f"[ReflectionLoop] {alt_tool} OK: {len(alt_str)} chars")
                    yield ("", False, {"type": "tool_result", "tool": alt_tool, "success": True, "reflection": True})
                except Exception as re_err:
                    log_warn_fn(f"[ReflectionLoop] {alt_tool} fehlgeschlagen: {re_err}")
                    tool_context += f"\n### 🔄 REFLECTION-FEHLER ({alt_tool}): {re_err}\n"

    # ── Phase 1.5 Commit 2: Clip tool_context before append (small mode) ──
    tool_context = orch._clip_tool_context(tool_context, _smm_stream)

    if tool_context:
        full_context = orch._append_context_block(
            full_context, tool_context, "tool_ctx", ctx_trace_stream
        )
        set_runtime_tool_results(verified_plan, tool_context)
        set_runtime_grounding_evidence(verified_plan, grounding_evidence_stream)
        set_runtime_successful_tool_runs(verified_plan, successful_tool_runs_stream)
        if _smm_stream:
            log_info_fn(
                f"[CTX] total context after tool_context: {len(full_context)} chars "
                f"(tool_context={len(tool_context)}, failure_ctx merged if any)"
            )

        has_failures_or_skips = orch._tool_context_has_failures_or_skips(tool_context)
        has_success = orch._tool_context_has_success(tool_context)
        if has_failures_or_skips:
            set_runtime_tool_failure(verified_plan, True)
        # Confidence Override: only when we have explicit successful tool evidence
        # and no skip/failure markers.
        if has_success and not has_failures_or_skips:
            set_runtime_tool_confidence(verified_plan, "high")
            log_info_fn("[Orchestrator] Tool confidence: HIGH — OutputLayer wird nicht gebremst")

        # WORKSPACE: Save tool execution results as note
        _tool_names = [t["tool"] if isinstance(t, dict) and "tool" in t else str(t) for t in suggested_tools]
        tool_summary = f"**Tools executed:** {', '.join(_tool_names)}\n\n{tool_context[:2000]}"
        ws_event = orch._save_workspace_entry(
            conversation_id, tool_summary, "note", "control"
        )
        if ws_event:
            yield ("", False, ws_event)
    else:
        set_runtime_grounding_evidence(verified_plan, grounding_evidence_stream)
        set_runtime_successful_tool_runs(verified_plan, successful_tool_runs_stream)

    has_failures_stream = any(
        str((item or {}).get("status", "")).strip().lower() in {"error", "skip", "partial", "unavailable"}
        for item in grounding_evidence_stream
        if isinstance(item, dict)
    )
    only_cron_create_stream = bool(successful_tool_runs_stream) and all(
        str((item or {}).get("tool_name", "")).strip() == "autonomy_cron_create_job"
        for item in successful_tool_runs_stream
        if isinstance(item, dict)
    )
    if host_runtime_lookup and not stream_direct_host_runtime_response and not host_runtime_exec_succeeded:
        _failure_reason = host_runtime_last_failure_reason or "host_runtime_chain_exhausted"
        stream_direct_host_runtime_failure_response = build_host_runtime_failure_response(
            reason=_failure_reason,
            attempted_blueprint_create=host_runtime_blueprint_fallback_attempted,
        )
    if stream_direct_cron_response and not has_failures_stream and only_cron_create_stream:
        set_runtime_direct_response(verified_plan, stream_direct_cron_response)
        execution_result_stream.direct_response = stream_direct_cron_response
    elif stream_direct_host_runtime_response and not has_failures_stream:
        set_runtime_direct_response(verified_plan, stream_direct_host_runtime_response)
        execution_result_stream.direct_response = stream_direct_host_runtime_response
    elif stream_direct_host_runtime_failure_response:
        set_runtime_direct_response(verified_plan, stream_direct_host_runtime_failure_response)
        execution_result_stream.direct_response = stream_direct_host_runtime_failure_response
    else:
        set_runtime_direct_response(verified_plan, "")
        execution_result_stream.direct_response = ""

    execution_result_stream.finalize_done_reason()
    if execution_result_stream.done_reason == DoneReason.STOP and suggested_tools:
        execution_result_stream.done_reason = DoneReason.SKIPPED
    persist_execution_result(verified_plan, execution_result_stream)
    # Fix #12B: Re-apply grounding evidence — persist_execution_result resets metadata={}
    if grounding_evidence_stream:
        set_runtime_grounding_evidence(verified_plan, grounding_evidence_stream)
    if successful_tool_runs_stream:
        set_runtime_successful_tool_runs(verified_plan, successful_tool_runs_stream)

    _active_container_ctx = await orch._maybe_build_active_container_capability_context(
        user_text=user_text,
        conversation_id=conversation_id,
        verified_plan=verified_plan,
        history_len=len(request.messages),
    )
    _active_container_ctx_text = str((_active_container_ctx or {}).get("context_text") or "").strip()
    if _active_container_ctx_text:
        full_context = orch._append_context_block(
            full_context,
            _active_container_ctx_text,
            "active_container_ctx",
            ctx_trace_stream,
        )
    _active_container_tool_results = str(
        (_active_container_ctx or {}).get("tool_results_text") or ""
    ).strip()
    if _active_container_tool_results:
        append_runtime_tool_results(
            verified_plan,
            f"\n{_active_container_tool_results}\n",
        )

    _skill_semantic_ctx = await orch._maybe_build_skill_semantic_context(
        user_text=user_text,
        conversation_id=conversation_id,
        verified_plan=verified_plan,
    )
    _skill_semantic_ctx_text = str((_skill_semantic_ctx or {}).get("context_text") or "").strip()
    if _skill_semantic_ctx_text:
        full_context = orch._append_context_block(
            full_context,
            _skill_semantic_ctx_text,
            "skill_catalog_ctx",
            ctx_trace_stream,
        )
    _skill_semantic_tool_results = str(
        (_skill_semantic_ctx or {}).get("tool_results_text") or ""
    ).strip()
    if _skill_semantic_tool_results:
        append_runtime_tool_results(
            verified_plan,
            f"\n{_skill_semantic_tool_results}\n",
        )

    orch._inject_carryover_grounding_evidence(
        conversation_id,
        verified_plan,
        history_len=len(request.messages),
    )
    _recovery_ctx_stream = await orch._maybe_auto_recover_grounding_once(
        conversation_id=conversation_id,
        user_text=user_text,
        verified_plan=verified_plan,
        thinking_plan=thinking_plan,
        history_len=len(request.messages),
        session_id=conversation_id or "",
    )
    if _recovery_ctx_stream:
        full_context = orch._append_context_block(
            full_context, _recovery_ctx_stream, "tool_ctx_recovery", ctx_trace_stream
        )
        append_runtime_tool_results(verified_plan, _recovery_ctx_stream)
        yield ("", False, {
            "type": "tool_result",
            "tool": "grounding_auto_recovery",
            "success": True,
        })

    orch._remember_conversation_grounding_state(
        conversation_id,
        verified_plan,
        history_len=len(request.messages),
    )

    # ═══════════════════════════════════════════════════
    # STEP 3: OUTPUT LAYER (STREAMING)
    # ═══════════════════════════════════════════════════
    log_info_fn(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 3 OUTPUT")
    log_info_fn("[Orchestrator] === LAYER 3: OUTPUT ===")

    full_response = ""
    first_chunk = True

    # Tool-Confidence Override: LoopEngine überspringen wenn Tools bereits Daten geliefert haben
    if use_loop_engine and get_runtime_tool_confidence(verified_plan) == "high":
        log_info_fn("[Orchestrator] LoopEngine SKIP — Tool-Ergebnisse bereits vorhanden (_tool_confidence=high)")
        use_loop_engine = False

    # ── Phase 1.5 Commit 1: Final hard cap (always active in small mode) ──
    # Falls back to SMALL_MODEL_CHAR_CAP when SMALL_MODEL_FINAL_CAP=0 (no longer optional).
    full_context = orch._apply_final_cap(full_context, ctx_trace_stream, _smm_stream, "stream")
    full_context = orch._apply_effective_context_guardrail(
        full_context, ctx_trace_stream, _smm_stream, "stream"
    )

    # ── Finalize orchestrator-side trace and hand off to OutputLayer ──
    # [CTX-PRE-OUTPUT]: orchestrator context string before OutputLayer adds persona/instructions/history.
    # [CTX-FINAL] is emitted inside OutputLayer after the full messages array is built.
    ctx_trace_stream["mode"] = orch._compute_ctx_mode(ctx_trace_stream, is_loop=use_loop_engine)
    if str(
        verified_plan.get("_authoritative_resolution_strategy")
        or verified_plan.get("resolution_strategy")
        or ""
    ).strip().lower() == "skill_catalog_context":
        skill_ctx = verified_plan.get("_skill_catalog_context")
        skill_ctx = skill_ctx if isinstance(skill_ctx, dict) else {}
        skill_policy = verified_plan.get("_skill_catalog_policy")
        skill_policy = skill_policy if isinstance(skill_policy, dict) else {}
        selected_doc_ids = list(skill_ctx.get("selected_doc_ids") or [])
        if not selected_doc_ids and str(skill_ctx.get("selected_docs") or "").strip():
            selected_doc_ids = [
                part.strip()
                for part in str(skill_ctx.get("selected_docs") or "").split(",")
                if str(part or "").strip()
            ]
        skill_route = verified_plan.get("_skill_catalog_tool_route")
        skill_route = skill_route if isinstance(skill_route, dict) else {}
        ctx_trace_stream["skill_catalog"] = {
            "selected_hints": list(verified_plan.get("strategy_hints") or []),
            "selected_docs": selected_doc_ids,
            "strict_mode": "answer_schema+semantic_postcheck",
            "postcheck": "pending",
            "thinking_suggested_tools": list(
                verified_plan.get("_thinking_suggested_tools")
                or verified_plan.get("suggested_tools")
                or []
            ),
            "final_execution_tools": list(verified_plan.get("_final_execution_tools") or []),
            "tool_route_status": skill_route.get("status"),
            "tool_route_reason": skill_route.get("reason"),
            "policy_mode": str(skill_policy.get("mode") or "").strip(),
            "required_tools": list(skill_policy.get("required_tools") or []),
            "force_sections": list(skill_policy.get("force_sections") or []),
        }
    log_info_fn(
        f"[CTX-PRE-OUTPUT] mode={ctx_trace_stream['mode']} "
        f"context_sources={','.join(ctx_trace_stream['context_sources'])} "
        f"context_chars={ctx_trace_stream['context_chars_final']} "
        f"retrieval_count={ctx_trace_stream['retrieval_count']}"
    )
    verified_plan["_ctx_trace"] = ctx_trace_stream
    verified_plan["_response_mode"] = response_mode_stream
    if "skill_catalog" in ctx_trace_stream:
        yield ("", False, {
            "type": "thinking_trace",
            "thinking": _build_thinking_ui_payload(verified_plan, source="trace"),
        })

    from core.orchestrator_pipeline_stages import prepare_output_invocation
    resolved_output_model_stream, memory_required_but_missing_stream = prepare_output_invocation(
        orch, request, verified_plan, mem_res, response_mode=response_mode_stream
    )

    if use_loop_engine:
        # ── LOOP ENGINE: OutputLayer bleibt aktiv, ruft Tools autonom auf ──
        from core.autonomous.loop_engine import LoopEngine
        from config import get_loop_engine_output_char_cap, get_loop_engine_max_predict
        log_info_fn("[Orchestrator] LoopEngine aktiv")
        yield ("", False, {
            "type": "loop_engine_start",
            "complexity": _loop_complexity,
            "sequential": _loop_sequential,
        })
        loop_engine = LoopEngine(
            model=resolved_output_model_stream or None,
            provider=str(model_resolution_stream.get("provider") or "").strip().lower() or None,
        )
        _loop_output_char_cap = int(get_loop_engine_output_char_cap())
        _loop_max_predict = int(get_loop_engine_max_predict())
        log_info_fn(
            f"[Orchestrator] LoopEngine budgets: char_cap={_loop_output_char_cap} "
            f"num_predict={_loop_max_predict}"
        )
        sys_prompt = orch.output.build_system_prompt(
            verified_plan, full_context,
            memory_required_but_missing=memory_required_but_missing_stream,
        )
        # [CTX-FINAL] for LoopEngine path: sys_prompt + user_text + initial tool_context
        # (LoopEngine bypasses OutputLayer.generate_stream, so we measure here)
        _loop_initial_chars = len(sys_prompt) + len(user_text) + len(tool_context or "")
        log_info_fn(
            f"[CTX-FINAL] mode={ctx_trace_stream['mode']} "
            f"context_sources={','.join(ctx_trace_stream['context_sources'])} "
            f"payload_chars={_loop_initial_chars} "
            f"retrieval_count={ctx_trace_stream['retrieval_count']}"
        )
        async for le_chunk, le_done, le_meta in loop_engine.run_stream(
            user_text=user_text,
            system_prompt=sys_prompt,
            initial_tool_context=tool_context,
            max_iterations=5,
            output_char_cap=_loop_output_char_cap,
            output_num_predict=_loop_max_predict,
        ):
            if le_meta.get("type") == "content" and le_chunk:
                if first_chunk:
                    log_info_fn(f"[TIMING] T+{time.time()-_t0:.2f}s: FIRST LOOP CHUNK")
                    first_chunk = False
                full_response += le_chunk
                yield (le_chunk, False, {"type": "content"})
            elif le_meta.get("type") not in ("done",):
                # Pass loop events to frontend (loop_iteration, loop_tool_call, etc.)
                yield ("", False, le_meta)
    else:
        # ── NORMALER OUTPUT: einmaliger OutputLayer-Call ──
        async for chunk in orch.output.generate_stream(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=full_context,
            model=resolved_output_model_stream,
            control_decision=control_decision,
            execution_result=verified_plan.get("_execution_result"),
            memory_required_but_missing=memory_required_but_missing_stream,
        ):
            if first_chunk:
                log_info_fn(f"[TIMING] T+{time.time()-_t0:.2f}s: FIRST OUTPUT CHUNK")
                first_chunk = False
            full_response += chunk
            yield (chunk, False, {"type": "content"})
    
    log_info_fn(f"[Orchestrator] Output: {len(full_response)} chars")

    _analysis_guard_evaluation = get_runtime_grounding_value(
        verified_plan,
        key="analysis_guard_evaluation",
        default={},
    )
    _analysis_guard_violation = get_runtime_grounding_value(
        verified_plan,
        key="analysis_guard_violation",
        default={},
    )
    if _emit_loop_trace and isinstance(_analysis_guard_evaluation, dict) and (
        _analysis_guard_evaluation.get("applicable")
        or _analysis_guard_evaluation.get("skipped_reason")
    ):
        yield ("", False, build_loop_trace_step_started_event(
            phase="output_postcheck",
            summary="Analyse-Guard im Livepfad geprueft",
            details={
                "applicable": bool(_analysis_guard_evaluation.get("applicable")),
                "trigger_source": _analysis_guard_evaluation.get("trigger_source"),
                "skipped_reason": _analysis_guard_evaluation.get("skipped_reason"),
                "violated": bool(_analysis_guard_evaluation.get("violated")),
                "checked_chars": int(_analysis_guard_evaluation.get("checked_chars") or 0),
            },
        ))
    if isinstance(_analysis_guard_violation, dict) and _analysis_guard_violation.get("violated"):
        if _emit_loop_trace:
            yield ("", False, build_loop_trace_correction_event(
                stage="output_postcheck",
                summary="Unbelegte Runtime-/Memory-/Status-Behauptungen wurden entfernt.",
                reasons=list(_analysis_guard_violation.get("reasons") or []),
                details={
                    "matches": list(_analysis_guard_violation.get("matches") or []),
                },
            ))

    repaired_response = await orch._apply_conversation_consistency_guard(
        conversation_id=conversation_id,
        verified_plan=verified_plan,
        answer=full_response,
    )
    _consistency_repaired = repaired_response != full_response
    if _consistency_repaired:
        full_response = repaired_response
        if full_response:
            yield (full_response, False, {
                "type": "response_repair",
                "reason": "consistency_guard",
            })
            if _emit_loop_trace:
                yield ("", False, build_loop_trace_correction_event(
                    stage="consistency_guard",
                    summary="Antwort wurde nach dem Schreiben konsistent korrigiert.",
                    reasons=["consistency_guard"],
                ))
    if isinstance(verified_plan.get("_ctx_trace"), dict) and isinstance(
        verified_plan["_ctx_trace"].get("skill_catalog"), dict
    ):
        yield ("", False, {
            "type": "thinking_trace",
            "thinking": _build_thinking_ui_payload(verified_plan, source="trace_final"),
        })
    
    # ═══════════════════════════════════════════════════
    # STEP 4: MEMORY SAVE
    # ═══════════════════════════════════════════════════
    orch._save_memory(
        conversation_id=conversation_id,
        answer=full_response,
        verified_plan=verified_plan
    )
    
    # ═══════════════════════════════════════════════════
    # DONE
    # ═══════════════════════════════════════════════════
    # [NEW] Lifecycle Finish
    orch.lifecycle.finish_task(req_id_str, {"status": "done", "duration": time.time()-_t0})
    orch._post_task_processing()
    _final_exec_result = execution_result_from_plan(verified_plan)
    _final_done_reason = str(_final_exec_result.done_reason.value or "stop")
    if _final_done_reason == "success":
        _final_done_reason = "stop"
    ws_done = orch._save_workspace_entry(
        conversation_id,
        orch._build_done_workspace_summary(
            _final_done_reason,
            response_mode=response_mode_stream,
            model=resolved_output_model_stream,
            memory_used=memory_used,
        ),
        "chat_done",
        "orchestrator",
    )
    if ws_done:
        yield ("", False, ws_done)

    _correction_count = 0
    if isinstance(_analysis_guard_violation, dict) and _analysis_guard_violation.get("violated"):
        _correction_count += 1
    if _consistency_repaired:
        _correction_count += 1
    if _emit_loop_trace:
        yield ("", False, build_loop_trace_completed_event(
            response_mode=response_mode_stream,
            model=resolved_output_model_stream,
            correction_count=_correction_count,
            summary="Loop-Trace abgeschlossen",
        ))

    yield (
        "",
        True,
        {
            "type": "done",
            "done_reason": _final_done_reason,
            "memory_used": memory_used,
            "model": resolved_output_model_stream,
        },
    )
    log_info_fn(f"[TIMING] T+{time.time()-_t0:.2f}s: COMPLETE")


# ===============================================================
# CHUNKING (moved from bridge.py)
# ===============================================================
