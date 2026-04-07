import { normalizeTerminalOutput } from "./helpers.js?v=20260322m";

function createXtermController(deps) {
    let xterm = null;
    let fitAddon = null;
    let shellSessions = [];
    let shellSessionActive = '';
    let xtermResizeObserver = null;
    let xtermWindowResizeBound = false;
    let xtermAppActivationBound = false;
    let xtermFitTimer = null;
    let blockedShellInputToastAt = 0;

    function initXterm() {
        const container = document.getElementById('xterm-container');
        if (!container || xterm) return;

        if (typeof Terminal === 'undefined') {
            container.style.display = 'none';
            const fallback = document.getElementById('log-output');
            if (fallback) fallback.style.display = 'block';
            return;
        }

        xterm = new Terminal({
            theme: {
                background: '#0a0a0a',
                foreground: '#e5e5e5',
                cursor: '#FFB302',
                cursorAccent: '#0a0a0a',
                selectionBackground: 'rgba(255, 179, 2, 0.3)',
                black: '#1a1a1a',
                red: '#ef4444',
                green: '#22c55e',
                yellow: '#FFB302',
                blue: '#3b82f6',
                magenta: '#a855f7',
                cyan: '#06b6d4',
                white: '#e5e5e5',
                brightBlack: '#555',
                brightRed: '#f87171',
                brightGreen: '#4ade80',
                brightYellow: '#fbbf24',
                brightBlue: '#60a5fa',
                brightMagenta: '#c084fc',
                brightCyan: '#22d3ee',
                brightWhite: '#ffffff',
            },
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
            fontSize: 13,
            lineHeight: 1.4,
            cursorBlink: true,
            cursorStyle: 'bar',
            scrollback: 5000,
            allowTransparency: true,
        });

        if (typeof FitAddon !== 'undefined') {
            fitAddon = new FitAddon.FitAddon();
            xterm.loadAddon(fitAddon);
        }

        xterm.open(container);
        observeXtermLayout(container);
        scheduleXtermFit();

        xterm.onData((data) => {
            const attachedContainer = deps.getAttachedContainer();
            if (attachedContainer) {
                if (deps.isTrionShellActive?.()) {
                    const now = Date.now();
                    if (now - blockedShellInputToastAt > 2000) {
                        deps.showToast?.('TRION controls the shell. Use the input bar below or /exit.', 'warn');
                        blockedShellInputToastAt = now;
                    }
                    return;
                }
                deps.wsSend({ type: 'stdin', container_id: attachedContainer, data });
            }
        });

        xterm.onResize(({ cols, rows }) => {
            const attachedContainer = deps.getAttachedContainer();
            if (attachedContainer) {
                deps.wsSend({ type: 'resize', container_id: attachedContainer, cols, rows });
            }
        });

        if (!xtermWindowResizeBound) {
            window.addEventListener('resize', scheduleXtermFit);
            xtermWindowResizeBound = true;
        }
        if (!xtermAppActivationBound) {
            window.addEventListener('trion:app-activated', (event) => {
                if (event?.detail?.appName === 'terminal') {
                    scheduleXtermFit();
                    if (deps.getLogPanelMode() === 'shell' && xterm) xterm.focus();
                }
            });
            xtermAppActivationBound = true;
        }

        xterm.writeln('\x1b[38;2;255;179;2m⬡ TRION Container Commander\x1b[0m');
        xterm.writeln('\x1b[90mType a command below or attach to a container.\x1b[0m');
        xterm.writeln('');
    }

    function observeXtermLayout(container) {
        if (!container || typeof ResizeObserver === 'undefined' || xtermResizeObserver) return;
        xtermResizeObserver = new ResizeObserver(() => {
            scheduleXtermFit();
        });
        xtermResizeObserver.observe(container);
        const root = document.getElementById('app-terminal');
        if (root && root !== container) xtermResizeObserver.observe(root);
    }

    function scheduleXtermFit() {
        if (!fitAddon || !xterm) return;
        const container = document.getElementById('xterm-container');
        if (!container) return;

        const runFit = () => {
            const host = document.getElementById('xterm-container');
            if (!host || host.clientWidth === 0 || host.clientHeight === 0) return;
            try {
                fitAddon.fit();
            } catch (_) {
                // Ignore transient layout states while panels animate into view.
            }
        };

        window.requestAnimationFrame(() => {
            runFit();
            window.requestAnimationFrame(runFit);
        });

        if (xtermFitTimer) window.clearTimeout(xtermFitTimer);
        xtermFitTimer = window.setTimeout(runFit, 90);
    }

    function autoFocusContainer(containerId) {
        deps.switchTab('logs');
        deps.setLogPanelMode('shell');
        initXterm();
        deps.setAttachedContainer(containerId);
        deps.wsSend({ type: 'attach', container_id: containerId });
        addShellSession(containerId);

        if (xterm) {
            xterm.writeln(`\x1b[32m▶ Auto-attached to ${containerId.slice(0, 12)}\x1b[0m`);
            scheduleXtermFit();
            xterm.focus();
        }
    }

    function addShellSession(containerId) {
        if (!containerId) return;
        if (!shellSessions.includes(containerId)) {
            shellSessions.push(containerId);
        }
        shellSessionActive = containerId;
        renderShellSessions();
    }

    function removeShellSession(containerId) {
        shellSessions = shellSessions.filter(id => id !== containerId);
        if (shellSessionActive === containerId) {
            shellSessionActive = shellSessions[0] || '';
            if (shellSessionActive) {
                deps.setAttachedContainer(shellSessionActive);
                deps.wsSend({ type: 'attach', container_id: shellSessionActive });
            } else {
                deps.setAttachedContainer(null);
                deps.wsSend({ type: 'detach' });
            }
        }
        renderShellSessions();
    }

    function renderShellSessions() {
        const host = document.getElementById('term-shell-sessions');
        if (!host) return;
        if (!shellSessions.length) {
            host.innerHTML = '<div class="term-history-empty">No attached shell sessions.</div>';
            return;
        }
        host.innerHTML = shellSessions.map(id => `
            <button class="shell-session-tab ${id === shellSessionActive ? 'active' : ''}" data-id="${deps.esc(id)}">
                ${deps.esc(id.slice(0, 12))}
                <span class="close" data-close-id="${deps.esc(id)}">×</span>
            </button>
        `).join('');
        host.querySelectorAll('.shell-session-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                if (deps.isTrionShellActive?.()) {
                    deps.showToast?.('Exit TRION shell mode before switching shell sessions.', 'warn');
                    return;
                }
                const id = btn.dataset.id || '';
                if (!id) return;
                shellSessionActive = id;
                deps.setAttachedContainer(id);
                deps.wsSend({ type: 'attach', container_id: id });
                renderShellSessions();
                if (xterm) xterm.focus();
            });
        });
        host.querySelectorAll('.shell-session-tab .close').forEach(el => {
            el.addEventListener('click', (event) => {
                event.stopPropagation();
                if (deps.isTrionShellActive?.()) {
                    deps.showToast?.('Exit TRION shell mode before closing shell sessions.', 'warn');
                    return;
                }
                removeShellSession(el.dataset.closeId || '');
            });
        });
    }

    function writeShellData(data) {
        if (!data) return false;
        if (xterm) {
            xterm.write(normalizeTerminalOutput(data, { forXterm: true }));
            return true;
        }
        return false;
    }

    function writeLogLine(msg, cls = '', enabled = true) {
        if (!xterm || !enabled) return false;
        const colorMap = {
            'ansi-green': '\x1b[32m',
            'ansi-red': '\x1b[31m',
            'ansi-yellow': '\x1b[33m',
            'ansi-cyan': '\x1b[36m',
            'ansi-dim': '\x1b[90m',
            'ansi-bold': '\x1b[1m',
        };
        const code = colorMap[cls] || '';
        const reset = code ? '\x1b[0m' : '';
        const normalized = normalizeTerminalOutput(msg, { forXterm: true });
        xterm.write(`${code}${normalized}${reset}\r\n`);
        return true;
    }

    function clearTerminal() {
        if (xterm) xterm.clear();
    }

    function focusTerminal() {
        if (xterm) xterm.focus();
    }

    function disposeXterm() {
        if (xtermResizeObserver) {
            xtermResizeObserver.disconnect();
            xtermResizeObserver = null;
        }
        if (xterm) {
            xterm.dispose();
            xterm = null;
        }
        fitAddon = null;
        xtermAppActivationBound = false;
    }

    return {
        addShellSession,
        autoFocusContainer,
        clearTerminal,
        disposeXterm,
        focusTerminal,
        initXterm,
        removeShellSession,
        renderShellSessions,
        scheduleXtermFit,
        writeLogLine,
        writeShellData,
    };
}

export { createXtermController };
