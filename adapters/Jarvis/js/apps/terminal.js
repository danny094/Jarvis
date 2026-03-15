/**
 * TRION Container Commander — Terminal App (Phase 3)
 * ═══════════════════════════════════════════════════════
 * Features:
 *   - xterm.js live terminal with WebSocket backend
 *   - Tab system: Blueprints / Containers / Vault / Logs
 *   - PTY stdin forwarding
 *   - trion> CLI with autocomplete
 *   - Auto-focus on container_started event
 *   - Approval dialog for network requests
 */

const HTTP_BASE = (() => {
    if (typeof window.getApiBase === "function") {
        const b = window.getApiBase();
        if (b) return b;
    }
    return `${window.location.protocol}//${window.location.host}`;
})();
const API = `${HTTP_BASE}/api/commander`;
const WS_URL = `${HTTP_BASE.replace(/^http/, "ws")}/api/commander/ws`;

// ── State ────────────────────────────────────────────────
let activeTab = 'dashboard';
let blueprints = [];
let containers = [];
let secrets = [];
let editingBp = null;
let ws = null;
let xterm = null;
let fitAddon = null;
let attachedContainer = null;
let cmdHistory = [];
let cmdHistoryIdx = -1;
let deployPreflightState = null;
let toastTimer = null;
let pendingApprovals = [];
let approvalHistory = [];
let approvalCenterOpen = false;
let approvalCenterTab = 'pending';
let approvalBannerTimer = null;
let logPanelMode = 'logs';
let logStreamBuffer = [];
let shellFallbackBuffer = [];
let activityFeed = [];
let activityRefreshTimer = null;
let memoryStatusState = null;
let memoryNotes = [];
let memoryQuery = '';
let containerDetailState = {
    open: false,
    containerId: '',
    tab: 'logs',
    pollTimer: null,
};
let volumeManagerState = {
    open: false,
    filter: '',
    volumes: [],
    snapshots: [],
    compareA: '',
    compareB: '',
};
let dashboardState = {
    audit: [],
    quota: null,
    volumes: [],
};
let commandPaletteOpen = false;
let shellSessions = [];
let shellSessionActive = '';
let cmdHistoryFilter = '';
let approvalSelection = new Set();
let lastApprovalBannerSeverity = -1;
let lastApprovalBannerId = '';
let activityDetailOpen = false;

// ── Init ─────────────────────────────────────────────────
export async function init() {
    const root = document.getElementById('app-terminal');
    if (!root) return;

    root.innerHTML = buildHTML();
    bindEvents();
    connectWebSocket();
    await switchTab('dashboard');
    // Guard against duplicate polling loops when the terminal app is re-initialized.
    if (!approvalPollTimer) pollApprovals();
}

// ── HTML Structure ───────────────────────────────────────
function buildHTML() {
    return `
    <div class="term-container">
        <!-- Header -->
        <div class="term-header">
            <h2><span class="term-icon">⬡</span> Container Commander</h2>
            <div class="term-header-actions">
                <button class="term-btn-sm" id="approval-center-btn">
                    📥 Approvals <span class="term-tab-count" id="approval-center-count">0</span>
                </button>
                <div class="term-conn-status">
                    <span class="term-conn-dot disconnected" id="term-conn-dot"></span>
                    <span class="term-conn-label" id="term-conn-label">Offline</span>
                </div>
            </div>
        </div>

        <!-- Tabs -->
        <div class="term-tabs">
            <button class="term-tab active" data-tab="dashboard">
                🪟 Dashboard
            </button>
            <button class="term-tab" data-tab="blueprints">
                📦 Blueprints <span class="term-tab-count" id="bp-count">0</span>
            </button>
            <button class="term-tab" data-tab="containers">
                🔄 Container <span class="term-tab-count" id="ct-count">0</span>
            </button>
            <button class="term-tab" data-tab="vault">
                🔐 Vault <span class="term-tab-count" id="vault-count">0</span>
            </button>
            <button class="term-tab" data-tab="logs">
                📋 Logs
            </button>
        </div>

        <!-- Approval Banner (hidden by default) -->
        <div class="term-approval-banner" id="approval-banner" style="display:none">
            <div class="term-approval-icon">⚠️</div>
            <div class="term-approval-text">
                <strong id="approval-reason">Container requests internet access</strong>
                <span id="approval-bp-id"></span>
                <span class="term-approval-ttl" id="approval-ttl"></span>
            </div>
            <div class="term-approval-actions">
                <button class="term-btn-sm danger" id="approval-reject">✖ Reject</button>
                <button class="term-btn-sm bp-deploy" id="approval-approve">✔ Approve</button>
            </div>
        </div>

        <aside class="approval-center" id="approval-center">
            <div class="approval-center-head">
                <h3>Approval Center</h3>
                <button class="approval-center-close" id="approval-center-close">✕</button>
            </div>
            <div class="approval-center-tabs">
                <button class="approval-center-tab active" data-approval-tab="pending">Pending</button>
                <button class="approval-center-tab" data-approval-tab="history">History</button>
            </div>
            <div id="approval-center-context"></div>
            <div class="approval-center-body">
                <div id="approval-center-pending"></div>
                <div id="approval-center-history" style="display:none"></div>
            </div>
        </aside>

        <!-- Panels -->
        <div class="term-panel active" id="panel-dashboard">
            <div class="dash-wrap">
                <section class="dash-kpis" id="dash-kpis"></section>
                <section class="dash-section">
                    <div class="dash-section-head">
                        <h3>Today Timeline</h3>
                        <button class="term-btn-sm" id="dash-refresh-btn">↻ Refresh</button>
                    </div>
                    <div class="dash-timeline" id="dash-timeline"></div>
                </section>
                <section class="dash-section">
                    <div class="dash-section-head">
                        <h3>Continue Working</h3>
                    </div>
                    <div class="dash-continue-grid">
                        <div class="dash-continue-col">
                            <h4>Recent Blueprints</h4>
                            <div id="dash-recent-blueprints"></div>
                        </div>
                        <div class="dash-continue-col">
                            <h4>Recent Volumes</h4>
                            <div id="dash-recent-volumes"></div>
                        </div>
                    </div>
                </section>
            </div>
        </div>

        <div class="term-panel" id="panel-blueprints">
            <div class="bp-preset-bar" id="bp-preset-bar">
                <button class="bp-preset-btn" data-preset="python">🐍 Python</button>
                <button class="bp-preset-btn" data-preset="node">🟢 Node</button>
                <button class="bp-preset-btn" data-preset="db">🗄 DB</button>
                <button class="bp-preset-btn" data-preset="shell">🖥 Shell</button>
                <button class="bp-preset-btn" data-preset="webscraper">🕷 Web Scraper</button>
            </div>
            <div class="bp-list" id="bp-list"></div>
            <div class="bp-editor" id="bp-editor"></div>
            <div class="bp-preflight" id="bp-preflight"></div>
            <div class="term-footer">
                <div class="term-footer-left">
                    <button class="term-btn-sm" id="bp-add-btn">+ Blueprint</button>
                    <button class="term-btn-sm" id="bp-import-btn">📥 Import YAML</button>
                </div>
                <div class="term-dropzone" id="bp-dropzone" style="display:none;">
                    <div class="drop-icon">📄</div>
                    <p>Drop Dockerfile or docker-compose.yml</p>
                    <small>Or click to browse</small>
                </div>
            </div>
        </div>

        <div class="term-panel" id="panel-containers">
            <div class="ct-list" id="ct-list"></div>
            <div class="ct-drawer" id="ct-drawer"></div>
            <div class="vm-manager" id="vm-manager"></div>
            <div class="term-footer">
                <div class="term-footer-left">
                    <button class="term-btn-sm" id="vm-toggle-btn">💾 Volumes</button>
                    <div class="term-quota" id="ct-quota">
                        <span>Quota:</span>
                        <div class="term-quota-bar"><div class="term-quota-fill" id="quota-fill" style="width:0%"></div></div>
                        <span id="ct-quota-text">0/2 Container</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="term-panel" id="panel-vault">
            <div class="vault-add-form" id="vault-form">
                <div class="vault-form-row">
                    <input type="text" id="vault-name" placeholder="SECRET_NAME" />
                    <select id="vault-scope">
                        <option value="global">Global</option>
                        <option value="blueprint">Blueprint</option>
                    </select>
                </div>
                <div class="vault-form-row">
                    <input type="password" id="vault-value" placeholder="Secret value..." />
                    <input type="text" id="vault-bp-id" placeholder="Blueprint ID (optional)" style="max-width:160px" />
                </div>
                <div class="bp-editor-footer">
                    <button class="proto-btn-cancel" id="vault-cancel">Cancel</button>
                    <button class="proto-btn-save" id="vault-save">🔐 Store</button>
                </div>
            </div>
            <div class="vault-list" id="vault-list"></div>
            <div class="term-footer">
                <div class="term-footer-left">
                    <button class="term-btn-sm" id="vault-add-btn">+ Secret</button>
                </div>
            </div>
        </div>

        <div class="term-panel" id="panel-logs">
            <div class="term-logs-layout">
                <div class="term-logs-main">
                    <div class="term-log-mode-tabs">
                        <button class="term-log-mode active" data-log-mode="logs">📋 Logs</button>
                        <button class="term-log-mode" data-log-mode="shell">⌨ Shell</button>
                        <button class="term-log-action" id="term-cmd-palette-btn">⌘ Command Palette</button>
                    </div>
                    <div class="term-log-mode-panel active" id="log-mode-logs">
                        <div class="term-log-tools">
                            <button class="term-btn-sm" id="log-copy-btn">📋 Copy Clean</button>
                            <button class="term-btn-sm" id="log-download-btn">⬇ Download</button>
                        </div>
                        <div class="term-output-plain" id="log-stream-output">Waiting for log stream...</div>
                    </div>
                    <div class="term-log-mode-panel" id="log-mode-shell">
                        <div class="term-shell-sessions" id="term-shell-sessions"></div>
                        <!-- xterm.js container -->
                        <div class="term-xterm-container" id="xterm-container"></div>
                        <!-- Fallback plain output -->
                        <div class="term-output-plain" id="log-output" style="display:none">Waiting for shell data...</div>
                    </div>
                    <!-- Input bar with autocomplete -->
                    <div class="term-input-bar">
                        <span class="term-prompt">trion&gt;</span>
                        <input class="term-input" id="term-cmd-input" type="text"
                               placeholder="Type command or /quick action… (Tab for autocomplete)" autocomplete="off" />
                        <button class="term-send-btn" id="term-send-btn">↵</button>
                        <!-- Autocomplete dropdown -->
                        <div class="term-autocomplete" id="term-autocomplete" style="display:none"></div>
                    </div>
                    <div class="term-history-strip">
                        <input id="term-history-filter" placeholder="Search command history..." />
                        <div class="term-history-list" id="term-history-list"></div>
                    </div>
                </div>
                <aside class="term-activity-feed" id="term-activity-feed">
                    <div class="term-activity-head">
                        <h4>TRION Activity</h4>
                        <button class="term-btn-sm" id="term-activity-refresh">↻</button>
                    </div>
                    <div class="term-activity-list" id="term-activity-list"></div>
                    <div class="term-memory-divider"></div>
                    <div class="term-memory-head">
                        <h4>TRION Memory</h4>
                        <button class="term-btn-sm" id="term-memory-refresh">↻</button>
                    </div>
                    <div class="term-memory-status" id="term-memory-status">Status: unknown</div>
                    <div class="term-memory-tools">
                        <textarea id="term-memory-note" placeholder="Important note..."></textarea>
                        <div class="term-memory-tools-row">
                            <select id="term-memory-category">
                                <option value="project_fact">project_fact</option>
                                <option value="user_preference">user_preference</option>
                                <option value="todo">todo</option>
                                <option value="note">note</option>
                            </select>
                            <button class="term-btn-sm" id="term-memory-remember">Remember</button>
                        </div>
                        <div class="term-memory-tools-row">
                            <input id="term-memory-query" placeholder="Search memory..." />
                            <button class="term-btn-sm" id="term-memory-search">Search</button>
                        </div>
                    </div>
                    <div class="term-memory-list" id="term-memory-list"></div>
                </aside>
            </div>
        </div>
        <div class="term-command-palette" id="term-command-palette">
            <div class="term-command-backdrop" id="term-cmd-backdrop"></div>
            <div class="term-command-dialog">
                <div class="term-command-head">
                    <h3>Command Palette</h3>
                    <button class="term-btn-sm" id="term-cmd-close">✕</button>
                </div>
                <input id="term-cmd-filter" placeholder="Type to filter commands..." />
                <div class="term-command-groups" id="term-command-groups"></div>
            </div>
        </div>
        <div class="term-activity-detail" id="term-activity-detail"></div>
        <div class="term-toast-stack" id="term-toast-stack"></div>
    </div>`;
}


// ═══════════════════════════════════════════════════════════
// WEBSOCKET
// ═══════════════════════════════════════════════════════════

function connectWebSocket() {
    if (ws && ws.readyState <= 1) return;

    updateConnectionStatus('connecting');

    try {
        ws = new WebSocket(WS_URL);
    } catch (e) {
        updateConnectionStatus(false);
        setTimeout(connectWebSocket, 5000);
        return;
    }

    ws.onopen = () => {
        updateConnectionStatus(true);
        logOutput('✅ WebSocket connected', 'ansi-green');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWsMessage(msg);
        } catch (e) {
            logOutput(`⚠️ Bad WS message: ${event.data}`, 'ansi-yellow');
        }
    };

    ws.onclose = () => {
        updateConnectionStatus(false);
        logOutput('🔌 WebSocket disconnected — reconnecting...', 'ansi-dim');
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
        updateConnectionStatus(false);
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
            logOutput(`❌ ${msg.message}`, 'ansi-red');
            break;

        case 'exit':
            logOutput(`⏹ Container ${msg.container_id?.slice(0,12)} exited (code: ${msg.exit_code})`, 'ansi-yellow');
            removeShellSession(msg.container_id || '');
            attachedContainer = null;
            loadContainers();
            break;

        case 'exec_done':
            // Just a notification, output already streamed
            break;

        default:
            logOutput(`[WS] ${msg.type}: ${JSON.stringify(msg)}`, 'ansi-dim');
    }
}

function handleEvent(msg) {
    const event = msg.event;
    const level = String(msg.level || 'info');
    const detailMessage = msg.message || event;
    pushActivity({
        level,
        event,
        message: detailMessage,
        container_id: msg.container_id || '',
        blueprint_id: msg.blueprint_id || '',
        created_at: new Date().toISOString(),
    });

    if (event === 'container_started') {
        logOutput(`▶ Container started: ${msg.container_id?.slice(0,12)} (${msg.blueprint_id})`, 'ansi-green');
        loadContainers();
        // Auto-focus: switch to logs tab and attach
        autoFocusContainer(msg.container_id);

    } else if (event === 'container_stopped') {
        logOutput(`⏹ Container stopped: ${msg.container_id?.slice(0,12)}`, 'ansi-yellow');
        if (attachedContainer === msg.container_id) attachedContainer = null;
        loadContainers();

    } else if (event === 'deploy_failed') {
        const reason = String(msg.message || 'Deploy failed');
        logOutput(`❌ Deploy failed (${msg.blueprint_id || 'unknown'}): ${reason}`, 'ansi-red');
        showToast(`Deploy failed: ${reason}`, 'error');
        loadContainers();

    } else if (event === 'approval_requested') {
        showApprovalBanner(msg.approval_id, msg.reason, msg.blueprint_id, msg.ttl_seconds || 300);
        refreshApprovalCenter();

    } else if (event === 'approval_resolved') {
        hideApprovalBanner();
        refreshApprovalCenter();
        if (msg.status === 'approved') loadContainers();

    } else if (event === 'approval_needed') {
        showApprovalBanner(msg.approval_id, msg.reason, msg.blueprint_id);

    } else if (event === 'memory_saved' || event === 'memory_skipped' || event === 'memory_denied') {
        void loadMemoryPanelSnapshot({ silent: true });

    } else if (event === 'attached') {
        logOutput(`🔗 Attached to ${msg.container_id?.slice(0,12)}`, 'ansi-cyan');
    }
}

function wsSend(msg) {
    if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify(msg));
    }
}

function routeStreamOutput(msg) {
    const stream = String(msg.stream || '').toLowerCase();
    const data = String(msg.data || '');
    if (!data) return;
    if (stream === 'logs') {
        appendLogStream(data);
        return;
    }
    if (stream === 'shell') {
        appendShellStream(data);
        return;
    }
    // Backward compatibility for old backend messages without explicit stream.
    appendShellStream(data);
}

function setLogPanelMode(mode) {
    logPanelMode = mode === 'shell' ? 'shell' : 'logs';
    document.querySelectorAll('.term-log-mode').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.logMode === logPanelMode);
    });
    document.querySelectorAll('.term-log-mode-panel').forEach(panel => {
        const shouldShow = panel.id === `log-mode-${logPanelMode}`;
        panel.classList.toggle('active', shouldShow);
    });
    if (logPanelMode === 'shell') {
        initXterm();
        renderShellSessions();
        if (xterm) xterm.focus();
    }
}

function appendToOutput(elId, chunk, maxChars = 160000) {
    const target = document.getElementById(elId);
    if (!target) return;
    target.textContent += chunk;
    if (target.textContent.length > maxChars) {
        target.textContent = target.textContent.slice(-maxChars);
    }
    target.scrollTop = target.scrollHeight;
}

function appendLogStream(data) {
    if (!data) return;
    logStreamBuffer.push(data);
    if (logStreamBuffer.length > 800) logStreamBuffer = logStreamBuffer.slice(-800);
    appendToOutput('log-stream-output', data);
    if (activeTab !== 'logs' || logPanelMode !== 'logs') {
        const tab = document.querySelector('.term-tab[data-tab="logs"]');
        if (tab) tab.style.color = '#FFB302';
    }
}

function appendShellStream(data) {
    if (!data) return;
    if (xterm) {
        xterm.write(data);
        return;
    }
    shellFallbackBuffer.push(data);
    if (shellFallbackBuffer.length > 800) shellFallbackBuffer = shellFallbackBuffer.slice(-800);
    appendToOutput('log-output', data);
}


// ═══════════════════════════════════════════════════════════
// XTERM.JS
// ═══════════════════════════════════════════════════════════

function initXterm() {
    const container = document.getElementById('xterm-container');
    if (!container || xterm) return;

    // Check if xterm.js is loaded
    if (typeof Terminal === 'undefined') {
        // Fallback to plain output
        container.style.display = 'none';
        document.getElementById('log-output').style.display = 'block';
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

    // Fit addon
    if (typeof FitAddon !== 'undefined') {
        fitAddon = new FitAddon.FitAddon();
        xterm.loadAddon(fitAddon);
    }

    xterm.open(container);
    if (fitAddon) fitAddon.fit();

    // Forward keyboard input to PTY
    xterm.onData((data) => {
        if (attachedContainer) {
            wsSend({ type: 'stdin', container_id: attachedContainer, data });
        }
    });

    // Handle resize
    xterm.onResize(({ cols, rows }) => {
        if (attachedContainer) {
            wsSend({ type: 'resize', container_id: attachedContainer, cols, rows });
        }
    });

    // Window resize → refit
    window.addEventListener('resize', () => {
        if (fitAddon) fitAddon.fit();
    });

    xterm.writeln('\x1b[38;2;255;179;2m⬡ TRION Container Commander\x1b[0m');
    xterm.writeln('\x1b[90mType a command below or attach to a container.\x1b[0m');
    xterm.writeln('');
}


// ═══════════════════════════════════════════════════════════
// AUTO-FOCUS
// ═══════════════════════════════════════════════════════════

function autoFocusContainer(containerId) {
    // Switch to logs tab
    switchTab('logs');
    setLogPanelMode('shell');

    // Init xterm if not yet done
    initXterm();

    // Attach to the new container
    attachedContainer = containerId;
    wsSend({ type: 'attach', container_id: containerId });
    addShellSession(containerId);

    if (xterm) {
        xterm.writeln(`\x1b[32m▶ Auto-attached to ${containerId.slice(0,12)}\x1b[0m`);
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
            attachedContainer = shellSessionActive;
            wsSend({ type: 'attach', container_id: shellSessionActive });
        } else {
            attachedContainer = null;
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
        <button class="shell-session-tab ${id === shellSessionActive ? 'active' : ''}" data-id="${esc(id)}">
            ${esc(id.slice(0, 12))}
            <span class="close" data-close-id="${esc(id)}">×</span>
        </button>
    `).join('');
    host.querySelectorAll('.shell-session-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id || '';
            if (!id) return;
            shellSessionActive = id;
            attachedContainer = id;
            wsSend({ type: 'attach', container_id: id });
            renderShellSessions();
            if (xterm) xterm.focus();
        });
    });
    host.querySelectorAll('.shell-session-tab .close').forEach(el => {
        el.addEventListener('click', (event) => {
            event.stopPropagation();
            removeShellSession(el.dataset.closeId || '');
        });
    });
}


// ═══════════════════════════════════════════════════════════
// APPROVAL DIALOG
// ═══════════════════════════════════════════════════════════

let currentApprovalId = null;
let approvalPollTimer = null;

function showApprovalBanner(approvalId, reason, blueprintId, ttlSeconds = 300) {
    if (approvalBannerTimer) {
        clearInterval(approvalBannerTimer);
        approvalBannerTimer = null;
    }
    currentApprovalId = approvalId;
    const banner = document.getElementById('approval-banner');
    if (!banner) return;

    document.getElementById('approval-reason').textContent = reason;
    document.getElementById('approval-bp-id').textContent = blueprintId ? `(${blueprintId})` : '';
    banner.style.display = 'flex';

    // TTL countdown
    let ttl = Number.isFinite(ttlSeconds) ? ttlSeconds : 300;
    const ttlEl = document.getElementById('approval-ttl');
    if (ttlEl) ttlEl.textContent = `${ttl}s`;
    approvalBannerTimer = setInterval(() => {
        ttl--;
        if (ttlEl) ttlEl.textContent = `${ttl}s`;
        if (ttl <= 0) {
            clearInterval(approvalBannerTimer);
            approvalBannerTimer = null;
            hideApprovalBanner();
            logOutput('⏰ Approval expired', 'ansi-yellow');
        }
    }, 1000);
}

function hideApprovalBanner() {
    const banner = document.getElementById('approval-banner');
    if (banner) banner.style.display = 'none';
    if (approvalBannerTimer) {
        clearInterval(approvalBannerTimer);
        approvalBannerTimer = null;
    }
    currentApprovalId = null;
}

function updateApprovalBadge() {
    const count = Array.isArray(pendingApprovals) ? pendingApprovals.length : 0;
    const badge = document.getElementById('approval-center-count');
    if (badge) badge.textContent = String(count);
}

function setApprovalCenterTab(tab) {
    approvalCenterTab = tab === 'history' ? 'history' : 'pending';
    document.querySelectorAll('.approval-center-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.approvalTab === approvalCenterTab);
    });
    const pendingEl = document.getElementById('approval-center-pending');
    const historyEl = document.getElementById('approval-center-history');
    if (pendingEl) pendingEl.style.display = approvalCenterTab === 'pending' ? 'block' : 'none';
    if (historyEl) historyEl.style.display = approvalCenterTab === 'history' ? 'block' : 'none';
}

function toggleApprovalCenter(force = null) {
    const root = document.getElementById('approval-center');
    if (!root) return;
    approvalCenterOpen = force === null ? !approvalCenterOpen : Boolean(force);
    root.classList.toggle('visible', approvalCenterOpen);
}

function approvalRisk(item) {
    const reason = String(item?.reason || '').toLowerCase();
    if (reason.includes('full') || reason.includes('internet') || reason.includes('trust')) return 3;
    if (reason.includes('bridge')) return 2;
    return 1;
}

function approvalRecommendation(item) {
    const risk = approvalRisk(item);
    if (risk >= 3) return 'Review carefully: high network/trust risk.';
    if (risk === 2) return 'Approve only if host-network access is required.';
    return 'Low risk request, usually safe.';
}

function renderApprovalContextCard() {
    const host = document.getElementById('approval-center-context');
    if (!host) return;
    const top = (pendingApprovals || [])[0];
    if (!top) {
        host.innerHTML = '<div class="approval-empty">No pending approval context.</div>';
        return;
    }
    host.innerHTML = `
        <div class="approval-context-card">
            <div class="approval-context-top">
                <strong>${esc(top.blueprint_id || 'unknown')}</strong>
                <span class="approval-risk r${approvalRisk(top)}">Risk ${approvalRisk(top)}</span>
            </div>
            <p>${esc(top.reason || '')}</p>
            <small>${esc(approvalRecommendation(top))}</small>
        </div>
    `;
}

function renderApprovalRows(items, historyMode = false) {
    if (!Array.isArray(items) || !items.length) {
        return `<div class="approval-empty">${historyMode ? 'No history yet.' : 'No pending approvals.'}</div>`;
    }
    return items.map(item => {
        const status = String(item?.status || 'pending');
        const ttl = Math.max(0, Number.parseInt(String(item?.ttl_remaining || 0), 10));
        const meta = historyMode
            ? `${esc(status)} · by ${esc(item?.resolved_by || 'n/a')}`
            : `ttl ${ttl}s`;
        const actions = historyMode
            ? ''
            : `
                <div class="approval-row-actions">
                    <label class="approval-check-wrap"><input type="checkbox" class="approval-select" data-approval-id="${esc(item?.id || '')}" ${approvalSelection.has(String(item?.id || '')) ? 'checked' : ''}/> batch</label>
                    <button class="term-btn-sm danger" onclick="termRejectRequest('${esc(item?.id || '')}')">Reject</button>
                    <button class="term-btn-sm bp-deploy" onclick="termApproveRequest('${esc(item?.id || '')}')">Approve</button>
                </div>
            `;
        return `
            <div class="approval-row">
                <div class="approval-row-main">
                    <div class="approval-row-title">${esc(item?.blueprint_id || 'unknown')} <span class="approval-status">${esc(status)}</span></div>
                    <div class="approval-row-reason">${esc(item?.reason || '')}</div>
                    <div class="approval-row-meta">${meta}</div>
                </div>
                ${actions}
            </div>
        `;
    }).join('');
}

function renderApprovalCenter() {
    const pendingEl = document.getElementById('approval-center-pending');
    const historyEl = document.getElementById('approval-center-history');
    if (pendingEl) {
        pendingEl.innerHTML = `
            <div class="approval-batch-actions">
                <button class="term-btn-sm" id="approval-batch-approve">Approve Selected</button>
                <button class="term-btn-sm danger" id="approval-batch-reject">Reject Selected</button>
            </div>
            ${renderApprovalRows(pendingApprovals, false)}
        `;
    }
    if (historyEl) historyEl.innerHTML = renderApprovalRows(approvalHistory, true);
    setApprovalCenterTab(approvalCenterTab);
    renderApprovalContextCard();
    pendingEl?.querySelectorAll('.approval-select').forEach(input => {
        input.addEventListener('change', (event) => {
            const approvalId = String(event.target?.dataset?.approvalId || '');
            if (!approvalId) return;
            if (event.target.checked) approvalSelection.add(approvalId);
            else approvalSelection.delete(approvalId);
        });
    });
    document.getElementById('approval-batch-approve')?.addEventListener('click', async () => {
        const ids = Array.from(approvalSelection);
        for (const id of ids) await resolveApprovalRequest(id, 'approve');
        approvalSelection.clear();
    });
    document.getElementById('approval-batch-reject')?.addEventListener('click', async () => {
        const ids = Array.from(approvalSelection);
        for (const id of ids) await resolveApprovalRequest(id, 'reject', 'Batch rejected');
        approvalSelection.clear();
    });
}

async function resolveApprovalRequest(approvalId, action, reason = '') {
    if (!approvalId) return;
    try {
        if (action === 'approve') {
            const data = await apiRequest(`/approvals/${approvalId}/approve`, { method: 'POST' }, 'Approve failed');
            if (data.approved) {
                showToast(`Approved ${approvalId}`, 'success');
                logOutput('✅ Approved — container starting...', 'ansi-green');
                await loadContainers();
            } else {
                showToast(data.error || 'Approve failed', 'error');
                logOutput(`❌ Approve failed: ${data.error || 'Unknown'}`, 'ansi-red');
            }
        } else {
            await apiRequest(`/approvals/${approvalId}/reject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: reason || 'User rejected' }),
            }, 'Reject failed');
            showToast(`Rejected ${approvalId}`, 'warn');
            logOutput('✖ Rejected', 'ansi-yellow');
        }
    } catch (e) {
        showToast(e.message || `${action} failed`, 'error');
        logOutput(`❌ ${action} error: ${e.message}`, 'ansi-red');
    }
    if (currentApprovalId === approvalId) hideApprovalBanner();
    await refreshApprovalCenter();
    if (activeTab === 'dashboard') await loadDashboard();
}

async function approveRequest() {
    if (!currentApprovalId) return;
    await resolveApprovalRequest(currentApprovalId, 'approve');
}

async function rejectRequest() {
    if (!currentApprovalId) return;
    await resolveApprovalRequest(currentApprovalId, 'reject', 'User rejected');
}

window.termApproveRequest = async function(approvalId) {
    await resolveApprovalRequest(approvalId, 'approve');
};

window.termRejectRequest = async function(approvalId) {
    await resolveApprovalRequest(approvalId, 'reject', 'Rejected from approval center');
};

async function refreshApprovalCenter() {
    try {
        const [pendingData, historyData] = await Promise.all([
            apiRequest('/approvals', {}, 'Could not load approvals'),
            apiRequest('/approvals/history', {}, 'Could not load approval history'),
        ]);
        pendingApprovals = (pendingData?.approvals || []).sort((a, b) => {
            const riskDiff = approvalRisk(b) - approvalRisk(a);
            if (riskDiff !== 0) return riskDiff;
            return Number(a?.ttl_remaining || 0) - Number(b?.ttl_remaining || 0);
        });
        const validIds = new Set(pendingApprovals.map(item => String(item?.id || '')));
        approvalSelection = new Set(Array.from(approvalSelection).filter(id => validIds.has(id)));
        approvalHistory = historyData?.history || [];
        updateApprovalBadge();
        renderApprovalCenter();
        if (activeTab === 'dashboard') renderDashboard();

        if (pendingApprovals.length > 0) {
            const top = pendingApprovals[0];
            const severity = approvalRisk(top);
            const isNew = !currentApprovalId || currentApprovalId !== top.id;
            const isEscalated = severity > lastApprovalBannerSeverity;
            if (isNew || isEscalated) {
                showApprovalBanner(top.id, top.reason, top.blueprint_id, top.ttl_remaining || 300);
                lastApprovalBannerSeverity = severity;
                lastApprovalBannerId = String(top.id || '');
            } else {
                const ttlEl = document.getElementById('approval-ttl');
                if (ttlEl) ttlEl.textContent = `${Math.max(0, Number.parseInt(String(top.ttl_remaining || 0), 10))}s`;
            }
        } else {
            hideApprovalBanner();
            lastApprovalBannerSeverity = -1;
            lastApprovalBannerId = '';
        }
    } catch (e) { /* silent in poll */ }
}

async function pollApprovals() {
    // Check for pending approvals every 5 seconds
    try {
        await refreshApprovalCenter();
    } catch (e) { /* silent */ }
    approvalPollTimer = setTimeout(pollApprovals, 5000);
}


// ═══════════════════════════════════════════════════════════
// EVENT BINDING
// ═══════════════════════════════════════════════════════════

function bindEvents() {
    // Tab switching
    document.querySelectorAll('.term-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Blueprint actions
    document.getElementById('bp-add-btn')?.addEventListener('click', showBlueprintEditor);
    document.getElementById('bp-import-btn')?.addEventListener('click', showImportDialog);
    document.querySelectorAll('.bp-preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const preset = buildBlueprintPreset(btn.dataset.preset || '');
            showBlueprintEditor(preset, { forceCreate: true });
        });
    });

    // Vault actions
    document.getElementById('vault-add-btn')?.addEventListener('click', () => {
        document.getElementById('vault-form')?.classList.toggle('visible');
    });
    document.getElementById('vault-cancel')?.addEventListener('click', () => {
        document.getElementById('vault-form')?.classList.remove('visible');
    });
    document.getElementById('vault-save')?.addEventListener('click', saveSecret);

    // Terminal input + autocomplete
    const cmdInput = document.getElementById('term-cmd-input');
    cmdInput?.addEventListener('keydown', handleInputKeydown);
    document.getElementById('term-send-btn')?.addEventListener('click', () => {
        handleCommand(cmdInput?.value.trim());
    });
    document.getElementById('term-history-filter')?.addEventListener('input', (event) => {
        cmdHistoryFilter = String(event.target?.value || '').trim().toLowerCase();
        renderHistoryList();
    });
    document.querySelectorAll('.term-log-mode').forEach(btn => {
        btn.addEventListener('click', () => setLogPanelMode(btn.dataset.logMode || 'logs'));
    });
    document.getElementById('term-activity-refresh')?.addEventListener('click', loadActivityFeedSnapshot);
    document.getElementById('term-memory-refresh')?.addEventListener('click', () => loadMemoryPanelSnapshot());
    document.getElementById('term-memory-search')?.addEventListener('click', runMemorySearchFromInput);
    document.getElementById('term-memory-remember')?.addEventListener('click', saveMemoryNoteFromUI);
    document.getElementById('term-memory-query')?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            runMemorySearchFromInput();
        }
    });
    document.getElementById('vm-toggle-btn')?.addEventListener('click', toggleVolumeManager);
    document.getElementById('dash-refresh-btn')?.addEventListener('click', loadDashboard);
    document.getElementById('log-copy-btn')?.addEventListener('click', copyCleanLogs);
    document.getElementById('log-download-btn')?.addEventListener('click', downloadLogs);
    document.getElementById('term-cmd-palette-btn')?.addEventListener('click', () => toggleCommandPalette(true));
    document.getElementById('term-cmd-close')?.addEventListener('click', () => toggleCommandPalette(false));
    document.getElementById('term-cmd-backdrop')?.addEventListener('click', () => toggleCommandPalette(false));
    document.getElementById('term-cmd-filter')?.addEventListener('input', renderCommandPalette);

    // Approval buttons
    document.getElementById('approval-approve')?.addEventListener('click', approveRequest);
    document.getElementById('approval-reject')?.addEventListener('click', rejectRequest);
    document.getElementById('approval-center-btn')?.addEventListener('click', () => {
        toggleApprovalCenter();
        refreshApprovalCenter();
    });
    document.getElementById('approval-center-close')?.addEventListener('click', () => toggleApprovalCenter(false));
    document.querySelectorAll('.approval-center-tab').forEach(tab => {
        tab.addEventListener('click', () => setApprovalCenterTab(tab.dataset.approvalTab || 'pending'));
    });

    // Drag & Drop
    setupDropzone();

    // Start in logs mode and render placeholders.
    setLogPanelMode('logs');
    renderActivityFeed();
    renderMemoryPanel();
    renderHistoryList();
    renderCommandPalette();

    window.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            toggleCommandPalette();
        }
    });
}


// ═══════════════════════════════════════════════════════════
// CLI INPUT + AUTOCOMPLETE
// ═══════════════════════════════════════════════════════════

const CLI_COMMANDS = [
    { cmd: 'help', desc: 'Show available commands' },
    { cmd: 'list', desc: 'List blueprints' },
    { cmd: 'deploy', desc: 'Deploy a blueprint: deploy <id>' },
    { cmd: 'restart', desc: 'Restart via blueprint: restart <container_id>' },
    { cmd: 'stop', desc: 'Stop a container: stop <id>' },
    { cmd: 'attach', desc: 'Attach to container: attach <id>' },
    { cmd: 'detach', desc: 'Detach from current container' },
    { cmd: 'exec', desc: 'Run command: exec <container> <cmd>' },
    { cmd: 'logs', desc: 'Show container logs: logs <id>' },
    { cmd: 'stats', desc: 'Show container stats: stats <id>' },
    { cmd: 'secrets', desc: 'List secrets' },
    { cmd: 'volumes', desc: 'List workspace volumes' },
    { cmd: 'snapshot', desc: 'Create snapshot: snapshot <volume>' },
    { cmd: 'restore', desc: 'Restore snapshot: restore <filename> [target_volume]' },
    { cmd: 'rmvolume', desc: 'Remove volume: rmvolume <volume_name>' },
    { cmd: 'quota', desc: 'Show resource quota' },
    { cmd: 'market', desc: 'Marketplace: market sync|list|install <id>' },
    { cmd: 'audit', desc: 'Show audit log' },
    { cmd: 'activity', desc: 'Show latest TRION activity events' },
    { cmd: 'clear', desc: 'Clear terminal output' },
    { cmd: 'cleanup', desc: 'Stop all containers' },
];

function getQuickCommands() {
    const attachedId = attachedContainer ? attachedContainer.slice(0, 12) : '';
    return [
        { cmd: '/help', expand: 'help', desc: 'Command help' },
        { cmd: '/blueprints', expand: 'list', desc: 'List blueprints' },
        { cmd: '/containers', expand: 'list containers', desc: 'Refresh containers list' },
        { cmd: '/logs', expand: attachedId ? `logs ${attachedId}` : 'logs ', desc: 'Tail logs' },
        { cmd: '/stats', expand: attachedId ? `stats ${attachedId}` : 'stats ', desc: 'Container stats' },
        { cmd: '/audit', expand: 'audit', desc: 'Show audit entries' },
        { cmd: '/quota', expand: 'quota', desc: 'Quota usage' },
        { cmd: '/market', expand: 'market list', desc: 'List marketplace catalog' },
        { cmd: '/detach', expand: 'detach', desc: 'Detach shell' },
    ];
}

const COMMAND_GROUPS = [
    {
        category: 'Container',
        items: [
            { label: 'List Containers', run: 'list containers' },
            { label: 'Attach Container', run: 'attach ' },
            { label: 'Stop Container', run: 'stop ' },
            { label: 'Container Stats', run: 'stats ' },
        ],
    },
    {
        category: 'Storage',
        items: [
            { label: 'List Volumes', run: 'volumes' },
            { label: 'Create Snapshot', run: 'snapshot ' },
            { label: 'Restore Snapshot', run: 'restore ' },
        ],
    },
    {
        category: 'Approval',
        items: [
            { label: 'Open Approval Center', run: 'activity' },
            { label: 'Refresh Approvals', run: 'activity' },
        ],
    },
    {
        category: 'Marketplace',
        items: [
            { label: 'Sync Catalog', run: 'market sync' },
            { label: 'List Catalog', run: 'market list' },
            { label: 'Install Blueprint', run: 'market install ' },
        ],
    },
];

function buildBlueprintPreset(type) {
    const suffix = Date.now().toString().slice(-6);
    const base = {
        id: `custom-${suffix}`,
        name: 'Custom Blueprint',
        description: '',
        icon: '📦',
        dockerfile: '',
        image: '',
        network: 'internal',
        tags: [],
        system_prompt: '',
        resources: {
            cpu_limit: '1.0',
            memory_limit: '512m',
            memory_swap: '1g',
            timeout_seconds: 300,
            pids_limit: 100,
        },
        mounts: [],
        secrets_required: [],
        allowed_exec: [],
    };
    const presets = {
        python: {
            id: `python-${suffix}`,
            name: 'Python Sandbox',
            icon: '🐍',
            image: 'python:3.12-slim',
            description: 'Python runtime with pip for scripts and analysis.',
            tags: ['python', 'sandbox'],
            allowed_exec: ['python', 'python3', 'pip', 'pip3', 'sh', 'bash'],
        },
        node: {
            id: `node-${suffix}`,
            name: 'Node Sandbox',
            icon: '🟢',
            image: 'node:20-slim',
            description: 'Node.js runtime for JS/TS tooling.',
            tags: ['node', 'javascript'],
            allowed_exec: ['node', 'npm', 'npx', 'sh', 'bash'],
        },
        db: {
            id: `db-${suffix}`,
            name: 'DB Workspace',
            icon: '🗄',
            image: 'postgres:16-alpine',
            description: 'Database-oriented environment for SQL tasks.',
            tags: ['database', 'sql'],
            network: 'internal',
        },
        shell: {
            id: `shell-${suffix}`,
            name: 'Shell Toolbox',
            icon: '🖥',
            image: 'alpine:latest',
            description: 'Minimal shell toolbox with system utilities.',
            tags: ['shell', 'tools'],
            allowed_exec: ['sh', 'ash', 'ls', 'cat', 'grep', 'echo', 'curl', 'wget'],
        },
        webscraper: {
            id: `web-scraper-${suffix}`,
            name: 'Web Scraper',
            icon: '🕷',
            image: 'python:3.12-slim',
            description: 'Requests + parsing workflows with controlled networking.',
            tags: ['scraping', 'python'],
            network: 'bridge',
            allowed_exec: ['python', 'python3', 'pip', 'sh', 'bash'],
        },
    };
    return { ...base, ...(presets[type] || {}) };
}

function handleInputKeydown(e) {
    const input = e.target;
    const val = input.value;

    if (e.key === 'Enter') {
        e.preventDefault();
        hideAutocomplete();
        handleCommand(val.trim());
        cmdHistoryIdx = -1;
        input.value = '';
        return;
    }

    if (e.key === 'Tab') {
        e.preventDefault();
        applyAutocomplete(input);
        return;
    }

    if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (cmdHistoryIdx < cmdHistory.length - 1) {
            cmdHistoryIdx++;
            input.value = cmdHistory[cmdHistoryIdx] || '';
        }
        return;
    }

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (cmdHistoryIdx > 0) {
            cmdHistoryIdx--;
            input.value = cmdHistory[cmdHistoryIdx] || '';
        } else {
            cmdHistoryIdx = -1;
            input.value = '';
        }
        return;
    }

    if (e.key === 'Escape') {
        hideAutocomplete();
        return;
    }

    // Show autocomplete after small delay
    setTimeout(() => showAutocomplete(input.value), 50);
}

function showAutocomplete(partial) {
    const dropdown = document.getElementById('term-autocomplete');
    if (!dropdown || !partial) { hideAutocomplete(); return; }

    const parts = partial.split(/\s+/);
    const first = parts[0].toLowerCase();

    let matches = [];

    if (parts.length === 1 && first.startsWith('/')) {
        matches = getQuickCommands()
            .filter(c => c.cmd.startsWith(first))
            .map(c => ({ cmd: c.cmd, desc: c.desc, expand: c.expand }));
    } else if (parts.length === 1) {
        // Autocomplete command name
        matches = CLI_COMMANDS.filter(c => c.cmd.startsWith(first) && c.cmd !== first);
    } else if (parts.length === 2 && ['deploy', 'attach', 'stop', 'restart', 'logs', 'stats', 'exec'].includes(first)) {
        // Autocomplete container/blueprint ID
        const prefix = parts[1].toLowerCase();
        if (['deploy'].includes(first)) {
            matches = blueprints.filter(b => b.id.toLowerCase().startsWith(prefix))
                .map(b => ({ cmd: b.id, desc: b.name }));
        } else {
            matches = containers.filter(c => c.container_id.startsWith(prefix) || c.name?.toLowerCase().startsWith(prefix))
                .map(c => ({ cmd: c.container_id.slice(0, 12), desc: c.name }));
        }
    }

    if (!matches.length) { hideAutocomplete(); return; }

    dropdown.innerHTML = matches.slice(0, 6).map(m =>
        `<div class="term-ac-item" data-value="${m.cmd}" data-expand="${esc(m.expand || m.cmd)}">
            <span class="term-ac-cmd">${m.cmd}</span>
            <span class="term-ac-desc">${m.desc || ''}</span>
        </div>`
    ).join('');

    dropdown.style.display = 'block';

    // Click handler
    dropdown.querySelectorAll('.term-ac-item').forEach(item => {
        item.addEventListener('click', () => {
            const input = document.getElementById('term-cmd-input');
            const expand = item.dataset.expand || item.dataset.value || '';
            if (String(item.dataset.value || '').startsWith('/')) {
                input.value = expand;
                input.focus();
                hideAutocomplete();
                return;
            }
            const parts = input.value.split(/\s+/);
            if (parts.length <= 1) {
                input.value = item.dataset.value + ' ';
            } else {
                parts[parts.length - 1] = item.dataset.value;
                input.value = parts.join(' ') + ' ';
            }
            input.focus();
            hideAutocomplete();
        });
    });
}

function applyAutocomplete(input) {
    const dropdown = document.getElementById('term-autocomplete');
    const first = dropdown?.querySelector('.term-ac-item');
    if (first) {
        const expand = first.dataset.expand || first.dataset.value || '';
        if (String(first.dataset.value || '').startsWith('/')) {
            input.value = expand;
            hideAutocomplete();
            return;
        }
        const parts = input.value.split(/\s+/);
        if (parts.length <= 1) {
            input.value = first.dataset.value + ' ';
        } else {
            parts[parts.length - 1] = first.dataset.value;
            input.value = parts.join(' ') + ' ';
        }
    }
    hideAutocomplete();
}

function hideAutocomplete() {
    const d = document.getElementById('term-autocomplete');
    if (d) d.style.display = 'none';
}

function renderHistoryList() {
    const root = document.getElementById('term-history-list');
    if (!root) return;
    const filtered = (cmdHistory || [])
        .filter(Boolean)
        .filter(cmd => !cmdHistoryFilter || cmd.toLowerCase().includes(cmdHistoryFilter))
        .slice(0, 8);
    if (!filtered.length) {
        root.innerHTML = '<div class="term-history-empty">No recent commands.</div>';
        return;
    }
    root.innerHTML = filtered.map(cmd => `
        <button class="term-history-item" data-cmd="${esc(cmd)}">${esc(cmd)}</button>
    `).join('');
    root.querySelectorAll('.term-history-item').forEach(btn => {
        btn.addEventListener('click', () => handleCommand(btn.dataset.cmd || ''));
    });
}

function stripAnsi(input) {
    return String(input || '').replace(/\x1B\[[0-9;]*[A-Za-z]/g, '');
}

async function copyCleanLogs() {
    const raw = document.getElementById('log-stream-output')?.textContent || '';
    const clean = stripAnsi(raw);
    if (!clean.trim()) {
        showToast('No logs to copy', 'warn');
        return;
    }
    try {
        await navigator.clipboard.writeText(clean);
        showToast('Logs copied to clipboard', 'success');
    } catch (_) {
        showToast('Clipboard unavailable', 'error');
    }
}

function downloadText(filename, text) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function downloadLogs() {
    const raw = document.getElementById('log-stream-output')?.textContent || '';
    const clean = stripAnsi(raw);
    if (!clean.trim()) {
        showToast('No logs to download', 'warn');
        return;
    }
    downloadText(`trion-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.log`, clean);
}

function toggleCommandPalette(force = null) {
    const root = document.getElementById('term-command-palette');
    if (!root) return;
    commandPaletteOpen = force === null ? !commandPaletteOpen : Boolean(force);
    root.classList.toggle('visible', commandPaletteOpen);
    if (commandPaletteOpen) {
        const filter = document.getElementById('term-cmd-filter');
        if (filter) {
            filter.focus();
            filter.select?.();
        }
        renderCommandPalette();
    }
}

function renderCommandPalette() {
    const host = document.getElementById('term-command-groups');
    if (!host) return;
    const q = String(document.getElementById('term-cmd-filter')?.value || '').trim().toLowerCase();
    const groups = COMMAND_GROUPS.map(group => {
        const items = group.items.filter(item => {
            if (!q) return true;
            return item.label.toLowerCase().includes(q) || item.run.toLowerCase().includes(q);
        });
        return { ...group, items };
    }).filter(group => group.items.length > 0);
    if (!groups.length) {
        host.innerHTML = '<div class="term-history-empty">No matching command.</div>';
        return;
    }
    host.innerHTML = groups.map(group => `
        <div class="term-command-group">
            <h4>${esc(group.category)}</h4>
            ${group.items.map(item => `
                <button class="term-command-item" data-run="${esc(item.run)}">
                    <span>${esc(item.label)}</span>
                    <small>${esc(item.run)}</small>
                </button>
            `).join('')}
        </div>
    `).join('');
    host.querySelectorAll('.term-command-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const cmd = btn.dataset.run || '';
            toggleCommandPalette(false);
            const input = document.getElementById('term-cmd-input');
            if (cmd.endsWith(' ')) {
                if (input) {
                    input.value = cmd;
                    input.focus();
                }
            } else {
                handleCommand(cmd);
            }
        });
    });
}


// ═══════════════════════════════════════════════════════════
// COMMAND HANDLER (enhanced)
// ═══════════════════════════════════════════════════════════

async function handleCommand(cmd) {
    const input = document.getElementById('term-cmd-input');
    if (!cmd) return;
    if (input) input.value = '';

    cmd = normalizeQuickCommand(cmd);
    if (!cmd) return;
    cmdHistory.unshift(cmd);
    cmdHistory = Array.from(new Set(cmdHistory)).filter(Boolean).slice(0, 120);
    renderHistoryList();

    logOutput(`trion> ${cmd}`, 'ansi-bold');

    const parts = cmd.split(/\s+/);
    const action = parts[0]?.toLowerCase();

    switch (action) {
        case 'help':
            logOutput('Available commands:', 'ansi-cyan');
            CLI_COMMANDS.forEach(c => logOutput(`  ${c.cmd.padEnd(12)} ${c.desc}`, 'ansi-dim'));
            break;

        case 'list':
            if (parts[1] === 'containers') {
                await loadContainers();
                if (!containers.length) {
                    logOutput('No containers running', 'ansi-dim');
                } else {
                    containers.forEach(c => logOutput(`  🔄 ${c.container_id?.slice(0, 12)} — ${c.name} (${c.status})`, 'ansi-dim'));
                }
            } else {
                await loadBlueprints();
                blueprints.forEach(bp => logOutput(`  ${bp.icon} ${bp.id} — ${bp.name}`, 'ansi-dim'));
            }
            break;

        case 'deploy':
            if (parts[1]) await window.termDeployBp(parts[1]);
            else logOutput('Usage: deploy <blueprint_id>', 'ansi-yellow');
            break;

        case 'stop':
            if (parts[1]) await window.termStopCt(parts[1]);
            else logOutput('Usage: stop <container_id>', 'ansi-yellow');
            break;
        case 'restart':
            if (parts[1]) {
                const current = containers.find(c => String(c.container_id || '').startsWith(parts[1]));
                if (!current) {
                    logOutput('Container not found for restart', 'ansi-yellow');
                    break;
                }
                await window.termStopCt(current.container_id);
                await window.termDeployBp(current.blueprint_id);
            } else logOutput('Usage: restart <container_id>', 'ansi-yellow');
            break;

        case 'attach':
            if (parts[1]) {
                attachedContainer = parts[1];
                wsSend({ type: 'attach', container_id: parts[1] });
                switchTab('logs');
                setLogPanelMode('shell');
                initXterm();
                addShellSession(parts[1]);
                rememberRecent('containers', parts[1]);
            } else logOutput('Usage: attach <container_id>', 'ansi-yellow');
            break;

        case 'detach':
            wsSend({ type: 'detach' });
            removeShellSession(attachedContainer);
            attachedContainer = null;
            logOutput('Detached', 'ansi-dim');
            break;

        case 'exec':
            if (parts[1] && parts[2]) {
                const ctId = parts[1];
                const execCmd = parts.slice(2).join(' ');
                wsSend({ type: 'exec', container_id: ctId, command: execCmd });
            } else logOutput('Usage: exec <container_id> <command>', 'ansi-yellow');
            break;

        case 'logs':
            if (parts[1]) {
                try {
                    const data = await apiRequest(`/containers/${parts[1]}/logs?tail=50`, {}, 'Could not load logs');
                    logOutput(data.logs || 'No logs', '');
                } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            } else logOutput('Usage: logs <container_id>', 'ansi-yellow');
            break;

        case 'stats':
            if (parts[1]) {
                try {
                    const s = await apiRequest(`/containers/${parts[1]}/stats`, {}, 'Could not load stats');
                    logOutput(`CPU: ${s.cpu_percent}% | RAM: ${s.memory_mb}/${s.memory_limit_mb} MB | Efficiency: ${s.efficiency?.level}`, 'ansi-cyan');
                } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            } else logOutput('Usage: stats <container_id>', 'ansi-yellow');
            break;

        case 'secrets':
            await loadSecrets();
            secrets.forEach(s => logOutput(`  🔑 ${s.name} (${s.scope})`, 'ansi-dim'));
            break;

        case 'volumes':
            try {
                const data = await apiRequest('/volumes', {}, 'Could not load volumes');
                if (data.volumes?.length) {
                    data.volumes.forEach(v => logOutput(`  💾 ${v.name} (${v.blueprint_id}) — ${v.created_at}`, 'ansi-dim'));
                } else logOutput('No volumes found', 'ansi-dim');
            } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            break;

        case 'snapshot':
            if (parts[1]) {
                logOutput(`📸 Creating snapshot of ${parts[1]}...`, 'ansi-cyan');
                try {
                    const data = await apiRequest('/snapshots/create', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ volume_name: parts[1], tag: parts[2] || '' })
                    }, 'Snapshot creation failed');
                    logOutput(data.created ? `✅ Snapshot: ${data.filename}` : `❌ ${data.error}`, data.created ? 'ansi-green' : 'ansi-red');
                } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            } else logOutput('Usage: snapshot <volume_name> [tag]', 'ansi-yellow');
            break;
        case 'restore':
            if (parts[1]) {
                try {
                    const payload = { filename: parts[1] };
                    if (parts[2]) payload.target_volume = parts[2];
                    const data = await apiRequest('/snapshots/restore', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    }, 'Snapshot restore failed');
                    if (data.restored) {
                        logOutput(`✅ Snapshot restored to volume ${data.volume}`, 'ansi-green');
                        await refreshVolumeManager();
                    } else {
                        logOutput(`❌ ${data.error || 'Restore failed'}`, 'ansi-red');
                    }
                } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            } else logOutput('Usage: restore <snapshot_filename> [target_volume]', 'ansi-yellow');
            break;
        case 'rmvolume':
            if (parts[1]) {
                try {
                    await apiRequest(`/volumes/${encodeURIComponent(parts[1])}`, { method: 'DELETE' }, 'Could not remove volume');
                    logOutput(`🗑️ Volume removed: ${parts[1]}`, 'ansi-yellow');
                    await refreshVolumeManager();
                } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            } else logOutput('Usage: rmvolume <volume_name>', 'ansi-yellow');
            break;

        case 'quota':
            try {
                const q = await apiRequest('/quota', {}, 'Could not load quota');
                logOutput(`Containers: ${q.containers_used}/${q.max_containers} | RAM: ${q.memory_used_mb}/${q.max_total_memory_mb} MB | CPU: ${q.cpu_used}/${q.max_total_cpu}`, 'ansi-cyan');
            } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            break;

        case 'market': {
            const sub = String(parts[1] || '').toLowerCase();
            if (sub === 'sync') {
                const payload = {};
                if (parts[2]) payload.repo_url = parts[2];
                if (parts[3]) payload.branch = parts[3];
                logOutput('🔄 Syncing marketplace catalog...', 'ansi-cyan');
                try {
                    const data = await apiRequest('/marketplace/catalog/sync', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    }, 'Marketplace sync failed');
                    const categories = data.categories || {};
                    logOutput(`✅ Catalog synced (${data.count || 0} blueprints) from ${data.source?.repo_url || 'source'}`, 'ansi-green');
                    Object.entries(categories).forEach(([cat, count]) => {
                        logOutput(`  ${cat}: ${count}`, 'ansi-dim');
                    });
                } catch (e) {
                    logOutput(`❌ ${e.message}`, 'ansi-red');
                }
                break;
            }

            if (sub === 'list') {
                const category = String(parts[2] || '').trim();
                const query = category ? `?category=${encodeURIComponent(category)}` : '';
                try {
                    const data = await apiRequest(`/marketplace/catalog${query}`, {}, 'Could not load marketplace catalog');
                    if (!data.blueprints?.length) {
                        logOutput('Marketplace catalog is empty. Run: market sync', 'ansi-yellow');
                        break;
                    }
                    logOutput(`🛍 Catalog (${data.count})${category ? ` [${category}]` : ''}`, 'ansi-cyan');
                    data.blueprints.slice(0, 80).forEach((bp) => {
                        logOutput(
                            `  ${bp.icon || '📦'} ${bp.id} — ${bp.name} [${bp.category}] trust=${bp.trusted_level}`,
                            'ansi-dim',
                        );
                    });
                    if ((data.blueprints || []).length > 80) {
                        logOutput('  ... truncated, use category filter', 'ansi-yellow');
                    }
                } catch (e) {
                    logOutput(`❌ ${e.message}`, 'ansi-red');
                }
                break;
            }

            if (sub === 'install') {
                const id = String(parts[2] || '').trim();
                if (!id) {
                    logOutput('Usage: market install <blueprint_id> [--overwrite]', 'ansi-yellow');
                    break;
                }
                const overwrite = parts.includes('--overwrite');
                try {
                    const data = await apiRequest(`/marketplace/catalog/install/${encodeURIComponent(id)}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ overwrite }),
                    }, 'Marketplace install failed');
                    if (data.installed || data.updated || data.exists) {
                        const mode = data.installed ? 'installed' : data.updated ? 'updated' : 'already exists';
                        logOutput(`✅ Marketplace blueprint ${mode}: ${data.blueprint?.id || id}`, 'ansi-green');
                        await loadBlueprints();
                    } else if (data.error) {
                        logOutput(`❌ ${data.error}`, 'ansi-red');
                    } else {
                        logOutput('❌ Marketplace install failed', 'ansi-red');
                    }
                } catch (e) {
                    logOutput(`❌ ${e.message}`, 'ansi-red');
                }
                break;
            }

            logOutput('Usage: market sync [repo_url] [branch] | market list [category] | market install <id> [--overwrite]', 'ansi-yellow');
            break;
        }

        case 'audit':
            await loadAuditLog();
            break;
        case 'activity':
            await loadActivityFeedSnapshot();
            activityFeed.slice(0, 25).forEach(item => {
                logOutput(`[${item.created_at}] ${item.level?.toUpperCase()} ${item.message}`, 'ansi-dim');
            });
            break;

        case 'clear':
            if (xterm) xterm.clear();
            document.getElementById('log-output').innerHTML = '';
            break;

        case 'cleanup':
            logOutput('🧹 Stopping all containers...', 'ansi-yellow');
            try {
                await apiRequest('/cleanup', { method: 'POST' }, 'Cleanup failed');
                logOutput('✅ All containers stopped', 'ansi-green');
                await loadContainers();
            } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            break;

        default:
            // If attached, send as exec
            if (attachedContainer) {
                wsSend({ type: 'exec', container_id: attachedContainer, command: cmd });
            } else {
                logOutput(`Unknown command: ${action}. Type "help" for commands.`, 'ansi-yellow');
            }
    }
}

function normalizeQuickCommand(cmd) {
    const clean = String(cmd || '').trim();
    if (!clean.startsWith('/')) return clean;
    const quick = getQuickCommands().find(item => item.cmd === clean.toLowerCase());
    if (quick) return quick.expand;
    return clean.slice(1);
}


// ═══════════════════════════════════════════════════════════
// TAB SWITCHING
// ═══════════════════════════════════════════════════════════

async function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.term-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.term-tab[data-tab="${tab}"]`)?.classList.add('active');
    document.querySelectorAll('.term-panel').forEach(p => p.classList.remove('active'));
    document.getElementById(`panel-${tab}`)?.classList.add('active');

    // Reset tab highlight
    const tabBtn = document.querySelector(`.term-tab[data-tab="${tab}"]`);
    if (tabBtn) tabBtn.style.color = '';

    if (tab === 'dashboard') {
        await loadDashboard();
        stopContainerDetailPolling();
    } else if (tab === 'blueprints') {
        await loadBlueprints();
        stopContainerDetailPolling();
    } else if (tab === 'containers') {
        await loadContainers();
        await loadQuota();
        await refreshVolumeManager();
    } else if (tab === 'vault') {
        await loadSecrets();
        stopContainerDetailPolling();
    } else if (tab === 'logs') {
        if (logPanelMode === 'shell') initXterm();
        await loadActivityFeedSnapshot();
        await loadMemoryPanelSnapshot();
        startActivityFeedPolling();
    } else {
        stopContainerDetailPolling();
    }
    if (tab !== 'logs') stopActivityFeedPolling();
}

async function loadDashboard() {
    try {
        const [quota, approvals, audit, vols, cts] = await Promise.all([
            apiRequest('/quota', {}, 'Could not load quota'),
            apiRequest('/approvals', {}, 'Could not load approvals'),
            apiRequest('/audit?limit=120', {}, 'Could not load audit log'),
            apiRequest('/volumes', {}, 'Could not load volumes'),
            apiRequest('/containers', {}, 'Could not load containers'),
        ]);
        dashboardState.quota = quota;
        dashboardState.audit = audit?.entries || [];
        dashboardState.volumes = vols?.volumes || [];
        containers = cts?.containers || containers;
        pendingApprovals = approvals?.approvals || pendingApprovals;
        renderDashboard();
    } catch (e) {
        const wrap = document.querySelector('#panel-dashboard .dash-wrap');
        if (wrap) wrap.innerHTML = renderEmpty('🪟', 'Dashboard unavailable', e.message || 'Try refresh');
    }
}

function getTodayTimelineItems() {
    const raw = dashboardState.audit || [];
    return raw.filter(entry => {
        const t = String(entry?.created_at || '');
        return t.startsWith(new Date().toISOString().slice(0, 10));
    }).slice(0, 20);
}

function getRecentItems(key) {
    try {
        const raw = localStorage.getItem(`trion_recent_${key}`) || '[]';
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
        return [];
    }
}

function rememberRecent(key, value) {
    if (!value) return;
    const current = getRecentItems(key);
    const next = [value, ...current.filter(x => x !== value)].slice(0, 8);
    localStorage.setItem(`trion_recent_${key}`, JSON.stringify(next));
}

function renderDashboard() {
    const kpiRoot = document.getElementById('dash-kpis');
    const timelineRoot = document.getElementById('dash-timeline');
    const recentBpRoot = document.getElementById('dash-recent-blueprints');
    const recentVolRoot = document.getElementById('dash-recent-volumes');
    if (!kpiRoot || !timelineRoot || !recentBpRoot || !recentVolRoot) return;

    const q = dashboardState.quota || {};
    const active = (containers || []).filter(c => c.status === 'running').length;
    const pendingCount = Array.isArray(pendingApprovals) ? pendingApprovals.length : 0;
    const timeline = getTodayTimelineItems();
    const lastErrors = (dashboardState.audit || []).filter(x => String(x?.action || '').includes('error') || String(x?.action || '').includes('failed')).length;
    kpiRoot.innerHTML = `
        <article class="dash-kpi-card glass">
            <small>Active Containers</small>
            <strong>${active}</strong>
            <p>${q.containers_used || 0}/${q.max_containers || 0} quota used</p>
        </article>
        <article class="dash-kpi-card glass">
            <small>Open Approvals</small>
            <strong>${pendingCount}</strong>
            <p>${pendingCount ? 'Requires attention' : 'All clear'}</p>
        </article>
        <article class="dash-kpi-card glass">
            <small>Memory / CPU</small>
            <strong>${q.memory_used_mb || 0}MB · ${q.cpu_used || 0}</strong>
            <p>${q.max_total_memory_mb || 0}MB / ${q.max_total_cpu || 0} CPU</p>
        </article>
        <article class="dash-kpi-card glass ${lastErrors ? 'warn' : ''}">
            <small>Recent Errors</small>
            <strong>${lastErrors}</strong>
            <p>${lastErrors ? 'Investigate audit timeline' : 'No critical errors'}</p>
        </article>
    `;
    timelineRoot.innerHTML = timeline.length
        ? timeline.map(item => `
            <button class="dash-timeline-item" data-activity-id="${esc(String(item.id || item.created_at || ''))}">
                <span class="dot ${toActivityLevel(item.action)}"></span>
                <div>
                    <div class="title">${esc(item.action || 'event')}</div>
                    <div class="meta">${esc(item.created_at || '')} · ${esc(item.blueprint_id || '')}</div>
                </div>
            </button>
        `).join('')
        : '<div class="term-activity-empty">No timeline entries for today.</div>';
    timelineRoot.querySelectorAll('.dash-timeline-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const activity = (dashboardState.audit || []).find(item => String(item.id || item.created_at) === btn.dataset.activityId);
            if (activity) openActivityDetail({
                created_at: activity.created_at,
                event: activity.action,
                message: activity.details || '',
                blueprint_id: activity.blueprint_id || '',
                container_id: activity.container_id || '',
                level: toActivityLevel(activity.action),
            });
        });
    });

    const recentBps = getRecentItems('blueprints');
    recentBpRoot.innerHTML = recentBps.length
        ? recentBps.map(id => `<button class="dash-chip" onclick="termDeployBp('${esc(id)}')">${esc(id)}</button>`).join('')
        : '<div class="term-history-empty">No recent blueprint yet.</div>';
    const recentVolumes = getRecentItems('volumes');
    recentVolRoot.innerHTML = recentVolumes.length
        ? recentVolumes.map(name => `<button class="dash-chip" onclick="termSnapshotVolume('${esc(name)}')">${esc(name)}</button>`).join('')
        : '<div class="term-history-empty">No recent volume yet.</div>';
}


// ═══════════════════════════════════════════════════════════
// BLUEPRINTS (unchanged from Phase 1)
// ═══════════════════════════════════════════════════════════

async function loadBlueprints() {
    try {
        const data = await apiRequest('/blueprints', {}, 'Could not load blueprints');
        blueprints = data.blueprints || [];
        document.getElementById('bp-count').textContent = blueprints.length;
        renderBlueprints();
        updateConnectionStatus(true);
    } catch (e) {
        updateConnectionStatus(false);
        document.getElementById('bp-list').innerHTML = renderEmpty('📦', 'Could not load blueprints', 'Check if admin-api is running');
    }
}

function renderBlueprints() {
    const list = document.getElementById('bp-list');
    if (!blueprints.length) {
        list.innerHTML = renderEmpty('📦', 'No blueprints yet', 'Create one or import a YAML file');
        return;
    }
    const quickStatus = (bp) => {
        if (bp.network === 'full') return { tone: 'pending_approval', icon: '🛡', label: 'Approval likely' };
        if (bp.image && !bp.image_digest) return { tone: 'warn', icon: '⚠', label: 'Unpinned image' };
        return { tone: 'running', icon: '●', label: 'Ready' };
    };
    list.innerHTML = blueprints.map(bp => `
        <div class="bp-card glass status-${quickStatus(bp).tone}" data-id="${bp.id}">
            <div class="bp-card-top">
                <div class="bp-card-title">
                    <span class="bp-emoji">${bp.icon || '📦'}</span>
                    <div>
                        <h3>${esc(bp.name)}</h3>
                        <span class="bp-id">${esc(bp.id)}</span>
                        <span class="bp-status-pill ${quickStatus(bp).tone}">${quickStatus(bp).icon} ${quickStatus(bp).label}</span>
                    </div>
                </div>
                <div class="bp-card-actions">
                    <button class="bp-action-btn" onclick="termCloneBp('${bp.id}')">⧉ Clone</button>
                    <button class="bp-action-btn" onclick="termEditBp('${bp.id}')">✏️</button>
                    <button class="bp-action-btn" onclick="termExportBp('${bp.id}')">📤</button>
                    <button class="bp-action-btn danger" onclick="termDeleteBp('${bp.id}')">🗑️</button>
                    <button class="bp-action-btn" onclick="termDeployBpWithOverrides('${bp.id}')">⚙ Deploy</button>
                    <button class="bp-action-btn bp-deploy" onclick="termDeployBp('${bp.id}')">▶ Deploy</button>
                </div>
            </div>
            <div class="bp-card-desc">${esc(bp.description || 'No description')}</div>
            <div class="bp-card-meta">
                <span class="bp-card-resource"><span class="bp-res-icon">⚡</span>${bp.resources?.cpu_limit || '1.0'} CPU</span>
                <span class="bp-card-resource"><span class="bp-res-icon">💾</span>${bp.resources?.memory_limit || '512m'}</span>
                <span class="bp-card-resource"><span class="bp-res-icon">🌐</span>${bp.network || 'internal'}</span>
                <div class="bp-card-tags">${(bp.tags || []).map(t => `<span class="bp-tag">${esc(t)}</span>`).join('')}</div>
            </div>
        </div>
    `).join('');
}

function toMountLines(mounts) {
    if (!Array.isArray(mounts)) return '';
    return mounts
        .map(m => `${m?.host || ''}:${m?.container || ''}:${m?.mode || 'rw'}`)
        .map(line => line.trim())
        .filter(Boolean)
        .join('\n');
}

function toEnvLines(environment) {
    if (!environment || typeof environment !== 'object') return '';
    return Object.entries(environment)
        .map(([key, value]) => `${String(key || '').trim()}=${String(value ?? '')}`)
        .map(line => line.trim())
        .filter(Boolean)
        .join('\n');
}

function toDeviceLines(devices) {
    if (!Array.isArray(devices)) return '';
    return devices
        .map(item => String(item || '').trim())
        .filter(Boolean)
        .join('\n');
}

function toSecretLines(secrets) {
    if (!Array.isArray(secrets)) return '';
    return secrets
        .map(s => {
            const name = String(s?.name || '').trim();
            if (!name) return '';
            const optional = s?.optional ? 'optional' : 'required';
            const description = String(s?.description || '').trim();
            return description ? `${name}|${optional}|${description}` : `${name}|${optional}`;
        })
        .filter(Boolean)
        .join('\n');
}

function closeBlueprintEditor() {
    const editor = document.getElementById('bp-editor');
    if (!editor) return;
    editor.classList.remove('visible');
}

function getBlueprintFieldErrorEl(fieldId) {
    return document.getElementById(`${fieldId}-error`);
}

function clearBlueprintFieldError(fieldId) {
    const wrap = document.querySelector(`.bp-field[data-field="${fieldId}"]`);
    const err = getBlueprintFieldErrorEl(fieldId);
    if (wrap) wrap.classList.remove('invalid');
    if (err) err.textContent = '';
}

function clearBlueprintEditorErrors() {
    const summary = document.getElementById('bp-editor-errors');
    if (summary) summary.innerHTML = '';
    document.querySelectorAll('.bp-field.invalid').forEach(el => el.classList.remove('invalid'));
    document.querySelectorAll('.bp-field-error').forEach(el => {
        el.textContent = '';
    });
}

function setBlueprintFieldError(fieldId, message) {
    const wrap = document.querySelector(`.bp-field[data-field="${fieldId}"]`);
    const err = getBlueprintFieldErrorEl(fieldId);
    if (wrap) wrap.classList.add('invalid');
    if (err) err.textContent = message;
}

function renderBlueprintEditorErrorSummary(errors) {
    const summary = document.getElementById('bp-editor-errors');
    if (!summary || !errors.length) return;
    summary.innerHTML = `
        <strong>Bitte korrigiere die markierten Felder:</strong>
        <ul>${errors.map(e => `<li>${esc(e.message)}</li>`).join('')}</ul>
    `;
}

function parseBlueprintMounts(raw) {
    const mounts = [];
    const errors = [];
    const lines = String(raw || '').split('\n').map(x => x.trim()).filter(Boolean);
    lines.forEach((line, idx) => {
        const parts = line.split(':').map(x => x.trim());
        if (parts.length < 2 || parts.length > 3 || !parts[0] || !parts[1]) {
            errors.push(`Mount Zeile ${idx + 1}: Format ist host:container[:ro|rw]`);
            return;
        }
        const mode = (parts[2] || 'rw').toLowerCase();
        if (mode !== 'ro' && mode !== 'rw') {
            errors.push(`Mount Zeile ${idx + 1}: Mode muss ro oder rw sein`);
            return;
        }
        mounts.push({ host: parts[0], container: parts[1], mode });
    });
    return { mounts, errors };
}

function parseBlueprintSecrets(raw) {
    const secrets = [];
    const errors = [];
    const lines = String(raw || '').split('\n').map(x => x.trim()).filter(Boolean);
    lines.forEach((line, idx) => {
        const parts = line.split('|').map(x => x.trim());
        const name = parts[0] || '';
        if (!name) {
            errors.push(`Secret Zeile ${idx + 1}: Name fehlt`);
            return;
        }
        let optional = false;
        let descStart = 1;
        const token = (parts[1] || '').toLowerCase();
        if (token) {
            if (['optional', 'opt', 'true', 'yes'].includes(token)) {
                optional = true;
                descStart = 2;
            } else if (['required', 'req', 'false', 'no'].includes(token)) {
                optional = false;
                descStart = 2;
            }
        }
        const description = parts.slice(descStart).join('|').trim();
        secrets.push({ name, optional, description });
    });
    return { secrets, errors };
}

function validateBlueprintFormAndBuildPayload() {
    clearBlueprintEditorErrors();
    const errors = [];

    const id = String(document.getElementById('bp-ed-id')?.value || '').trim();
    const name = String(document.getElementById('bp-ed-name')?.value || '').trim();
    const icon = String(document.getElementById('bp-ed-icon')?.value || '📦').trim() || '📦';
    const description = String(document.getElementById('bp-ed-desc')?.value || '').trim();
    const dockerfile = String(document.getElementById('bp-ed-dockerfile')?.value || '').trim();
    const systemPrompt = String(document.getElementById('bp-ed-prompt')?.value || '').trim();
    const image = String(document.getElementById('bp-ed-image')?.value || '').trim();
    const network = String(document.getElementById('bp-ed-network')?.value || 'internal').trim() || 'internal';
    const extendsId = String(document.getElementById('bp-ed-extends')?.value || '').trim();
    const tagsRaw = String(document.getElementById('bp-ed-tags')?.value || '');
    const allowedExecRaw = String(document.getElementById('bp-ed-allowed-exec')?.value || '');

    const cpuLimit = String(document.getElementById('bp-ed-cpu')?.value || '').trim();
    const memoryLimit = String(document.getElementById('bp-ed-ram')?.value || '').trim();
    const memorySwap = String(document.getElementById('bp-ed-swap')?.value || '').trim();
    const ttlRaw = String(document.getElementById('bp-ed-ttl')?.value || '').trim();
    const pidsRaw = String(document.getElementById('bp-ed-pids')?.value || '').trim();

    const mountsRaw = String(document.getElementById('bp-ed-mounts')?.value || '');
    const secretsRaw = String(document.getElementById('bp-ed-secrets')?.value || '');
    const environmentRaw = String(document.getElementById('bp-ed-env')?.value || '');
    const devicesRaw = String(document.getElementById('bp-ed-devices')?.value || '');

    if (!id) errors.push({ field: 'bp-ed-id', message: 'ID ist erforderlich' });
    if (!name) errors.push({ field: 'bp-ed-name', message: 'Name ist erforderlich' });
    if (id && !/^[a-z0-9][a-z0-9-]{1,63}$/.test(id)) {
        errors.push({ field: 'bp-ed-id', message: 'ID darf nur Kleinbuchstaben, Zahlen und Bindestriche enthalten' });
    }

    if (!dockerfile && !image) {
        errors.push({ field: 'bp-ed-dockerfile', message: 'Dockerfile oder Image muss gesetzt sein' });
        errors.push({ field: 'bp-ed-image', message: 'Dockerfile oder Image muss gesetzt sein' });
    }

    if (cpuLimit && !/^\d+(?:\.\d+)?$/.test(cpuLimit)) {
        errors.push({ field: 'bp-ed-cpu', message: 'CPU muss eine Zahl sein, z. B. 0.5 oder 2.0' });
    }
    if (memoryLimit && !/^\d+(?:\.\d+)?[kmg]$/i.test(memoryLimit)) {
        errors.push({ field: 'bp-ed-ram', message: 'RAM-Format: Zahl + k/m/g, z. B. 512m oder 2g' });
    }
    if (memorySwap && !/^\d+(?:\.\d+)?[kmg]$/i.test(memorySwap)) {
        errors.push({ field: 'bp-ed-swap', message: 'Swap-Format: Zahl + k/m/g, z. B. 1g' });
    }

    const ttl = parseInt(ttlRaw, 10);
    if (!Number.isFinite(ttl) || ttl <= 0) {
        errors.push({ field: 'bp-ed-ttl', message: 'TTL muss eine positive Ganzzahl sein' });
    }

    const pids = parseInt(pidsRaw, 10);
    if (!Number.isFinite(pids) || pids <= 0) {
        errors.push({ field: 'bp-ed-pids', message: 'PIDs-Limit muss eine positive Ganzzahl sein' });
    }

    if (!['none', 'internal', 'bridge', 'full'].includes(network)) {
        errors.push({ field: 'bp-ed-network', message: 'Ungültiger Netzwerkmodus' });
    }

    const mountParse = parseBlueprintMounts(mountsRaw);
    if (mountParse.errors.length) {
        errors.push({ field: 'bp-ed-mounts', message: mountParse.errors[0] });
    }

    const secretParse = parseBlueprintSecrets(secretsRaw);
    if (secretParse.errors.length) {
        errors.push({ field: 'bp-ed-secrets', message: secretParse.errors[0] });
    }

    let environment = {};
    try {
        environment = parseEnvOverrides(environmentRaw);
    } catch (e) {
        errors.push({ field: 'bp-ed-env', message: e.message || 'Ungültige Environment Variables' });
    }

    let devices = [];
    try {
        devices = parseDeviceOverrides(devicesRaw);
    } catch (e) {
        errors.push({ field: 'bp-ed-devices', message: e.message || 'Ungültige Device Mappings' });
    }

    if (errors.length) {
        errors.forEach(e => setBlueprintFieldError(e.field, e.message));
        renderBlueprintEditorErrorSummary(errors);
        logOutput('⚠️ Blueprint nicht gespeichert: Formular prüfen', 'ansi-yellow');
        return null;
    }

    const payload = {
        id,
        name,
        description,
        dockerfile,
        system_prompt: systemPrompt,
        icon,
        image: image || null,
        extends: extendsId || null,
        network,
        tags: tagsRaw.split(',').map(t => t.trim()).filter(Boolean),
        mounts: mountParse.mounts,
        devices,
        environment,
        secrets_required: secretParse.secrets,
        allowed_exec: allowedExecRaw
            .split(/[\n,]/)
            .map(x => x.trim())
            .filter(Boolean),
        resources: {
            cpu_limit: cpuLimit || '1.0',
            memory_limit: memoryLimit || '512m',
            memory_swap: memorySwap || '1g',
            timeout_seconds: ttl || 300,
            pids_limit: pids || 100,
        },
    };

    return payload;
}

function validateBlueprintFieldLive(fieldId) {
    if (!fieldId) return;
    const read = (id) => String(document.getElementById(id)?.value || '').trim();
    const validators = {
        'bp-ed-id': () => {
            const id = read('bp-ed-id');
            if (!id) return 'ID ist erforderlich';
            if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(id)) return 'Nur Kleinbuchstaben/Zahlen/Bindestrich';
            return '';
        },
        'bp-ed-name': () => read('bp-ed-name') ? '' : 'Name ist erforderlich',
        'bp-ed-cpu': () => (!read('bp-ed-cpu') || /^\d+(?:\.\d+)?$/.test(read('bp-ed-cpu'))) ? '' : 'CPU muss numerisch sein',
        'bp-ed-ram': () => (!read('bp-ed-ram') || /^\d+(?:\.\d+)?[kmg]$/i.test(read('bp-ed-ram'))) ? '' : 'Format z. B. 512m',
        'bp-ed-swap': () => (!read('bp-ed-swap') || /^\d+(?:\.\d+)?[kmg]$/i.test(read('bp-ed-swap'))) ? '' : 'Format z. B. 1g',
        'bp-ed-ttl': () => (Number.parseInt(read('bp-ed-ttl'), 10) > 0) ? '' : 'TTL > 0',
        'bp-ed-pids': () => (Number.parseInt(read('bp-ed-pids'), 10) > 0) ? '' : 'PIDs > 0',
        'bp-ed-dockerfile': () => {
            const dockerfile = read('bp-ed-dockerfile');
            const image = read('bp-ed-image');
            return (dockerfile || image) ? '' : 'Dockerfile oder Image erforderlich';
        },
        'bp-ed-image': () => {
            const dockerfile = read('bp-ed-dockerfile');
            const image = read('bp-ed-image');
            return (dockerfile || image) ? '' : 'Dockerfile oder Image erforderlich';
        },
    };
    const fn = validators[fieldId];
    if (!fn) return;
    const message = fn();
    if (!message) clearBlueprintFieldError(fieldId);
    else setBlueprintFieldError(fieldId, message);
}

function showBlueprintEditor(bp = null, options = {}) {
    editingBp = options.forceCreate ? null : bp;
    const editor = document.getElementById('bp-editor');
    const mountsValue = toMountLines(bp?.mounts || []);
    const environmentValue = toEnvLines(bp?.environment || {});
    const devicesValue = toDeviceLines(bp?.devices || []);
    const secretsValue = toSecretLines(bp?.secrets_required || []);
    const allowedExecValue = Array.isArray(bp?.allowed_exec) ? bp.allowed_exec.join(', ') : '';
    editor.innerHTML = `
        <form id="bp-editor-form" class="bp-editor-form" novalidate>
            <div class="bp-editor-head">
                <div>
                    <div class="bp-editor-title">${editingBp ? '✏️ Edit Blueprint' : '📦 New Blueprint'}</div>
                    <div class="bp-editor-subtitle">Lege Container-Profil, Ressourcen und Netzwerk sauber fest.</div>
                </div>
                <button type="button" class="bp-editor-close" id="bp-editor-close" aria-label="Close editor">✕</button>
            </div>

            <div class="bp-editor-section">
                <h4>Basis</h4>
                <div class="bp-editor-grid bp-editor-grid-3">
                    <div class="bp-field" data-field="bp-ed-id">
                        <label for="bp-ed-id">ID</label>
                        <input id="bp-ed-id" value="${bp?.id || ''}" ${editingBp ? 'disabled' : ''} placeholder="python-sandbox" />
                        <div class="bp-field-hint">Kleinbuchstaben, Zahlen, Bindestriche</div>
                        <div class="bp-field-error" id="bp-ed-id-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-name">
                        <label for="bp-ed-name">Name</label>
                        <input id="bp-ed-name" value="${esc(bp?.name || '')}" placeholder="Python Sandbox" />
                        <div class="bp-field-error" id="bp-ed-name-error"></div>
                    </div>
                    <div class="bp-field bp-field-icon" data-field="bp-ed-icon">
                        <label for="bp-ed-icon">Icon</label>
                        <input id="bp-ed-icon" value="${bp?.icon || '📦'}" />
                        <div class="bp-field-error" id="bp-ed-icon-error"></div>
                    </div>
                </div>
                <div class="bp-editor-grid bp-editor-grid-2">
                    <div class="bp-field" data-field="bp-ed-desc">
                        <label for="bp-ed-desc">Beschreibung</label>
                        <input id="bp-ed-desc" value="${esc(bp?.description || '')}" placeholder="Kurzbeschreibung für Team und KI" />
                        <div class="bp-field-error" id="bp-ed-desc-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-extends">
                        <label for="bp-ed-extends">Extends</label>
                        <input id="bp-ed-extends" value="${bp?.extends || ''}" placeholder="optional: base-blueprint-id" />
                        <div class="bp-field-error" id="bp-ed-extends-error"></div>
                    </div>
                </div>
            </div>

            <div class="bp-editor-section">
                <h4>Image & Runtime</h4>
                <div class="bp-editor-grid bp-editor-grid-2">
                    <div class="bp-field" data-field="bp-ed-image">
                        <label for="bp-ed-image">Image (optional)</label>
                        <input id="bp-ed-image" value="${esc(bp?.image || '')}" placeholder="python:3.12-slim" />
                        <div class="bp-field-hint">Alternativ zu Dockerfile</div>
                        <div class="bp-field-error" id="bp-ed-image-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-network">
                        <label for="bp-ed-network">Netzwerk</label>
                        <select id="bp-ed-network">
                            <option value="none" ${bp?.network === 'none' ? 'selected' : ''}>None (isoliert)</option>
                            <option value="internal" ${(!bp?.network || bp?.network === 'internal') ? 'selected' : ''}>Internal</option>
                            <option value="bridge" ${bp?.network === 'bridge' ? 'selected' : ''}>Bridge</option>
                            <option value="full" ${bp?.network === 'full' ? 'selected' : ''}>Full (Internet)</option>
                        </select>
                        <div class="bp-field-error" id="bp-ed-network-error"></div>
                    </div>
                </div>
                <div class="bp-field" data-field="bp-ed-dockerfile">
                    <label for="bp-ed-dockerfile">Dockerfile</label>
                    <textarea id="bp-ed-dockerfile" placeholder="FROM python:3.12-slim">${esc(bp?.dockerfile || '')}</textarea>
                    <div class="bp-field-hint">Entweder Dockerfile oder Image angeben</div>
                    <div class="bp-field-error" id="bp-ed-dockerfile-error"></div>
                </div>
                <div class="bp-field" data-field="bp-ed-prompt">
                    <label for="bp-ed-prompt">System Prompt</label>
                    <textarea id="bp-ed-prompt" placeholder="Kontext für den Container-Agenten">${esc(bp?.system_prompt || '')}</textarea>
                    <div class="bp-field-error" id="bp-ed-prompt-error"></div>
                </div>
            </div>

            <div class="bp-editor-section">
                <h4>Ressourcen</h4>
                <div class="bp-editor-grid bp-editor-grid-5">
                    <div class="bp-field" data-field="bp-ed-cpu">
                        <label for="bp-ed-cpu">CPU</label>
                        <input id="bp-ed-cpu" value="${bp?.resources?.cpu_limit || '1.0'}" />
                        <div class="bp-field-error" id="bp-ed-cpu-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-ram">
                        <label for="bp-ed-ram">RAM</label>
                        <input id="bp-ed-ram" value="${bp?.resources?.memory_limit || '512m'}" />
                        <div class="bp-field-error" id="bp-ed-ram-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-swap">
                        <label for="bp-ed-swap">Swap</label>
                        <input id="bp-ed-swap" value="${bp?.resources?.memory_swap || '1g'}" />
                        <div class="bp-field-error" id="bp-ed-swap-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-ttl">
                        <label for="bp-ed-ttl">TTL (s)</label>
                        <input id="bp-ed-ttl" value="${bp?.resources?.timeout_seconds || 300}" type="number" min="1" />
                        <div class="bp-field-error" id="bp-ed-ttl-error"></div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-pids">
                        <label for="bp-ed-pids">PIDs</label>
                        <input id="bp-ed-pids" value="${bp?.resources?.pids_limit || 100}" type="number" min="1" />
                        <div class="bp-field-error" id="bp-ed-pids-error"></div>
                    </div>
                </div>
            </div>

            <details class="bp-editor-advanced">
                <summary>Advanced Configuration</summary>
                <div class="bp-editor-section">
                    <div class="bp-editor-grid bp-editor-grid-2">
                        <div class="bp-field" data-field="bp-ed-tags">
                            <label for="bp-ed-tags">Tags</label>
                            <input id="bp-ed-tags" value="${(bp?.tags || []).join(', ')}" placeholder="python, data, internal" />
                            <div class="bp-field-error" id="bp-ed-tags-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-allowed-exec">
                            <label for="bp-ed-allowed-exec">Allowed Exec</label>
                            <input id="bp-ed-allowed-exec" value="${esc(allowedExecValue)}" placeholder="python, pip, bash" />
                            <div class="bp-field-hint">Komma- oder newline-separiert</div>
                            <div class="bp-field-error" id="bp-ed-allowed-exec-error"></div>
                        </div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-mounts">
                        <label for="bp-ed-mounts">Mounts</label>
                        <textarea id="bp-ed-mounts" placeholder="/host/path:/container/path:rw">${esc(mountsValue)}</textarea>
                        <div class="bp-field-hint">Pro Zeile: host:container[:ro|rw]</div>
                        <div class="bp-field-error" id="bp-ed-mounts-error"></div>
                    </div>
                    <div class="bp-editor-grid bp-editor-grid-2">
                        <div class="bp-field" data-field="bp-ed-env">
                            <label for="bp-ed-env">Environment Variables</label>
                            <textarea id="bp-ed-env" placeholder="KEY=value&#10;ANOTHER_KEY=value">${esc(environmentValue)}</textarea>
                            <div class="bp-field-hint">Pro Zeile: KEY=VALUE</div>
                            <div class="bp-field-error" id="bp-ed-env-error"></div>
                        </div>
                        <div class="bp-field" data-field="bp-ed-devices">
                            <label for="bp-ed-devices">Devices</label>
                            <textarea id="bp-ed-devices" placeholder="/dev/dri:/dev/dri&#10;/dev/video0:/dev/video0">${esc(devicesValue)}</textarea>
                            <div class="bp-field-hint">Pro Zeile: /dev/...:/dev/...</div>
                            <div class="bp-field-error" id="bp-ed-devices-error"></div>
                        </div>
                    </div>
                    <div class="bp-field" data-field="bp-ed-secrets">
                        <label for="bp-ed-secrets">Secrets Required</label>
                        <textarea id="bp-ed-secrets" placeholder="OPENAI_API_KEY|required|Access token">${esc(secretsValue)}</textarea>
                        <div class="bp-field-hint">Pro Zeile: NAME|required|Beschreibung (oder optional)</div>
                        <div class="bp-field-error" id="bp-ed-secrets-error"></div>
                    </div>
                </div>
            </details>

            <div id="bp-editor-errors" class="bp-editor-errors" role="alert" aria-live="assertive"></div>

            <div class="bp-editor-footer">
                <button type="button" class="proto-btn-cancel" id="bp-editor-cancel">Cancel</button>
                <button type="submit" class="proto-btn-save">💾 Save Blueprint</button>
            </div>
        </form>`;
    editor.classList.add('visible');

    const form = document.getElementById('bp-editor-form');
    const cancelBtn = document.getElementById('bp-editor-cancel');
    const closeBtn = document.getElementById('bp-editor-close');

    form?.addEventListener('submit', (event) => {
        event.preventDefault();
        window.termSaveBp();
    });
    form?.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeBlueprintEditor();
        }
    });
    cancelBtn?.addEventListener('click', closeBlueprintEditor);
    closeBtn?.addEventListener('click', closeBlueprintEditor);

    ['bp-ed-id', 'bp-ed-name', 'bp-ed-image', 'bp-ed-dockerfile', 'bp-ed-cpu', 'bp-ed-ram', 'bp-ed-swap', 'bp-ed-ttl', 'bp-ed-pids', 'bp-ed-mounts', 'bp-ed-secrets', 'bp-ed-env', 'bp-ed-devices']
        .forEach(id => {
            document.getElementById(id)?.addEventListener('input', () => {
                clearBlueprintFieldError(id);
                validateBlueprintFieldLive(id);
                if (id === 'bp-ed-image') validateBlueprintFieldLive('bp-ed-dockerfile');
                if (id === 'bp-ed-dockerfile') validateBlueprintFieldLive('bp-ed-image');
            });
        });

    const focusId = editingBp ? 'bp-ed-name' : 'bp-ed-id';
    const focusEl = document.getElementById(focusId);
    if (focusEl) {
        focusEl.focus();
        if (focusEl.select) focusEl.select();
    }
}

function closeDeployPreflight() {
    const modal = document.getElementById('bp-preflight');
    if (!modal) return;
    modal.classList.remove('visible');
    modal.innerHTML = '';
    deployPreflightState = null;
}

function parseMemoryToMb(rawValue) {
    const value = String(rawValue || '').trim().toLowerCase();
    if (!value) return NaN;
    const match = value.match(/^(\d+(?:\.\d+)?)([kmg])$/);
    if (!match) return NaN;
    const amount = Number(match[1]);
    const unit = match[2];
    if (!Number.isFinite(amount) || amount <= 0) return NaN;
    if (unit === 'g') return amount * 1024;
    if (unit === 'm') return amount;
    return amount / 1024;
}

function formatMemoryMb(mb) {
    if (!Number.isFinite(mb) || mb <= 0) return 'n/a';
    if (mb >= 1024) return `${(mb / 1024).toFixed(2)}g`;
    return `${Math.round(mb)}m`;
}

function parseEnvOverrides(rawText) {
    const env = {};
    const lines = String(rawText || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
    for (const line of lines) {
        const idx = line.indexOf('=');
        if (idx <= 0) {
            throw new Error(`Invalid env line: "${line}" (expected KEY=VALUE)`);
        }
        const key = line.slice(0, idx).trim();
        const value = line.slice(idx + 1);
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
            throw new Error(`Invalid env key: "${key}"`);
        }
        env[key] = value;
    }
    return env;
}

function parseDeviceOverrides(rawText) {
    const devices = [];
    const seen = new Set();
    const lines = String(rawText || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
    for (const line of lines) {
        if (/\s/.test(line)) {
            throw new Error(`Invalid device mapping (no spaces allowed): "${line}"`);
        }
        const hostPath = line.split(':')[0].trim();
        if (!hostPath.startsWith('/dev/')) {
            throw new Error(`Invalid device host path (must start with /dev/): "${line}"`);
        }
        if (hostPath.includes('..')) {
            throw new Error(`Invalid device host path: "${line}"`);
        }
        if (!seen.has(line)) {
            seen.add(line);
            devices.push(line);
        }
    }
    return devices;
}

function normalizeManagedPathCatalog(payload) {
    const catalog = Array.isArray(payload?.catalog) ? payload.catalog : [];
    const normalized = [];
    const seen = new Set();
    for (const item of catalog) {
        const path = String(item?.path || '').trim();
        if (!path || seen.has(path)) continue;
        seen.add(path);
        normalized.push({
            id: String(item?.id || `mp-${normalized.length + 1}`),
            label: String(item?.label || path.split('/').filter(Boolean).pop() || path),
            path,
        });
    }
    if (!normalized.length) {
        const fallback = Array.isArray(payload?.managed_paths) ? payload.managed_paths : [];
        for (const raw of fallback) {
            const path = String(raw || '').trim();
            if (!path || seen.has(path)) continue;
            seen.add(path);
            normalized.push({
                id: `mp-${normalized.length + 1}`,
                label: path.split('/').filter(Boolean).pop() || path,
                path,
            });
        }
    }
    return normalized.sort((a, b) => a.path.localeCompare(b.path));
}

function getPreflightFormValues(state) {
    const base = state.blueprint?.resources || {};
    return {
        resources: {
            cpu_limit: String(document.getElementById('pf-cpu')?.value || base.cpu_limit || '1.0').trim(),
            memory_limit: String(document.getElementById('pf-memory')?.value || base.memory_limit || '512m').trim().toLowerCase(),
            memory_swap: String(document.getElementById('pf-swap')?.value || base.memory_swap || '1g').trim().toLowerCase(),
            timeout_seconds: Number.parseInt(String(document.getElementById('pf-ttl')?.value || base.timeout_seconds || 300), 10),
            pids_limit: Number.parseInt(String(document.getElementById('pf-pids')?.value || base.pids_limit || 100), 10),
        },
        env_raw: String(document.getElementById('pf-env')?.value || ''),
        devices_raw: String(document.getElementById('pf-devices')?.value || ''),
        resume_volume: String(document.getElementById('pf-resume')?.value || '').trim(),
        managed_path: String(document.getElementById('pf-storage-path')?.value || '').trim(),
        managed_container: String(document.getElementById('pf-storage-container')?.value || '/workspace/managed').trim(),
        managed_mode: String(document.getElementById('pf-storage-mode')?.value || 'rw').trim().toLowerCase() === 'ro' ? 'ro' : 'rw',
    };
}

function hasResourceOverride(base, current) {
    return String(base.cpu_limit || '') !== String(current.cpu_limit || '')
        || String(base.memory_limit || '').toLowerCase() !== String(current.memory_limit || '').toLowerCase()
        || String(base.memory_swap || '').toLowerCase() !== String(current.memory_swap || '').toLowerCase()
        || Number(base.timeout_seconds || 0) !== Number(current.timeout_seconds || 0)
        || Number(base.pids_limit || 0) !== Number(current.pids_limit || 0);
}

function evaluateDeployPreflight(blueprint, quota, secrets, resources) {
    const blockers = [];
    const warnings = [];
    const checks = [];

    if (!blueprint?.dockerfile && !blueprint?.image) {
        blockers.push('Blueprint has neither Dockerfile nor image configured.');
    }

    const required = Array.isArray(blueprint?.secrets_required) ? blueprint.secrets_required : [];
    const available = new Set();
    (Array.isArray(secrets) ? secrets : []).forEach(s => {
        if (s?.scope === 'global') available.add(String(s.name || '').trim());
        if (s?.scope === 'blueprint' && s?.blueprint_id === blueprint.id) {
            available.add(String(s.name || '').trim());
        }
    });

    required.forEach(req => {
        const name = String(req?.name || '').trim();
        if (!name) return;
        if (!available.has(name)) {
            if (req?.optional) warnings.push(`Optional secret missing: ${name}`);
            else blockers.push(`Required secret missing: ${name}`);
        }
    });
    if (!required.length) checks.push('No declared secrets required.');

    const reqCpu = Number.parseFloat(String(resources.cpu_limit || '0'));
    if (!Number.isFinite(reqCpu) || reqCpu <= 0) {
        blockers.push(`Invalid CPU limit: ${resources.cpu_limit}`);
    }
    const reqMemMb = parseMemoryToMb(resources.memory_limit);
    if (!Number.isFinite(reqMemMb) || reqMemMb <= 0) {
        blockers.push(`Invalid memory limit: ${resources.memory_limit}`);
    }
    const reqSwapMb = parseMemoryToMb(resources.memory_swap);
    if (!Number.isFinite(reqSwapMb) || reqSwapMb <= 0) {
        blockers.push(`Invalid swap limit: ${resources.memory_swap}`);
    }
    if (!Number.isFinite(resources.timeout_seconds) || resources.timeout_seconds <= 0) {
        blockers.push(`Invalid timeout (TTL): ${resources.timeout_seconds}`);
    }
    if (!Number.isFinite(resources.pids_limit) || resources.pids_limit <= 0) {
        blockers.push(`Invalid pids limit: ${resources.pids_limit}`);
    }

    const containersUsed = Number(quota?.containers_used || 0);
    const maxContainers = Number(quota?.max_containers || 0);
    const memoryUsed = Number(quota?.memory_used_mb || 0);
    const memoryMax = Number(quota?.max_total_memory_mb || 0);
    const cpuUsed = Number(quota?.cpu_used || 0);
    const cpuMax = Number(quota?.max_total_cpu || 0);
    const remainingSlots = maxContainers - containersUsed;
    const remainingMemMb = memoryMax - memoryUsed;
    const remainingCpu = cpuMax - cpuUsed;

    if (remainingSlots <= 0) blockers.push(`Container quota exhausted (${containersUsed}/${maxContainers}).`);
    else checks.push(`Container slots available: ${remainingSlots}/${maxContainers}.`);

    if (Number.isFinite(reqMemMb) && reqMemMb > remainingMemMb) {
        blockers.push(`Not enough memory quota. Need ${formatMemoryMb(reqMemMb)}, available ${formatMemoryMb(remainingMemMb)}.`);
    } else if (Number.isFinite(reqMemMb)) {
        checks.push(`Memory check passed (${formatMemoryMb(reqMemMb)} requested).`);
    }

    if (Number.isFinite(reqCpu) && reqCpu > remainingCpu + 1e-9) {
        blockers.push(`Not enough CPU quota. Need ${reqCpu.toFixed(2)}, available ${Math.max(remainingCpu, 0).toFixed(2)}.`);
    } else if (Number.isFinite(reqCpu)) {
        checks.push(`CPU check passed (${reqCpu.toFixed(2)} requested).`);
    }

    const network = String(blueprint?.network || 'internal');
    if (network === 'full') warnings.push('Network mode FULL requires explicit user approval.');
    else if (network === 'bridge') warnings.push('Network mode BRIDGE has host-level network access.');
    else checks.push(`Network mode ${network.toUpperCase()} (restricted).`);

    if (blueprint?.image && !blueprint?.image_digest) {
        warnings.push('Image is not digest-pinned. Consider setting image_digest for stronger trust guarantees.');
    } else if (blueprint?.image && blueprint?.image_digest) {
        checks.push('Image digest pinning configured.');
    }

    return {
        blockers,
        warnings,
        checks,
        requested: {
            cpu: reqCpu,
            memory_mb: reqMemMb,
            swap_mb: reqSwapMb,
        },
    };
}

function applyManagedStoragePreflightChecks(report, formValues, managedCatalog) {
    const selectedPath = String(formValues?.managed_path || '').trim();
    if (!selectedPath) {
        report.checks.push('Managed storage picker: no extra host path selected.');
        return;
    }

    const selected = Array.isArray(managedCatalog)
        ? managedCatalog.find(item => String(item?.path || '').trim() === selectedPath)
        : null;
    if (!selected) {
        report.blockers.push(`Managed storage path is not in catalog: ${selectedPath}`);
        return;
    }

    const containerPath = String(formValues?.managed_container || '').trim();
    if (!containerPath || !containerPath.startsWith('/')) {
        report.blockers.push(`Managed mount target must be an absolute container path: ${containerPath || '(empty)'}`);
        return;
    }
    if (containerPath === '/') {
        report.blockers.push('Managed mount target "/" is not allowed.');
        return;
    }

    const mode = String(formValues?.managed_mode || 'rw').trim().toLowerCase() === 'ro' ? 'ro' : 'rw';
    if (mode === 'rw') {
        report.warnings.push(`Managed storage mount with write access: ${selectedPath} → ${containerPath}.`);
    } else {
        report.checks.push(`Managed storage mount (read-only): ${selectedPath} → ${containerPath}.`);
    }
}

function applyAdvancedOverridesPreflightChecks(report, blueprint, formValues) {
    try {
        const env = parseEnvOverrides(formValues?.env_raw || '');
        const count = Object.keys(env).length;
        if (count > 0) {
            report.warnings.push(`Environment overrides configured: ${count} variable(s).`);
        } else {
            report.checks.push('Environment overrides: none.');
        }
    } catch (e) {
        report.blockers.push(e.message || 'Invalid environment overrides.');
    }

    try {
        const devices = parseDeviceOverrides(formValues?.devices_raw || '');
        if (devices.length > 0) {
            report.warnings.push(`Device overrides configured: ${devices.length} mapping(s).`);
        } else if (Array.isArray(blueprint?.devices) && blueprint.devices.length > 0) {
            report.checks.push(`Blueprint has ${blueprint.devices.length} static device mapping(s).`);
        } else {
            report.checks.push('Device overrides: none.');
        }
    } catch (e) {
        report.blockers.push(e.message || 'Invalid device overrides.');
    }
}

function deriveTrustInfo(blueprint) {
    const network = String(blueprint?.network || 'internal');
    const risk = network === 'full' ? 'high' : (network === 'bridge' ? 'medium' : 'low');
    const digest = blueprint?.image_digest ? 'pinned' : 'unverified';
    const signature = blueprint?.signature_verified ? 'verified' : 'unknown';
    const recommendation = risk === 'high'
        ? 'High-risk network path. Require explicit approval.'
        : (risk === 'medium' ? 'Bridge network increases host exposure.' : 'Restricted network profile.');
    return { risk, digest, signature, recommendation };
}

function renderPreflightList(items, listClass, emptyText) {
    if (!items.length) return `<div class="pf-empty">${esc(emptyText)}</div>`;
    return `<ul class="${listClass}">${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`;
}

function renderDeployPreflightModal(state) {
    const modal = document.getElementById('bp-preflight');
    if (!modal) return;
    const bp = state.blueprint;
    const r = bp?.resources || {};
    const trust = deriveTrustInfo(bp);
    modal.innerHTML = `
        <div class="bp-preflight-backdrop" id="pf-backdrop"></div>
        <div class="bp-preflight-dialog" role="dialog" aria-modal="true" aria-label="Deploy Preflight">
            <div class="bp-preflight-head">
                <div>
                    <div class="bp-preflight-title">🚀 Deploy Preflight</div>
                    <div class="bp-preflight-subtitle">${esc(bp?.name || bp?.id || 'Blueprint')}</div>
                </div>
                <button class="bp-preflight-close" id="pf-close" aria-label="Close preflight">✕</button>
            </div>

            <div class="bp-preflight-quick">
                <span class="pf-chip">${esc(bp?.id || '')}</span>
                <span class="pf-chip">Network: ${esc(String(bp?.network || 'internal'))}</span>
                <span class="pf-chip">Image: ${esc(bp?.image || 'Dockerfile')}</span>
            </div>

            <div class="bp-preflight-trust">
                <h4>Trust Panel</h4>
                <div class="bp-preflight-trust-grid">
                    <div class="pf-trust-item"><span>Network Risk</span><strong class="risk-${esc(trust.risk)}">${esc(trust.risk.toUpperCase())}</strong></div>
                    <div class="pf-trust-item"><span>Digest</span><strong>${esc(trust.digest)}</strong></div>
                    <div class="pf-trust-item"><span>Signature</span><strong>${esc(trust.signature)}</strong></div>
                    <div class="pf-trust-item"><span>Recommendation</span><strong>${esc(trust.recommendation)}</strong></div>
                </div>
            </div>

            <details class="bp-preflight-overrides" id="pf-overrides" ${state.advanced ? 'open' : ''}>
                <summary>Overrides & Environment</summary>
                <div class="bp-preflight-grid">
                    <div class="bp-field">
                        <label for="pf-cpu">CPU</label>
                        <input id="pf-cpu" value="${esc(r.cpu_limit || '1.0')}" />
                    </div>
                    <div class="bp-field">
                        <label for="pf-memory">RAM</label>
                        <input id="pf-memory" value="${esc(r.memory_limit || '512m')}" />
                    </div>
                    <div class="bp-field">
                        <label for="pf-swap">Swap</label>
                        <input id="pf-swap" value="${esc(r.memory_swap || '1g')}" />
                    </div>
                    <div class="bp-field">
                        <label for="pf-ttl">TTL (s)</label>
                        <input id="pf-ttl" type="number" min="1" step="1" value="${esc(String(r.timeout_seconds || 300))}" />
                    </div>
                    <div class="bp-field">
                        <label for="pf-pids">PIDs</label>
                        <input id="pf-pids" type="number" min="1" step="1" value="${esc(String(r.pids_limit || 100))}" />
                    </div>
                </div>
                <div class="bp-field">
                    <label for="pf-resume">Resume Volume (optional)</label>
                    <input id="pf-resume" placeholder="trion_ws_blueprint_..." />
                </div>
                <div class="bp-field">
                    <label for="pf-env">Environment Variables (Overrides)</label>
                    <textarea id="pf-env" placeholder="KEY=value&#10;ANOTHER_KEY=value"></textarea>
                    <div class="bp-field-hint">One variable per line, format KEY=VALUE</div>
                </div>
                <div class="bp-field">
                    <label for="pf-devices">Device Overrides (optional)</label>
                    <textarea id="pf-devices" placeholder="/dev/dri:/dev/dri&#10;/dev/video0:/dev/video0"></textarea>
                    <div class="bp-field-hint">One mapping per line. Host path must start with /dev/.</div>
                </div>
                <div class="bp-field">
                    <label for="pf-storage-path">Managed Storage Path (Storage Broker)</label>
                    <select id="pf-storage-path">
                        <option value="">No additional managed path</option>
                        ${(state.managedCatalog || []).map(item => `
                            <option value="${esc(item.path)}">${esc(item.label)} — ${esc(item.path)}</option>
                        `).join('')}
                    </select>
                    <div class="bp-field-hint">
                        Select a broker-managed host path to mount without manual path typing.
                    </div>
                </div>
                <div class="bp-preflight-grid">
                    <div class="bp-field">
                        <label for="pf-storage-container">Container Mount Target</label>
                        <input id="pf-storage-container" value="/workspace/managed" placeholder="/workspace/data" />
                    </div>
                    <div class="bp-field">
                        <label for="pf-storage-mode">Mount Mode</label>
                        <select id="pf-storage-mode">
                            <option value="rw">Read + Write (rw)</option>
                            <option value="ro">Read-only (ro)</option>
                        </select>
                    </div>
                </div>
            </details>

            <div class="bp-preflight-section">
                <h4>Blockers</h4>
                <div id="pf-blockers"></div>
            </div>
            <div class="bp-preflight-section">
                <h4>Warnings</h4>
                <div id="pf-warnings"></div>
            </div>
            <div class="bp-preflight-section">
                <h4>Checks</h4>
                <div id="pf-checks"></div>
            </div>

            <div class="bp-preflight-footer">
                <button class="proto-btn-cancel" id="pf-cancel">Cancel</button>
                <button class="proto-btn-save" id="pf-deploy">Deploy</button>
            </div>
        </div>
    `;
    modal.classList.add('visible');

    document.getElementById('pf-close')?.addEventListener('click', closeDeployPreflight);
    document.getElementById('pf-cancel')?.addEventListener('click', closeDeployPreflight);
    document.getElementById('pf-backdrop')?.addEventListener('click', closeDeployPreflight);
    document.getElementById('pf-deploy')?.addEventListener('click', executeDeployPreflight);
    ['pf-cpu', 'pf-memory', 'pf-swap', 'pf-ttl', 'pf-pids', 'pf-env', 'pf-devices', 'pf-resume', 'pf-storage-path', 'pf-storage-container', 'pf-storage-mode'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', recalcDeployPreflight);
        document.getElementById(id)?.addEventListener('change', recalcDeployPreflight);
    });
}

function recalcDeployPreflight() {
    if (!deployPreflightState) return;
    const formValues = getPreflightFormValues(deployPreflightState);
    deployPreflightState.form = formValues;
    const report = evaluateDeployPreflight(
        deployPreflightState.blueprint,
        deployPreflightState.quota,
        deployPreflightState.secrets,
        formValues.resources,
    );
    applyManagedStoragePreflightChecks(report, formValues, deployPreflightState.managedCatalog || []);
    applyAdvancedOverridesPreflightChecks(report, deployPreflightState.blueprint, formValues);
    deployPreflightState.report = report;

    const blockers = document.getElementById('pf-blockers');
    const warnings = document.getElementById('pf-warnings');
    const checks = document.getElementById('pf-checks');
    const deployBtn = document.getElementById('pf-deploy');
    if (blockers) blockers.innerHTML = renderPreflightList(report.blockers, 'pf-list pf-list-blockers', 'No blockers detected.');
    if (warnings) warnings.innerHTML = renderPreflightList(report.warnings, 'pf-list pf-list-warnings', 'No warnings.');
    if (checks) checks.innerHTML = renderPreflightList(report.checks, 'pf-list pf-list-checks', 'No checks available.');
    if (deployBtn) {
        deployBtn.disabled = report.blockers.length > 0;
        deployBtn.textContent = report.blockers.length > 0 ? 'Fix blockers before deploy' : 'Deploy';
    }
}

async function openDeployPreflight(blueprintId, options = {}) {
    const modal = document.getElementById('bp-preflight');
    if (!modal) return;
    modal.classList.add('visible');
    modal.innerHTML = `
        <div class="bp-preflight-backdrop"></div>
        <div class="bp-preflight-dialog bp-preflight-loading">
            <div class="term-spinner"></div>
            <p>Running preflight for <strong>${esc(blueprintId)}</strong>...</p>
        </div>
    `;

    try {
        const [blueprint, quota, secretData] = await Promise.all([
            apiRequest(`/blueprints/${encodeURIComponent(blueprintId)}`, {}, 'Could not load blueprint'),
            apiRequest('/quota', {}, 'Could not load quota'),
            apiRequest('/secrets', {}, 'Could not load secrets'),
        ]);
        let managedCatalog = [];
        try {
            const managedData = await apiRequest('/storage/managed-paths', {}, 'Could not load managed storage paths');
            managedCatalog = normalizeManagedPathCatalog(managedData);
        } catch (_) {
            managedCatalog = [];
        }
        deployPreflightState = {
            blueprint,
            quota,
            secrets: secretData?.secrets || [],
            managedCatalog,
            advanced: Boolean(options.advanced),
            form: null,
            report: null,
        };
        renderDeployPreflightModal(deployPreflightState);
        recalcDeployPreflight();
    } catch (e) {
        modal.innerHTML = `
            <div class="bp-preflight-backdrop" id="pf-backdrop"></div>
            <div class="bp-preflight-dialog">
                <div class="bp-preflight-title">Preflight failed</div>
                <p class="bp-preflight-error">${esc(e.message || 'Unknown error')}</p>
                <div class="bp-preflight-footer">
                    <button class="proto-btn-cancel" id="pf-cancel">Close</button>
                </div>
            </div>
        `;
        document.getElementById('pf-backdrop')?.addEventListener('click', closeDeployPreflight);
        document.getElementById('pf-cancel')?.addEventListener('click', closeDeployPreflight);
    }
}

async function executeDeployPreflight() {
    if (!deployPreflightState) return;
    recalcDeployPreflight();
    const state = deployPreflightState;
    if (!state?.form || !state?.report) return;
    if (state.report.blockers.length > 0) {
        showToast('Preflight has blockers. Fix them before deploy.', 'error');
        return;
    }

    let env = {};
    try {
        env = parseEnvOverrides(state.form.env_raw);
    } catch (e) {
        showToast(e.message || 'Invalid environment overrides', 'error');
        return;
    }
    let devices = [];
    try {
        devices = parseDeviceOverrides(state.form.devices_raw);
    } catch (e) {
        showToast(e.message || 'Invalid device overrides', 'error');
        return;
    }

    const payload = { blueprint_id: state.blueprint.id };
    if (hasResourceOverride(state.blueprint.resources || {}, state.form.resources)) {
        payload.override_resources = state.form.resources;
    }
    if (Object.keys(env).length > 0) payload.environment = env;
    if (devices.length > 0) payload.device_overrides = devices;
    if (state.form.resume_volume) payload.resume_volume = state.form.resume_volume;
    if (state.form.managed_path) {
        payload.mount_overrides = [
            {
                host: state.form.managed_path,
                container: state.form.managed_container || '/workspace/managed',
                type: 'bind',
                mode: state.form.managed_mode === 'ro' ? 'ro' : 'rw',
            },
        ];
        payload.storage_scope_override = '__auto__';
    }

    try {
        const data = await apiRequest('/containers/deploy', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(payload),
        }, 'Deploy failed');
        if (data.deployed) {
            closeDeployPreflight();
            showToast(`Container started: ${data.container?.container_id?.slice(0, 12) || 'ok'}`, 'success');
            logOutput(`✅ Container started: ${data.container?.container_id?.slice(0,12)}`, 'ansi-green');
            if (data.container?.container_id) autoFocusContainer(data.container.container_id);
            rememberRecent('blueprints', state.blueprint.id);
            await loadContainers();
            if (activeTab === 'dashboard') await loadDashboard();
            return;
        }
        if (data.pending_approval) {
            closeDeployPreflight();
            showApprovalBanner(data.approval_id, data.reason, state.blueprint.id);
            showToast(`Approval required: ${data.reason}`, 'warn');
            logOutput(`⚠️ Approval required: ${data.reason}`, 'ansi-yellow');
            return;
        }
        showToast(data.error || data.note || 'Deploy did not start', 'warn');
    } catch (e) {
        const hint = suggestFix(e.message || '');
        showToast(e.message || 'Deploy failed', 'error');
        if (hint) showToast(`Why blocked: ${hint}`, 'warn');
        logOutput(`❌ ${e.message}`, 'ansi-red');
    }
}

// Global handlers
window.termSaveBp = async function() {
    const data = validateBlueprintFormAndBuildPayload();
    if (!data) return;
    try {
        const method = editingBp ? 'PUT' : 'POST';
        const url = editingBp ? `/blueprints/${data.id}` : '/blueprints';
        const result = await apiRequest(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) }, 'Could not save blueprint');
        if (result.created || result.updated) {
            logOutput(`✅ Blueprint "${data.id}" ${editingBp ? 'updated' : 'created'}`, 'ansi-green');
            closeBlueprintEditor();
            await loadBlueprints();
        } else {
            const msg = result.error || 'Unknown';
            renderBlueprintEditorErrorSummary([{ field: 'bp-ed-name', message: msg }]);
            logOutput(`❌ ${msg}`, 'ansi-red');
        }
    } catch (e) {
        logOutput(`❌ ${e.message}`, 'ansi-red');
    }
};

window.termDeleteBp = async function(id) {
    if (!confirm(`Delete blueprint "${id}"?`)) return;
    try {
        await apiRequest(`/blueprints/${id}`, { method: 'DELETE' }, 'Could not delete blueprint');
        logOutput(`🗑️ "${id}" deleted`, 'ansi-yellow');
        await loadBlueprints();
    } catch (e) {
        showToast(e.message || 'Delete failed', 'error');
        logOutput(`❌ ${e.message}`, 'ansi-red');
    }
};
window.termEditBp = async function(id) { const bp = blueprints.find(b => b.id === id); if (bp) showBlueprintEditor(bp); };
window.termCloneBp = async function(id) {
    const source = blueprints.find(b => b.id === id);
    if (!source) {
        showToast(`Blueprint "${id}" not found`, 'error');
        return;
    }
    const cloned = JSON.parse(JSON.stringify(source));
    cloned.id = `${source.id}-copy`;
    cloned.name = `${source.name || source.id} (Copy)`;
    showBlueprintEditor(cloned, { forceCreate: true });
    showToast(`Clone prepared: ${cloned.id}`, 'success');
};
window.termExportBp = async function(id) {
    try {
        const data = await apiRequest(`/blueprints/${id}/yaml`, {}, 'Could not export blueprint');
        const yaml = String(data.yaml || '');
        if (!yaml.trim()) {
            showToast('No YAML content returned', 'warn');
            return;
        }
        downloadText(`${id}.yaml`, yaml);
        if (navigator.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(yaml);
                showToast(`YAML exported + copied: ${id}.yaml`, 'success');
            } catch (_) {
                showToast(`YAML exported: ${id}.yaml`, 'success');
            }
        } else {
            showToast(`YAML exported: ${id}.yaml`, 'success');
        }
        logOutput(`📤 YAML export ready for ${id}\n${yaml.slice(0, 4000)}`, 'ansi-cyan');
        switchTab('logs');
    } catch(e) {
        showToast(e.message || 'Export failed', 'error');
        logOutput(`❌ ${e.message}`, 'ansi-red');
    }
};
window.termDeployBpWithOverrides = async function(id) {
    rememberRecent('blueprints', id);
    await openDeployPreflight(id, { advanced: true });
};
window.termDeployBp = async function(id) {
    rememberRecent('blueprints', id);
    await openDeployPreflight(id, { advanced: false });
};


// ═══════════════════════════════════════════════════════════
// CONTAINERS
// ═══════════════════════════════════════════════════════════

async function loadContainers() {
    try {
        const data = await apiRequest('/containers', {}, 'Could not load containers');
        containers = data.containers || [];
        document.getElementById('ct-count').textContent = containers.length;
        renderContainers();
        if (containerDetailState.open) {
            const stillExists = containers.some(c => c.container_id === containerDetailState.containerId);
            if (!stillExists) closeContainerDrawer();
        }
    } catch (e) {
        document.getElementById('ct-list').innerHTML = renderEmpty('🔄', 'No containers running', 'Deploy a blueprint');
    }
}

function renderContainers() {
    const list = document.getElementById('ct-list');
    if (!containers.length) { list.innerHTML = renderEmpty('🔄', 'No containers running', 'Deploy a blueprint'); return; }
    const iconForStatus = (status) => {
        if (status === 'running') return '🟢';
        if (status === 'error') return '🔴';
        if (status === 'stopped') return '🟠';
        return '⚪';
    };
    list.innerHTML = containers.map(ct => `
        <div class="ct-row glass ct-${esc(ct.status || 'unknown')}" onclick="termOpenCtDetails('${ct.container_id}')">
            <div class="ct-row-status"><span class="bp-status-dot ${ct.status}"></span></div>
            <div class="ct-row-info">
                <div class="ct-row-name">${iconForStatus(ct.status)} ${esc(ct.name)}</div>
                <div class="ct-row-detail">${ct.container_id?.slice(0,12)} · ${ct.blueprint_id}</div>
            </div>
            <div class="ct-row-stats">
                <div class="ct-stat"><div class="ct-stat-val">${ct.cpu_percent?.toFixed(1)}%</div><div class="ct-stat-label">CPU</div></div>
                <div class="ct-stat"><div class="ct-stat-val">${ct.memory_mb?.toFixed(0)}M</div><div class="ct-stat-label">RAM</div></div>
            </div>
            <div class="ct-row-actions">
                <button class="term-btn-sm" onclick="event.stopPropagation();termOpenCtDetails('${ct.container_id}')">🔎</button>
                <button class="term-btn-sm" onclick="event.stopPropagation();termAttachCt('${ct.container_id}')">🔗</button>
                <button class="term-btn-sm" onclick="event.stopPropagation();termStopCt('${ct.container_id}')">⏹</button>
            </div>
        </div>
    `).join('');
}

async function loadQuota() {
    try {
        const q = await apiRequest('/quota', {}, 'Could not load quota');
        const pct = (q.containers_used / q.max_containers) * 100;
        const fill = document.getElementById('quota-fill');
        if (fill) fill.style.width = `${pct}%`;
        const text = document.getElementById('ct-quota-text');
        if (text) text.textContent = `${q.containers_used}/${q.max_containers} Container · ${q.memory_used_mb}/${q.max_total_memory_mb} MB`;
    } catch (e) { /* silent */ }
}

window.termStopCt = async function(id) {
    try {
        await apiRequest(`/containers/${id}/stop`, { method: 'POST' }, 'Could not stop container');
        logOutput(`⏹ Stopped ${id.slice(0,12)}`, 'ansi-yellow');
        await loadContainers();
        if (activeTab === 'dashboard') await loadDashboard();
    } catch (e) {
        logOutput(`❌ ${e.message}`, 'ansi-red');
    }
};
window.termAttachCt = function(id) {
    attachedContainer = id;
    wsSend({ type: 'attach', container_id: id });
    switchTab('logs'); initXterm();
    setLogPanelMode('shell');
    addShellSession(id);
    rememberRecent('containers', id);
    logOutput(`🔗 Attached to ${id.slice(0,12)}`, 'ansi-cyan');
};

function stopContainerDetailPolling() {
    if (containerDetailState.pollTimer) {
        clearInterval(containerDetailState.pollTimer);
        containerDetailState.pollTimer = null;
    }
}

function setContainerDetailTab(tab) {
    containerDetailState.tab = ['logs', 'stats', 'events'].includes(tab) ? tab : 'logs';
    document.querySelectorAll('.ct-drawer-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.ctTab === containerDetailState.tab);
    });
    document.querySelectorAll('.ct-drawer-pane').forEach(pane => {
        pane.classList.toggle('active', pane.dataset.ctPane === containerDetailState.tab);
    });
}

function renderContainerDrawerShell(containerId) {
    const drawer = document.getElementById('ct-drawer');
    if (!drawer) return;
    drawer.innerHTML = `
        <div class="ct-drawer-head">
            <div>
                <h3>Container Detail</h3>
                <div class="ct-drawer-sub">${esc(containerId.slice(0, 12))}</div>
            </div>
            <button class="ct-drawer-close" id="ct-drawer-close">✕</button>
        </div>
        <div class="ct-drawer-toolbar">
            <span id="ct-drawer-refresh-status">Auto refresh every 7s</span>
            <span id="ct-drawer-last-update">Last update: -</span>
        </div>
        <div class="ct-control-grid">
            <section class="ct-control-col">
                <h4>Logs</h4>
                <pre id="ct-drawer-logs">Loading logs...</pre>
                <div id="ct-drawer-log-hint" class="ct-drawer-hint"></div>
            </section>
            <section class="ct-control-col">
                <h4>Stats</h4>
                <div id="ct-drawer-stats">Loading stats...</div>
                <div id="ct-drawer-stat-hint" class="ct-drawer-hint"></div>
            </section>
            <section class="ct-control-col">
                <h4>Events</h4>
                <div id="ct-drawer-events">Loading events...</div>
            </section>
        </div>
        <div class="ct-drawer-actions">
            <button class="term-btn-sm" id="ct-drawer-refresh">↻ Refresh</button>
            <button class="term-btn-sm" id="ct-drawer-attach">🔗 Attach</button>
            <button class="term-btn-sm" id="ct-drawer-restart">⟳ Restart</button>
            <button class="term-btn-sm" id="ct-drawer-snapshot">📸 Snapshot</button>
            <button class="term-btn-sm danger" id="ct-drawer-stop">⏹ Stop</button>
        </div>
    `;
    drawer.classList.add('visible');
    document.getElementById('ct-drawer-close')?.addEventListener('click', closeContainerDrawer);
    document.getElementById('ct-drawer-refresh')?.addEventListener('click', refreshContainerDetail);
    document.getElementById('ct-drawer-attach')?.addEventListener('click', () => {
        if (!containerDetailState.containerId) return;
        window.termAttachCt(containerDetailState.containerId);
    });
    document.getElementById('ct-drawer-stop')?.addEventListener('click', async () => {
        if (!containerDetailState.containerId) return;
        await window.termStopCt(containerDetailState.containerId);
        await loadContainers();
        await refreshContainerDetail();
    });
    document.getElementById('ct-drawer-restart')?.addEventListener('click', async () => {
        const current = containers.find(c => c.container_id === containerDetailState.containerId);
        if (!current) return;
        if (!confirm(`Restart container from blueprint "${current.blueprint_id}"?`)) return;
        await window.termStopCt(current.container_id);
        await window.termDeployBp(current.blueprint_id);
    });
    document.getElementById('ct-drawer-snapshot')?.addEventListener('click', async () => {
        const current = containers.find(c => c.container_id === containerDetailState.containerId);
        const volumeName = current?.volume_name || '';
        if (!volumeName) {
            showToast('No workspace volume attached', 'warn');
            return;
        }
        await window.termSnapshotVolume(volumeName);
    });
}

function closeContainerDrawer() {
    containerDetailState.open = false;
    containerDetailState.containerId = '';
    stopContainerDetailPolling();
    const drawer = document.getElementById('ct-drawer');
    if (drawer) {
        drawer.classList.remove('visible');
        drawer.innerHTML = '';
    }
}

function renderContainerDetailStats(stats) {
    if (!stats || stats.error) {
        return `<div class="ct-drawer-empty">${esc(stats?.error || 'No stats available')}</div>`;
    }
    return `
        <div class="ct-drawer-kpis">
            <div class="ct-kpi"><span>CPU</span><strong>${esc(String(stats.cpu_percent ?? '0'))}%</strong></div>
            <div class="ct-kpi"><span>RAM</span><strong>${esc(String(stats.memory_mb ?? '0'))} / ${esc(String(stats.memory_limit_mb ?? '0'))} MB</strong></div>
            <div class="ct-kpi"><span>RX/TX</span><strong>${esc(String(stats.network_rx_bytes ?? 0))} / ${esc(String(stats.network_tx_bytes ?? 0))}</strong></div>
            <div class="ct-kpi"><span>Efficiency</span><strong>${esc(String(stats.efficiency?.level || 'n/a'))}</strong></div>
        </div>
    `;
}

function renderContainerDetailEvents(entries, containerId) {
    const rows = (entries || []).filter(entry => {
        const cid = String(entry?.container_id || '');
        return cid === containerId || cid.startsWith(containerId.slice(0, 12));
    });
    if (!rows.length) return '<div class="ct-drawer-empty">No matching events.</div>';
    return rows.slice(0, 40).map(entry => `
        <div class="ct-drawer-event">
            <div class="ct-drawer-event-top">
                <span>${esc(entry.created_at || '')}</span>
                <span>${esc(entry.action || '')}</span>
            </div>
            <div class="ct-drawer-event-msg">${esc(entry.details || '')}</div>
        </div>
    `).join('');
}

function suggestFix(message) {
    const msg = String(message || '').toLowerCase();
    if (msg.includes('not found')) return 'Suggestion: verify container ID and refresh the list.';
    if (msg.includes('secret')) return 'Suggestion: open Vault tab and add missing secret.';
    if (msg.includes('quota')) return 'Suggestion: stop old containers or lower resource limits.';
    if (msg.includes('approval')) return 'Suggestion: open Approval Center and resolve pending requests.';
    if (msg.includes('healthcheck_timeout_auto_stopped') || msg.includes('healthcheck timeout')) {
        return 'Suggestion: container did not become healthy in time. Check logs/healthcheck and increase readiness timeout if needed.';
    }
    if (msg.includes('healthcheck_unhealthy_auto_stopped') || msg.includes('reported unhealthy')) {
        return 'Suggestion: healthcheck failed. Verify ports/command/env and inspect container logs.';
    }
    if (msg.includes('container_exited_before_ready_auto_stopped') || msg.includes('exited before ready')) {
        return 'Suggestion: startup failed before readiness. Inspect logs and required secrets/env vars.';
    }
    return '';
}

async function refreshContainerDetail() {
    if (!containerDetailState.open || !containerDetailState.containerId) return;
    const containerId = containerDetailState.containerId;
    try {
        const [logsData, statsData, auditData] = await Promise.all([
            apiRequest(`/containers/${containerId}/logs?tail=180`, {}, 'Could not load logs'),
            apiRequest(`/containers/${containerId}/stats`, {}, 'Could not load stats'),
            apiRequest('/audit?limit=120', {}, 'Could not load audit log'),
        ]);
        const logsEl = document.getElementById('ct-drawer-logs');
        if (logsEl) logsEl.textContent = String(logsData?.logs || 'No logs');
        const logHint = document.getElementById('ct-drawer-log-hint');
        if (logHint) logHint.textContent = suggestFix(logsData?.logs || '');
        const statsEl = document.getElementById('ct-drawer-stats');
        if (statsEl) statsEl.innerHTML = renderContainerDetailStats(statsData);
        const statHint = document.getElementById('ct-drawer-stat-hint');
        if (statHint) statHint.textContent = suggestFix(statsData?.error || '');
        const eventsEl = document.getElementById('ct-drawer-events');
        if (eventsEl) eventsEl.innerHTML = renderContainerDetailEvents(auditData?.entries || [], containerId);
        const stamp = document.getElementById('ct-drawer-last-update');
        if (stamp) stamp.textContent = `Last update: ${new Date().toLocaleTimeString()}`;
    } catch (e) {
        const logsEl = document.getElementById('ct-drawer-logs');
        if (logsEl) logsEl.textContent = e.message || 'Could not load details';
        const logHint = document.getElementById('ct-drawer-log-hint');
        if (logHint) logHint.textContent = suggestFix(e.message || '');
    }
}

function openContainerDrawer(containerId) {
    if (!containerId) return;
    containerDetailState.open = true;
    containerDetailState.containerId = containerId;
    renderContainerDrawerShell(containerId);
    setContainerDetailTab(containerDetailState.tab || 'logs');
    refreshContainerDetail();
    stopContainerDetailPolling();
    containerDetailState.pollTimer = setInterval(refreshContainerDetail, 7000);
}

window.termOpenCtDetails = function(id) {
    openContainerDrawer(id);
};

function getVolumeUsageMap() {
    const usage = new Map();
    (containers || []).forEach(ct => {
        const name = String(ct?.volume_name || '');
        if (!name) return;
        if (!usage.has(name)) usage.set(name, []);
        usage.get(name).push(ct.container_id?.slice(0, 12) || ct.name || 'container');
    });
    return usage;
}

function renderVolumeRows() {
    const usage = getVolumeUsageMap();
    const filtered = volumeManagerState.volumes.filter(v => {
        if (!volumeManagerState.filter) return true;
        const query = volumeManagerState.filter.toLowerCase();
        return String(v.name || '').toLowerCase().includes(query)
            || String(v.blueprint_id || '').toLowerCase().includes(query);
    });
    if (!filtered.length) return '<div class="vm-empty">No volumes match this filter.</div>';
    return filtered.map(v => {
        const usedBy = usage.get(v.name) || [];
        return `
            <div class="vm-row vm-card">
                <div class="vm-main">
                    <div class="vm-title">${esc(v.name)} ${usedBy.length ? '<span class="vm-badge inuse">In Use</span>' : '<span class="vm-badge idle">Idle</span>'}</div>
                    <div class="vm-meta">${esc(v.blueprint_id || 'n/a')} · ${esc(v.created_at || '')}</div>
                    <div class="vm-usage">${usedBy.length ? `Used by: ${esc(usedBy.join(', '))}` : 'Not attached to container'}</div>
                </div>
                <div class="vm-actions">
                    <button class="term-btn-sm" onclick="termSnapshotVolume('${esc(v.name)}')">📸 Snapshot</button>
                    <button class="term-btn-sm danger" onclick="termRemoveVolume('${esc(v.name)}')">🗑️ Delete</button>
                </div>
            </div>
        `;
    }).join('');
}

function renderSnapshotRows() {
    const rows = volumeManagerState.snapshots || [];
    if (!rows.length) return '<div class="vm-empty">No snapshots available.</div>';
    return rows.slice(0, 120).map(s => `
        <div class="vm-row vm-row-snapshot vm-card">
            <div class="vm-main">
                <div class="vm-title">${esc(s.filename || '')}</div>
                <div class="vm-meta">${esc(s.volume_name || 'volume?')} · ${esc(String(s.size_mb || 0))} MB · ${esc(s.created_at || '')}</div>
            </div>
            <div class="vm-actions">
                <button class="term-btn-sm" onclick="termRestoreSnapshot('${esc(s.filename || '')}')">♻ Restore</button>
                <button class="term-btn-sm danger" onclick="termDeleteSnapshot('${esc(s.filename || '')}')">🗑️ Delete</button>
            </div>
        </div>
    `).join('');
}

function renderSnapshotCompare() {
    const rows = volumeManagerState.snapshots || [];
    const byName = new Map(rows.map(s => [s.filename, s]));
    const a = byName.get(volumeManagerState.compareA);
    const b = byName.get(volumeManagerState.compareB);
    if (!a || !b) return '<div class="vm-empty">Choose two snapshots to compare.</div>';
    const delta = Number((a.size_mb || 0) - (b.size_mb || 0)).toFixed(1);
    return `
        <div class="vm-compare-card">
            <div><strong>A:</strong> ${esc(a.filename)} · ${esc(String(a.size_mb || 0))} MB</div>
            <div><strong>B:</strong> ${esc(b.filename)} · ${esc(String(b.size_mb || 0))} MB</div>
            <div><strong>Δ Size:</strong> ${delta} MB</div>
            <div><strong>Source:</strong> ${esc(a.volume_name || '-')} vs ${esc(b.volume_name || '-')}</div>
        </div>
    `;
}

function renderVolumeManager() {
    const root = document.getElementById('vm-manager');
    if (!root) return;
    if (!volumeManagerState.open) {
        root.classList.remove('visible');
        root.innerHTML = '';
        return;
    }
    root.classList.add('visible');
    root.innerHTML = `
        <div class="vm-head">
            <h3>Volumes & Snapshots</h3>
            <button class="term-btn-sm" id="vm-refresh-btn">↻ Refresh</button>
        </div>
        <div class="vm-toolbar">
            <input id="vm-filter" placeholder="Filter volume or blueprint..." value="${esc(volumeManagerState.filter)}" />
        </div>
        <div class="vm-columns">
            <div class="vm-column">
                <h4>Volumes</h4>
                <div class="vm-list" id="vm-volume-list">${renderVolumeRows()}</div>
            </div>
            <div class="vm-column">
                <h4>Snapshots</h4>
                <div class="vm-compare-toolbar">
                    <select id="vm-compare-a">
                        <option value="">Snapshot A</option>
                        ${(volumeManagerState.snapshots || []).map(s => `<option value="${esc(s.filename)}" ${volumeManagerState.compareA === s.filename ? 'selected' : ''}>${esc(s.filename)}</option>`).join('')}
                    </select>
                    <select id="vm-compare-b">
                        <option value="">Snapshot B</option>
                        ${(volumeManagerState.snapshots || []).map(s => `<option value="${esc(s.filename)}" ${volumeManagerState.compareB === s.filename ? 'selected' : ''}>${esc(s.filename)}</option>`).join('')}
                    </select>
                </div>
                <div class="vm-compare" id="vm-compare">${renderSnapshotCompare()}</div>
                <div class="vm-list" id="vm-snapshot-list">${renderSnapshotRows()}</div>
            </div>
        </div>
    `;
    document.getElementById('vm-refresh-btn')?.addEventListener('click', refreshVolumeManager);
    document.getElementById('vm-filter')?.addEventListener('input', (event) => {
        volumeManagerState.filter = String(event.target?.value || '').trim();
        renderVolumeManager();
    });
    document.getElementById('vm-compare-a')?.addEventListener('change', (event) => {
        volumeManagerState.compareA = String(event.target?.value || '');
        renderVolumeManager();
    });
    document.getElementById('vm-compare-b')?.addEventListener('change', (event) => {
        volumeManagerState.compareB = String(event.target?.value || '');
        renderVolumeManager();
    });
}

async function refreshVolumeManager() {
    if (!volumeManagerState.open && activeTab !== 'containers') return;
    try {
        const [volData, snapData] = await Promise.all([
            apiRequest('/volumes', {}, 'Could not load volumes'),
            apiRequest('/snapshots', {}, 'Could not load snapshots'),
        ]);
        volumeManagerState.volumes = volData?.volumes || [];
        volumeManagerState.snapshots = snapData?.snapshots || [];
        renderVolumeManager();
    } catch (e) {
        showToast(e.message || 'Could not load volume manager', 'error');
    }
}

function toggleVolumeManager() {
    volumeManagerState.open = !volumeManagerState.open;
    renderVolumeManager();
    if (volumeManagerState.open) refreshVolumeManager();
}

window.termSnapshotVolume = async function(volumeName) {
    const tag = prompt(`Snapshot tag for ${volumeName} (optional):`, '') || '';
    try {
        const payload = { volume_name: volumeName };
        if (tag.trim()) payload.tag = tag.trim();
        const data = await apiRequest('/snapshots/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, 'Snapshot creation failed');
        if (data.created) {
            showToast(`Snapshot created: ${data.filename}`, 'success');
            rememberRecent('volumes', volumeName);
            await refreshVolumeManager();
        }
    } catch (e) {
        showToast(e.message || 'Snapshot failed', 'error');
    }
};

window.termRestoreSnapshot = async function(filename) {
    const target = prompt(`Restore target volume for ${filename}\nLeave empty to auto-create new volume:`, '') || '';
    if (target && volumeManagerState.volumes.some(v => v.name === target)) {
        const overwrite = confirm(`Volume "${target}" already exists. Continue restore into existing target?`);
        if (!overwrite) return;
    }
    const proceed = confirm(`Restore snapshot "${filename}" ${target ? `into "${target}"` : 'into new volume'}?`);
    if (!proceed) return;
    try {
        const payload = { filename };
        if (target.trim()) payload.target_volume = target.trim();
        const data = await apiRequest('/snapshots/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, 'Snapshot restore failed');
        if (data.restored) {
            showToast(`Snapshot restored to ${data.volume}`, 'success');
            rememberRecent('volumes', data.volume);
            await refreshVolumeManager();
        }
    } catch (e) {
        showToast(e.message || 'Restore failed', 'error');
    }
};

window.termDeleteSnapshot = async function(filename) {
    if (!confirm(`Delete snapshot "${filename}"?`)) return;
    try {
        await apiRequest(`/snapshots/${encodeURIComponent(filename)}`, { method: 'DELETE' }, 'Could not delete snapshot');
        showToast(`Snapshot deleted: ${filename}`, 'warn');
        await refreshVolumeManager();
    } catch (e) {
        showToast(e.message || 'Delete snapshot failed', 'error');
    }
};

window.termRemoveVolume = async function(volumeName) {
    if (!confirm(`Delete volume "${volumeName}"?`)) return;
    try {
        await apiRequest(`/volumes/${encodeURIComponent(volumeName)}`, { method: 'DELETE' }, 'Could not remove volume');
        showToast(`Volume removed: ${volumeName}`, 'warn');
        await refreshVolumeManager();
    } catch (e) {
        showToast(e.message || 'Remove volume failed', 'error');
    }
};


// ═══════════════════════════════════════════════════════════
// VAULT (unchanged)
// ═══════════════════════════════════════════════════════════

async function loadSecrets() {
    try {
        const data = await apiRequest('/secrets', {}, 'Could not load secrets');
        secrets = data.secrets || [];
        document.getElementById('vault-count').textContent = secrets.length;
        renderSecrets();
    } catch (e) {
        document.getElementById('vault-list').innerHTML = renderEmpty('🔐', 'Vault is empty', 'Add secrets');
    }
}

function renderSecrets() {
    const list = document.getElementById('vault-list');
    if (!secrets.length) { list.innerHTML = renderEmpty('🔐', 'No secrets', 'Add API keys or credentials'); return; }
    list.innerHTML = secrets.map(s => `
        <div class="vault-row">
            <div class="vault-icon">🔑</div>
            <div class="vault-info"><div class="vault-name">${esc(s.name)}</div><div class="vault-scope">${s.scope}${s.blueprint_id ? ' · '+s.blueprint_id : ''}</div></div>
            <div class="vault-mask">••••••••</div>
            <div class="vault-actions"><button class="term-btn-sm danger" onclick="termDeleteSecret('${s.name}','${s.scope}','${s.blueprint_id||''}')">🗑️</button></div>
        </div>
    `).join('');
}

async function saveSecret() {
    const name = document.getElementById('vault-name')?.value.trim();
    const value = document.getElementById('vault-value')?.value;
    const scope = document.getElementById('vault-scope')?.value || 'global';
    const bpId = document.getElementById('vault-bp-id')?.value.trim() || null;
    if (!name || !value) { logOutput('⚠️ Name and Value required', 'ansi-yellow'); return; }
    try {
        const data = await apiRequest('/secrets', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name, value, scope, blueprint_id: bpId }) }, 'Could not store secret');
        if (data.stored) {
            logOutput(`🔐 "${name}" stored`, 'ansi-green');
            document.getElementById('vault-form')?.classList.remove('visible');
            document.getElementById('vault-name').value = ''; document.getElementById('vault-value').value = '';
            await loadSecrets();
        }
    } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
}

window.termDeleteSecret = async function(name, scope, bpId) {
    if (!confirm(`Delete secret "${name}"?`)) return;
    let path = `/secrets/${encodeURIComponent(name)}?scope=${encodeURIComponent(scope)}`;
    if (bpId) path += `&blueprint_id=${encodeURIComponent(bpId)}`;
    try {
        await apiRequest(path, { method: 'DELETE' }, 'Could not delete secret');
        logOutput(`🗑️ "${name}" deleted`, 'ansi-yellow');
        await loadSecrets();
    } catch (e) {
        logOutput(`❌ ${e.message}`, 'ansi-red');
    }
};


// ═══════════════════════════════════════════════════════════
// LOGS / OUTPUT
// ═══════════════════════════════════════════════════════════

async function loadAuditLog() {
    try {
        const data = await apiRequest('/audit', {}, 'Could not load audit log');
        if (data.entries?.length) {
            data.entries.forEach(e => logOutput(`[${e.created_at}] ${e.action} — ${e.blueprint_id} ${e.details||''}`, 'ansi-dim'));
        }
    } catch (e) { /* silent */ }
}

function toActivityLevel(levelLike) {
    const value = String(levelLike || '').toLowerCase();
    if (['error', 'failed', 'fatal'].includes(value)) return 'error';
    if (['warn', 'warning', 'rejected', 'expired'].includes(value)) return 'warn';
    if (['success', 'ok', 'started', 'approved'].includes(value)) return 'success';
    return 'info';
}

function pushActivity(entry) {
    const activity = {
        created_at: entry?.created_at || new Date().toISOString(),
        level: toActivityLevel(entry?.level || entry?.status || entry?.action),
        event: String(entry?.event || entry?.action || 'event'),
        message: String(entry?.message || entry?.details || entry?.reason || entry?.action || ''),
        container_id: String(entry?.container_id || ''),
        blueprint_id: String(entry?.blueprint_id || ''),
    };
    activityFeed.unshift(activity);
    if (activityFeed.length > 250) activityFeed = activityFeed.slice(0, 250);
    renderActivityFeed();
}

function renderActivityFeed() {
    const list = document.getElementById('term-activity-list');
    if (!list) return;
    if (!activityFeed.length) {
        list.innerHTML = '<div class="term-activity-empty">No activity yet.</div>';
        return;
    }
    list.innerHTML = activityFeed.slice(0, 120).map(item => `
        <button class="term-activity-item ${esc(item.level)}" data-activity-ts="${esc(item.created_at)}" data-activity-event="${esc(item.event)}">
            <div class="term-activity-top">
                <span class="term-activity-level">${esc(item.level.toUpperCase())}</span>
                <span class="term-activity-time">${esc(item.created_at)}</span>
            </div>
            <div class="term-activity-msg">${esc(item.message || item.event)}</div>
            <div class="term-activity-meta">${esc(item.event)} ${item.blueprint_id ? `· ${esc(item.blueprint_id)}` : ''} ${item.container_id ? `· ${esc(item.container_id.slice(0, 12))}` : ''}</div>
        </button>
    `).join('');
    list.querySelectorAll('.term-activity-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const item = activityFeed.find(a => a.created_at === btn.dataset.activityTs && a.event === btn.dataset.activityEvent);
            if (item) openActivityDetail(item);
        });
    });
}

function mapAuditEntryToActivity(entry) {
    const action = String(entry?.action || '');
    return {
        created_at: entry?.created_at || new Date().toISOString(),
        level: toActivityLevel(action),
        event: action,
        message: `${action} ${entry?.details || ''}`.trim(),
        container_id: entry?.container_id || '',
        blueprint_id: entry?.blueprint_id || '',
    };
}

function memoryStatusTone(status) {
    const s = String(status || '').toLowerCase();
    if (s === 'connected') return 'success';
    if (s === 'degraded') return 'warn';
    return 'error';
}

function formatNoteTime(ts) {
    const value = String(ts || '').trim();
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch (_) {
        return value;
    }
}

function renderMemoryPanel() {
    const statusEl = document.getElementById('term-memory-status');
    const listEl = document.getElementById('term-memory-list');
    if (!statusEl || !listEl) return;

    const status = String(memoryStatusState?.home_status || 'unknown');
    const code = String(memoryStatusState?.home_error_code || '');
    statusEl.className = `term-memory-status ${memoryStatusTone(status)}`;
    statusEl.textContent = `Status: ${status}${code ? ` (${code})` : ''}`;

    if (!memoryNotes.length) {
        listEl.innerHTML = '<div class="term-activity-empty">No memory notes yet.</div>';
        return;
    }

    listEl.innerHTML = memoryNotes.map(note => `
        <div class="term-memory-item">
            <div class="term-memory-item-top">
                <span class="term-memory-category">${esc(note?.category || 'note')}</span>
                <span class="term-memory-importance">${Number(note?.importance || 0).toFixed(2)}</span>
            </div>
            <div class="term-memory-content">${esc(note?.content || '')}</div>
            <div class="term-memory-meta">${esc(formatNoteTime(note?.timestamp))} · ${esc(note?.trigger || 'auto')}</div>
        </div>
    `).join('');
}

async function loadMemoryPanelSnapshot(options = {}) {
    const silent = Boolean(options?.silent);
    try {
        const query = String(memoryQuery || '').trim();
        const [statusData, notesData] = await Promise.all([
            apiRequest('/trion/memory/status', {}, 'Could not load memory status'),
            query
                ? apiRequest(`/trion/memory/recall?query=${encodeURIComponent(query)}&limit=25`, {}, 'Could not search memory')
                : apiRequest('/trion/memory/recent?limit=25', {}, 'Could not load recent memory'),
        ]);
        memoryStatusState = statusData || {};
        memoryNotes = Array.isArray(notesData?.notes) ? notesData.notes : [];
        renderMemoryPanel();
    } catch (e) {
        memoryStatusState = {
            home_status: 'offline',
            home_error_code: e?.error_code || '',
        };
        memoryNotes = [];
        renderMemoryPanel();
        if (!silent) {
            showToast(e.message || 'Could not refresh memory panel', 'error');
        }
    }
}

async function runMemorySearchFromInput() {
    const input = document.getElementById('term-memory-query');
    memoryQuery = String(input?.value || '').trim();
    await loadMemoryPanelSnapshot();
}

async function saveMemoryNoteFromUI() {
    const noteEl = document.getElementById('term-memory-note');
    const catEl = document.getElementById('term-memory-category');
    const content = String(noteEl?.value || '').trim();
    const category = String(catEl?.value || 'note').trim() || 'note';
    if (!content) {
        showToast('Memory note is empty', 'warn');
        return;
    }
    try {
        const payload = {
            content,
            category,
            importance: 0.86,
            trigger: 'manual_ui',
            context: 'webui:terminal',
            why: 'Captured from TRION Memory panel',
        };
        const data = await apiRequest(
            '/trion/memory/remember',
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            },
            'Could not store memory note',
        );
        if (data?.saved) {
            if (noteEl) noteEl.value = '';
            showToast('Memory note saved', 'success');
        } else {
            showToast('Note skipped by policy', 'warn');
        }
        await loadMemoryPanelSnapshot({ silent: true });
    } catch (e) {
        showToast(e.message || 'Could not store memory note', 'error');
    }
}

async function loadActivityFeedSnapshot() {
    try {
        const data = await apiRequest('/audit?limit=80', {}, 'Could not load audit log');
        const entries = Array.isArray(data?.entries) ? data.entries : [];
        const mapped = entries.map(mapAuditEntryToActivity);
        const liveOnly = activityFeed.filter(item => String(item.event || '').startsWith('approval_') || String(item.event || '').startsWith('deploy_'));
        activityFeed = [...liveOnly, ...mapped]
            .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
            .slice(0, 250);
        renderActivityFeed();
    } catch (e) {
        showToast(e.message || 'Could not refresh activity', 'error');
    }
}

function startActivityFeedPolling() {
    stopActivityFeedPolling();
    activityRefreshTimer = setInterval(() => {
        loadActivityFeedSnapshot();
        loadMemoryPanelSnapshot({ silent: true });
    }, 15000);
}

function stopActivityFeedPolling() {
    if (activityRefreshTimer) {
        clearInterval(activityRefreshTimer);
        activityRefreshTimer = null;
    }
}

function openActivityDetail(item) {
    const root = document.getElementById('term-activity-detail');
    if (!root || !item) return;
    activityDetailOpen = true;
    root.classList.add('visible');
    root.innerHTML = `
        <div class="term-activity-detail-backdrop" id="activity-detail-backdrop"></div>
        <div class="term-activity-detail-dialog">
            <div class="term-activity-detail-head">
                <h3>Audit Event</h3>
                <button class="term-btn-sm" id="activity-detail-close">✕</button>
            </div>
            <div class="term-activity-detail-grid">
                <div><strong>Time</strong><span>${esc(item.created_at || '')}</span></div>
                <div><strong>Level</strong><span>${esc(item.level || '')}</span></div>
                <div><strong>Event</strong><span>${esc(item.event || '')}</span></div>
                <div><strong>Blueprint</strong><span>${esc(item.blueprint_id || '-')}</span></div>
                <div><strong>Container</strong><span>${esc(item.container_id || '-')}</span></div>
                <div><strong>Message</strong><span>${esc(item.message || '-')}</span></div>
            </div>
        </div>
    `;
    document.getElementById('activity-detail-close')?.addEventListener('click', closeActivityDetail);
    document.getElementById('activity-detail-backdrop')?.addEventListener('click', closeActivityDetail);
}

function closeActivityDetail() {
    activityDetailOpen = false;
    const root = document.getElementById('term-activity-detail');
    if (!root) return;
    root.classList.remove('visible');
    root.innerHTML = '';
}

function logOutput(msg, cls = '') {
    // Write to xterm if available
    if (xterm && activeTab === 'logs') {
        const colorMap = { 'ansi-green': '\x1b[32m', 'ansi-red': '\x1b[31m', 'ansi-yellow': '\x1b[33m',
            'ansi-cyan': '\x1b[36m', 'ansi-dim': '\x1b[90m', 'ansi-bold': '\x1b[1m' };
        const code = colorMap[cls] || '';
        const reset = code ? '\x1b[0m' : '';
        xterm.writeln(`${code}${msg}${reset}`);
        return;
    }

    // Fallback to plain output
    const out = document.getElementById('log-output');
    if (!out) return;
    out.style.display = 'block';
    const line = document.createElement('div');
    line.className = cls;
    line.textContent = msg;
    out.appendChild(line);
    out.scrollTop = out.scrollHeight;

    // Highlight logs tab if not active
    if (activeTab !== 'logs') {
        const tab = document.querySelector('.term-tab[data-tab="logs"]');
        if (tab) tab.style.color = '#FFB302';
    }
}


// ═══════════════════════════════════════════════════════════
// DRAG & DROP (unchanged)
// ═══════════════════════════════════════════════════════════

function setupDropzone() {
    const zone = document.getElementById('bp-dropzone');
    const panel = document.getElementById('panel-blueprints');
    if (!zone || !panel) return;
    panel.addEventListener('dragover', (e) => { e.preventDefault(); zone.style.display = 'block'; zone.classList.add('dragover'); });
    panel.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    panel.addEventListener('drop', async (e) => {
        e.preventDefault(); zone.classList.remove('dragover'); zone.style.display = 'none';
        const file = e.dataTransfer?.files?.[0]; if (!file) return;
        const text = await file.text(); logOutput(`📄 Importing ${file.name}...`, 'ansi-cyan');
        try {
            const data = await apiRequest('/blueprints/import', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ yaml: text }) }, 'Could not import blueprint');
            if (data.imported) { logOutput(`✅ Imported "${data.blueprint?.id}"`, 'ansi-green'); await loadBlueprints(); }
            else logOutput(`❌ ${data.error}`, 'ansi-red');
        } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
    });
}

function showImportDialog() {
    const z = document.getElementById('bp-dropzone');
    if (z) z.style.display = z.style.display === 'none' ? 'block' : 'none';
}


// ═══════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════

function toApiErrorMessage(payload, fallbackMessage) {
    if (payload && typeof payload.error === 'string' && payload.error.trim()) return payload.error;
    if (payload && typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail;
    return fallbackMessage;
}

function toApiErrorHint(errorCode) {
    const code = String(errorCode || '').trim();
    if (!code) return '';
    const hints = {
        bad_request: 'Please check the entered values.',
        not_found: 'Verify ID or object still exists.',
        conflict: 'Resource conflict detected. Refresh and retry.',
        validation_error: 'One or more fields are invalid.',
        unauthorized: 'Permission is missing.',
        forbidden: 'Action is currently blocked by policy.',
        approval_failed: 'Approval was resolved, expired, or rejected.',
        snapshot_failed: 'Volume state prevented snapshot creation.',
        restore_failed: 'Snapshot restore could not be completed.',
        deploy_conflict: 'Deploy blocked by runtime or trust constraints.',
        healthcheck_timeout: 'Container did not become healthy in time and was auto-stopped.',
        healthcheck_unhealthy: 'Container failed healthcheck and was auto-stopped.',
        container_not_ready: 'Container exited before readiness and was auto-stopped.',
        policy_denied: 'Request blocked by TRION memory policy.',
        home_container_missing: 'TRION home container is not available.',
        home_container_not_running: 'TRION home container exists but is not running.',
        home_container_ambiguous: 'Multiple home containers detected. Resolve ambiguity first.',
        home_container_unavailable: 'Home memory is currently unavailable.',
    };
    return hints[code] || '';
}

function showToast(message, level = 'info') {
    const stack = document.getElementById('term-toast-stack');
    if (!stack || !message) return;
    stack.innerHTML = '';
    const toast = document.createElement('div');
    toast.className = `term-toast ${level}`;
    toast.textContent = String(message);
    stack.appendChild(toast);
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        stack.innerHTML = '';
    }, 3400);
}

async function apiRequest(path, options = {}, fallbackMessage = 'Request failed') {
    const response = await fetch(`${API}${path}`, options);

    let payload = {};
    try {
        payload = await response.json();
    } catch (_) {
        payload = {};
    }

    if (!response.ok) {
        const message = toApiErrorMessage(payload, fallbackMessage);
        const errorCode = payload && typeof payload.error_code === 'string' ? payload.error_code : '';
        const hint = toApiErrorHint(errorCode);
        const codePrefix = errorCode ? `[${errorCode}] ` : '';
        const composed = `${codePrefix}${message}${hint ? ` — ${hint}` : ''} (HTTP ${response.status})`;
        const err = new Error(composed);
        err.error_code = errorCode;
        err.status = response.status;
        err.details = payload && typeof payload.details === 'object' ? payload.details : {};
        throw err;
    }

    return payload;
}

function updateConnectionStatus(state) {
    const dot = document.getElementById('term-conn-dot');
    const label = document.getElementById('term-conn-label');
    if (state === 'connecting') {
        if (dot) dot.className = 'term-conn-dot connecting';
        if (label) label.textContent = 'Connecting...';
    } else {
        if (dot) dot.className = `term-conn-dot ${state ? 'connected' : 'disconnected'}`;
        if (label) label.textContent = state ? 'Connected' : 'Offline';
    }
}

function renderEmpty(icon, title, sub) {
    return `<div class="term-empty"><div class="term-empty-icon">${icon}</div><p>${title}</p><small>${sub}</small></div>`;
}

function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }


// ── Start ────────────────────────────────────────────────
// Don't auto-init — shell.js calls init() on demand
