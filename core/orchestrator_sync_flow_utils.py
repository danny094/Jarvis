import asyncio
import re
import time
from typing import Any, Dict, List, Optional


def _extract_blueprint_hint_from_history(messages: Optional[List[dict]], current_user_text: str) -> str:
    """
    A3 Fix: extract a blueprint name from recent chat history.

    When a follow-up like "neuer Container bitte" doesn't contain a blueprint name,
    the Blueprint Router can't match. This function scans the last 6 messages for
    hyphenated words (blueprint names like 'gaming-station', 'python-sandbox') that
    are NOT already in the current user text.

    Returns the most recently mentioned blueprint candidate, or "" if none found.
    """
    if not messages:
        return ""
    current_lower = current_user_text.lower()
    # Blueprint names are typically hyphenated: gaming-station, python-sandbox, db-sandbox
    pattern = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")
    # Common hyphenated words that are NOT blueprint names
    skip = {"follow-up", "step-by-step", "well-known", "real-time", "up-to-date", "built-in"}
    for msg in reversed(messages[-6:]):
        content = str(msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "") or "")
        matches = pattern.findall(content.lower())
        for candidate in matches:
            if candidate in skip:
                continue
            if len(candidate) < 5:
                continue
            if candidate in current_lower:
                continue  # already in the current query
            return candidate
    return ""

from core.control_contract import (
    control_decision_from_plan,
    persist_control_decision,
)
from core.plan_runtime_bridge import (
    append_runtime_tool_results,
    set_runtime_tool_confidence,
    set_runtime_tool_failure,
    set_runtime_tool_results,
)

async def process_request(
    orch: Any,
    request: Any,
    *,
    core_chat_response_cls: Any,
    intent_system_available: bool,
    get_master_settings_fn: Any,
    thinking_plan_cache: Any,
    soften_control_deny_fn: Any,
    log_info_fn: Any,
    log_warn_fn: Any,
    log_warning_fn: Any,
) -> Any:
    """
    Standard (non-streaming) pipeline execution.
    
    Pipeline:
    1. Intent Confirmation Check
    2. Thinking Layer -> Plan
    3. Context Retrieval (via ContextManager)
    4. Control Layer -> Verify
    5. Output Layer -> Generate
    6. Memory Save
    """
    log_info_fn(f"[Orchestrator] Processing request from {request.source_adapter}")
    
    # [NEW] Lifecycle Start
    req_id = f"req-{int(time.time()*1000)}"
    _lifecycle_user_text = str(request.get_last_user_message() or "")
    orch.lifecycle.start_task(
        req_id,
        {"user_text": _lifecycle_user_text, "conversation_id": request.conversation_id},
    )
    
    user_text = str(request.get_last_user_message() or "")
    conversation_id = request.conversation_id
    forced_response_mode = orch._requested_response_mode(request)
    request_retrieval_cache: Dict[str, Any] = {}
    tone_signal = await orch._classify_tone_signal(user_text, request.messages)
    
    # ===============================================================
    # STEP 1: Intent Confirmation Check
    # ===============================================================
    if intent_system_available:
        confirmation_result = await orch._check_pending_confirmation(
            user_text, conversation_id
        )
        if confirmation_result:
            log_info_fn("[Orchestrator] Returning confirmation result")
            return confirmation_result

    from core.orchestrator_modules.task_loop import maybe_handle_task_loop_sync
    task_loop_response = await maybe_handle_task_loop_sync(
        orch,
        request,
        user_text,
        conversation_id,
        core_chat_response_cls=core_chat_response_cls,
        log_info_fn=log_info_fn,
        log_warn_fn=log_warn_fn,
        tone_signal=tone_signal,
    )
    if task_loop_response is not None:
        orch.lifecycle.finish_task(req_id, {"task_loop": True})
        orch._post_task_processing()
        return task_loop_response

    # ===============================================================
    # STEP 1.1: CONTEXT COMPRESSION (non-stream, deep-aware)
    # ===============================================================
    try:
        _deep_hint = forced_response_mode == "deep" or orch._is_explicit_deep_request(user_text)
        if _deep_hint:
            from core.context_compressor import get_compressor, estimate_protocol_tokens
            from utils.settings import settings as _settings
            _compression_enabled = _settings.get("CONTEXT_COMPRESSION_ENABLED", True)
            if _compression_enabled:
                _token_est = estimate_protocol_tokens()
                _compression_threshold = _settings.get("COMPRESSION_THRESHOLD", 100000)
                if _token_est >= _compression_threshold:
                    _compression_mode = _settings.get("CONTEXT_COMPRESSION_MODE", "sync")
                    log_info_fn(
                        "[Orchestrator] Context compression triggered (sync path) "
                        f"tokens={_token_est} mode={_compression_mode}"
                    )
                    if _compression_mode == "sync":
                        await get_compressor().check_and_compress()
                    else:
                        asyncio.create_task(get_compressor().check_and_compress())
    except Exception as _ce_sync:
        log_warn_fn(f"[Orchestrator] Context compression skipped (sync path): {_ce_sync}")
    
    # ===============================================================
    # STEP 1.5: Tool Selector (Layer 0)
    # ===============================================================
    from core.orchestrator_pipeline_stages import run_tool_selection_stage
    selected_tools, query_budget_signal, domain_route_signal, _last_assistant_msg = (
        await run_tool_selection_stage(
            orch, user_text, request, forced_response_mode, tone_signal, log_info_fn
        )
    )
    
    # ===============================================================
    # STEP 2: Thinking Layer
    # ===============================================================
    # Check if we should skip ThinkingLayer for Master
    skip_thinking = False
    if request.source_adapter == "master_orchestrator":
        settings = get_master_settings_fn()
        skip_thinking = not settings.get("use_thinking_layer", False)
        if skip_thinking:
            log_info_fn("[Pipeline] Skipping ThinkingLayer for Master (settings: use_thinking_layer=False)")
            thinking_plan = orch.thinking._default_plan()
            thinking_plan = orch._ensure_dialogue_controls(
                thinking_plan,
                tone_signal,
                user_text=user_text,
                selected_tools=selected_tools,
            )
    if (
        not skip_thinking
        and orch._should_skip_thinking_from_query_budget(
            query_budget_signal,
            user_text=user_text,
            forced_mode=forced_response_mode,
        )
    ):
        skip_thinking = True
        log_info_fn("[Pipeline] Skipping ThinkingLayer via QueryBudget signal")
        thinking_plan = orch.thinking._default_plan()
        thinking_plan = orch._ensure_dialogue_controls(
            thinking_plan,
            tone_signal,
            user_text=user_text,
            selected_tools=selected_tools,
        )
    
    if not skip_thinking:
        # ── ThinkingLayer Cache-Check (Sync-Pfad) ──
        # Kurze Inputs niemals cachen — vollständig kontextabhängig.
        _is_short_input = len(user_text.split()) < 5
        _cached_plan_sync = None if _is_short_input else thinking_plan_cache.get(user_text)
        if _is_short_input:
            log_info_fn("[Orchestrator] ThinkingLayer Cache SKIP: short input is context-dependent [sync]")
        if _cached_plan_sync:
            thinking_plan = _cached_plan_sync
            thinking_plan = orch._ensure_dialogue_controls(
                thinking_plan,
                tone_signal,
                user_text=user_text,
                selected_tools=selected_tools,
            )
            # Touch TTL on hit so repeated turns don't expire mid-benchmark.
            thinking_plan_cache.set(user_text, thinking_plan)
            log_info_fn(f"[Orchestrator] CACHE HIT ThinkingLayer (sync): intent='{thinking_plan.get('intent')}'")
        else:
            # Skill-Graph Pre-Fetch — policy-gated (sync path)
            _sync_skill_ctx, _sync_prefetch_mode = orch._maybe_prefetch_skills(
                user_text, selected_tools
            )
            # Variante A: Kontext-Anreicherung für extrem kurze Inputs.
            _thinking_user_text = user_text
            if _last_assistant_msg and len(user_text.split()) < 5:
                _ctx_snippet = _last_assistant_msg.strip()[-200:]
                _thinking_user_text = f"{user_text}. [Kontext: {_ctx_snippet}]"
                log_info_fn("[Orchestrator] A-Enrichment: ThinkingLayer user_text angereichert [sync]")

            thinking_plan = await orch.thinking.analyze(
                _thinking_user_text,
                memory_context=_sync_skill_ctx,
                available_tools=selected_tools,
                tone_signal=tone_signal,
            )
            thinking_plan = orch._ensure_dialogue_controls(
                thinking_plan,
                tone_signal,
                user_text=user_text,
                selected_tools=selected_tools,
            )
            thinking_plan["_trace_skills_prefetch"] = bool(_sync_skill_ctx)
            thinking_plan["_trace_skills_prefetch_mode"] = _sync_prefetch_mode
            thinking_plan_cache.set(user_text, thinking_plan)
            log_info_fn(f"[Orchestrator] ThinkingLayer plan cached (sync) prefetch={_sync_prefetch_mode}")
    # ===============================================================
    # STEP 2.1: PLAN FINALIZATION + RESPONSE MODE
    # ===============================================================
    from core.orchestrator_pipeline_stages import run_plan_finalization
    thinking_plan, response_mode = run_plan_finalization(
        orch, user_text, request, thinking_plan, selected_tools,
        query_budget_signal, domain_route_signal, forced_response_mode,
        conversation_id, log_info_fn,
    )
    log_info_fn(f"[Orchestrator] response_mode={response_mode} (sync)")

    # WORKSPACE: Save thinking observations (sync-Pfad Parität zu stream_flow_utils)
    _obs_text_sync = orch._extract_workspace_observations(thinking_plan)
    if _obs_text_sync:
        orch._save_workspace_entry(conversation_id, _obs_text_sync, "observation", "thinking")

    # ===============================================================
    # STEP 1.7+1.8: PRE-CONTROL GATES (Skill Dedup, Container, Hardware)
    # ===============================================================
    from core.orchestrator_pipeline_stages import run_pre_control_gates
    run_pre_control_gates(orch, user_text, thinking_plan, request, log_info_fn, log_warn_fn)

    # ===============================================================
    # STEP 3: Context Retrieval (unified via _build_effective_context)
    # ===============================================================
    log_info_fn("[Orchestrator] === CONTEXT RETRIEVAL ===")
    from config import get_small_model_mode as _get_smm
    _smm = _get_smm()
    retrieved_memory, ctx_trace, mem_res = orch.build_effective_context(
        user_text=user_text,
        conv_id=conversation_id,
        small_model_mode=_smm,
        cleanup_payload=thinking_plan,
        debug_flags={
            "skills_prefetch_used": bool(thinking_plan.get("_trace_skills_prefetch")),
            "skills_prefetch_mode": thinking_plan.get("_trace_skills_prefetch_mode", "off" if _smm else "full"),
            "detection_rules_used": thinking_plan.get("_trace_detection_rules_mode", "false"),
        },
        request_cache=request_retrieval_cache,
    )
    memory_used = ctx_trace.get("memory_used", False)
    # NOTE: context_text_chars = background context only (NOW/RULES/NEXT, capped).
    # tool_context is appended separately after tool execution and is NOT included here.
    log_info_fn(
        f"[CTX] mode={'small' if ctx_trace['small_model_mode'] else 'full'} "
        f"context_text_chars={ctx_trace['context_chars']} retrieval={ctx_trace['retrieval_count']} "
        f"src={','.join(ctx_trace['context_sources'])}"
    )

    # ===============================================================
    # STEP 4: Control Layer
    # ===============================================================
    verification, verified_plan = await orch._execute_control_layer(
        user_text,
        thinking_plan,
        retrieved_memory,
        conversation_id,
        response_mode=response_mode,
    )
    control_decision = control_decision_from_plan(
        verified_plan,
        default_approved=False,
    )

    # Skill confirmation must short-circuit the sync pipeline just like stream mode.
    if verified_plan.get("_pending_intent"):
        pending = verified_plan["_pending_intent"]
        return core_chat_response_cls(
            model=request.model,
            content=f"🛠️ Möchtest du den Skill **{pending.get('skill_name')}** erstellen? (Ja/Nein)",
            conversation_id=conversation_id,
            done=True,
            done_reason="confirmation_pending",
            memory_used=memory_used,
            validation_passed=True,
        )
    
    # ── ControlLayer Tool-Decision (sync-Pfad) ──
    _ctrl_decisions_sync = await orch._collect_control_tool_decisions(
        user_text,
        verified_plan,
        control_decision=control_decision,
        stream=False,
    )
    persist_control_decision(verified_plan, control_decision)

    # WORKSPACE: persist control decision (sync-Pfad Parität zu stream_flow_utils)
    _ctrl_summary_sync = orch._build_control_workspace_summary(
        verification,
        skipped=False,
        skip_reason="",
    )
    orch._save_workspace_entry(conversation_id, _ctrl_summary_sync, "control_decision", "control")

    # Control is the only hard-block authority.
    if orch._is_control_hard_block_decision(verification):
        log_info_fn("[Orchestrator] Request blocked (NON-STREAMING) - generating explanation...")
        
        warnings = verification.get("warnings", [])
        reason = verification.get("reason", "Safety policy violation")

        fallback = f"Diese Anfrage wurde aus Sicherheitsgründen blockiert: {reason}"
        if warnings:
            fallback += f" ({', '.join(warnings)})"
        
        return core_chat_response_cls(
            model=request.model,
            content=fallback,
            conversation_id=conversation_id,
            done=True,
            done_reason="blocked",
            memory_used=False,
        )
    if verification.get("approved") == False:
        soften_control_deny_fn(verification)
        control_decision = control_decision_from_plan(
            {"_control_decision": verification},
            default_approved=False,
        )
        persist_control_decision(verified_plan, control_decision)
        log_warning_fn("[Orchestrator] Soft control deny converted to warning (sync path)")
    
    # Extra memory lookup if Control corrected — gated by retrieval budget (Commit 4)
    if verification.get("corrections", {}).get("memory_keys"):
        from config import get_control_corrections_memory_keys_max
        _extra_limit = get_control_corrections_memory_keys_max()
        _raw_extra_keys = verification["corrections"]["memory_keys"] or []
        if not isinstance(_raw_extra_keys, (list, tuple)):
            _raw_extra_keys = []
        _seen_extra = set()
        extra_keys = []
        for _k in _raw_extra_keys:
            _nk = str(_k or "").strip()
            if not _nk or _nk in _seen_extra:
                continue
            extra_keys.append(_nk)
            _seen_extra.add(_nk)
            if len(extra_keys) >= _extra_limit:
                break
        if _extra_limit == 0:
            extra_keys = []
        if len(_raw_extra_keys) > len(extra_keys):
            log_info_fn(
                f"[CTX] extra-lookup keys capped: kept={len(extra_keys)} "
                f"dropped={len(_raw_extra_keys) - len(extra_keys)} limit={_extra_limit}"
            )
        _policy = orch._compute_retrieval_policy(thinking_plan, verified_plan)
        _retrieval_budget = _policy["max_retrievals"]
        for key in extra_keys:
            if key not in thinking_plan.get("memory_keys", []):
                if ctx_trace["retrieval_count"] >= _retrieval_budget:
                    log_info_fn(
                        f"[CTX] extra-lookup skipped (budget exhausted): "
                        f"key='{key}' count={ctx_trace['retrieval_count']} max={_retrieval_budget}"
                    )
                    continue
                log_info_fn(f"[Orchestrator-Control] Extra memory lookup: {key}")
                extra_text, extra_trace, _extra_res = orch.build_effective_context(
                    user_text=key,
                    conv_id=conversation_id,
                    small_model_mode=_smm,
                    cleanup_payload={"needs_memory": True, "memory_keys": [key]},
                    include_blocks={"compact": False, "system_tools": False, "memory_data": True},
                    request_cache=request_retrieval_cache,
                )
                if extra_text:
                    retrieved_memory = orch._append_context_block(
                        retrieved_memory, "\n" + extra_text, "jit_memory", ctx_trace
                    )
                    memory_used = True
                    ctx_trace["retrieval_count"] += 1
                    log_info_fn(
                        f"[CTX] extra-lookup key='{key}' "
                        f"chars={extra_trace['context_chars']} "
                        f"src={','.join(extra_trace['context_sources'])}"
                    )
    
    # ===============================================================
    # STEP 4.5: TOOL EXECUTION
    # ===============================================================
    suggested_tools = orch._resolve_execution_suggested_tools(
        user_text,
        verified_plan,
        _ctrl_decisions_sync,
        control_decision=control_decision,
        stream=False,
        enable_skill_trigger_router=False,
        conversation_id=conversation_id,
        chat_history=request.messages,
    )

    tool_context = ""
    if suggested_tools:
        log_info_fn(f"[Orchestrator] === TOOL EXECUTION: {suggested_tools} ===")
        # Suggest-Nachricht vorbereiten (wenn suggest-Zone, nicht no-match)
        _bp_suggest_data = thinking_plan.get("_blueprint_suggest")
        _bp_suggest_msg = ""
        if _bp_suggest_data:
            _cands = ", ".join(f"{c['id']} ({c['score']:.2f})" for c in _bp_suggest_data.get("candidates", []))
            _bp_suggest_msg = f"RÜCKFRAGE: Welchen Blueprint soll ich starten? Meinst du: {_cands}? Bitte präzisiere."

        tool_context = await asyncio.to_thread(
            orch._execute_tools_sync,
            suggested_tools, user_text, _ctrl_decisions_sync,
            last_assistant_msg=_last_assistant_msg,
            control_decision=control_decision,
            time_reference=thinking_plan.get("time_reference"),
            thinking_suggested_tools=thinking_plan.get("suggested_tools", []),
            blueprint_gate_blocked=thinking_plan.get("_blueprint_gate_blocked", False),
            blueprint_router_id=(thinking_plan.get("_blueprint_router") or {}).get("blueprint_id"),
            blueprint_suggest_msg=_bp_suggest_msg,
            session_id=conversation_id or "",
            verified_plan=verified_plan,
        )

    # ── Phase 1.5 Commit 2: Clip tool_context before append (small mode) ──
    tool_context = orch._clip_tool_context(tool_context, _smm)

    # ── Phase 1.5 Commit 3: Unified failure-compact (sync adopts stream pattern) ──
    # Prepend fail_block to tool_context; register source manually; single tool_ctx
    # append counts all chars once (no double-counting between failure_ctx + tool_ctx).
    if tool_context and "TOOL-FEHLER" in tool_context:
        _fail_block = orch._build_failure_compact_block(
            conversation_id, len(retrieved_memory), _smm
        )
        if _fail_block:
            log_info_fn(f"[CTX] failure-compact injected chars={len(_fail_block)} (via entry-point, sync path)")
            tool_context = _fail_block + tool_context
            ctx_trace["context_sources"].append("failure_ctx")

    if tool_context:
        retrieved_memory = orch._append_context_block(
            retrieved_memory, tool_context, "tool_ctx", ctx_trace
        )
        set_runtime_tool_results(verified_plan, tool_context)
        has_failures_or_skips = orch._tool_context_has_failures_or_skips(tool_context)
        has_success = orch._tool_context_has_success(tool_context)
        if has_failures_or_skips:
            set_runtime_tool_failure(verified_plan, True)
        if has_success and not has_failures_or_skips:
            set_runtime_tool_confidence(verified_plan, "high")
        if _smm:
            log_info_fn(
                f"[CTX] total context after tool_context: {len(retrieved_memory)} chars "
                f"(tool_context={len(tool_context)}, failure_ctx merged if any)"
            )

    _active_container_ctx = await orch._maybe_build_active_container_capability_context(
        user_text=user_text,
        conversation_id=conversation_id,
        verified_plan=verified_plan,
        history_len=len(request.messages),
    )
    _active_container_ctx_text = str((_active_container_ctx or {}).get("context_text") or "").strip()
    if _active_container_ctx_text:
        retrieved_memory = orch._append_context_block(
            retrieved_memory,
            _active_container_ctx_text,
            "active_container_ctx",
            ctx_trace,
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
        retrieved_memory = orch._append_context_block(
            retrieved_memory,
            _skill_semantic_ctx_text,
            "skill_catalog_ctx",
            ctx_trace,
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
    _recovery_ctx_sync = await orch._maybe_auto_recover_grounding_once(
        conversation_id=conversation_id,
        user_text=user_text,
        verified_plan=verified_plan,
        thinking_plan=thinking_plan,
        history_len=len(request.messages),
        session_id=conversation_id or "",
    )
    if _recovery_ctx_sync:
        retrieved_memory = orch._append_context_block(
            retrieved_memory, _recovery_ctx_sync, "tool_ctx_recovery", ctx_trace
        )
        append_runtime_tool_results(verified_plan, _recovery_ctx_sync)
        log_info_fn(
            f"[CTX] grounding auto-recovery injected chars={len(_recovery_ctx_sync)}"
        )

    orch._remember_conversation_grounding_state(
        conversation_id,
        verified_plan,
        history_len=len(request.messages),
    )

    # ── Phase 1.5 Commit 1: Final hard cap (always active in small mode) ──
    # Falls back to SMALL_MODEL_CHAR_CAP when SMALL_MODEL_FINAL_CAP=0 (no longer optional).
    retrieved_memory = orch._apply_final_cap(retrieved_memory, ctx_trace, _smm, "sync")
    retrieved_memory = orch._apply_effective_context_guardrail(
        retrieved_memory, ctx_trace, _smm, "sync"
    )

    # ── Finalize orchestrator-side trace and hand off to OutputLayer ──
    # [CTX-PRE-OUTPUT]: orchestrator context string before OutputLayer adds persona/instructions/history.
    # [CTX-FINAL] is emitted inside OutputLayer after the full messages array is built.
    ctx_trace["mode"] = orch._compute_ctx_mode(ctx_trace)
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
        ctx_trace["skill_catalog"] = {
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
        f"[CTX-PRE-OUTPUT] mode={ctx_trace['mode']} "
        f"context_sources={','.join(ctx_trace['context_sources'])} "
        f"context_chars={ctx_trace['context_chars_final']} "
        f"retrieval_count={ctx_trace['retrieval_count']}"
    )
    verified_plan["_ctx_trace"] = ctx_trace
    verified_plan["_response_mode"] = response_mode
    try:
        from config import get_output_timeout_interactive_s, get_output_timeout_deep_s
        verified_plan["_output_time_budget_s"] = (
            get_output_timeout_deep_s() if response_mode == "deep" else get_output_timeout_interactive_s()
        )
    except Exception:
        pass

    # ===============================================================
    # STEP 5: Output Layer
    # ===============================================================
    from core.orchestrator_pipeline_stages import prepare_output_invocation
    resolved_output_model, memory_required_but_missing = prepare_output_invocation(
        orch, request, verified_plan, mem_res, response_mode=verified_plan.get("_response_mode", "interactive")
    )

    log_info_fn("[Orchestrator] === LAYER 3: OUTPUT ===")
    if memory_required_but_missing:
        log_info_fn("[Orchestrator-Output] WARNING: Memory required but not found!")
    answer = await orch.output.generate(
        user_text=user_text,
        verified_plan=verified_plan,
        memory_data=retrieved_memory,
        model=resolved_output_model,
        chat_history=request.messages,
        control_decision=control_decision,
        execution_result=verified_plan.get("_execution_result"),
        memory_required_but_missing=memory_required_but_missing,
    )
    log_info_fn(f"[Orchestrator-Output] Generated {len(answer)} chars")

    answer = await orch._apply_conversation_consistency_guard(
        conversation_id=conversation_id,
        verified_plan=verified_plan,
        answer=answer,
    )
    
    # ===============================================================
    # STEP 6: Memory Save
    # ===============================================================
    orch._save_memory(conversation_id, verified_plan, answer)
    
    # ===============================================================
    # RETURN
    # ===============================================================
    # [NEW] Lifecycle Finish
    orch.lifecycle.finish_task(req_id, {"chars": len(answer)})
    orch._post_task_processing()
    _exec_result_sync = verified_plan.get("_execution_result", {})
    _done_reason_sync = str((_exec_result_sync or {}).get("done_reason") or "stop")
    if _done_reason_sync == "success":
        _done_reason_sync = "stop"

    # WORKSPACE: persist done entry (sync-Pfad Parität zu stream_flow_utils)
    orch._save_workspace_entry(
        conversation_id,
        orch._build_done_workspace_summary(
            _done_reason_sync,
            response_mode=response_mode,
            model=resolved_output_model,
            memory_used=memory_used,
        ),
        "chat_done",
        "orchestrator",
    )

    return core_chat_response_cls(
        model=resolved_output_model,
        content=answer,
        conversation_id=conversation_id,
        done=True,
        done_reason=_done_reason_sync,
        memory_used=memory_used,
        validation_passed=True,
    )

# ===============================================================
# STREAMING PIPELINE
# ===============================================================
