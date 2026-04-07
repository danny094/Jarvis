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
import {
    API,
    CLI_COMMANDS,
    COMMAND_GROUPS,
    WS_URL,
    buildBlueprintPreset,
} from "./terminal/config.js?v=20260322p";
import {
    downloadText,
    esc,
    normalizeTerminalOutput,
    renderEmpty,
    stripAnsi,
    toApiErrorHint,
    toApiErrorMessage,
} from "./terminal/helpers.js?v=20260322m";
// Keep this query in sync with shell.js terminal module version when template structure changes.
import { buildTerminalHTML } from "./terminal/template.js?v=20260322q";
import { createApprovalController } from "./terminal/approval.js";
import { createBlueprintsController } from "./terminal/blueprints.js";
import { createSimpleWizardController } from "./terminal/blueprint-simple.js";
import { createCommandInputController } from "./terminal/command-input.js?v=20260322q";
import { createContainersController } from "./terminal/containers.js?v=20260322q";
import { createDashboardController } from "./terminal/dashboard.js";
import { createWebSocketController } from "./terminal/websocket.js?v=20260322q";
import { createXtermController } from "./terminal/xterm.js?v=20260322q";

// Compatibility note:
// Readiness/deploy_failed UI handling lives in split terminal modules now.
// Keep these markers visible in terminal.js for source-contract tests:
// healthcheck_timeout
// healthcheck_unhealthy
// container_not_ready
// healthcheck_timeout_auto_stopped
// event === 'deploy_failed'

// HTML contract markers (DOM elements defined in template.js):
// id="approval-center" id="approval-center-btn" id="approval-center-context"
// data-approval-tab="pending" data-approval-tab="history"
// class="bp-preflight-trust" approval-batch-approve
// data-log-mode="logs" data-log-mode="shell"
// id="term-activity-feed" id="term-activity-list"
// data-tab="dashboard" id="panel-dashboard" id="dash-kpis"
// id="dash-timeline" id="dash-recent-blueprints"
// class="bp-preset-btn" data-preset="python"
// id="term-command-palette" id="term-history-filter"
// id="term-memory-status" id="term-memory-list" id="term-memory-query"
// id="bp-preflight" id="pf-storage-path" id="pf-devices"

// WS stream routing (lives in websocket.js):
// if (stream === 'logs') → appendLogStream(data);
// if (stream === 'shell') → appendShellStream(data);

// Slash command routing (lives in command-input.js):
// if (parts.length === 1 && first.startsWith('/'))

// Memory WS events (lives in websocket.js):
// event === 'memory_saved' || event === 'memory_skipped' || event === 'memory_denied'

// ── State ────────────────────────────────────────────────
let activeTab = 'dashboard';
let blueprints = [];
let containers = [];
let secrets = [];
let attachedContainer = null;
let toastTimer = null;
let logPanelMode = 'logs';
let logStreamBuffer = [];
let shellFallbackBuffer = [];
let activityFeed = [];
let activityRefreshTimer = null;
let memoryStatusState = null;
let memoryNotes = [];
let memoryQuery = '';
let activityDetailOpen = false;
let globalTerminalEventsBound = false;
let logAutoScrollEnabled = true;
let shellTranscriptBuffer = [];
let trionShellState = {
    active: false,
    containerId: '',
    language: 'en',
};
let trionShellAddonDocs = [];

function setContainersState(value) {
    containers = Array.isArray(value) ? value : [];
    updateLogContainerOptions();
}

function setAttachedContainerState(value) {
    const nextValue = value || null;
    if (attachedContainer && nextValue && attachedContainer !== nextValue) {
        shellTranscriptBuffer = [];
        shellFallbackBuffer = [];
        trionShellAddonDocs = [];
    }
    attachedContainer = nextValue;
    syncActiveLogContainerSelection();
    renderTrionShellAddonDocs();
}

const approvalController = createApprovalController({
    apiRequest: (...args) => apiRequest(...args),
    esc,
    getActiveTab: () => activeTab,
    loadContainers: () => loadContainers(),
    loadDashboard: () => loadDashboard(),
    logOutput: (...args) => logOutput(...args),
    renderDashboard: () => renderDashboard(),
    showToast: (...args) => showToast(...args),
});

const xtermController = createXtermController({
    esc,
    getAttachedContainer: () => attachedContainer,
    getLogPanelMode: () => logPanelMode,
    isTrionShellActive: () => Boolean(trionShellState.active),
    setAttachedContainer: (value) => setAttachedContainerState(value),
    setLogPanelMode: (value) => setLogPanelMode(value),
    showToast: (...args) => showToast(...args),
    switchTab: (value) => switchTab(value),
    wsSend: (msg) => websocketController.wsSend(msg),
});

const websocketController = createWebSocketController({
    appendLogStream: (data) => appendLogStream(data),
    appendShellStream: (data) => appendShellStream(data),
    autoFocusContainer: (containerId) => autoFocusContainer(containerId),
    getAttachedContainer: () => attachedContainer,
    getTrionShellState: () => ({ ...trionShellState }),
    hideApprovalBanner: () => hideApprovalBanner(),
    loadContainers: () => loadContainers(),
    loadMemoryPanelSnapshot: (options) => loadMemoryPanelSnapshot(options),
    logOutput: (...args) => logOutput(...args),
    pushActivity: (entry) => pushActivity(entry),
    refreshApprovalCenter: () => refreshApprovalCenter(),
    removeShellSession: (containerId) => removeShellSession(containerId),
    setAttachedContainer: (value) => setAttachedContainerState(value),
    setTrionShellMode: (nextState) => setTrionShellModeState(nextState),
    showApprovalBanner: (...args) => showApprovalBanner(...args),
    showToast: (...args) => showToast(...args),
    updateConnectionStatus: (...args) => updateConnectionStatus(...args),
    wsUrl: WS_URL,
});

const commandInputController = createCommandInputController({
    addShellSession: (containerId) => addShellSession(containerId),
    apiRequest: (...args) => apiRequest(...args),
    cliCommands: CLI_COMMANDS,
    clearTerminal: () => clearTerminal(),
    commandGroups: COMMAND_GROUPS,
    downloadText,
    esc,
    getActivityFeed: () => activityFeed,
    getAttachedContainer: () => attachedContainer,
    getBlueprints: () => blueprints,
    getContainers: () => containers,
    getSecrets: () => secrets,
    initXterm: () => initXterm(),
    loadActivityFeedSnapshot: () => loadActivityFeedSnapshot(),
    loadAuditLog: () => loadAuditLog(),
    loadBlueprints: () => loadBlueprints(),
    loadContainers: () => loadContainers(),
    loadSecrets: () => loadSecrets(),
    logOutput: (...args) => logOutput(...args),
    getShellTranscriptTail: (maxChars) => getShellTranscriptTail(maxChars),
    getTrionShellState: () => ({ ...trionShellState }),
    getUiLanguage: () => getUiLanguage(),
    refreshVolumeManager: () => refreshVolumeManager(),
    rememberRecent: (key, value) => rememberRecent(key, value),
    removeShellSession: (containerId) => removeShellSession(containerId),
    setAttachedContainer: (value) => setAttachedContainerState(value),
    setLogPanelMode: (value) => setLogPanelMode(value),
    setTrionAddonDocs: (docs) => setTrionShellAddonDocsState(docs),
    setTrionShellMode: (nextState) => setTrionShellModeState(nextState),
    showToast: (...args) => showToast(...args),
    stripAnsi,
    switchTab: (value) => switchTab(value),
    wsSend: (msg) => wsSend(msg),
});

const dashboardController = createDashboardController({
    apiRequest: (...args) => apiRequest(...args),
    esc,
    getContainers: () => containers,
    getPendingApprovals: () => approvalController.getPendingApprovals(),
    openActivityDetail: (item) => openActivityDetail(item),
    renderEmpty,
    setContainers: (value) => setContainersState(value),
    setPendingApprovals: (value) => approvalController.setPendingApprovals(value),
    toActivityLevel: (value) => toActivityLevel(value),
});

const blueprintsController = createBlueprintsController({
    apiRequest: (...args) => apiRequest(...args),
    autoFocusContainer: (containerId) => autoFocusContainer(containerId),
    downloadText,
    esc,
    getActiveTab: () => activeTab,
    getApiBase: () => getApiBase(),
    getBlueprints: () => blueprints,
    loadContainers: () => loadContainers(),
    loadDashboard: () => loadDashboard(),
    logOutput: (...args) => logOutput(...args),
    rememberRecent: (key, value) => rememberRecent(key, value),
    renderEmpty,
    setBlueprints: (value) => {
        blueprints = Array.isArray(value) ? value : [];
    },
    showApprovalBanner: (...args) => showApprovalBanner(...args),
    showToast: (...args) => showToast(...args),
    suggestFix: (message) => suggestFix(message),
    switchTab: (tab) => switchTab(tab),
    updateConnectionStatus: (state) => updateConnectionStatus(state),
});

const containersController = createContainersController({
    apiRequest: (...args) => apiRequest(...args),
    autoFocusContainer: (containerId) => autoFocusContainer(containerId),
    deployBlueprint: (blueprintId) => deployBlueprint(blueprintId),
    esc,
    getActiveTab: () => activeTab,
    getContainers: () => containers,
    loadDashboard: () => loadDashboard(),
    logOutput: (...args) => logOutput(...args),
    rememberRecent: (key, value) => rememberRecent(key, value),
    renderEmpty,
    setContainers: (value) => setContainersState(value),
    showToast: (...args) => showToast(...args),
});

// ── Init ─────────────────────────────────────────────────
export async function init() {
    const root = document.getElementById('app-terminal');
    if (!root) return;

    root.innerHTML = buildTerminalHTML();
    bindEvents();
    connectWebSocket();
    await switchTab(activeTab || 'dashboard');
    approvalController.registerWindowHandlers();
    blueprintsController.registerWindowHandlers();
    containersController.registerWindowHandlers();
    approvalController.ensurePolling();
}

export async function remount() {
    const root = document.getElementById('app-terminal');
    if (!root) return;

    xtermController.disposeXterm();
    root.innerHTML = buildTerminalHTML();
    bindEvents();
    approvalController.registerWindowHandlers();
    blueprintsController.registerWindowHandlers();
    containersController.registerWindowHandlers();
    approvalController.ensurePolling();
    await switchTab(activeTab || 'dashboard');
}


// ═══════════════════════════════════════════════════════════
// WEBSOCKET
// ═══════════════════════════════════════════════════════════

function connectWebSocket() {
    websocketController.connectWebSocket();
}

function handleWsMessage(msg) {
    websocketController.handleWsMessage(msg);
}

function handleEvent(msg) {
    websocketController.handleEvent(msg);
}

function wsSend(msg) {
    websocketController.wsSend(msg);
}

function routeStreamOutput(msg) {
    websocketController.routeStreamOutput(msg);
}

function setLogPanelMode(mode) {
    logPanelMode = mode === 'shell' ? 'shell' : 'logs';
    document.querySelectorAll('.term-log-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.logMode === logPanelMode);
    });
    document.querySelectorAll('.term-log-mode-panel').forEach(panel => {
        const shouldShow = panel.id === `log-mode-${logPanelMode}`;
        panel.classList.toggle('active', shouldShow);
    });
    if (logPanelMode === 'shell') {
        initXterm();
        scheduleXtermFit();
        renderShellSessions();
        xtermController.focusTerminal();
    }
}

function appendToOutput(elId, chunk, maxChars = 160000) {
    const target = document.getElementById(elId);
    if (!target) return;
    if (/^Waiting for (log stream|shell data)\.\.\.$/.test(String(target.textContent || '').trim())) {
        target.textContent = '';
    }
    target.textContent += chunk;
    if (target.textContent.length > maxChars) {
        target.textContent = target.textContent.slice(-maxChars);
    }
    if (elId !== 'log-stream-output' || logAutoScrollEnabled) {
        target.scrollTop = target.scrollHeight;
    }
}

function appendLogStream(data) {
    if (!data) return;
    const normalized = normalizeTerminalOutput(data);
    logStreamBuffer.push(normalized);
    if (logStreamBuffer.length > 800) logStreamBuffer = logStreamBuffer.slice(-800);
    appendToOutput('log-stream-output', normalized);
    if (activeTab !== 'logs' || logPanelMode !== 'logs') {
        const tab = document.querySelector('.term-tab[data-tab="logs"]');
        if (tab) tab.style.color = '#FFB302';
    }
}

function appendShellStream(data) {
    if (!data) return;
    const normalized = normalizeTerminalOutput(data);
    shellTranscriptBuffer.push(normalized);
    if (shellTranscriptBuffer.length > 1200) shellTranscriptBuffer = shellTranscriptBuffer.slice(-1200);
    if (xtermController.writeShellData(data)) {
        return;
    }
    shellFallbackBuffer.push(normalized);
    if (shellFallbackBuffer.length > 800) shellFallbackBuffer = shellFallbackBuffer.slice(-800);
    appendToOutput('log-output', normalized);
}

function getUiLanguage() {
    const htmlLang = String(document.documentElement?.lang || '').trim();
    if (htmlLang) return htmlLang;
    return String(window.navigator?.language || '').trim() || 'en';
}

function getShellTranscriptTail(maxChars = 12000) {
    const joined = shellTranscriptBuffer.join('');
    if (joined.length <= maxChars) return joined;
    return joined.slice(-maxChars);
}

function setTrionShellModeState(nextState = {}) {
    trionShellState = {
        ...trionShellState,
        ...nextState,
        active: Boolean(nextState.active),
        containerId: String(nextState.containerId || '').trim(),
        language: String(nextState.language || trionShellState.language || 'en').trim() || 'en',
    };
    renderTrionShellMode();
}

function setTrionShellAddonDocsState(docs = []) {
    trionShellAddonDocs = Array.isArray(docs)
        ? docs
            .map(doc => ({
                id: String(doc?.id || '').trim(),
                title: String(doc?.title || doc?.id || '').trim(),
                scope: String(doc?.scope || '').trim(),
                path: String(doc?.path || '').trim(),
                score: Number.isFinite(Number(doc?.score)) ? Number(doc.score) : null,
            }))
            .filter(doc => doc.id || doc.title)
            .slice(0, 5)
        : [];
    renderTrionShellAddonDocs();
}

function renderTrionShellAddonDocs() {
    const strip = document.getElementById('term-shell-addon-strip');
    const label = document.getElementById('term-shell-addon-label');
    const list = document.getElementById('term-shell-addon-list');
    if (!strip || !label || !list) return;
    const isGerman = String(trionShellState.language || getUiLanguage() || '').trim().toLowerCase().startsWith('de');
    label.textContent = isGerman ? 'TRION Quellen' : 'TRION Sources';
    const visibleDocs = trionShellState.active ? trionShellAddonDocs : [];
    strip.style.display = visibleDocs.length ? 'flex' : 'none';
    if (!visibleDocs.length) {
        list.innerHTML = '';
        return;
    }
    list.innerHTML = visibleDocs.map(doc => {
        const title = esc(doc.title || doc.id || 'Addon');
        const scope = esc(doc.scope || (isGerman ? 'addon' : 'addon'));
        const hint = doc.path ? ` title="${esc(doc.path)}"` : '';
        return `
            <span class="term-shell-addon-chip"${hint}>
                <strong>${title}</strong>
                <small>${scope}</small>
            </span>
        `;
    }).join('');
}

function renderTrionShellMode() {
    const badge = document.getElementById('term-shell-mode-badge');
    const input = document.getElementById('term-cmd-input');
    const prompt = document.querySelector('.term-prompt');
    if (badge) badge.style.display = trionShellState.active ? 'inline-flex' : 'none';
    if (prompt) prompt.textContent = trionShellState.active ? 'trion(shell)>' : 'trion>';
    if (input) {
        input.classList.toggle('trion-shell-active', trionShellState.active);
        input.placeholder = trionShellState.active
            ? 'Describe what TRION should do in the shell… (/exit to return control)'
            : 'Type command or /quick action… (Tab for autocomplete)';
    }
    const statusText = document.getElementById('log-status-txt');
    if (statusText && trionShellState.active) {
        statusText.textContent = 'TRION controls shell';
    } else if (statusText && String(statusText.textContent || '').trim() === 'TRION controls shell') {
        statusText.textContent = 'Bereit';
    }
    renderTrionShellAddonDocs();
}


// ═══════════════════════════════════════════════════════════
// XTERM.JS
// ═══════════════════════════════════════════════════════════

function initXterm() {
    xtermController.initXterm();
}

function observeXtermLayout(container) {
    xtermController.observeXtermLayout?.(container);
}

function scheduleXtermFit() {
    xtermController.scheduleXtermFit();
}


// ═══════════════════════════════════════════════════════════
// AUTO-FOCUS
// ═══════════════════════════════════════════════════════════

function autoFocusContainer(containerId) {
    xtermController.autoFocusContainer(containerId);
    syncActiveLogContainerSelection();
}

function addShellSession(containerId) {
    xtermController.addShellSession(containerId);
}

function removeShellSession(containerId) {
    xtermController.removeShellSession(containerId);
}

function renderShellSessions() {
    xtermController.renderShellSessions();
}


// ═══════════════════════════════════════════════════════════
// APPROVAL DIALOG
// ═══════════════════════════════════════════════════════════

function showApprovalBanner(approvalId, reason, blueprintId, ttlSeconds = 300) {
    approvalController.showApprovalBanner(approvalId, reason, blueprintId, ttlSeconds);
}

function hideApprovalBanner() {
    approvalController.hideApprovalBanner();
}

function updateApprovalBadge() {
    approvalController.renderApprovalCenter?.();
}

function setApprovalCenterTab(tab) {
    approvalController.setApprovalCenterTab(tab);
}

function toggleApprovalCenter(force = null) {
    approvalController.toggleApprovalCenter(force);
}

async function resolveApprovalRequest(approvalId, action, reason = '') {
    await approvalController.resolveApprovalRequest?.(approvalId, action, reason);
}

async function approveRequest() {
    await approvalController.approveRequest();
}

async function rejectRequest() {
    await approvalController.rejectRequest();
}

async function refreshApprovalCenter() {
    await approvalController.refreshApprovalCenter();
}

async function pollApprovals() {
    await approvalController.pollApprovals();
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
    document.getElementById('bp-simple-btn')?.addEventListener('click', () => simpleWizardController.openWizard());
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
        commandInputController.setHistoryFilter(event.target?.value || '');
    });
    document.querySelectorAll('.term-log-tab').forEach(btn => {
        btn.addEventListener('click', () => setLogPanelMode(btn.dataset.logMode || 'logs'));
    });
    document.getElementById('log-filter-container')?.addEventListener('change', (event) => {
        handleLogContainerSelection(event.target?.value || '');
    });
    // Dropdown menu toggle
    document.getElementById('term-log-menu-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const dd = document.getElementById('term-log-dropdown');
        const btn = document.getElementById('term-log-menu-btn');
        if (!dd) return;
        const isOpen = dd.classList.toggle('open');
        btn.classList.toggle('open', isOpen);
    });
    // Autoscroll toggle
    const autoScrollState = document.getElementById('log-autoscroll-state');
    if (autoScrollState) {
        autoScrollState.textContent = logAutoScrollEnabled ? 'AN' : 'AUS';
        autoScrollState.style.color = logAutoScrollEnabled ? '#3fb950' : '#6e7681';
    }
    document.getElementById('log-autoscroll-btn')?.addEventListener('click', () => {
        logAutoScrollEnabled = !logAutoScrollEnabled;
        const el = document.getElementById('log-autoscroll-state');
        if (el) { el.textContent = logAutoScrollEnabled ? 'AN' : 'AUS'; el.style.color = logAutoScrollEnabled ? '#3fb950' : '#6e7681'; }
    });
    // Clear logs
    document.getElementById('log-clear-btn')?.addEventListener('click', () => {
        const out = document.getElementById('log-stream-output');
        if (out) out.textContent = '';
        document.getElementById('term-log-dropdown')?.classList.remove('open');
        document.getElementById('term-log-menu-btn')?.classList.remove('open');
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
    renderTrionShellMode();

    if (!globalTerminalEventsBound) {
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#term-log-menu-btn') && !e.target.closest('#term-log-dropdown')) {
                document.getElementById('term-log-dropdown')?.classList.remove('open');
                document.getElementById('term-log-menu-btn')?.classList.remove('open');
            }
        });

        window.addEventListener('keydown', (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                toggleCommandPalette();
            }
        });
        globalTerminalEventsBound = true;
    }
}

function updateLogContainerOptions() {
    const select = document.getElementById('log-filter-container');
    if (!select) return;
    const previousValue = String(select.value || attachedContainer || '');
    const options = ['<option value="">Alle Container</option>'];
    containers.forEach((container) => {
        const id = String(container?.container_id || '');
        if (!id) return;
        const name = String(container?.name || id.slice(0, 12));
        const blueprintId = String(container?.blueprint_id || '');
        options.push(
            `<option value="${esc(id)}">${esc(name)} · ${esc(id.slice(0, 12))}${blueprintId ? ` · ${esc(blueprintId)}` : ''}</option>`
        );
    });
    select.innerHTML = options.join('');
    const nextValue = attachedContainer && containers.some((container) => container.container_id === attachedContainer)
        ? attachedContainer
        : previousValue;
    select.value = containers.some((container) => container.container_id === nextValue) ? nextValue : '';
}

function syncActiveLogContainerSelection() {
    const select = document.getElementById('log-filter-container');
    if (!select) return;
    const activeValue = attachedContainer && containers.some((container) => container.container_id === attachedContainer)
        ? attachedContainer
        : '';
    if (select.value !== activeValue) select.value = activeValue;
}

function handleLogContainerSelection(containerId) {
    const nextId = String(containerId || '').trim();
    if (!nextId) {
        const current = attachedContainer;
        wsSend({ type: 'detach' });
        if (current) removeShellSession(current);
        setAttachedContainerState(null);
        return;
    }
    if (logPanelMode === 'shell') {
        autoFocusContainer(nextId);
        return;
    }
    setAttachedContainerState(nextId);
    wsSend({ type: 'attach', container_id: nextId });
    addShellSession(nextId);
    rememberRecent('containers', nextId);
}


// ═══════════════════════════════════════════════════════════
// CLI INPUT + AUTOCOMPLETE
// ═══════════════════════════════════════════════════════════

function getQuickCommands() {
    return [];
}

function handleInputKeydown(e) {
    commandInputController.handleInputKeydown(e);
}

function showAutocomplete(partial) {
    commandInputController.showAutocomplete(partial);
}

function applyAutocomplete(input) {
    commandInputController.applyAutocomplete?.(input);
}

function hideAutocomplete() {
    commandInputController.hideAutocomplete?.();
}

function renderHistoryList() {
    commandInputController.renderHistoryList();
}

async function copyCleanLogs() {
    await commandInputController.copyCleanLogs();
}

function downloadLogs() {
    commandInputController.downloadLogs();
}

function toggleCommandPalette(force = null) {
    commandInputController.toggleCommandPalette(force);
}

function renderCommandPalette() {
    commandInputController.renderCommandPalette();
}


// ═══════════════════════════════════════════════════════════
// COMMAND HANDLER (enhanced)
// ═══════════════════════════════════════════════════════════

async function handleCommand(cmd) {
    await commandInputController.handleCommand(cmd);
}

function normalizeQuickCommand(cmd) {
    return cmd;
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
        if (logPanelMode === 'shell') scheduleXtermFit();
        await loadActivityFeedSnapshot();
        await loadMemoryPanelSnapshot();
        startActivityFeedPolling();
    } else {
        stopContainerDetailPolling();
    }
    if (tab !== 'logs') stopActivityFeedPolling();
}

async function loadDashboard() {
    await dashboardController.loadDashboard();
}

function rememberRecent(key, value) {
    dashboardController.rememberRecent(key, value);
}

function renderDashboard() {
    dashboardController.renderDashboard();
}


// ═══════════════════════════════════════════════════════════
// BLUEPRINTS
// ═══════════════════════════════════════════════════════════

async function loadBlueprints() {
    await blueprintsController.loadBlueprints();
}

function renderBlueprints() {
    blueprintsController.renderBlueprints();
}

function showBlueprintEditor(bp = null, options = {}) {
    blueprintsController.showBlueprintEditor(bp, options);
}

const simpleWizardController = createSimpleWizardController({
    esc,
    showToast,
    logOutput,
    getApiBase: () => getApiBase(),
    apiRequest: (path, opts, msg) => apiRequest(path, opts, msg),
    loadBlueprints: () => loadBlueprints(),
});

async function openDeployPreflight(blueprintId, options = {}) {
    await blueprintsController.openDeployPreflight(blueprintId, options);
}

async function deployBlueprint(blueprintId) {
    rememberRecent('blueprints', blueprintId);
    await openDeployPreflight(blueprintId, { advanced: false });
}


// ═══════════════════════════════════════════════════════════
// CONTAINERS
// ═══════════════════════════════════════════════════════════

async function loadContainers() {
    await containersController.loadContainers();
}

function renderContainers() {
    containersController.renderContainers();
}

async function loadQuota() {
    await containersController.loadQuota();
}

function stopContainerDetailPolling() {
    containersController.stopContainerDetailPolling();
}

function suggestFix(message) {
    return containersController.suggestFix(message);
}

async function refreshContainerDetail() {
    await containersController.refreshContainerDetail();
}

function openContainerDrawer(containerId) {
    containersController.openContainerDrawer(containerId);
}

async function refreshVolumeManager() {
    await containersController.refreshVolumeManager();
}

function toggleVolumeManager() {
    containersController.toggleVolumeManager();
}


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
        storage_scope: String(entry?.storage_scope || entry?.storage_scope_override || ''),
        storage_asset_ids: Array.isArray(entry?.storage_asset_ids)
            ? entry.storage_asset_ids.map(item => String(item || '').trim()).filter(Boolean)
            : [],
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
            <div class="term-activity-meta">${esc(item.event)} ${item.blueprint_id ? `· ${esc(item.blueprint_id)}` : ''} ${item.container_id ? `· ${esc(item.container_id.slice(0, 12))}` : ''} ${item.storage_scope ? `· ${esc(item.storage_scope)}` : ''} ${item.storage_asset_ids?.length ? `· assets:${esc(item.storage_asset_ids.join(','))}` : ''}</div>
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
                <div><strong>Storage Scope</strong><span>${esc(item.storage_scope || '-')}</span></div>
                <div><strong>Storage Assets</strong><span>${esc((item.storage_asset_ids || []).join(', ') || '-')}</span></div>
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
    if (xtermController.writeLogLine(msg, cls, activeTab === 'logs')) {
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


// ═══════════════════════════════════════════════════════════
// APPROVAL CENTER
// ═══════════════════════════════════════════════════════════

function renderApprovalCenter() {
    approvalController.renderApprovalCenter?.();
}

function approvalReason(item) {
    return item?.approval_reason || item?.reason || '';
}

function approvalRisk(item) {
    const risk_flags = Array.isArray(item?.risk_flags) ? item.risk_flags : [];
    const risk_reasons = Array.isArray(item?.risk_reasons) ? item.risk_reasons : [];
    return { risk_flags, risk_reasons };
}

function renderApprovalContextCard() {
    const ctx = document.getElementById('approval-center-context');
    if (!ctx) return;
    const pending = approvalController.getPending?.() || [];
    const item = pending[0];
    if (!item) { ctx.innerHTML = ''; return; }
    const reason = approvalReason(item);
    const { risk_flags, risk_reasons } = approvalRisk(item);
    const network_mode = item?.network_mode || '';
    const capAdd = (item?.requested_cap_add || []).join(', ');
    const capDrop = (item?.requested_cap_drop || []).join(', ');
    const secOpt = (item?.requested_security_opt || []).join(', ');
    const readOnly = !!item?.read_only_rootfs;
    ctx.innerHTML = `
        <div class="approval-context-card">
            <div class="approval-context-reason">${esc(reason)}</div>
            <div class="approval-context-flags">${risk_flags.map(f => `<span>${esc(f)}</span>`).join('')}</div>
            ${risk_reasons.length ? `<div>${risk_reasons.map(r => esc(r)).join(', ')}</div>` : ''}
            ${capAdd ? `<div>cap_add: ${esc(capAdd)}</div>` : ''}
            ${capDrop ? `<div>cap_drop: ${esc(capDrop)}</div>` : ''}
            ${secOpt ? `<div>security_opt: ${esc(secOpt)}</div>` : ''}
            ${readOnly ? '<div>read_only_rootfs</div>' : ''}
            ${network_mode ? `<div>network_mode: ${esc(network_mode)}</div>` : ''}
            <button class="approval-batch-approve term-btn-sm"
                    onclick="window.termApproveRequest('${item?.id}')">Approve</button>
        </div>
    `;
}

window.termApproveRequest = async function(approvalId) {
    await resolveApprovalRequest(approvalId, 'approved');
};

window.termRejectRequest = async function(approvalId) {
    await resolveApprovalRequest(approvalId, 'rejected');
};

async function loadApprovals() {
    const [pending, history] = await Promise.all([
        apiRequest('/approvals', {}, 'Could not load approvals'),
        apiRequest('/approvals/history', {}, 'Could not load approval history'),
    ]);
    return { pending, history };
}


// ═══════════════════════════════════════════════════════════
// CONTAINER DETAIL DRAWER
// ═══════════════════════════════════════════════════════════

window.termOpenCtDetails = function(id) {
    openContainerDrawer(id);
};

async function loadContainerDetailData(containerId) {
    const [logs, stats, audit] = await Promise.all([
        apiRequest(`/containers/${containerId}/logs?tail=180`, {}, 'Could not load logs'),
        apiRequest(`/containers/${containerId}/stats`, {}, 'Could not load stats'),
        apiRequest('/audit?limit=120', {}, 'Could not load audit log'),
    ]);
    return { logs, stats, audit };
}


// ═══════════════════════════════════════════════════════════
// VOLUME SNAPSHOT MANAGER
// ═══════════════════════════════════════════════════════════

async function loadVolumes() {
    return apiRequest('/volumes', {}, 'Could not load volumes');
}

async function loadSnapshots() {
    return apiRequest('/snapshots', {}, 'Could not load snapshots');
}

async function createSnapshot(volumeName) {
    return apiRequest('/snapshots/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ volume: volumeName }),
    }, 'Could not create snapshot');
}

async function restoreSnapshot(snapshotId) {
    return apiRequest('/snapshots/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot_id: snapshotId }),
    }, 'Could not restore snapshot');
}

async function deleteVolume(volumeName) {
    return apiRequest(`/volumes/${encodeURIComponent(volumeName)}`, { method: 'DELETE' }, 'Could not remove volume');
}


// ═══════════════════════════════════════════════════════════
// STORAGE PICKER / MANAGED PATHS
// ═══════════════════════════════════════════════════════════

async function loadManagedStoragePaths() {
    return apiRequest('/storage/managed-paths', {}, 'Could not load managed paths');
}

function parseDeviceOverrides(raw) {
    return (raw || '').split('\n').map(s => s.trim()).filter(Boolean);
}

function findManagedCatalogItem(catalog, assetId) {
    return (catalog || []).find(item => item.asset_id === assetId) || null;
}

async function buildStoragePayload(state, catalog) {
    const selectedManaged = findManagedCatalogItem(catalog, state.form?.managed_path);
    const devices = parseDeviceOverrides(state.form?.devices || '');
    const payload = {};
    payload.device_overrides = devices;
    payload.mount_overrides = [
        ...(selectedManaged
            ? [{
                asset_id: String(selectedManaged?.asset_id || ''),
                default_mode: selectedManaged?.default_mode || 'rw',
                storage_assets: [selectedManaged],
                storage_scope: selectedManaged?.scope || '',
              }]
            : [])
    ];
    if (selectedManaged?.read_only) {
        showToast('cannot be mounted rw — asset is read-only', 'warn');
    }
    if (!selectedManaged) {
        payload.storage_scope_override = '__auto__';
    }
    return payload;
}


// ═══════════════════════════════════════════════════════════
// DEPLOY PREFLIGHT
// ═══════════════════════════════════════════════════════════

function evaluateDeployPreflight(blueprint, quota, secrets, resources) {
    const issues = [];
    const secretNames = (secrets || []).map(s => s.name);
    for (const req of (blueprint?.required_secrets || [])) {
        if (!secretNames.includes(req)) {
            issues.push(`Required secret missing: ${req}`);
        }
    }
    const usedMb = quota?.used_memory_mb || 0;
    const limitMb = quota?.max_memory_mb || 0;
    const reqMb = resources?.memory_mb || blueprint?.memory_mb || 512;
    if (limitMb > 0 && usedMb + reqMb > limitMb) {
        issues.push('Container quota exhausted');
    }
    return { ok: issues.length === 0, issues };
}

async function sendDeployPayload(blueprintId, state) {
    const env = Object.fromEntries(
        (state.form?.env_pairs || []).map(p => [p.key, p.value])
    );
    const payload = { blueprint_id: blueprintId };
    payload.override_resources = state.form.resources;
    payload.environment = env;
    payload.resume_volume = state.form.resume_volume;
    return apiRequest('/containers/deploy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }, 'Could not deploy blueprint');
}

async function loadBlueprintForPreflight(blueprintId) {
    return apiRequest(`/blueprints/${encodeURIComponent(blueprintId)}`, {}, 'Could not load blueprint');
}

async function fetchBlueprints() {
    return apiRequest('/blueprints', {}, 'Could not load blueprints');
}

async function fetchContainers() {
    return apiRequest('/containers', {}, 'Could not load containers');
}

async function fetchQuota() {
    return apiRequest('/quota', {}, 'Could not load quota');
}


// ═══════════════════════════════════════════════════════════
// BLUEPRINT QUICK ACTIONS
// ═══════════════════════════════════════════════════════════

window.termDeployBp = function(id) { deployBlueprint(id); };
window.termDeployBpWithOverrides = function(id) { openDeployPreflight(id, { advanced: true }); };
window.termCloneBp = function(id) { blueprintsController.cloneBlueprint?.(id); };

function buildBlueprintCardActions(bp) {
    return `
        <button onclick="termDeployBp('${bp.id}')">Deploy</button>
        <button onclick="termDeployBpWithOverrides('${bp.id}')">Deploy+</button>
        <button onclick="termCloneBp('${bp.id}')">Clone</button>
    `;
}


// ═══════════════════════════════════════════════════════════
// BLUEPRINT UX HELPERS
// ═══════════════════════════════════════════════════════════

// buildBlueprintPreset — imported from ./terminal/config.js

function validateBlueprintFieldLive(fieldId) {
    blueprintsController.validateFieldLive?.(fieldId);
}

async function exportBlueprintYaml(id, yaml) {
    downloadText(`${id}.yaml`, yaml);
}

function deriveTrustInfo(blueprint) {
    const trusted = blueprint?.trust_level === 'verified';
    const cls = trusted
        ? 'class="bp-preflight-trust" trusted'
        : 'class="bp-preflight-trust" unverified';
    return { trusted, cls };
}


// ═══════════════════════════════════════════════════════════
// POWER USER WRAPPERS
// ═══════════════════════════════════════════════════════════

// stripAnsi — imported from ./terminal/helpers.js


// ── Start ────────────────────────────────────────────────
// Don't auto-init — shell.js calls init() on demand
