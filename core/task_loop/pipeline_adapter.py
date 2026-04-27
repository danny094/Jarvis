from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional

from core.task_loop.capabilities.container.context import build_container_context
from core.task_loop.chat_runtime import is_task_loop_continue
from core.tool_exposure import build_available_tools_snapshot, build_detection_hints


async def build_task_loop_planning_context(
    orch: Any,
    user_text: str,
    *,
    conversation_id: str = "",
    request: Any = None,
    forced_response_mode: Optional[str] = None,
    tone_signal: Optional[Dict[str, Any]] = None,
    log_info_fn: Any = None,
    log_warn_fn: Any = None,
) -> Dict[str, Any]:
    try:
        thinking = getattr(orch, "thinking", None)
        analyze = getattr(thinking, "analyze", None)
        if analyze is None:
            return {}
        info = log_info_fn or (lambda _msg: None)
        selected_tools = []
        memory_context = ""
        last_assistant_msg = ""
        request_obj = request if request is not None else SimpleNamespace(messages=[], raw_request={})

        tool_selector = getattr(orch, "tool_selector", None)
        if tool_selector is not None:
            try:
                from core.orchestrator_pipeline_stages import run_tool_selection_stage

                selected_tools, _, _, last_assistant_msg = await run_tool_selection_stage(
                    orch,
                    user_text,
                    request_obj,
                    forced_response_mode,
                    tone_signal,
                    info,
                )
            except Exception as exc:
                if log_warn_fn:
                    log_warn_fn(f"[TaskLoop] Tool selection for planning context skipped: {exc}")

        maybe_prefetch_skills = getattr(orch, "_maybe_prefetch_skills", None)
        if callable(maybe_prefetch_skills):
            try:
                memory_context, _prefetch_mode = maybe_prefetch_skills(user_text, selected_tools)
                if memory_context:
                    info(
                        "[TaskLoop] Skill context prepared for planning "
                        f"mode={_prefetch_mode}"
                    )
            except Exception as exc:
                if log_warn_fn:
                    log_warn_fn(f"[TaskLoop] Skill prefetch for planning context skipped: {exc}")

        thinking_user_text = user_text
        if last_assistant_msg and len(user_text.split()) < 5:
            context_snippet = last_assistant_msg.strip()[-200:]
            thinking_user_text = f"{user_text}. [Kontext: {context_snippet}]"

        _hub_ref = getattr(orch, "mcp_hub", None)
        available_tools_snapshot = build_available_tools_snapshot(
            selected_tools,
            hub=_hub_ref,
        )
        tool_hints = build_detection_hints(hub=_hub_ref)

        plan = await analyze(
            thinking_user_text,
            memory_context=memory_context,
            available_tools=available_tools_snapshot,
            tone_signal=tone_signal,
            tool_hints=tool_hints,
        )
        ensure_dialogue_controls = getattr(orch, "_ensure_dialogue_controls", None)
        if isinstance(plan, dict) and callable(ensure_dialogue_controls):
            plan = ensure_dialogue_controls(
                plan,
                tone_signal,
                user_text=user_text,
                selected_tools=selected_tools,
            )
        maybe_active_container_ctx = getattr(orch, "_maybe_build_active_container_capability_context", None)
        if (
            isinstance(plan, dict)
            and callable(maybe_active_container_ctx)
            and str(conversation_id or "").strip()
        ):
            try:
                await maybe_active_container_ctx(
                    user_text=user_text,
                    conversation_id=str(conversation_id or "").strip(),
                    verified_plan=plan,
                )
            except Exception as exc:
                if log_warn_fn:
                    log_warn_fn(
                        "[TaskLoop] Active-container context for planning context skipped: "
                        f"{exc}"
                    )
        if (
            isinstance(plan, dict)
            and not plan.get("suggested_tools")
            and selected_tools
            and is_task_loop_continue(user_text)
        ):
            plan["suggested_tools"] = list(selected_tools)
        if isinstance(plan, dict):
            capability_context = build_container_context(
                user_text,
                thinking_plan=plan,
                selected_tools=selected_tools or list(plan.get("suggested_tools") or []),
                existing_context=plan.get("_container_capability_context"),
            )
            if capability_context:
                plan["_container_capability_context"] = capability_context
        return plan if isinstance(plan, dict) else {}
    except Exception as exc:
        if log_warn_fn:
            log_warn_fn(f"[TaskLoop] Thinking planning context skipped: {exc}")
        return {}
