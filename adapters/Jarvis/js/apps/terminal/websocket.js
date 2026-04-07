function createWebSocketController(deps) {
    let ws = null;
    let pendingMessages = [];

    function flushPendingMessages() {
        if (!ws || ws.readyState !== 1 || !pendingMessages.length) return;
        const queue = pendingMessages.slice();
        pendingMessages = [];
        queue.forEach((msg) => {
            try {
                ws.send(JSON.stringify(msg));
            } catch (_) {
                pendingMessages.push(msg);
            }
        });
    }

    function connectWebSocket() {
        if (ws && ws.readyState <= 1) return;

        deps.updateConnectionStatus('connecting');

        try {
            ws = new WebSocket(deps.wsUrl);
        } catch (_) {
            deps.updateConnectionStatus(false);
            window.setTimeout(connectWebSocket, 5000);
            return;
        }

        ws.onopen = () => {
            deps.updateConnectionStatus(true);
            deps.logOutput('✅ WebSocket connected', 'ansi-green');
            const attachedContainer = String(deps.getAttachedContainer?.() || '').trim();
            if (attachedContainer) {
                pendingMessages.unshift({ type: 'attach', container_id: attachedContainer });
            }
            flushPendingMessages();
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleWsMessage(msg);
            } catch (_) {
                deps.logOutput(`⚠️ Bad WS message: ${event.data}`, 'ansi-yellow');
            }
        };

        ws.onclose = () => {
            deps.updateConnectionStatus(false);
            deps.logOutput('🔌 WebSocket disconnected — reconnecting...', 'ansi-dim');
            ws = null;
            window.setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = () => {
            deps.updateConnectionStatus(false);
        };
    }

    function handleWsMessage(msg) {
        switch (msg.type) {
            case 'output':
                routeStreamOutput(msg);
                break;
            case 'event':
                handleEvent(msg);
                break;
            case 'error':
                deps.logOutput(`❌ ${msg.message}`, 'ansi-red');
                break;
            case 'exit':
                deps.logOutput(`⏹ Container ${msg.container_id?.slice(0, 12)} exited (code: ${msg.exit_code})`, 'ansi-yellow');
                deps.removeShellSession(msg.container_id || '');
                if (deps.getTrionShellState?.().active && deps.getTrionShellState?.().containerId === (msg.container_id || '')) {
                    deps.setTrionShellMode?.({ active: false, containerId: '', language: 'en' });
                }
                deps.setAttachedContainer(null);
                deps.loadContainers();
                break;
            case 'exec_done':
                break;
            default:
                deps.logOutput(`[WS] ${msg.type}: ${JSON.stringify(msg)}`, 'ansi-dim');
        }
    }

    function handleEvent(msg) {
        const event = msg.event;
        const level = String(msg.level || 'info');
        const detailMessage = msg.message || event;
        deps.pushActivity({
            level,
            event,
            message: detailMessage,
            container_id: msg.container_id || '',
            blueprint_id: msg.blueprint_id || '',
            created_at: new Date().toISOString(),
        });

        if (event === 'container_started') {
            deps.logOutput(`▶ Container started: ${msg.container_id?.slice(0, 12)} (${msg.blueprint_id})`, 'ansi-green');
            deps.loadContainers();
            deps.autoFocusContainer(msg.container_id);
        } else if (event === 'container_stopped') {
            deps.logOutput(`⏹ Container stopped: ${msg.container_id?.slice(0, 12)}`, 'ansi-yellow');
            if (deps.getAttachedContainer() === msg.container_id) deps.setAttachedContainer(null);
            deps.loadContainers();
        } else if (event === 'deploy_failed') {
            const reason = String(msg.message || 'Deploy failed');
            deps.logOutput(`❌ Deploy failed (${msg.blueprint_id || 'unknown'}): ${reason}`, 'ansi-red');
            deps.showToast(`Deploy failed: ${reason}`, 'error');
            deps.loadContainers();
        } else if (event === 'approval_requested') {
            deps.showApprovalBanner(msg.approval_id, msg.approval_reason || msg.reason, msg.blueprint_id, msg.ttl_seconds || 300);
            deps.refreshApprovalCenter();
        } else if (event === 'approval_resolved') {
            deps.hideApprovalBanner();
            deps.refreshApprovalCenter();
            if (msg.status === 'approved') deps.loadContainers();
        } else if (event === 'approval_needed') {
            deps.showApprovalBanner(msg.approval_id, msg.approval_reason || msg.reason, msg.blueprint_id);
        } else if (event === 'memory_saved' || event === 'memory_skipped' || event === 'memory_denied') {
            void deps.loadMemoryPanelSnapshot({ silent: true });
        } else if (event === 'attached') {
            deps.logOutput(`🔗 Attached to ${msg.container_id?.slice(0, 12)}`, 'ansi-cyan');
        } else if (event === 'trion_shell_mode_started') {
            deps.logOutput(`🧠 ${detailMessage}`, 'ansi-cyan');
        } else if (event === 'trion_shell_mode_stopped') {
            deps.logOutput(`🧠 ${detailMessage}`, 'ansi-dim');
        } else if (event === 'workspace_update') {
            window.dispatchEvent(new CustomEvent("sse-event", {
                detail: {
                    type: "workspace_update",
                    source: msg.source || "event",
                    entry_id: msg.entry_id,
                    content: msg.content || "",
                    entry_type: msg.entry_type || "event",
                    event_data: msg.event_data || {},
                    source_layer: msg.source_layer || "shell",
                    conversation_id: msg.conversation_id || "",
                    timestamp: msg.timestamp || new Date().toISOString(),
                },
            }));
        }
    }

    function wsSend(msg) {
        if (ws && ws.readyState === 1) {
            ws.send(JSON.stringify(msg));
            return;
        }
        pendingMessages.push(msg);
        if (!ws || ws.readyState > 1) connectWebSocket();
    }

    function routeStreamOutput(msg) {
        const stream = String(msg.stream || '').toLowerCase();
        const data = String(msg.data || '');
        if (!data) return;
        if (stream === 'logs') {
            deps.appendLogStream(data);
            return;
        }
        if (stream === 'shell') {
            deps.appendShellStream(data);
            return;
        }
        deps.appendShellStream(data);
    }

    return {
        connectWebSocket,
        handleEvent,
        handleWsMessage,
        routeStreamOutput,
        wsSend,
    };
}

export { createWebSocketController };
