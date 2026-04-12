from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_admin_api_stream_keeps_typed_metadata_events():
    src = _read("adapters/admin-api/main.py")
    assert 'elif chunk_type and chunk_type != "content" and metadata:' in src
    assert "**metadata" in src
    assert '"done": bool(metadata.get("done", False))' in src


def test_lobechat_adapter_stream_keeps_typed_metadata_events():
    src = _read("adapters/lobechat/main.py")
    assert 'elif chunk_type and chunk_type != "content" and metadata:' in src
    assert "**metadata" in src
    assert '"done": bool(metadata.get("done", False))' in src


def test_lobechat_done_branch_checked_before_generic_metadata_branch():
    src = _read("adapters/lobechat/main.py")
    idx_done = src.index("if is_done:")
    idx_generic = src.index('elif chunk_type and chunk_type != "content" and metadata:')
    assert idx_done < idx_generic


def test_lobechat_done_branch_keeps_terminal_done_fields():
    src = _read("adapters/lobechat/main.py")
    done_block = src[src.index("if is_done:"): src.index('elif chunk_type == "thinking_stream":')]
    assert '"done": True' in done_block
    assert '"done_reason": metadata.get("done_reason", "stop")' in done_block
    assert 'response_data["type"] = metadata.get("type")' in done_block


def test_admin_api_terminal_done_contract_fields():
    src = _read("adapters/admin-api/main.py")
    done_block = src[src.index("if is_done:"): src.index('elif chunk_type == "thinking_stream":')]
    assert '"done": True' in done_block
    assert '"done_reason": metadata.get("done_reason", "stop")' in done_block


def test_api_stream_typed_event_passthrough():
    src = _read("adapters/Jarvis/static/js/api.js")
    assert 'if (data.type && typeof data.type === "string") {' in src
    assert "yield data;" in src


def test_chat_forwards_non_content_events_to_panel_bridge():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert 'if (chunk.type && !["content", "memory", "done"].includes(chunk.type)) {' in src
    assert 'window.dispatchEvent(new CustomEvent("sse-event", { detail: chunk }))' in src


def test_stream_thinking_event_contract_supports_legacy_and_current_chunk_fields():
    src = _read("core/orchestrator_stream_flow_utils.py")
    assert '"type": "thinking_stream"' in src
    assert '"chunk": chunk' in src
    assert '"thinking_chunk": chunk' in src


def test_chat_reads_both_thinking_chunk_field_variants_and_uses_thinking_label():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert 'Thinking.createThinkingBox(baseMsgId, "Thinking", "brain")' in src
    assert 'chunk.chunk || chunk.thinking_chunk || ""' in src
    assert 'if (chunk.type === "thinking_trace") {' in src
    assert "Thinking.finalizeThinking(controlThinkingId, chunk.thinking);" in src


def test_loop_trace_events_are_routed_into_plan_box():
    src = _read("adapters/Jarvis/static/js/chat.js")
    for marker in [
        '"loop_trace_started"',
        '"loop_trace_plan_normalized"',
        '"loop_trace_step_started"',
        '"loop_trace_correction"',
        '"loop_trace_completed"',
        '"task_loop_update"',
        "I'm tracing and correcting the loop...",
        "I'm working on the next step...",
    ]:
        assert marker in src


def test_task_loop_content_is_rendered_as_separate_assistant_segments():
    src = _read("adapters/Jarvis/static/js/chat.js")
    required_markers = [
        'let sawTaskLoopEvent = false;',
        'let taskLoopBotMsgId = null;',
        'let taskLoopBuffer = "";',
        'let taskLoopSegmentBoundary = false;',
        'if (planType === "task_loop_update") {',
        'if (sawTaskLoopEvent) {',
        'taskLoopBotMsgId = Render.renderMessage("assistant", "", true);',
        'taskLoopBuffer += contentChunk;',
        'Render.updateMessage(taskLoopBotMsgId, taskLoopBuffer, true);',
        'segmentedResponses.push(taskLoopBuffer.trimEnd());',
        'const finalResponses = segmentedResponses.length ? segmentedResponses : (fullResponse ? [fullResponse] : []);',
        'ai_response: finalResponses.join("\\n\\n")',
    ]
    for marker in required_markers:
        assert marker in src


def test_chat_render_uses_lightweight_streaming_shell_for_live_updates():
    src = _read("adapters/Jarvis/static/js/chat-render.js")
    for marker in [
        "const STREAM_RENDER_STATE = new Map();",
        'function ensureStreamingShell(contentEl) {',
        'data-stream-text="true"',
        'data-stream-cursor="true"',
        "requestAnimationFrame(() => {",
        "applyStreamingMessageContent(messageId, pending.content, true);",
        "queueStreamingMessageRender(messageId, content);",
        "clearStreamingMessageRender(messageId);",
    ]:
        assert marker in src


def test_thinking_box_renders_compact_strategy_and_trace_metadata():
    src = _read("adapters/Jarvis/static/js/chat-thinking.js")
    required_markers = [
        'renderMetaRow("Strategy"',
        'renderMetaRow("Memory"',
        'renderMetaRow("Tools"',
        'renderMetaRow("Exec Tools"',
        'renderMetaRow("Catalog Hints"',
        'renderMetaRow("Addon Docs"',
        'renderMetaRow("Inventory Mode"',
        'renderMetaRow("Postcheck"',
        'renderMetaRow("Tool Route"',
        'renderMetaRow("Route Reason"',
        'renderMetaRow("Loop Mode"',
        'renderMetaRow("Loop Reason"',
        'renderMetaRow("Plan Fixes"',
        'renderMetaRow("Fact Query"',
        'renderMetaRow("Uses History"',
        'renderMetaRow("Source"',
        'renderMetaRow("Reason"',
        'thinking.source === "trace_final"',
        "JSON.stringify(finalTrace, null, 2)",
    ]
    for marker in required_markers:
        assert marker in src


def test_plan_box_renders_loop_trace_event_variants():
    src = _read("adapters/Jarvis/static/js/chat-plan.js")
    for marker in [
        'eventType === "loop_trace_started"',
        'eventType === "loop_trace_plan_normalized"',
        'eventType === "loop_trace_step_started"',
        'eventType === "loop_trace_correction"',
        'eventType === "loop_trace_completed"',
        'eventType === "task_loop_update"',
        'title: "Loop-Trace gestartet"',
        'title: "Korrektur angewendet"',
        '"Task-Loop abgeschlossen"',
        '"Task-Loop läuft"',
    ]:
        assert marker in src


def test_stream_flow_emits_loop_trace_events():
    src = _read("core/orchestrator_stream_flow_utils.py")
    for marker in [
        "build_loop_trace_started_event",
        "build_loop_trace_plan_normalized_event",
        "build_loop_trace_step_started_event",
        "build_loop_trace_correction_event",
        "build_loop_trace_completed_event",
    ]:
        assert marker in src


def test_activity_mappings_cover_core_runtime_events():
    src = _read("adapters/Jarvis/static/js/chat.js")
    required_markers = [
        "I'm running tools",
        "I'm evaluating tool results...",
        "I'm in ${mode} mode...",
        "I'm updating workspace context...",
        "I'm analyzing your request...",
        "I'm working through sequential steps...",
        "I'm writing the response...",
        "Finalizing response...",
        "Ready for input",
    ]
    for marker in required_markers:
        assert marker in src


def test_workspace_replay_contract_for_planning_events():
    src = _read("adapters/Jarvis/static/js/workspace.js")
    assert "/^planning_(start|step|done|error)$/.test(item.entry_type)" in src
    assert "replay: true" in src


def test_sequential_plugin_handles_planning_workspace_events():
    src = _read("trion/plugins/sequential-thinking/plugin.ts")
    assert "this.ctx.events.on('workspace_update'" in src
    assert "entryType === 'planning_start'" in src
    assert "entryType === 'planning_step'" in src
    assert "entryType === 'planning_done'" in src
    assert "entryType === 'planning_error'" in src
