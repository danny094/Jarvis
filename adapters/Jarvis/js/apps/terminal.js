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

const API = `http://${window.location.hostname}:8200/api/commander`;
const WS_URL = `ws://${window.location.hostname}:8200/api/commander/ws`;

// ── State ────────────────────────────────────────────────
let activeTab = 'blueprints';
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

// ── Init ─────────────────────────────────────────────────
export async function init() {
    const root = document.getElementById('app-terminal');
    if (!root) return;

    root.innerHTML = buildHTML();
    bindEvents();
    connectWebSocket();
    await switchTab('blueprints');
    pollApprovals();
}

// ── HTML Structure ───────────────────────────────────────
function buildHTML() {
    return `
    <div class="term-container">
        <!-- Header -->
        <div class="term-header">
            <h2><span class="term-icon">⬡</span> Container Commander</h2>
            <div class="term-header-actions">
                <div class="term-conn-status">
                    <span class="term-conn-dot disconnected" id="term-conn-dot"></span>
                    <span class="term-conn-label" id="term-conn-label">Offline</span>
                </div>
            </div>
        </div>

        <!-- Tabs -->
        <div class="term-tabs">
            <button class="term-tab active" data-tab="blueprints">
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

        <!-- Panels -->
        <div class="term-panel active" id="panel-blueprints">
            <div class="bp-list" id="bp-list"></div>
            <div class="bp-editor" id="bp-editor"></div>
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
            <div class="term-footer">
                <div class="term-footer-left">
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
            <!-- xterm.js container -->
            <div class="term-xterm-container" id="xterm-container"></div>
            <!-- Fallback plain output -->
            <div class="term-output-plain" id="log-output" style="display:none">Waiting for log data...</div>
            <!-- Input bar with autocomplete -->
            <div class="term-input-bar">
                <span class="term-prompt">trion&gt;</span>
                <input class="term-input" id="term-cmd-input" type="text"
                       placeholder="Type a command... (Tab for autocomplete)" autocomplete="off" />
                <button class="term-send-btn" id="term-send-btn">↵</button>
                <!-- Autocomplete dropdown -->
                <div class="term-autocomplete" id="term-autocomplete" style="display:none"></div>
            </div>
        </div>
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
            // Write to xterm if available, otherwise fallback
            if (xterm) {
                xterm.write(msg.data);
            } else {
                logOutput(msg.data.trimEnd(), '');
            }
            break;

        case 'event':
            handleEvent(msg);
            break;

        case 'error':
            logOutput(`❌ ${msg.message}`, 'ansi-red');
            break;

        case 'exit':
            logOutput(`⏹ Container ${msg.container_id?.slice(0,12)} exited (code: ${msg.exit_code})`, 'ansi-yellow');
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

    if (event === 'container_started') {
        logOutput(`▶ Container started: ${msg.container_id?.slice(0,12)} (${msg.blueprint_id})`, 'ansi-green');
        loadContainers();
        // Auto-focus: switch to logs tab and attach
        autoFocusContainer(msg.container_id);

    } else if (event === 'container_stopped') {
        logOutput(`⏹ Container stopped: ${msg.container_id?.slice(0,12)}`, 'ansi-yellow');
        if (attachedContainer === msg.container_id) attachedContainer = null;
        loadContainers();

    } else if (event === 'approval_needed') {
        showApprovalBanner(msg.approval_id, msg.reason, msg.blueprint_id);

    } else if (event === 'attached') {
        logOutput(`🔗 Attached to ${msg.container_id?.slice(0,12)}`, 'ansi-cyan');
    }
}

function wsSend(msg) {
    if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify(msg));
    }
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

    // Init xterm if not yet done
    initXterm();

    // Attach to the new container
    attachedContainer = containerId;
    wsSend({ type: 'attach', container_id: containerId });

    if (xterm) {
        xterm.writeln(`\x1b[32m▶ Auto-attached to ${containerId.slice(0,12)}\x1b[0m`);
        xterm.focus();
    }
}


// ═══════════════════════════════════════════════════════════
// APPROVAL DIALOG
// ═══════════════════════════════════════════════════════════

let currentApprovalId = null;
let approvalPollTimer = null;

function showApprovalBanner(approvalId, reason, blueprintId) {
    currentApprovalId = approvalId;
    const banner = document.getElementById('approval-banner');
    if (!banner) return;

    document.getElementById('approval-reason').textContent = reason;
    document.getElementById('approval-bp-id').textContent = blueprintId ? `(${blueprintId})` : '';
    banner.style.display = 'flex';

    // TTL countdown
    let ttl = 300;
    const ttlEl = document.getElementById('approval-ttl');
    const timer = setInterval(() => {
        ttl--;
        if (ttlEl) ttlEl.textContent = `${ttl}s`;
        if (ttl <= 0) {
            clearInterval(timer);
            hideApprovalBanner();
            logOutput('⏰ Approval expired', 'ansi-yellow');
        }
    }, 1000);
}

function hideApprovalBanner() {
    const banner = document.getElementById('approval-banner');
    if (banner) banner.style.display = 'none';
    currentApprovalId = null;
}

async function approveRequest() {
    if (!currentApprovalId) return;
    try {
        const res = await fetch(`${API}/approvals/${currentApprovalId}/approve`, { method: 'POST' });
        const data = await res.json();
        if (data.approved) {
            logOutput('✅ Approved — container starting...', 'ansi-green');
        } else {
            logOutput(`❌ Approve failed: ${data.error || 'Unknown'}`, 'ansi-red');
        }
    } catch (e) {
        logOutput(`❌ Approve error: ${e.message}`, 'ansi-red');
    }
    hideApprovalBanner();
}

async function rejectRequest() {
    if (!currentApprovalId) return;
    try {
        await fetch(`${API}/approvals/${currentApprovalId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: 'User rejected' }),
        });
        logOutput('✖ Rejected', 'ansi-yellow');
    } catch (e) {
        logOutput(`❌ Reject error: ${e.message}`, 'ansi-red');
    }
    hideApprovalBanner();
}

async function pollApprovals() {
    // Check for pending approvals every 5 seconds
    try {
        const res = await fetch(`${API}/approvals`);
        const data = await res.json();
        if (data.approvals?.length > 0 && !currentApprovalId) {
            const a = data.approvals[0];
            showApprovalBanner(a.id, a.reason, a.blueprint_id);
        }
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

    // Approval buttons
    document.getElementById('approval-approve')?.addEventListener('click', approveRequest);
    document.getElementById('approval-reject')?.addEventListener('click', rejectRequest);

    // Drag & Drop
    setupDropzone();
}


// ═══════════════════════════════════════════════════════════
// CLI INPUT + AUTOCOMPLETE
// ═══════════════════════════════════════════════════════════

const CLI_COMMANDS = [
    { cmd: 'help', desc: 'Show available commands' },
    { cmd: 'list', desc: 'List blueprints' },
    { cmd: 'deploy', desc: 'Deploy a blueprint: deploy <id>' },
    { cmd: 'stop', desc: 'Stop a container: stop <id>' },
    { cmd: 'attach', desc: 'Attach to container: attach <id>' },
    { cmd: 'detach', desc: 'Detach from current container' },
    { cmd: 'exec', desc: 'Run command: exec <container> <cmd>' },
    { cmd: 'logs', desc: 'Show container logs: logs <id>' },
    { cmd: 'stats', desc: 'Show container stats: stats <id>' },
    { cmd: 'secrets', desc: 'List secrets' },
    { cmd: 'volumes', desc: 'List workspace volumes' },
    { cmd: 'snapshot', desc: 'Create snapshot: snapshot <volume>' },
    { cmd: 'quota', desc: 'Show resource quota' },
    { cmd: 'audit', desc: 'Show audit log' },
    { cmd: 'clear', desc: 'Clear terminal output' },
    { cmd: 'cleanup', desc: 'Stop all containers' },
];

function handleInputKeydown(e) {
    const input = e.target;
    const val = input.value;

    if (e.key === 'Enter') {
        e.preventDefault();
        hideAutocomplete();
        handleCommand(val.trim());
        cmdHistory.unshift(val.trim());
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

    if (parts.length === 1) {
        // Autocomplete command name
        matches = CLI_COMMANDS.filter(c => c.cmd.startsWith(first) && c.cmd !== first);
    } else if (parts.length === 2 && ['deploy', 'attach', 'stop', 'logs', 'stats', 'exec'].includes(first)) {
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
        `<div class="term-ac-item" data-value="${m.cmd}">
            <span class="term-ac-cmd">${m.cmd}</span>
            <span class="term-ac-desc">${m.desc || ''}</span>
        </div>`
    ).join('');

    dropdown.style.display = 'block';

    // Click handler
    dropdown.querySelectorAll('.term-ac-item').forEach(item => {
        item.addEventListener('click', () => {
            const input = document.getElementById('term-cmd-input');
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


// ═══════════════════════════════════════════════════════════
// COMMAND HANDLER (enhanced)
// ═══════════════════════════════════════════════════════════

async function handleCommand(cmd) {
    const input = document.getElementById('term-cmd-input');
    if (!cmd) return;
    if (input) input.value = '';

    logOutput(`trion> ${cmd}`, 'ansi-bold');

    const parts = cmd.split(/\s+/);
    const action = parts[0]?.toLowerCase();

    switch (action) {
        case 'help':
            logOutput('Available commands:', 'ansi-cyan');
            CLI_COMMANDS.forEach(c => logOutput(`  ${c.cmd.padEnd(12)} ${c.desc}`, 'ansi-dim'));
            break;

        case 'list':
            await loadBlueprints();
            blueprints.forEach(bp => logOutput(`  ${bp.icon} ${bp.id} — ${bp.name}`, 'ansi-dim'));
            break;

        case 'deploy':
            if (parts[1]) await window.termDeployBp(parts[1]);
            else logOutput('Usage: deploy <blueprint_id>', 'ansi-yellow');
            break;

        case 'stop':
            if (parts[1]) await window.termStopCt(parts[1]);
            else logOutput('Usage: stop <container_id>', 'ansi-yellow');
            break;

        case 'attach':
            if (parts[1]) {
                attachedContainer = parts[1];
                wsSend({ type: 'attach', container_id: parts[1] });
                initXterm();
            } else logOutput('Usage: attach <container_id>', 'ansi-yellow');
            break;

        case 'detach':
            wsSend({ type: 'detach' });
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
                    const res = await fetch(`${API}/containers/${parts[1]}/logs?tail=50`);
                    const data = await res.json();
                    logOutput(data.logs || 'No logs', '');
                } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            } else logOutput('Usage: logs <container_id>', 'ansi-yellow');
            break;

        case 'stats':
            if (parts[1]) {
                try {
                    const res = await fetch(`${API}/containers/${parts[1]}/stats`);
                    const s = await res.json();
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
                const res = await fetch(`${API}/volumes`);
                const data = await res.json();
                if (data.volumes?.length) {
                    data.volumes.forEach(v => logOutput(`  💾 ${v.name} (${v.blueprint_id}) — ${v.created_at}`, 'ansi-dim'));
                } else logOutput('No volumes found', 'ansi-dim');
            } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            break;

        case 'snapshot':
            if (parts[1]) {
                logOutput(`📸 Creating snapshot of ${parts[1]}...`, 'ansi-cyan');
                try {
                    const res = await fetch(`${API}/snapshots/create`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ volume_name: parts[1], tag: parts[2] || '' })
                    });
                    const data = await res.json();
                    logOutput(data.created ? `✅ Snapshot: ${data.filename}` : `❌ ${data.error}`, data.created ? 'ansi-green' : 'ansi-red');
                } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            } else logOutput('Usage: snapshot <volume_name> [tag]', 'ansi-yellow');
            break;

        case 'quota':
            try {
                const res = await fetch(`${API}/quota`);
                const q = await res.json();
                logOutput(`Containers: ${q.containers_used}/${q.max_containers} | RAM: ${q.memory_used_mb}/${q.max_total_memory_mb} MB | CPU: ${q.cpu_used}/${q.max_total_cpu}`, 'ansi-cyan');
            } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
            break;

        case 'audit':
            await loadAuditLog();
            break;

        case 'clear':
            if (xterm) xterm.clear();
            document.getElementById('log-output').innerHTML = '';
            break;

        case 'cleanup':
            logOutput('🧹 Stopping all containers...', 'ansi-yellow');
            try {
                await fetch(`${API}/cleanup`, { method: 'POST' });
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

    if (tab === 'blueprints') await loadBlueprints();
    else if (tab === 'containers') { await loadContainers(); await loadQuota(); }
    else if (tab === 'vault') await loadSecrets();
    else if (tab === 'logs') { initXterm(); await loadAuditLog(); }
}


// ═══════════════════════════════════════════════════════════
// BLUEPRINTS (unchanged from Phase 1)
// ═══════════════════════════════════════════════════════════

async function loadBlueprints() {
    try {
        const res = await fetch(`${API}/blueprints`);
        const data = await res.json();
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
    list.innerHTML = blueprints.map(bp => `
        <div class="bp-card" data-id="${bp.id}">
            <div class="bp-card-top">
                <div class="bp-card-title">
                    <span class="bp-emoji">${bp.icon || '📦'}</span>
                    <div><h3>${esc(bp.name)}</h3><span class="bp-id">${esc(bp.id)}</span></div>
                </div>
                <div class="bp-card-actions">
                    <button class="bp-action-btn" onclick="termEditBp('${bp.id}')">✏️</button>
                    <button class="bp-action-btn" onclick="termExportBp('${bp.id}')">📤</button>
                    <button class="bp-action-btn danger" onclick="termDeleteBp('${bp.id}')">🗑️</button>
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

function showBlueprintEditor(bp = null) {
    editingBp = bp;
    const editor = document.getElementById('bp-editor');
    editor.innerHTML = `
        <div class="bp-editor-title">${bp ? '✏️ Edit' : '📦 New'} Blueprint</div>
        <div class="bp-editor-row">
            <div style="flex:1"><label>ID</label><input id="bp-ed-id" value="${bp?.id || ''}" ${bp ? 'disabled' : ''} placeholder="python-sandbox" /></div>
            <div style="flex:1"><label>Name</label><input id="bp-ed-name" value="${esc(bp?.name || '')}" placeholder="Python Sandbox" /></div>
            <div style="width:60px"><label>Icon</label><input id="bp-ed-icon" value="${bp?.icon || '📦'}" style="text-align:center" /></div>
        </div>
        <div class="bp-editor-row"><div style="flex:1"><label>Description</label><input id="bp-ed-desc" value="${esc(bp?.description || '')}" /></div></div>
        <div class="bp-editor-row"><div style="flex:1"><label>Dockerfile</label><textarea id="bp-ed-dockerfile">${esc(bp?.dockerfile || '')}</textarea></div></div>
        <div class="bp-editor-row"><div style="flex:1"><label>System Prompt</label><textarea id="bp-ed-prompt">${esc(bp?.system_prompt || '')}</textarea></div></div>
        <label style="font-size:10px;color:#666;text-transform:uppercase;font-weight:600;letter-spacing:0.5px;margin-bottom:6px;display:block">Resource Limits</label>
        <div class="bp-editor-limits">
            <div class="bp-limit-group"><label>CPU</label><input id="bp-ed-cpu" value="${bp?.resources?.cpu_limit || '1.0'}" /></div>
            <div class="bp-limit-group"><label>RAM</label><input id="bp-ed-ram" value="${bp?.resources?.memory_limit || '512m'}" /></div>
            <div class="bp-limit-group"><label>TTL (s)</label><input id="bp-ed-ttl" value="${bp?.resources?.timeout_seconds || 300}" type="number" /></div>
        </div>
        <div class="bp-editor-row">
            <div style="flex:1"><label>Network</label>
                <select id="bp-ed-network">
                    <option value="none" ${bp?.network==='none'?'selected':''}>None</option>
                    <option value="internal" ${(!bp?.network||bp?.network==='internal')?'selected':''}>Internal</option>
                    <option value="bridge" ${bp?.network==='bridge'?'selected':''}>Bridge</option>
                    <option value="full" ${bp?.network==='full'?'selected':''}>Full (Internet)</option>
                </select></div>
            <div style="flex:1"><label>Tags</label><input id="bp-ed-tags" value="${(bp?.tags||[]).join(', ')}" /></div>
            <div style="flex:1"><label>Extends</label><input id="bp-ed-extends" value="${bp?.extends || ''}" /></div>
        </div>
        <div class="bp-editor-footer">
            <button class="proto-btn-cancel" onclick="document.getElementById('bp-editor').classList.remove('visible')">Cancel</button>
            <button class="proto-btn-save" onclick="termSaveBp()">💾 Save</button>
        </div>`;
    editor.classList.add('visible');
}

// Global handlers
window.termSaveBp = async function() {
    const data = {
        id: document.getElementById('bp-ed-id')?.value.trim(),
        name: document.getElementById('bp-ed-name')?.value.trim(),
        description: document.getElementById('bp-ed-desc')?.value.trim(),
        dockerfile: document.getElementById('bp-ed-dockerfile')?.value,
        system_prompt: document.getElementById('bp-ed-prompt')?.value,
        icon: document.getElementById('bp-ed-icon')?.value || '📦',
        extends: document.getElementById('bp-ed-extends')?.value.trim() || null,
        network: document.getElementById('bp-ed-network')?.value || 'internal',
        tags: (document.getElementById('bp-ed-tags')?.value || '').split(',').map(t => t.trim()).filter(Boolean),
        resources: {
            cpu_limit: document.getElementById('bp-ed-cpu')?.value || '1.0',
            memory_limit: document.getElementById('bp-ed-ram')?.value || '512m',
            timeout_seconds: parseInt(document.getElementById('bp-ed-ttl')?.value) || 300,
        }
    };
    if (!data.id || !data.name) { logOutput('⚠️ ID and Name required', 'ansi-yellow'); return; }
    try {
        const method = editingBp ? 'PUT' : 'POST';
        const url = editingBp ? `${API}/blueprints/${data.id}` : `${API}/blueprints`;
        const res = await fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
        const result = await res.json();
        if (result.created || result.updated) {
            logOutput(`✅ Blueprint "${data.id}" ${editingBp ? 'updated' : 'created'}`, 'ansi-green');
            document.getElementById('bp-editor')?.classList.remove('visible');
            await loadBlueprints();
        } else logOutput(`❌ ${result.error || 'Unknown'}`, 'ansi-red');
    } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
};

window.termDeleteBp = async function(id) {
    if (!confirm(`Delete blueprint "${id}"?`)) return;
    await fetch(`${API}/blueprints/${id}`, { method: 'DELETE' });
    logOutput(`🗑️ "${id}" deleted`, 'ansi-yellow'); await loadBlueprints();
};
window.termEditBp = async function(id) { const bp = blueprints.find(b => b.id === id); if (bp) showBlueprintEditor(bp); };
window.termExportBp = async function(id) {
    try { const res = await fetch(`${API}/blueprints/${id}/yaml`); const data = await res.json();
        logOutput(`📤 YAML:\n${data.yaml}`, 'ansi-cyan'); switchTab('logs');
    } catch(e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
};
window.termDeployBp = async function(id) {
    logOutput(`▶ Deploying "${id}"...`, 'ansi-yellow');
    try {
        const res = await fetch(`${API}/containers/deploy`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ blueprint_id: id })
        });
        const data = await res.json();
        if (data.deployed) {
            logOutput(`✅ Container started: ${data.container?.container_id?.slice(0,12)}`, 'ansi-green');
            autoFocusContainer(data.container.container_id);
        } else if (data.pending_approval) {
            showApprovalBanner(data.approval_id, data.reason, id);
            logOutput(`⚠️ Approval required: ${data.reason}`, 'ansi-yellow');
        } else logOutput(`ℹ️ ${data.error || data.note || 'Unknown'}`, 'ansi-dim');
    } catch (e) { logOutput(`❌ ${e.message}`, 'ansi-red'); }
};


// ═══════════════════════════════════════════════════════════
// CONTAINERS
// ═══════════════════════════════════════════════════════════

async function loadContainers() {
    try {
        const res = await fetch(`${API}/containers`);
        const data = await res.json();
        containers = data.containers || [];
        document.getElementById('ct-count').textContent = containers.length;
        renderContainers();
    } catch (e) {
        document.getElementById('ct-list').innerHTML = renderEmpty('🔄', 'No containers running', 'Deploy a blueprint');
    }
}

function renderContainers() {
    const list = document.getElementById('ct-list');
    if (!containers.length) { list.innerHTML = renderEmpty('🔄', 'No containers running', 'Deploy a blueprint'); return; }
    list.innerHTML = containers.map(ct => `
        <div class="ct-row">
            <div class="ct-row-status"><span class="bp-status-dot ${ct.status}"></span></div>
            <div class="ct-row-info">
                <div class="ct-row-name">${esc(ct.name)}</div>
                <div class="ct-row-detail">${ct.container_id?.slice(0,12)} · ${ct.blueprint_id}</div>
            </div>
            <div class="ct-row-stats">
                <div class="ct-stat"><div class="ct-stat-val">${ct.cpu_percent?.toFixed(1)}%</div><div class="ct-stat-label">CPU</div></div>
                <div class="ct-stat"><div class="ct-stat-val">${ct.memory_mb?.toFixed(0)}M</div><div class="ct-stat-label">RAM</div></div>
            </div>
            <div class="ct-row-actions">
                <button class="term-btn-sm" onclick="termAttachCt('${ct.container_id}')">🔗</button>
                <button class="term-btn-sm" onclick="termStopCt('${ct.container_id}')">⏹</button>
            </div>
        </div>
    `).join('');
}

async function loadQuota() {
    try {
        const res = await fetch(`${API}/quota`);
        const q = await res.json();
        const pct = (q.containers_used / q.max_containers) * 100;
        const fill = document.getElementById('quota-fill');
        if (fill) fill.style.width = `${pct}%`;
        const text = document.getElementById('ct-quota-text');
        if (text) text.textContent = `${q.containers_used}/${q.max_containers} Container · ${q.memory_used_mb}/${q.max_total_memory_mb} MB`;
    } catch (e) { /* silent */ }
}

window.termStopCt = async function(id) {
    await fetch(`${API}/containers/${id}/stop`, { method: 'POST' });
    logOutput(`⏹ Stopped ${id.slice(0,12)}`, 'ansi-yellow'); await loadContainers();
};
window.termAttachCt = function(id) {
    attachedContainer = id;
    wsSend({ type: 'attach', container_id: id });
    switchTab('logs'); initXterm();
    logOutput(`🔗 Attached to ${id.slice(0,12)}`, 'ansi-cyan');
};


// ═══════════════════════════════════════════════════════════
// VAULT (unchanged)
// ═══════════════════════════════════════════════════════════

async function loadSecrets() {
    try {
        const res = await fetch(`${API}/secrets`);
        const data = await res.json();
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
        const res = await fetch(`${API}/secrets`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name, value, scope, blueprint_id: bpId }) });
        const data = await res.json();
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
    let url = `${API}/secrets/${name}?scope=${scope}`; if (bpId) url += `&blueprint_id=${bpId}`;
    await fetch(url, { method: 'DELETE' }); logOutput(`🗑️ "${name}" deleted`, 'ansi-yellow'); await loadSecrets();
};


// ═══════════════════════════════════════════════════════════
// LOGS / OUTPUT
// ═══════════════════════════════════════════════════════════

async function loadAuditLog() {
    try {
        const res = await fetch(`${API}/audit`);
        const data = await res.json();
        if (data.entries?.length) {
            data.entries.forEach(e => logOutput(`[${e.created_at}] ${e.action} — ${e.blueprint_id} ${e.details||''}`, 'ansi-dim'));
        }
    } catch (e) { /* silent */ }
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
            const res = await fetch(`${API}/blueprints/import`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ yaml: text }) });
            const data = await res.json();
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
