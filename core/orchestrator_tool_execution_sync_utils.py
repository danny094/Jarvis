import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.control_contract import (
    ControlDecision,
    DoneReason,
    execution_result_from_plan,
    persist_execution_result,
    tool_allowed_by_control_decision,
)
from core.plan_runtime_bridge import (
    get_runtime_grounding_evidence,
    get_runtime_successful_tool_runs,
    set_runtime_direct_response,
    set_runtime_grounding_evidence,
    set_runtime_successful_tool_runs,
)
from core.host_runtime_policy import (
    build_direct_host_runtime_response,
    build_host_runtime_blueprint_create_args,
    build_host_runtime_exec_args,
    build_host_runtime_failure_response,
    extract_blueprint_id_from_create_result,
)


def execute_tools_sync(
    suggested_tools: list,
    user_text: str,
    *,
    control_tool_decisions: Optional[dict] = None,
    control_decision: Optional[ControlDecision] = None,
    time_reference: Optional[str] = None,
    thinking_suggested_tools: Optional[list] = None,
    blueprint_gate_blocked: bool = False,
    blueprint_router_id: Optional[str] = None,
    blueprint_suggest_msg: str = "",
    session_id: str = "",
    verified_plan: Optional[Dict[str, Any]] = None,
    get_hub_fn: Callable[[], Any],
    get_recent_container_state_fn: Callable[[str], Any],
    build_tool_args_fn: Callable[..., Dict[str, Any]],
    route_blueprint_request_fn: Callable[[str, Dict[str, Any]], Any],
    tool_requires_container_id_fn: Callable[[str], bool],
    resolve_pending_container_id_sync_fn: Callable[..., Tuple[str, str]],
    validate_tool_args_fn: Callable[[Any, str, Dict[str, Any], str], Tuple[bool, Dict[str, Any], str]],
    bind_cron_conversation_id_fn: Callable[[str, Dict[str, Any], str], None],
    format_tool_result_fn: Callable[[Any, str], Tuple[str, bool, Dict[str, Any]]],
    build_tool_result_card_fn: Callable[[str, str, str, str], Tuple[str, str]],
    build_grounding_evidence_entry_fn: Callable[..., Dict[str, Any]],
    sanitize_tool_args_for_state_fn: Callable[[Any], Dict[str, Any]],
    verify_container_running_fn: Callable[[str], bool],
    save_workspace_entry_fn: Callable[[str, str, str, str], Any],
    update_container_state_from_tool_result_fn: Callable[[str, str, Dict[str, Any], Any], None],
    tool_intelligence_handle_tool_result_fn: Callable[..., Dict[str, Any]],
    build_direct_cron_create_response_fn: Callable[..., str],
    recover_home_read_directory_with_fast_lane_fn: Callable[[str], Tuple[bool, str]],
    build_container_event_content_fn: Callable[..., Any],
    save_container_event_fn: Callable[[str, Dict[str, Any]], None],
    log_info_fn: Callable[[str], None],
    log_warn_fn: Callable[[str], None],
    log_error_fn: Callable[[str], None],
    log_warning_fn: Optional[Callable[[str], None]] = None,
) -> str:
    tool_context = ""
    verified = verified_plan if isinstance(verified_plan, dict) else {}
    execution_result = execution_result_from_plan(verified)
    grounding_evidence: List[Dict[str, Any]] = []
    successful_tool_runs: List[Dict[str, Any]] = []
    direct_cron_response = ""
    direct_host_runtime_response = ""
    direct_host_runtime_failure_response = ""
    tool_hub = get_hub_fn()
    tool_hub.initialize()

    _log_warning = log_warning_fn or log_warn_fn
    host_runtime_lookup = bool(verified.get("_host_runtime_chain_applied"))
    host_runtime_bootstrap_attempted = False
    host_runtime_blueprint_fallback_attempted = False
    host_runtime_created_blueprint_id = ""
    host_runtime_last_failure_reason = ""
    host_runtime_exec_succeeded = False

    last_container_id = None
    container_state = get_recent_container_state_fn(session_id)
    known_last_container_id = ""
    if isinstance(container_state, dict):
        known_last_container_id = str(container_state.get("last_active_container_id", "")).strip()

    try:
        from core.tools.fast_lane.executor import get_fast_lane_executor

        fast_lane = get_fast_lane_executor()
    except ImportError:
        log_error_fn("[Orchestrator] FastLaneExecutor import failed!")
        fast_lane = None

    fast_lane_tools = {"home_read", "home_write", "home_list"}

    tool_queue = list(suggested_tools or [])
    tool_index = 0
    while tool_index < len(tool_queue):
        tool_spec = tool_queue[tool_index]
        tool_index += 1
        try:
            if isinstance(tool_spec, dict) and "tool" in tool_spec:
                tool_name = tool_spec["tool"]
                tool_args = tool_spec.get("args", {})
            elif isinstance(tool_spec, dict):
                tool_name = tool_spec.get("name")
                control_decisions = control_tool_decisions or {}
                tool_args = control_decisions.get(tool_name) or build_tool_args_fn(
                    tool_name,
                    user_text,
                    verified_plan=verified,
                )
            else:
                tool_name = tool_spec
                control_decisions = control_tool_decisions or {}
                tool_args = control_decisions.get(tool_name) or build_tool_args_fn(
                    tool_name,
                    user_text,
                    verified_plan=verified,
                )

            if not tool_allowed_by_control_decision(control_decision, tool_name):
                reason = "control_tool_not_allowed"
                log_warn_fn(f"[Orchestrator-Sync] Skipping {tool_name} — {reason}")
                execution_result.append_tool_status(tool_name=tool_name, status="unavailable", reason=reason)
                grounding_evidence.append(
                    {
                        "tool_name": tool_name,
                        "status": "unavailable",
                        "reason": reason,
                    }
                )
                continue

            if host_runtime_lookup:
                if tool_name == "exec_in_container":
                    existing_container_id = "PENDING"
                    if isinstance(tool_args, dict):
                        existing_container_id = str(tool_args.get("container_id") or "PENDING")
                    tool_args = build_host_runtime_exec_args(
                        container_id=existing_container_id
                    )
                elif tool_name == "blueprint_create" and host_runtime_blueprint_fallback_attempted:
                    tool_args = build_host_runtime_blueprint_create_args(user_text=user_text)

            if tool_name == "memory_graph_search" and time_reference:
                log_info_fn(
                    f"[Orchestrator] Blocking memory_graph_search — time_reference={time_reference}, protocol is source"
                )
                continue

            if tool_name == "home_write" and thinking_suggested_tools is not None:
                if "home_write" not in thinking_suggested_tools:
                    log_info_fn(
                        "[Orchestrator] Blocking home_write — not in ThinkingLayer suggested_tools (ControlLayer hallucination)"
                    )
                    continue

            if tool_name in {"autonomous_skill_task", "create_skill", "run_skill"} and verified.get(
                "_skill_gate_blocked"
            ):
                skill_reason = verified.get("_skill_gate_reason", "skill_router_unavailable")
                log_warn_fn(f"[Orchestrator-Sync] Tool unavailable {tool_name} — reason={skill_reason}")
                tool_context += (
                    f"\n[{tool_name}]: FEHLER: Skill-Router nicht verfügbar ({skill_reason}). "
                    "Tool kann in dieser Runtime nicht ausgeführt werden."
                )
                execution_result.append_tool_status(
                    tool_name=tool_name,
                    status="unavailable",
                    reason=skill_reason,
                )
                grounding_evidence.append(
                    {
                        "tool_name": tool_name,
                        "status": "unavailable",
                        "reason": skill_reason,
                    }
                )
                continue

            if tool_name == "request_container":
                if host_runtime_lookup and host_runtime_created_blueprint_id:
                    tool_args["blueprint_id"] = host_runtime_created_blueprint_id
                    tool_args["session_id"] = session_id
                    tool_args["conversation_id"] = session_id
                    log_info_fn(
                        "[Orchestrator-Sync] Host-runtime fallback blueprint injected: "
                        f"{host_runtime_created_blueprint_id}"
                    )
                elif blueprint_gate_blocked:
                    log_info_fn("[Orchestrator-Sync] request_container unavailable — blueprint gate preplanned")
                    block_msg = (
                        blueprint_suggest_msg
                        if blueprint_suggest_msg
                        else (
                            "FEHLER: Kein passender Blueprint gefunden. "
                            "Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                        )
                    )
                    if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                        host_runtime_blueprint_fallback_attempted = True
                        host_runtime_last_failure_reason = "request_container_blocked:no_blueprint_match"
                        tool_context += (
                            "\n[request_container]: FEHLER: Kein passender Blueprint im Router-Match. "
                            "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                        )
                        tool_queue[tool_index:tool_index] = ["blueprint_create", "request_container", "exec_in_container"]
                        continue
                    host_runtime_last_failure_reason = "request_container_blocked:no_blueprint_match"
                    tool_context += f"\n[request_container]: {block_msg}"
                    execution_result.append_tool_status(
                        tool_name=tool_name,
                        status="unavailable",
                        reason="no_blueprint_match",
                    )
                    continue
                elif blueprint_router_id:
                    tool_args["blueprint_id"] = blueprint_router_id
                    tool_args["session_id"] = session_id
                    tool_args["conversation_id"] = session_id
                    log_info_fn(f"[Orchestrator-Sync] blueprint_id injected: {blueprint_router_id}")
                else:
                    try:
                        jit_decision = route_blueprint_request_fn(user_text, {})
                        if jit_decision and jit_decision.get("blocked"):
                            jit_reason = jit_decision.get("reason", "blueprint_router_unavailable")
                            log_warn_fn(
                                f"[Orchestrator-Sync] JIT router blocked request_container — reason={jit_reason}"
                            )
                            if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                                host_runtime_blueprint_fallback_attempted = True
                                host_runtime_last_failure_reason = f"request_container_blocked:{jit_reason}"
                                tool_context += (
                                    "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. "
                                    "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                                )
                                tool_queue[tool_index:tool_index] = [
                                    "blueprint_create",
                                    "request_container",
                                    "exec_in_container",
                                ]
                                continue
                            host_runtime_last_failure_reason = f"request_container_blocked:{jit_reason}"
                            tool_context += (
                                "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. "
                                "Kein Freestyle-Container erlaubt."
                            )
                            execution_result.append_tool_status(
                                tool_name=tool_name,
                                status="unavailable",
                                reason=jit_reason,
                            )
                            continue
                        elif jit_decision and not jit_decision.get("suggest"):
                            tool_args["blueprint_id"] = jit_decision["blueprint_id"]
                            tool_args["session_id"] = session_id
                            tool_args["conversation_id"] = session_id
                            log_info_fn(
                                "[Orchestrator-Sync] JIT blueprint_id injected: "
                                f"{jit_decision['blueprint_id']} (score={jit_decision['score']:.2f})"
                            )
                        elif jit_decision and jit_decision.get("suggest"):
                            jit_cands = ", ".join(
                                f"{c['id']} ({c['score']:.2f})" for c in jit_decision["candidates"]
                            )
                            if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                                host_runtime_blueprint_fallback_attempted = True
                                host_runtime_last_failure_reason = "request_container_suggest:needs_manual_selection"
                                tool_context += (
                                    "\n[request_container]: Router ist unklar (Suggest-Zone). "
                                    "Host-Runtime-Fallback startet deterministisch mit blueprint_create."
                                )
                                tool_queue[tool_index:tool_index] = [
                                    "blueprint_create",
                                    "request_container",
                                    "exec_in_container",
                                ]
                                continue
                            log_info_fn(f"[Orchestrator-Sync] JIT suggest: {jit_cands} — Rückfrage nötig")
                            tool_context += (
                                "\n[request_container]: RÜCKFRAGE: Welchen Blueprint soll ich starten? "
                                f"Meinst du: {jit_cands}? Bitte präzisiere."
                            )
                            execution_result.append_tool_status(
                                tool_name=tool_name,
                                status="unavailable",
                                reason="jit_suggest_requires_selection",
                            )
                            continue
                        else:
                            log_info_fn(
                                "[Orchestrator-Sync] JIT Blueprint Gate: kein Match — blocking request_container"
                            )
                            if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                                host_runtime_blueprint_fallback_attempted = True
                                host_runtime_last_failure_reason = "request_container_blocked:no_jit_match"
                                tool_context += (
                                    "\n[request_container]: Kein Router-Match gefunden. "
                                    "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                                )
                                tool_queue[tool_index:tool_index] = [
                                    "blueprint_create",
                                    "request_container",
                                    "exec_in_container",
                                ]
                                continue
                            host_runtime_last_failure_reason = "request_container_blocked:no_jit_match"
                            tool_context += (
                                "\n[request_container]: FEHLER: Kein passender Blueprint gefunden. "
                                "Verfügbare Blueprints: python-sandbox, node-sandbox, db-sandbox, shell-sandbox."
                            )
                            execution_result.append_tool_status(
                                tool_name=tool_name,
                                status="unavailable",
                                reason="no_jit_match",
                            )
                            continue
                    except Exception as jit_error:
                        if host_runtime_lookup and not host_runtime_blueprint_fallback_attempted:
                            host_runtime_blueprint_fallback_attempted = True
                            host_runtime_last_failure_reason = f"request_container_jit_error:{jit_error}"
                            tool_context += (
                                "\n[request_container]: FEHLER: Blueprint-Router Laufzeitfehler. "
                                "Host-Runtime-Fallback startet: blueprint_create -> request_container -> exec_in_container."
                            )
                            tool_queue[tool_index:tool_index] = [
                                "blueprint_create",
                                "request_container",
                                "exec_in_container",
                            ]
                            continue
                        host_runtime_last_failure_reason = f"request_container_jit_error:{jit_error}"
                        log_warn_fn(
                            "[Orchestrator-Sync] JIT router error: "
                            f"{jit_error} — blocking request_container (no freestyle fallback)"
                        )
                        tool_context += (
                            "\n[request_container]: FEHLER: Blueprint-Router nicht verfügbar. "
                            "Kein Freestyle-Container erlaubt."
                        )
                        execution_result.append_tool_status(
                            tool_name=tool_name,
                            status="error",
                            reason=f"jit_router_error:{jit_error}",
                        )
                        continue

            if last_container_id and tool_args.get("container_id") == "PENDING":
                tool_args["container_id"] = last_container_id
            elif known_last_container_id and tool_args.get("container_id") == "PENDING":
                tool_args["container_id"] = known_last_container_id
            elif tool_args.get("container_id") == "PENDING":
                resolve_reason = "no_pending_resolution_attempted"
                if tool_requires_container_id_fn(tool_name):
                    preferred_ids = [
                        last_container_id,
                        known_last_container_id,
                        (container_state or {}).get("home_container_id", ""),
                        (container_state or {}).get("last_active_container_id", ""),
                    ]
                    resolved_id, resolve_reason = resolve_pending_container_id_sync_fn(
                        tool_hub,
                        session_id,
                        preferred_ids=[str(v or "").strip() for v in preferred_ids if str(v or "").strip()],
                    )
                    if resolved_id:
                        tool_args["container_id"] = resolved_id
                        last_container_id = resolved_id
                        known_last_container_id = resolved_id
                        log_info_fn(
                            f"[Orchestrator-Sync] Auto-resolved container_id for {tool_name}: {resolved_id[:12]}"
                        )

                if tool_args.get("container_id") == "PENDING" and tool_name != "request_container":
                    if host_runtime_lookup and tool_name == "exec_in_container" and not host_runtime_bootstrap_attempted:
                        host_runtime_bootstrap_attempted = True
                        host_runtime_last_failure_reason = f"exec_missing_container:{resolve_reason}"
                        tool_context += (
                            "\n[exec_in_container]: Keine aktive container_id gefunden. "
                            "Host-Runtime-Fallback startet: request_container -> exec_in_container."
                        )
                        tool_queue[tool_index:tool_index] = ["request_container", "exec_in_container"]
                        continue
                    skip_reason = f"missing_container_id:auto_resolve_failed:{resolve_reason}"
                    log_warn_fn(f"[Orchestrator-Sync] Skipping {tool_name} - {skip_reason}")
                    tool_context += f"\n### TOOL-SKIP ({tool_name}): {skip_reason}\n"
                    execution_result.append_tool_status(
                        tool_name=tool_name,
                        status="unavailable",
                        reason=skip_reason,
                    )
                    grounding_evidence.append(
                        {
                            "tool_name": tool_name,
                            "status": "unavailable",
                            "reason": skip_reason,
                        }
                    )
                    continue

            valid, tool_args, arg_reason = validate_tool_args_fn(tool_hub, tool_name, tool_args, user_text)
            if not valid:
                log_warn_fn(f"[Orchestrator] Skipping {tool_name} due to invalid args: {arg_reason}")
                if host_runtime_lookup and tool_name in {"exec_in_container", "request_container", "blueprint_create"}:
                    host_runtime_last_failure_reason = f"{tool_name}_invalid_args:{arg_reason}"
                tool_context += f"\n### TOOL-SKIP ({tool_name}): {arg_reason}\n"
                execution_result.append_tool_status(
                    tool_name=tool_name,
                    status="unavailable",
                    reason=arg_reason,
                )
                grounding_evidence.append(
                    {
                        "tool_name": tool_name,
                        "status": "unavailable",
                        "reason": arg_reason,
                    }
                )
                continue
            bind_cron_conversation_id_fn(tool_name, tool_args, session_id)

            is_fast_lane = tool_name in fast_lane_tools
            executed = False
            if is_fast_lane and fast_lane:
                try:
                    log_info_fn(f"[Orchestrator] Executing {tool_name} via Fast Lane")
                    result = fast_lane.execute(tool_name, tool_args)
                    formatted, success, _metadata = format_tool_result_fn(result, tool_name)
                    fl_status = "ok" if success else "error"
                    fl_raw = formatted.strip()
                    card, ref = build_tool_result_card_fn(tool_name, fl_raw, fl_status, session_id)
                    tool_context += card
                    grounding_evidence.append(
                        build_grounding_evidence_entry_fn(
                            tool_name=tool_name,
                            raw_result=fl_raw,
                            status=fl_status,
                            ref_id=ref,
                        )
                    )
                    if success:
                        execution_result.append_tool_status(
                            tool_name=tool_name,
                            status="ok",
                            reason="fast_lane",
                        )
                        successful_tool_runs.append(
                            {
                                "tool_name": str(tool_name),
                                "args": sanitize_tool_args_for_state_fn(tool_args),
                            }
                        )
                    else:
                        execution_result.append_tool_status(
                            tool_name=tool_name,
                            status="error",
                            reason="fast_lane_error",
                        )
                    executed = True
                except Exception as fast_lane_error:
                    _log_warning(
                        f"[Orchestrator] Fast Lane failed for {tool_name}, falling back to MCP: {fast_lane_error}"
                    )

            if not executed:
                if tool_name == "exec_in_container" and tool_args.get("container_id"):
                    cid = tool_args["container_id"]
                    if cid != last_container_id:
                        if not verify_container_running_fn(cid):
                            log_warn_fn(
                                f"[Orchestrator-Verify] Container {cid[:12]} NOT running — aborting exec"
                            )
                            stop_event = json.dumps(
                                {
                                    "container_id": cid,
                                    "stopped_at": datetime.utcnow().isoformat() + "Z",
                                    "reason": "verify_failed",
                                    "session_id": session_id,
                                },
                                ensure_ascii=False,
                            )
                            save_workspace_entry_fn(
                                "_container_events",
                                stop_event,
                                "container_stopped",
                                "orchestrator",
                            )
                            tool_context += (
                                f"\n### VERIFY-FEHLER ({tool_name}): Container {cid[:12]} ist nicht mehr aktiv.\n"
                            )
                            grounding_evidence.append(
                                {
                                    "tool_name": tool_name,
                                    "status": "error",
                                    "reason": "container_not_running",
                                }
                            )
                            execution_result.append_tool_status(
                                tool_name=tool_name,
                                status="error",
                                reason="container_not_running",
                            )
                            continue

                log_info_fn(f"[Orchestrator] Calling tool: {tool_name}({tool_args})")
                result = tool_hub.call_tool(tool_name, tool_args)

                if tool_name == "request_container" and isinstance(result, dict):
                    last_container_id = result.get("container_id", "") or result.get("container", {}).get(
                        "container_id",
                        "",
                    )
                    known_last_container_id = last_container_id or known_last_container_id
                if tool_name == "blueprint_create":
                    _created_id = extract_blueprint_id_from_create_result(result)
                    if _created_id:
                        host_runtime_created_blueprint_id = _created_id
                        log_info_fn(f"[Orchestrator-Sync] Host-runtime blueprint created: {_created_id}")
                    elif host_runtime_lookup:
                        host_runtime_last_failure_reason = "blueprint_create_missing_id"

                update_container_state_from_tool_result_fn(
                    session_id,
                    tool_name,
                    tool_args,
                    result,
                )

                result_str = (
                    json.dumps(result, ensure_ascii=False, default=str)
                    if isinstance(result, (dict, list))
                    else str(result)
                )
                intelligence_result = tool_intelligence_handle_tool_result_fn(
                    tool_name=tool_name,
                    result=result,
                    tool_args=tool_args,
                    tool_hub=tool_hub,
                )

                retry_result = intelligence_result.get("retry_result")
                if retry_result and retry_result.get("success"):
                    log_info_fn(f"[AutoRetry] Success on attempt {retry_result['attempts']}!")
                    result = retry_result["result"]
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    retry_info = (
                        f"Auto-Retry OK (fix={retry_result['fix_applied']}, "
                        f"attempt={retry_result['attempts']}/2)\n{result_str}"
                    )
                    card, ref = build_tool_result_card_fn(tool_name, retry_info, "ok", session_id)
                    tool_context += card
                    grounding_evidence.append(
                        build_grounding_evidence_entry_fn(
                            tool_name=tool_name,
                            raw_result=retry_info,
                            status="ok",
                            ref_id=ref,
                        )
                    )
                    successful_tool_runs.append(
                        {
                            "tool_name": str(tool_name),
                            "args": sanitize_tool_args_for_state_fn(tool_args),
                        }
                    )
                    execution_result.append_tool_status(
                        tool_name=tool_name,
                        status="ok",
                        reason="retry_success",
                    )
                    if tool_name == "autonomy_cron_create_job":
                        direct_msg = build_direct_cron_create_response_fn(
                            result=result,
                            tool_args=tool_args,
                            conversation_id=session_id,
                        )
                        if direct_msg:
                            direct_cron_response = direct_msg
                    direct_host_msg = build_direct_host_runtime_response(tool_name, tool_args, result)
                    if direct_host_msg:
                        direct_host_runtime_response = direct_host_msg
                        host_runtime_exec_succeeded = True
                    log_info_fn(f"[Orchestrator] Tool {tool_name} OK after retry ref={ref}")

                elif intelligence_result["is_error"]:
                    error_msg = intelligence_result["error_msg"]
                    solutions = intelligence_result.get("solutions", "")
                    if host_runtime_lookup and tool_name in {"exec_in_container", "request_container", "blueprint_create"}:
                        host_runtime_last_failure_reason = f"{tool_name}_error:{error_msg}"
                    if tool_name == "home_read" and "is a directory" in str(error_msg or "").lower():
                        dir_path = str(tool_args.get("path") or ".")
                        rec_ok, rec_payload = recover_home_read_directory_with_fast_lane_fn(dir_path)
                        if rec_ok and str(rec_payload).strip():
                            log_info_fn(
                                f"[Orchestrator] home_read recovery (sync) for directory '{dir_path}' succeeded"
                            )
                            card, ref = build_tool_result_card_fn(
                                tool_name,
                                rec_payload,
                                "ok",
                                session_id,
                            )
                            tool_context += card
                            grounding_evidence.append(
                                build_grounding_evidence_entry_fn(
                                    tool_name=tool_name,
                                    raw_result=rec_payload,
                                    status="ok",
                                    ref_id=ref,
                                )
                            )
                            successful_tool_runs.append(
                                {
                                    "tool_name": str(tool_name),
                                    "args": sanitize_tool_args_for_state_fn(tool_args),
                                }
                            )
                            continue

                    log_warn_fn(f"[Orchestrator] Tool {tool_name} FAILED: {error_msg}")
                    err_detail = error_msg + (f"\n{solutions}" if solutions else "")
                    if retry_result:
                        err_detail += f"\nAuto-Retry: {retry_result.get('reason', '')}"
                    card, ref = build_tool_result_card_fn(tool_name, err_detail, "error", session_id)
                    tool_context += f"\n### TOOL-FEHLER ({tool_name}):\n"
                    tool_context += card
                    grounding_evidence.append(
                        build_grounding_evidence_entry_fn(
                            tool_name=tool_name,
                            raw_result=err_detail,
                            status="error",
                            ref_id=ref,
                        )
                    )
                    execution_result.append_tool_status(
                        tool_name=tool_name,
                        status="error",
                        reason=error_msg,
                    )
                else:
                    card, ref = build_tool_result_card_fn(tool_name, result_str, "ok", session_id)
                    tool_context += card
                    grounding_evidence.append(
                        build_grounding_evidence_entry_fn(
                            tool_name=tool_name,
                            raw_result=result_str,
                            status="ok",
                            ref_id=ref,
                        )
                    )
                    successful_tool_runs.append(
                        {
                            "tool_name": str(tool_name),
                            "args": sanitize_tool_args_for_state_fn(tool_args),
                        }
                    )
                    execution_result.append_tool_status(
                        tool_name=tool_name,
                        status="ok",
                        reason="tool_ok",
                    )
                    if tool_name == "autonomy_cron_create_job":
                        direct_msg = build_direct_cron_create_response_fn(
                            result=result,
                            tool_args=tool_args,
                            conversation_id=session_id,
                        )
                        if direct_msg:
                            direct_cron_response = direct_msg
                    direct_host_msg = build_direct_host_runtime_response(tool_name, tool_args, result)
                    if direct_host_msg:
                        direct_host_runtime_response = direct_host_msg
                        host_runtime_exec_succeeded = True
                    log_info_fn(f"[Orchestrator] Tool {tool_name} OK: {len(result_str)} chars ref={ref}")

                container_evt = build_container_event_content_fn(
                    tool_name,
                    result,
                    user_text,
                    tool_args,
                    session_id=session_id,
                )
                if container_evt:
                    save_container_event_fn("_container_events", container_evt)
                    log_info_fn(f"[Orchestrator] Container event: {container_evt['event_type']}")

        except Exception as tool_error:
            log_error_fn(f"[Orchestrator] Tool {tool_name} failed: {tool_error}")
            if host_runtime_lookup and tool_name in {"exec_in_container", "request_container", "blueprint_create"}:
                host_runtime_last_failure_reason = f"{tool_name}_exception:{tool_error}"
            tool_context += f"\n### TOOL-FEHLER ({tool_name}): {str(tool_error)}\n"
            grounding_evidence.append(
                {
                    "tool_name": tool_name,
                    "status": "error",
                    "reason": str(tool_error),
                }
            )
            execution_result.append_tool_status(
                tool_name=tool_name,
                status="error",
                reason=str(tool_error),
            )

    if isinstance(verified, dict):
        if host_runtime_lookup and not direct_host_runtime_response:
            detail_reason = host_runtime_last_failure_reason or "host_runtime_chain_exhausted"
            direct_host_runtime_failure_response = build_host_runtime_failure_response(
                reason=detail_reason,
                attempted_blueprint_create=host_runtime_blueprint_fallback_attempted,
            )

        existing_evidence = get_runtime_grounding_evidence(verified)
        set_runtime_grounding_evidence(
            verified,
            [*existing_evidence, *grounding_evidence],
        )

        existing_runs = get_runtime_successful_tool_runs(verified)
        set_runtime_successful_tool_runs(
            verified,
            [*existing_runs, *successful_tool_runs],
        )

        has_failures = any(
            str((item or {}).get("status", "")).strip().lower() in {"error", "skip", "partial", "unavailable"}
            for item in grounding_evidence
            if isinstance(item, dict)
        )
        only_cron_create = bool(successful_tool_runs) and all(
            str((item or {}).get("tool_name", "")).strip() == "autonomy_cron_create_job"
            for item in successful_tool_runs
            if isinstance(item, dict)
        )
        if direct_cron_response and not has_failures and only_cron_create:
            set_runtime_direct_response(verified, direct_cron_response)
            execution_result.direct_response = direct_cron_response
        elif direct_host_runtime_response and not has_failures:
            set_runtime_direct_response(verified, direct_host_runtime_response)
            execution_result.direct_response = direct_host_runtime_response
        elif direct_host_runtime_failure_response:
            set_runtime_direct_response(verified, direct_host_runtime_failure_response)
            execution_result.direct_response = direct_host_runtime_failure_response
        else:
            set_runtime_direct_response(verified, "")
            execution_result.direct_response = ""

    execution_result.finalize_done_reason()
    if execution_result.done_reason == DoneReason.STOP and suggested_tools:
        execution_result.done_reason = DoneReason.SKIPPED
    persist_execution_result(verified, execution_result)

    return tool_context
