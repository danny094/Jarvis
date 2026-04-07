/**
 * tools.js - MCP Manager App (Modern V1)
 * Features:
 * - MCP list with search and status badges
 * - MCP detail panel on click
 * - Enable/Disable (custom MCPs)
 * - Restart/reload MCP hub
 * - Config editor for custom MCPs
 */

import {
    STORAGE_BROKER_BUSY_STATE,
    createStorageBrokerState,
    isStorageBroker,
    renderStorageBrokerPanel,
} from "./storage-broker.js";

function getApiBase() {
    if (typeof window.getApiBase === "function" && window.getApiBase !== getApiBase) {
        return window.getApiBase();
    }
    if (window.location.port === "3000" || window.location.port === "80" || window.location.port === "") {
        return "";
    }
    return `${window.location.protocol}//${window.location.hostname}:8200`;
}

function getSameHostServiceUrl(port, path = "") {
    const protocol = String(window.location.protocol || "http:").trim() || "http:";
    const host = String(window.location.hostname || "127.0.0.1").trim() || "127.0.0.1";
    const suffix = String(path || "").trim();
    return `${protocol}//${host}:${port}${suffix}`;
}

function esc(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
}

function normalizeMcpName(name) {
    return String(name || "").trim().toLowerCase().replace(/[_\s]+/g, "-");
}

const state = {
    mcps: [],
    selected: "",
    details: null,
    tools: [],
    configEditable: false,
    configText: "",
    filter: "",
    busy: {
        refresh: false,
        restart: false,
        toggle: false,
        saveConfig: false,
        deleteMcp: false,
        installZip: false,
        installPkg: false,
        ...STORAGE_BROKER_BUSY_STATE,
        timeSave: false,
        timeTest: false,
        seqLoad: false,
        seqSave: false,
        seqHealth: false,
        seqMasterSave: false,
        memLoad: false,
        memSearch: false,
        memAction: false,
    },
    time: {
        testOutput: "",
    },
    seq: {
        loaded: false,
        runtime: null,
        master: null,
        readiness: null,
        probeSummary: "",
        probeOutput: "",
        probeError: "",
        probeTruncated: false,
        probeSteps: [],
        probeProgress: -1,
        uiTab: "status",
    },
    mem: {
        loaded: false,
        mode: "basic",              // basic | advanced
        tab: "overview",            // overview | search | maintenance | graph | settings
        settingsTab: "embeddings",  // embeddings | security
        health: null,
        maintenanceStatus: null,
        graphStats: null,
        recents: [],
        conversations: [],
        workspace: [],
        embeddings: null,
        secrets: [],
        loadError: "",
        search: {
            query: "",
            mode: "fts",            // like | fts | semantic | graph
            limit: 20,
            conversationId: "",
            results: [],
            raw: "",
            summary: "",
            error: "",
            selectedKey: "",
        },
        maintenance: {
            running: false,
            progress: 0,
            phase: "Idle",
            logs: [],
            result: null,
            error: "",
            tasks: {
                duplicates: true,
                promote: true,
                summarize: true,
                graph: true,
            },
            controller: null,
        },
        graph: {
            nodeId: "",
            neighbors: [],
            neighborsRaw: "",
            actionOutput: "",
        },
        embedBackfill: {
            batchSize: 100,
            dryRun: true,
            output: "",
        },
        security: {
            newSecretName: "",
            newSecretValue: "",
            resetConfirm: "",
            output: "",
        },
    },
    sb: createStorageBrokerState(),
    feedbackTimer: null,
};

async function apiJson(path, options = {}) {
    const res = await fetch(`${getApiBase()}${path}`, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data?.ok === false || data?.error) {
        const err = new Error(String(data?.error || data?.detail || data?.error_code || `HTTP ${res.status}`));
        err.status = res.status;
        err.code = data?.error_code || "";
        err.details = data?.details || null;
        throw err;
    }
    return data;
}

function setBusy(key, value) {
    state.busy[key] = Boolean(value);
    renderHeaderActions();
    renderDetailActions();
}

function setFeedback(msg, level = "info") {
    const el = document.getElementById("mcp-feedback");
    if (!el) return;
    if (state.feedbackTimer) {
        clearTimeout(state.feedbackTimer);
        state.feedbackTimer = null;
    }
    const text = String(msg || "").trim();
    if (!text) {
        el.textContent = "";
        el.className = "mcp-feedback hidden";
        return;
    }
    el.textContent = text;
    el.className = `mcp-feedback ${level}`;
    // Avoid sticky status text in the side panel.
    if (msg && level !== "err") {
        state.feedbackTimer = setTimeout(() => {
            const node = document.getElementById("mcp-feedback");
            if (!node) return;
            node.textContent = "";
            node.className = "mcp-feedback hidden";
            state.feedbackTimer = null;
        }, 3500);
    }
}

function renderLayout(root) {
    root.innerHTML = `
        <div class="mcp-app">
            <header class="mcp-head">
                <h2><i data-lucide="wrench"></i> MCP Tools</h2>
                <div class="mcp-head-actions" id="mcp-head-actions"></div>
            </header>

            <section class="mcp-top-grid">
                <article class="mcp-card">
                    <h3>Install Package</h3>
                    <div class="mcp-install-row">
                        <input id="tool-install-input" type="text" placeholder="Package (e.g. mcp-server-git)" />
                        <button id="tool-install-btn" class="mcp-btn primary"><i data-lucide="download"></i> Install</button>
                    </div>
                    <div id="install-logs" class="mcp-install-logs"></div>
                </article>

                <article class="mcp-card">
                    <h3>Install from ZIP</h3>
                    <div class="mcp-install-row mcp-install-zip">
                        <input type="file" id="mcp-zip-input" accept=".zip" />
                        <button id="btn-upload-mcp" class="mcp-btn primary"><i data-lucide="upload"></i> Upload</button>
                    </div>
                    <div id="upload-status" class="mcp-mini-status"></div>
                </article>
            </section>

            <section class="mcp-main-grid">
                <article class="mcp-card">
                    <div class="mcp-list-head">
                        <h3>Installed MCPs</h3>
                        <input id="mcp-filter" type="text" placeholder="Search MCP..." />
                    </div>
                    <div id="mcp-list" class="mcp-list"></div>
                </article>

                <article class="mcp-card mcp-detail-card">
                    <div class="mcp-detail-head">
                        <h3>MCP Details</h3>
                        <div id="mcp-detail-actions" class="mcp-detail-actions"></div>
                    </div>
                    <div id="mcp-detail" class="mcp-detail"></div>
                </article>
            </section>

            <footer id="mcp-feedback" class="mcp-feedback hidden"></footer>
        </div>
    `;

    if (window.lucide) window.lucide.createIcons();
}

function renderHeaderActions() {
    const el = document.getElementById("mcp-head-actions");
    if (!el) return;

    const refreshDisabled = state.busy.refresh;
    const restartDisabled = state.busy.restart;

    el.innerHTML = `
        <button id="mcp-refresh-btn" class="mcp-btn ghost" ${refreshDisabled ? "disabled" : ""}>
            <i data-lucide="refresh-cw"></i> ${refreshDisabled ? "Refreshing..." : "Refresh"}
        </button>
        <button id="mcp-restart-btn" class="mcp-btn ghost" ${restartDisabled ? "disabled" : ""}>
            <i data-lucide="rotate-ccw"></i> ${restartDisabled ? "Reloading..." : "Restart MCP Hub"}
        </button>
    `;

    document.getElementById("mcp-refresh-btn")?.addEventListener("click", refreshAll);
    document.getElementById("mcp-restart-btn")?.addEventListener("click", restartHub);

    if (window.lucide) window.lucide.createIcons();
}

function statusBadge(mcp) {
    const online = Boolean(mcp?.online);
    const enabled = Boolean(mcp?.enabled);
    const status = online ? "online" : "offline";
    const enabledTxt = enabled ? "enabled" : "disabled";
    return `
        <span class="mcp-chip ${online ? "ok" : "err"}">${status}</span>
        <span class="mcp-chip ${enabled ? "ok" : "warn"}">${enabledTxt}</span>
    `;
}

function renderMcpList() {
    const list = document.getElementById("mcp-list");
    if (!list) return;

    const q = String(state.filter || "").trim().toLowerCase();
    const rows = state.mcps.filter((mcp) => {
        if (!q) return true;
        const hay = [mcp.name, mcp.description, mcp.transport, mcp.url]
            .map((v) => String(v || "").toLowerCase())
            .join(" ");
        return hay.includes(q);
    });

    if (!rows.length) {
        list.innerHTML = `<div class="mcp-empty">No MCPs found.</div>`;
        return;
    }

    list.innerHTML = rows
        .map((mcp) => {
            const name = String(mcp.name || "");
            const active = name === state.selected;
            return `
                <button class="mcp-list-item ${active ? "active" : ""}" data-action="select" data-name="${esc(name)}">
                    <div class="mcp-list-item-main">
                        <strong>${esc(name)}</strong>
                        <small>${esc(mcp.description || "No description")}</small>
                        <div class="mcp-list-meta">
                            <span>${esc(mcp.transport || "-")}</span>
                            <span>${Number(mcp.tools_count || 0)} tools</span>
                        </div>
                    </div>
                    <div class="mcp-list-item-status">
                        ${statusBadge(mcp)}
                    </div>
                </button>
            `;
        })
        .join("");
}

function renderDetailActions() {
    const el = document.getElementById("mcp-detail-actions");
    if (!el) return;

    const selected = state.mcps.find((m) => String(m.name || "") === state.selected);
    if (!selected) {
        el.innerHTML = "";
        return;
    }

    const isEditable = Boolean(state.configEditable);
    const isCoreProtected = isCoreProtectedMcp(state.selected);
    const isSb = isStorageBroker(state.selected);
    const toggleDisabled = state.busy.toggle || !isEditable || isCoreProtected;
    const deleteDisabled = state.busy.deleteMcp || !isEditable || isCoreProtected;
    const enableLabel = selected.enabled ? "Disable" : "Enable";
    const sbFullscreenLabel = state.sb.fullscreen ? "Kleine Ansicht" : "Vollbild";

    el.innerHTML = `
        ${isSb ? `<button id="mcp-sb-fullscreen-btn" class="mcp-btn ghost">${sbFullscreenLabel}</button>` : ""}
        <button id="mcp-toggle-btn" class="mcp-btn" ${toggleDisabled ? "disabled" : ""}>${state.busy.toggle ? "Working..." : enableLabel}</button>
        <button id="mcp-delete-btn" class="mcp-btn danger" ${deleteDisabled ? "disabled" : ""}>${state.busy.deleteMcp ? "Deleting..." : "Delete"}</button>
    `;

    document.getElementById("mcp-sb-fullscreen-btn")?.addEventListener("click", toggleStorageBrokerFullscreen);
    document.getElementById("mcp-toggle-btn")?.addEventListener("click", toggleSelectedMcp);
    document.getElementById("mcp-delete-btn")?.addEventListener("click", deleteSelectedMcp);
}

function toggleStorageBrokerFullscreen() {
    if (!isStorageBroker(state.selected)) return;
    state.sb.fullscreen = !Boolean(state.sb.fullscreen);
    renderDetailActions();
    renderDetail();
}

function renderDetail() {
    const root = document.getElementById("mcp-detail");
    const appRoot = document.getElementById("app-tools");
    if (!root) return;

    const selected = state.mcps.find((m) => String(m.name || "") === state.selected);
    if (!selected) {
        if (appRoot) appRoot.setAttribute("data-sb-focus", "0");
        if (appRoot) appRoot.setAttribute("data-sb-fullscreen", "0");
        root.innerHTML = `<div class="mcp-empty">Select an MCP from the left to view details and settings.</div>`;
        return;
    }

    if (appRoot) {
        const focused = isStorageBroker(state.selected) || isSqlMemoryMcp(state.selected);
        appRoot.setAttribute("data-sb-focus", focused ? "1" : "0");
        appRoot.setAttribute("data-sb-fullscreen", isStorageBroker(state.selected) && state.sb.fullscreen ? "1" : "0");
    }

    // Storage Broker gets its own rich settings panel
    if (isStorageBroker(state.selected)) {
        renderStorageBrokerPanel({
            state,
            apiJson,
            esc,
            setBusy,
            setFeedback,
            renderDetail,
            renderMcpList,
            renderDetailActions,
        });
        return;
    }

    // SQL Memory gets a dedicated operations panel
    if (isSqlMemoryMcp(state.selected)) {
        if (!state.mem.loaded && !state.busy.memLoad) {
            mmLoadAll().then(() => renderDetail());
            root.innerHTML = `<div class="mcp-empty">SQL Memory wird geladen...</div>`;
            return;
        }
        renderSqlMemoryDetail(selected, state.details || selected, Array.isArray(state.tools) ? state.tools : []);
        return;
    }

    const details = state.details || selected;
    const tools = Array.isArray(state.tools) ? state.tools : [];

    // Time MCP gets its own settings panel
    if (isTimeMcp(state.selected)) {
        renderTimeMcpDetail(selected, details, tools);
        return;
    }

    // Sequential Thinking MCP gets its own policy + health panel
    if (isSequentialMcp(state.selected)) {
        if (!state.seq.loaded && !state.busy.seqLoad) {
            sqLoadAll().then(() => renderDetail());
            root.innerHTML = `<div class="mcp-empty">Sequential Thinking wird geladen...</div>`;
            return;
        }
        renderSequentialMcpDetail(selected, details, tools);
        return;
    }

    const saveDisabled = state.busy.saveConfig || !state.configEditable;

    root.innerHTML = `
        <div class="mcp-detail-block">
            <div class="mcp-kv"><span>Name</span><strong>${esc(details.name || selected.name || "")}</strong></div>
            <div class="mcp-kv"><span>Transport</span><strong>${esc(details.transport || selected.transport || "-")}</strong></div>
            <div class="mcp-kv"><span>URL/Command</span><strong class="mono">${esc(details.url || selected.url || "-")}</strong></div>
            <div class="mcp-kv"><span>Status</span><strong>${statusBadge(selected)}</strong></div>
        </div>

        <div class="mcp-detail-block">
            <h4>Available Tools (${tools.length})</h4>
            <div class="mcp-tool-list">
                ${tools.length ? tools.map((tool) => `
                    <div class="mcp-tool-item">
                        <strong>${esc(tool.name || "")}</strong>
                        <small>${esc(tool.description || "No description")}</small>
                    </div>
                `).join("") : '<div class="mcp-empty-inline">No tools exposed for this MCP.</div>'}
            </div>
        </div>

        <div class="mcp-detail-block">
            <h4>Settings (Custom MCP)</h4>
            <textarea id="mcp-config-editor" class="mcp-config-editor" spellcheck="false" ${state.configEditable ? "" : "disabled"}>${esc(state.configText || "")}</textarea>
            <div class="mcp-config-actions">
                <button id="mcp-save-config-btn" class="mcp-btn primary" ${saveDisabled ? "disabled" : ""}>
                    ${state.busy.saveConfig ? "Saving..." : "Save Config"}
                </button>
                <small>${state.configEditable ? "Editable config.json detected." : "Read-only: core MCP or no editable config."}</small>
            </div>
        </div>
    `;

    document.getElementById("mcp-save-config-btn")?.addEventListener("click", saveSelectedConfig);
}

async function refreshMcpList() {
    const data = await apiJson("/api/mcp/list");
    const rows = Array.isArray(data?.mcps) ? data.mcps.filter((mcp) => !isHiddenMcp(mcp?.name)) : [];
    rows.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
    state.mcps = rows;

    if (!state.selected && rows.length) {
        state.selected = String(rows[0].name || "");
    }
    if (state.selected && !rows.some((m) => String(m.name || "") === state.selected)) {
        state.selected = rows.length ? String(rows[0].name || "") : "";
    }

    renderMcpList();
}

async function loadSelectedDetails() {
    const name = String(state.selected || "").trim();
    state.details = null;
    state.tools = [];
    state.configEditable = false;
    state.configText = "";

    if (!name) {
        renderDetailActions();
        renderDetail();
        return;
    }

    const detailsReq = apiJson(`/api/mcp/${encodeURIComponent(name)}/details`);
    const configReq = apiJson(`/api/mcp/${encodeURIComponent(name)}/config`);
    const [detailsRes, configRes] = await Promise.allSettled([detailsReq, configReq]);

    if (detailsRes.status === "fulfilled") {
        state.details = detailsRes.value?.mcp || null;
        state.tools = Array.isArray(detailsRes.value?.tools) ? detailsRes.value.tools : [];
    }

    if (isSequentialMcp(name)) {
        state.seq.loaded = false;
    }
    if (isSqlMemoryMcp(name)) {
        state.mem.loaded = false;
    }

    if (configRes.status === "fulfilled" && configRes.value?.config) {
        state.configEditable = true;
        state.configText = JSON.stringify(configRes.value.config, null, 2);
    } else {
        state.configEditable = false;
        const fallback = state.details || state.mcps.find((m) => String(m.name || "") === name) || {};
        state.configText = JSON.stringify(fallback, null, 2);
    }

    renderDetailActions();
    renderDetail();
}

async function refreshAll() {
    setBusy("refresh", true);
    try {
        await refreshMcpList();
        await loadSelectedDetails();
        setFeedback("", "info");
    } catch (err) {
        setFeedback(`Failed to load MCPs: ${err.message || err}`, "err");
    } finally {
        setBusy("refresh", false);
    }
}

async function restartHub() {
    setBusy("restart", true);
    try {
        const data = await apiJson("/mcp/refresh", { method: "POST" });
        setFeedback(`MCP hub reloaded (${Number(data?.total_tools || 0)} tools)`, "ok");
        await refreshAll();
    } catch (err) {
        setFeedback(`Restart failed: ${err.message || err}`, "err");
    } finally {
        setBusy("restart", false);
    }
}

async function toggleSelectedMcp() {
    const name = String(state.selected || "").trim();
    if (!name) return;

    setBusy("toggle", true);
    try {
        const data = await apiJson(`/api/mcp/${encodeURIComponent(name)}/toggle`, { method: "POST" });
        const enabled = Boolean(data?.enabled);
        setFeedback(`${name} is now ${enabled ? "enabled" : "disabled"}`, "ok");
        await refreshAll();
    } catch (err) {
        setFeedback(`Toggle failed for ${name}: ${err.message || err}`, "err");
    } finally {
        setBusy("toggle", false);
    }
}

async function deleteSelectedMcp() {
    const name = String(state.selected || "").trim();
    if (!name) return;

    const ok = window.confirm(`Delete MCP '${name}'?`);
    if (!ok) return;

    setBusy("deleteMcp", true);
    try {
        await apiJson(`/api/mcp/${encodeURIComponent(name)}`, { method: "DELETE" });
        setFeedback(`Deleted MCP: ${name}`, "ok");
        state.selected = "";
        await refreshAll();
    } catch (err) {
        setFeedback(`Delete failed for ${name}: ${err.message || err}`, "err");
    } finally {
        setBusy("deleteMcp", false);
    }
}

async function saveSelectedConfig() {
    const name = String(state.selected || "").trim();
    if (!name || !state.configEditable) return;

    const editor = document.getElementById("mcp-config-editor");
    if (!editor) return;

    let parsed = null;
    try {
        parsed = JSON.parse(editor.value);
    } catch (err) {
        setFeedback(`Invalid JSON: ${err.message || err}`, "err");
        return;
    }

    setBusy("saveConfig", true);
    try {
        await apiJson(`/api/mcp/${encodeURIComponent(name)}/config`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config: parsed }),
        });
        setFeedback(`Config saved for ${name}`, "ok");
        await refreshAll();
    } catch (err) {
        setFeedback(`Save failed for ${name}: ${err.message || err}`, "err");
    } finally {
        setBusy("saveConfig", false);
    }
}

function setInstalling(isInstalling) {
    setBusy("installPkg", isInstalling);
    const btn = document.getElementById("tool-install-btn");
    if (!btn) return;

    if (isInstalling) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="animate-spin"></i> Installing...`;
    } else {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="download"></i> Install`;
    }

    if (window.lucide) window.lucide.createIcons();
}

function showInstallLog(msg, level = "info") {
    const logBox = document.getElementById("install-logs");
    if (!logBox) return;
    const line = document.createElement("div");
    line.className = `mcp-install-line ${level}`;
    line.textContent = msg;
    logBox.appendChild(line);
    logBox.scrollTop = logBox.scrollHeight;
}

function bindEvents(root) {
    document.getElementById("tool-install-btn")?.addEventListener("click", () => {
        const input = document.getElementById("tool-install-input");
        const pkg = String(input?.value || "").trim();
        if (!pkg) return;

        if (!window.TRIONBridge?.request) {
            setFeedback("Package install bridge unavailable", "err");
            return;
        }

        setInstalling(true);
        showInstallLog(`Installing package: ${pkg}`);
        window.TRIONBridge.request("mcp:install", { package: pkg });
    });

    document.getElementById("tool-install-input")?.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            document.getElementById("tool-install-btn")?.click();
        }
    });

    document.getElementById("btn-upload-mcp")?.addEventListener("click", async () => {
        const zipInput = document.getElementById("mcp-zip-input");
        const statusEl = document.getElementById("upload-status");
        const file = zipInput?.files?.[0];
        if (!file) {
            setFeedback("Select a ZIP first", "warn");
            return;
        }

        if (!String(file.name || "").toLowerCase().endsWith(".zip")) {
            setFeedback("Only ZIP files are supported", "warn");
            return;
        }

        setBusy("installZip", true);
        if (statusEl) {
            statusEl.textContent = "Uploading...";
            statusEl.className = "mcp-mini-status info";
        }

        try {
            const form = new FormData();
            form.append("file", file);
            const res = await fetch(`${getApiBase()}/api/mcp/install`, { method: "POST", body: form });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data?.detail || `HTTP ${res.status}`);
            }

            if (statusEl) {
                statusEl.textContent = `Installed: ${data?.mcp?.name || file.name}`;
                statusEl.className = "mcp-mini-status ok";
            }
            setFeedback("ZIP MCP installed successfully", "ok");
            if (zipInput) zipInput.value = "";
            await refreshAll();
        } catch (err) {
            if (statusEl) {
                statusEl.textContent = `Error: ${err.message || err}`;
                statusEl.className = "mcp-mini-status err";
            }
            setFeedback(`ZIP install failed: ${err.message || err}`, "err");
        } finally {
            setBusy("installZip", false);
        }
    });

    document.getElementById("mcp-filter")?.addEventListener("input", (e) => {
        state.filter = String(e.target?.value || "");
        renderMcpList();
    });

    root.addEventListener("click", (e) => {
        const btn = e.target?.closest?.("[data-action='select']");
        if (!btn) return;
        const name = String(btn.getAttribute("data-name") || "").trim();
        if (!name) return;
        state.selected = name;
        renderMcpList();
        loadSelectedDetails().catch((err) => {
            setFeedback(`Failed to load details: ${err.message || err}`, "err");
        });
    });

    if (window.TRIONBridge) {
        window.TRIONBridge.on("mcp:install_success", (data) => {
            showInstallLog(`Success: ${data.package || "package installed"}`, "ok");
            setInstalling(false);
            refreshAll();
        });
        window.TRIONBridge.on("mcp:install_error", (data) => {
            showInstallLog(`Error: ${data.error || "install failed"}`, "err");
            setInstalling(false);
        });
    }
}

// ══════════════════════════════════════════════════════════
// TIME MCP — Custom Settings Panel
// ══════════════════════════════════════════════════════════

const CORE_PROTECTED_MCPS = new Set([
    "sql-memory",
    "sequential-thinking",
    "cim",
    "skill-server",
    "storage-broker",
    "time-mcp",
]);

const HIDDEN_MCPS = new Set([
    "sql-memory",
    "sequential-thinking",
    "cim",
    "skill-server",
    "time-mcp",
]);

function isHiddenMcp(name) {
    return HIDDEN_MCPS.has(normalizeMcpName(name));
}

function isCoreProtectedMcp(name) {
    return CORE_PROTECTED_MCPS.has(normalizeMcpName(name));
}

function isTimeMcp(name) {
    return normalizeMcpName(name).replace(/-/g, "") === "timemcp";
}

function tmDefaultConfig() {
    return {
        name: "time-mcp",
        tier: "simple",
        url: getSameHostServiceUrl(8090),
        description: "Simple MCP server providing current time information",
        timezone: "UTC",
        country: "US",
        region: "",
        locale: "en-US",
        hour_cycle: "24h",
    };
}

function tmParseConfig() {
    const defaults = tmDefaultConfig();
    if (!state.configEditable) return defaults;
    try {
        const raw = JSON.parse(String(state.configText || "{}"));
        if (!raw || typeof raw !== "object") return defaults;
        return { ...defaults, ...raw };
    } catch {
        return defaults;
    }
}

function tmReadFormValues(root) {
    return {
        country: String(root.querySelector("#tm-country")?.value || "").trim(),
        region: String(root.querySelector("#tm-region")?.value || "").trim(),
        timezone: String(root.querySelector("#tm-timezone")?.value || "").trim() || "UTC",
        locale: String(root.querySelector("#tm-locale")?.value || "").trim() || "en-US",
        hour_cycle: String(root.querySelector("#tm-hour-cycle")?.value || "24h").trim() === "12h" ? "12h" : "24h",
    };
}

function tmExtractProbePayload(result) {
    if (!result || typeof result !== "object") return { result };
    const content = Array.isArray(result.content) ? result.content : [];
    const textEntry = content.find((item) => item && item.type === "text" && typeof item.text === "string");
    if (!textEntry) return result;
    try {
        return JSON.parse(textEntry.text);
    } catch {
        return { text: textEntry.text };
    }
}

async function tmSaveConfigFromForm(root) {
    const name = String(state.selected || "").trim();
    if (!name || !state.configEditable) {
        setFeedback("Time MCP Config ist hier nicht editierbar.", "warn");
        return;
    }

    const formValues = tmReadFormValues(root);
    let current = {};
    try {
        current = JSON.parse(String(state.configText || "{}"));
    } catch {
        current = {};
    }

    const nextConfig = {
        ...tmDefaultConfig(),
        ...(current && typeof current === "object" ? current : {}),
        ...formValues,
        name: "time-mcp",
    };
    if (!String(nextConfig.url || "").trim()) nextConfig.url = getSameHostServiceUrl(8090);
    if (!String(nextConfig.description || "").trim()) nextConfig.description = "Simple MCP server providing current time information";

    setBusy("timeSave", true);
    try {
        await apiJson(`/api/mcp/${encodeURIComponent(name)}/config`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config: nextConfig }),
        });
        state.configText = JSON.stringify(nextConfig, null, 2);
        setFeedback("Time MCP Settings gespeichert.", "ok");
        await loadSelectedDetails();
    } catch (err) {
        setFeedback(`Time MCP Settings konnten nicht gespeichert werden: ${err.message || err}`, "err");
    } finally {
        setBusy("timeSave", false);
    }
}

async function tmRunProbe() {
    setBusy("timeTest", true);
    try {
        const response = await apiJson("/mcp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                id: Date.now(),
                method: "tools/call",
                params: {
                    name: "get_current_time",
                    arguments: { format: "all" },
                },
            }),
        });
        const payload = tmExtractProbePayload(response?.result);
        state.time.testOutput = JSON.stringify(payload, null, 2);
        setFeedback("Time MCP Test erfolgreich.", "ok");
        renderDetail();
    } catch (err) {
        state.time.testOutput = JSON.stringify({ error: String(err?.message || err) }, null, 2);
        setFeedback(`Time MCP Test fehlgeschlagen: ${err.message || err}`, "err");
        renderDetail();
    } finally {
        setBusy("timeTest", false);
    }
}

function renderTimeMcpDetail(selected, details, tools) {
    const root = document.getElementById("mcp-detail");
    if (!root) return;

    const cfg = tmParseConfig();
    const saveDisabled = state.busy.timeSave || !state.configEditable;
    const testDisabled = state.busy.timeTest || !Boolean(selected?.online);
    const output = String(state.time.testOutput || "").trim();

    root.innerHTML = `
        <div class="mcp-detail-block">
            <div class="mcp-kv"><span>Name</span><strong>${esc(details?.name || selected?.name || "time-mcp")}</strong></div>
            <div class="mcp-kv"><span>Status</span><strong>${statusBadge(selected || {})}</strong></div>
            <div class="mcp-kv"><span>Transport</span><strong>${esc(details?.transport || selected?.transport || "-")}</strong></div>
            <div class="mcp-kv"><span>Tools</span><strong>${Number(Array.isArray(tools) ? tools.length : 0)}</strong></div>
        </div>

        <div class="mcp-detail-block tm-panel">
            <h4>Zeit-Einstellungen</h4>
            <p class="tm-hint">Lege Land, Region und Zeitzone fest. Diese Werte nutzt <code>get_current_time</code> und <code>get_timezone</code>.</p>
            <div class="tm-grid">
                <label class="tm-field">
                    <span>Land</span>
                    <input id="tm-country" class="tm-input" value="${esc(cfg.country || "")}" placeholder="US" />
                </label>
                <label class="tm-field">
                    <span>Region</span>
                    <input id="tm-region" class="tm-input" value="${esc(cfg.region || "")}" placeholder="California" />
                </label>
                <label class="tm-field">
                    <span>Zeitzone (IANA)</span>
                    <input id="tm-timezone" class="tm-input" value="${esc(cfg.timezone || "UTC")}" placeholder="Europe/Berlin" />
                </label>
                <label class="tm-field">
                    <span>Locale</span>
                    <input id="tm-locale" class="tm-input" value="${esc(cfg.locale || "en-US")}" placeholder="de-DE" />
                </label>
                <label class="tm-field">
                    <span>Uhrformat</span>
                    <select id="tm-hour-cycle" class="tm-select">
                        <option value="24h" ${String(cfg.hour_cycle || "24h") === "24h" ? "selected" : ""}>24h</option>
                        <option value="12h" ${String(cfg.hour_cycle || "") === "12h" ? "selected" : ""}>12h</option>
                    </select>
                </label>
            </div>
            <div class="tm-actions">
                <button id="tm-save-btn" class="mcp-btn primary" ${saveDisabled ? "disabled" : ""}>${state.busy.timeSave ? "Speichern..." : "Settings speichern"}</button>
                <button id="tm-test-btn" class="mcp-btn" ${testDisabled ? "disabled" : ""}>${state.busy.timeTest ? "Teste..." : "Zeit jetzt testen"}</button>
                <small>${state.configEditable ? "Werte werden in custom_mcps/time-mcp/config.json gespeichert." : "Config derzeit nicht editierbar."}</small>
            </div>
            <details class="tm-raw">
                <summary>Rohkonfiguration</summary>
                <pre>${esc(state.configText || "{}")}</pre>
            </details>
        </div>

        <div class="mcp-detail-block">
            <h4>Verfuegbare Time-Tools (${Array.isArray(tools) ? tools.length : 0})</h4>
            <div class="mcp-tool-list">
                ${Array.isArray(tools) && tools.length ? tools.map((tool) => `
                    <div class="mcp-tool-item">
                        <strong>${esc(tool.name || "")}</strong>
                        <small>${esc(tool.description || "No description")}</small>
                    </div>
                `).join("") : '<div class="mcp-empty-inline">Keine Tools gefunden.</div>'}
            </div>
        </div>

        <div class="mcp-detail-block">
            <h4>Test-Ausgabe</h4>
            <pre class="tm-output">${esc(output || 'Noch kein Test ausgefuehrt. Klicke auf "Zeit jetzt testen".')}</pre>
        </div>
    `;

    root.querySelector("#tm-save-btn")?.addEventListener("click", () => {
        tmSaveConfigFromForm(root);
    });
    root.querySelector("#tm-test-btn")?.addEventListener("click", () => {
        tmRunProbe();
    });
}

// ══════════════════════════════════════════════════════════
// SEQUENTIAL THINKING MCP — Runtime Policy Panel
// ══════════════════════════════════════════════════════════

function isSequentialMcp(name) {
    return String(name || "").toLowerCase().replace(/[-_]/g, "") === "sequentialthinking";
}

const SQ_RUNTIME_FIELDS = [
    { key: "DEFAULT_RESPONSE_MODE", label: "Default Response Mode", type: "enum", options: ["interactive", "deep"], hint: "interactive = schnell, deep = ausfuehrlich" },
    { key: "RESPONSE_MODE_SEQUENTIAL_THRESHOLD", label: "Sequential Threshold", type: "int", min: 1, max: 10 },
    { key: "SEQUENTIAL_TIMEOUT_S", label: "Sequential Timeout (s)", type: "int", min: 5, max: 300 },
    { key: "QUERY_BUDGET_ENABLE", label: "Query Budget aktiv", type: "bool" },
    { key: "QUERY_BUDGET_EMBEDDING_ENABLE", label: "Embedding Refinement", type: "bool" },
    { key: "QUERY_BUDGET_SKIP_THINKING_ENABLE", label: "Skip-Thinking erlaubt", type: "bool" },
    { key: "QUERY_BUDGET_SKIP_THINKING_MIN_CONFIDENCE", label: "Skip Min Confidence", type: "float", min: 0, max: 1, step: "0.01" },
    { key: "QUERY_BUDGET_MAX_TOOLS_FACTUAL_LOW", label: "Max Tools (factual/low)", type: "int", min: 0, max: 5 },
    { key: "LOOP_ENGINE_TRIGGER_COMPLEXITY", label: "Loop Trigger Complexity", type: "int", min: 1, max: 10 },
    { key: "LOOP_ENGINE_MIN_TOOLS", label: "Loop Min Tools", type: "int", min: 0, max: 10 },
    { key: "LOOP_ENGINE_MAX_PREDICT", label: "Loop Max Predict", type: "int", min: 0, max: 8192 },
    { key: "LOOP_ENGINE_OUTPUT_CHAR_CAP", label: "Loop Output Char Cap", type: "int", min: 0, max: 200000 },
];

function sqRuntimeEntry(key) {
    const eff = state.seq.runtime?.effective || {};
    const defaults = state.seq.runtime?.defaults || {};
    const entry = eff[key] || null;
    return {
        value: entry?.value ?? defaults[key] ?? "",
        source: entry?.source || "default",
        defaultValue: defaults[key],
    };
}

function sqSourceChip(source) {
    const s = String(source || "default").toLowerCase();
    if (s === "override") return `<span class="mcp-chip ok">override</span>`;
    if (s === "env") return `<span class="mcp-chip warn">env</span>`;
    return `<span class="mcp-chip">default</span>`;
}

function sqExtractToolPayload(result) {
    if (!result || typeof result !== "object") return result;
    const content = Array.isArray(result.content) ? result.content : [];
    const textEntry = content.find((item) => item && item.type === "text" && typeof item.text === "string");
    if (!textEntry) return result;
    try {
        return JSON.parse(textEntry.text);
    } catch {
        return { text: textEntry.text };
    }
}

function sqNormalizeProbePayload(value, depth = 0) {
    const MAX_DEPTH = 5;
    const MAX_KEYS = 40;
    const MAX_ITEMS = 30;
    const MAX_STRING = 700;
    if (value == null) return value;
    if (depth > MAX_DEPTH) return "[truncated: depth limit]";
    if (typeof value === "string") {
        if (value.length <= MAX_STRING) return value;
        return `${value.slice(0, MAX_STRING)} ... [truncated ${value.length - MAX_STRING} chars]`;
    }
    if (typeof value !== "object") return value;
    if (Array.isArray(value)) {
        if (value.length <= MAX_ITEMS) {
            return value.map((entry) => sqNormalizeProbePayload(entry, depth + 1));
        }
        const head = value.slice(0, MAX_ITEMS).map((entry) => sqNormalizeProbePayload(entry, depth + 1));
        head.push(`[truncated: ${value.length - MAX_ITEMS} more items]`);
        return head;
    }
    const entries = Object.entries(value);
    const trimmed = entries.slice(0, MAX_KEYS);
    const out = {};
    for (const [k, v] of trimmed) out[k] = sqNormalizeProbePayload(v, depth + 1);
    if (entries.length > MAX_KEYS) out.__truncated_keys__ = entries.length - MAX_KEYS;
    return out;
}

function sqSerializeProbePayload(payload) {
    const MAX_TOTAL = 12000;
    const normalized = sqNormalizeProbePayload(payload);
    let text = "";
    try {
        text = JSON.stringify(normalized, null, 2);
    } catch {
        text = String(normalized);
    }
    const fullLength = text.length;
    if (fullLength > MAX_TOTAL) {
        return {
            text: `${text.slice(0, MAX_TOTAL)}\n... [truncated ${fullLength - MAX_TOTAL} chars]`,
            truncated: true,
            fullLength,
        };
    }
    return { text, truncated: false, fullLength };
}

function sqBuildProbeSummary(payload, meta) {
    if (payload == null) return "Keine Payload vom Tool erhalten.";
    if (typeof payload === "string") return `String-Antwort (${payload.length} Zeichen).`;
    if (Array.isArray(payload)) return `Array-Antwort (${payload.length} Eintraege).`;
    if (typeof payload === "object") {
        const keys = Object.keys(payload);
        const keyPreview = keys.slice(0, 6).join(", ") || "keine";
        return `Objekt-Antwort mit ${keys.length} Feldern (${keyPreview}). ${meta.truncated ? "Gekuerzt angezeigt." : "Vollstaendig angezeigt."}`;
    }
    return `Antworttyp: ${typeof payload}.`;
}

async function sqRunProbe() {
    setBusy("seqHealth", true);
    try {
        const response = await apiJson("/mcp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                id: Date.now(),
                method: "tools/call",
                params: {
                    name: "think_simple",
                    arguments: {
                        message: "Health check: antworte mit einem kurzen Status.",
                        steps: 1,
                    },
                },
            }),
        });
        const payload = sqExtractToolPayload(response?.result);
        const serialized = sqSerializeProbePayload(payload);
        state.seq.probeOutput = serialized.text;
        state.seq.probeTruncated = serialized.truncated;
        state.seq.probeSummary = sqBuildProbeSummary(payload, serialized);
        state.seq.probeError = "";
        setFeedback("Sequential Probe erfolgreich.", "ok");
    } catch (err) {
        state.seq.probeError = String(err?.message || err);
        const serialized = sqSerializeProbePayload({ error: state.seq.probeError });
        state.seq.probeOutput = serialized.text;
        state.seq.probeSummary = "Probe ist mit Fehler beendet.";
        state.seq.probeTruncated = serialized.truncated;
        setFeedback(`Sequential Probe fehlgeschlagen: ${state.seq.probeError}`, "err");
    } finally {
        setBusy("seqHealth", false);
        renderDetail();
    }
}

async function sqLoadAll() {
    setBusy("seqLoad", true);
    try {
        const [runtimeRes, masterRes, readinessRes] = await Promise.allSettled([
            apiJson("/api/settings/sequential/runtime"),
            apiJson("/api/settings/master"),
            apiJson("/api/runtime/autonomy-status"),
        ]);

        if (runtimeRes.status === "fulfilled") state.seq.runtime = runtimeRes.value || null;
        if (masterRes.status === "fulfilled") state.seq.master = masterRes.value || null;
        if (readinessRes.status === "fulfilled") state.seq.readiness = readinessRes.value || null;
        state.seq.loaded = true;
    } catch (err) {
        setFeedback(`Sequential Panel konnte nicht geladen werden: ${err.message || err}`, "err");
    } finally {
        setBusy("seqLoad", false);
    }
}

function sqReadRuntimePayload(root) {
    const payload = {};
    for (const field of SQ_RUNTIME_FIELDS) {
        const id = `sq-rt-${field.key.toLowerCase()}`;
        const el = root.querySelector(`#${id}`);
        if (!el) continue;
        if (field.type === "bool") {
            payload[field.key] = Boolean(el.checked);
            continue;
        }
        if (field.type === "enum") {
            payload[field.key] = String(el.value || "").trim();
            continue;
        }
        if (field.type === "float") {
            const val = Number.parseFloat(String(el.value || "").trim());
            if (Number.isFinite(val)) payload[field.key] = val;
            continue;
        }
        const val = Number.parseInt(String(el.value || "").trim(), 10);
        if (Number.isFinite(val)) payload[field.key] = val;
    }
    return payload;
}

async function sqSaveRuntime(root) {
    const payload = sqReadRuntimePayload(root);
    setBusy("seqSave", true);
    try {
        await apiJson("/api/settings/sequential/runtime", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        setFeedback("Sequential Runtime Policy gespeichert.", "ok");
        state.seq.loaded = false;
        await sqLoadAll();
        renderDetail();
    } catch (err) {
        setFeedback(`Sequential Runtime Save fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("seqSave", false);
    }
}

async function sqSaveMaster(root) {
    const payload = {
        enabled: Boolean(root.querySelector("#sq-master-enabled")?.checked),
        use_thinking_layer: Boolean(root.querySelector("#sq-master-thinking")?.checked),
        max_loops: Number.parseInt(String(root.querySelector("#sq-master-max-loops")?.value || "10"), 10) || 10,
        completion_threshold: Number.parseInt(String(root.querySelector("#sq-master-completion-threshold")?.value || "2"), 10) || 2,
    };
    setBusy("seqMasterSave", true);
    try {
        await apiJson("/api/settings/master", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        setFeedback("Master-Orchestrator Settings gespeichert.", "ok");
        state.seq.loaded = false;
        await sqLoadAll();
        renderDetail();
    } catch (err) {
        setFeedback(`Master Settings Save fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("seqMasterSave", false);
    }
}

function sqRenderRuntimeField(field) {
    const entry = sqRuntimeEntry(field.key);
    const safeKey = `sq-rt-${field.key.toLowerCase()}`;
    const value = entry.value;
    const hint = field.hint ? `<small>${esc(field.hint)}</small>` : "";

    if (field.type === "bool") {
        return `
            <div class="sq-row">
                <label class="sq-field-label" for="${safeKey}">${esc(field.label)}</label>
                <div class="sq-row-inline">
                    <input id="${safeKey}" type="checkbox" ${value ? "checked" : ""} />
                    ${sqSourceChip(entry.source)}
                </div>
                ${hint}
            </div>
        `;
    }

    if (field.type === "enum") {
        return `
            <div class="sq-row">
                <label class="sq-field-label" for="${safeKey}">${esc(field.label)}</label>
                <div class="sq-row-inline">
                    <select id="${safeKey}" class="sq-input">
                        ${field.options.map((opt) => `<option value="${esc(opt)}" ${String(value) === opt ? "selected" : ""}>${esc(opt)}</option>`).join("")}
                    </select>
                    ${sqSourceChip(entry.source)}
                </div>
                ${hint}
            </div>
        `;
    }

    const type = field.type === "float" ? "number" : "number";
    const step = field.step || (field.type === "float" ? "0.01" : "1");
    const minAttr = field.min !== undefined ? `min="${field.min}"` : "";
    const maxAttr = field.max !== undefined ? `max="${field.max}"` : "";
    return `
        <div class="sq-row">
            <label class="sq-field-label" for="${safeKey}">${esc(field.label)}</label>
            <div class="sq-row-inline">
                <input id="${safeKey}" class="sq-input" type="${type}" step="${step}" ${minAttr} ${maxAttr} value="${esc(value)}" />
                ${sqSourceChip(entry.source)}
            </div>
            ${hint}
        </div>
    `;
}

function renderSequentialMcpDetail(selected, details, tools) {
    const root = document.getElementById("mcp-detail");
    if (!root) return;

    const master = state.seq.master || {};
    const readiness = state.seq.readiness || {};
    const planning = readiness?.planning_tools?.available || {};
    const planningAll = Boolean(readiness?.planning_tools?.all_required_available);
    const probeDisabled = state.busy.seqHealth || !Boolean(selected?.online);
    const probeText = String(state.seq.probeOutput || "").trim();
    const probeSummary = String(state.seq.probeSummary || "").trim();
    const activeTab = String(state.seq.uiTab || "status");

    // Build probe steps from probe output or summary
    const probeSteps = state.seq.probeSteps || [];
    const probeOk = probeText && !state.seq.probeError;

    // Status grid
    const statusItems = [
        { label: "MCP Status",       ok: Boolean(selected?.online),             val: selected?.online ? "Online & bereit" : "Offline" },
        { label: "Planning Tools",   ok: planningAll,                            val: planningAll ? "Vollst\u00e4ndig" : "Teilweise" },
        { label: "Sequential Tool",  ok: Boolean(planning.sequential_thinking),  val: planning.sequential_thinking ? "Bereit" : "Fehlt" },
        { label: "Workspace Save",   ok: Boolean(planning.workspace_event_save), val: planning.workspace_event_save ? "Bereit" : "Fehlt" },
        { label: "Workspace List",   ok: Boolean(planning.workspace_event_list), val: planning.workspace_event_list ? "Bereit" : "Fehlt" },
        { label: "Master Thinking",  ok: Boolean(master.use_thinking_layer),     val: master.use_thinking_layer ? "Aktiv" : "Inaktiv" },
    ];
    const statusGrid = statusItems.map(item => `
        <div class="sq-stat-card">
            <div class="sq-stat-label">${esc(item.label)}</div>
            <div class="sq-stat-val">
                <span class="sq-dot ${item.ok ? "sq-dot-ok" : "sq-dot-warn"}"></span>
                ${esc(item.val)}
            </div>
        </div>`).join("");

    // Probe steps
    const defaultProbeSteps = [
        { title: "Tool-Aufruf: think_simple", sub: "Anfrage an Sequential Thinking Engine senden" },
        { title: "CIM-Validierung", sub: "Causal Intelligence Module pr\u00fcft den Denkschritt" },
        { title: "Workspace gespeichert", sub: "workspace_event_save speichert Session-Zustand" },
        { title: "E2E-Test abgeschlossen", sub: "Alle Pfade gepr\u00fcft \u2014 Engine einsatzbereit" },
    ];
    const stepsToRender = probeSteps.length ? probeSteps : defaultProbeSteps;
    const probeStepsHtml = stepsToRender.map((step, i) => {
        const isDone = probeOk || (state.seq.probeProgress > i);
        const isActive = !probeOk && state.seq.probeProgress === i && state.busy.seqHealth;
        const cls = isDone ? "sq-pstep-ok" : isActive ? "sq-pstep-active" : "sq-pstep-todo";
        const timeStr = step.time ? `<span class="sq-pstep-time">+${step.time}ms</span>` : "";
        return `
            <div class="sq-probe-step">
                <div class="sq-pstep-num ${cls}">${isDone ? "&#10003;" : String(i+1)}</div>
                <div class="sq-pstep-body">
                    <div class="sq-pstep-title">${esc(step.title)}</div>
                    <div class="sq-pstep-sub">${esc(step.sub)}</div>
                </div>
                ${timeStr}
            </div>`;
    }).join("");

    const probeStatusText = state.seq.probeError
        ? `<span style="color:#A32D2D;">Fehler: ${esc(state.seq.probeError)}</span>`
        : probeOk ? `<span style="color:#3B6D11;">&#10003; Erfolgreich</span>`
        : `<span style="color:var(--sq-text-muted);">Noch keine Probe ausgef\u00fchrt</span>`;

    // Runtime fields
    const runtimeFields = SQ_RUNTIME_FIELDS.map(field => {
        const entry = sqRuntimeEntry(field.key);
        const safeKey = `sq-rt-${field.key.toLowerCase()}`;
        const value = entry.value;
        let control = "";
        if (field.type === "bool") {
            control = `<label class="sq-toggle"><input type="checkbox" id="${safeKey}" ${value ? "checked" : ""} /><span class="sq-toggle-slider"></span></label>`;
        } else if (field.type === "enum") {
            control = `<select class="sq-field-select" id="${safeKey}">${field.options.map(o => `<option value="${esc(o)}" ${String(value)===o?"selected":""}>${esc(o)}</option>`).join("")}</select>`;
        } else {
            const step = field.step || (field.type === "float" ? "0.01" : "1");
            const min = field.min !== undefined ? `min="${field.min}"` : "";
            const max = field.max !== undefined ? `max="${field.max}"` : "";
            control = `<input class="sq-field-input" id="${safeKey}" type="number" step="${step}" ${min} ${max} value="${esc(value)}" />`;
        }
        return `
            <div class="sq-field">
                <div class="sq-field-label">${esc(field.label)}</div>
                ${field.hint ? `<div class="sq-field-hint">${esc(field.hint)}</div>` : ""}
                ${control}
            </div>`;
    }).join("");

    // Think-flow diagram
    const flowSteps = [
        { cls: "sq-fc-input",  icon: "E", label: "Eingabe / Task",            desc: "TRION empf\u00e4ngt eine komplexe Anfrage die strukturiertes Denken erfordert.", tag: "ThinkingLayer", tagCls: "sq-tag-blue" },
        { cls: "sq-fc-think",  icon: "1", label: "Schritt 1 \u2014 Problemzerlegung", desc: "think_simple zerlegt die Anfrage in atomare Teilprobleme. Jeder Schritt wird separat verarbeitet.", tag: "think_simple \u00b7 " + esc(String(master.max_loops || 10)) + " Loops max", tagCls: "sq-tag-purple" },
        { cls: "sq-fc-cim",   icon: "\u2713", label: "CIM-Validierung",            desc: "Das Causal Intelligence Module pr\u00fcft jeden Schritt auf kausale Konsistenz und Anti-Pattern.", tag: "CIM v2 \u00b7 Frank's Module", tagCls: "sq-tag-amber" },
        { cls: "sq-fc-think",  icon: "N", label: "Weitere Schritte",           desc: "Der Prozess wiederholt sich bis der Completion Threshold erreicht ist. Workspace sichert den Zustand.", tag: "Threshold: " + esc(String(master.completion_threshold || 2)), tagCls: "sq-tag-purple" },
        { cls: "sq-fc-output", icon: "\u2713", label: "Validierte Ausgabe",        desc: "Das Ergebnis wird an TRION zur\u00fcckgegeben \u2014 vollst\u00e4ndig nachvollziehbar und auditierbar.", tag: "OutputLayer", tagCls: "sq-tag-green" },
    ];
    const flowHtml = flowSteps.map((s, i) => `
        <div class="sq-flow-step">
            <div class="sq-flow-left">
                <div class="sq-fc ${s.cls}">${s.icon}</div>
                ${i < flowSteps.length - 1 ? '<div class="sq-flow-line"></div>' : ""}
            </div>
            <div class="sq-flow-content">
                <div class="sq-flow-label">${s.label}</div>
                <div class="sq-flow-desc">${s.desc}</div>
                <span class="sq-tag ${s.tagCls}">${s.tag}</span>
            </div>
        </div>`).join("");

    // Tabs
    const tabs = ["status", "flow", "master", "runtime"];
    const tabLabels = { status: "Status & Probe", flow: "Think-Flow", master: "Master Orchestrator", runtime: "Runtime Policy" };
    const tabsHtml = tabs.map(t => `<button class="sq-tab${activeTab === t ? " active" : ""}" data-sq-tab="${t}">${tabLabels[t]}</button>`).join("");

    const tabContent = {
        status: `
            <div class="sq-status-grid">${statusGrid}</div>
            <div class="sq-probe-card">
                <div class="sq-probe-card-header">
                    <div style="display:flex;align-items:center;gap:8px;">${probeStatusText}</div>
                </div>
                <div class="sq-probe-steps">${probeStepsHtml}</div>
                ${probeSummary && !state.seq.probeError ? `<div class="sq-probe-summary">${esc(probeSummary)}</div>` : ""}
            </div>`,
        flow: `<div class="sq-flow-wrap">${flowHtml}</div>`,
        master: `
            <div class="sq-section">
                <div class="sq-section-hdr"><div class="sq-section-title">Master Orchestrator</div><div class="sq-section-sub">Steuert wann und wie Sequential Thinking aktiviert wird.</div></div>
                <div class="sq-section-rows">
                    <div class="sq-section-row">
                        <div class="sq-row-info"><div class="sq-row-label">Master aktiviert</div><div class="sq-row-hint">Erlaubt TRION Sequential Thinking autonom zu nutzen.</div></div>
                        <label class="sq-toggle"><input id="sq-master-enabled" type="checkbox" ${master.enabled ? "checked" : ""} /><span class="sq-toggle-slider"></span></label>
                    </div>
                    <div class="sq-section-row">
                        <div class="sq-row-info"><div class="sq-row-label">Thinking Layer nutzen</div><div class="sq-row-hint">Erweiterte Reasoning-F\u00e4higkeiten des Modells aktivieren.</div></div>
                        <label class="sq-toggle"><input id="sq-master-thinking" type="checkbox" ${master.use_thinking_layer ? "checked" : ""} /><span class="sq-toggle-slider"></span></label>
                    </div>
                    <div class="sq-section-row">
                        <div class="sq-row-info"><div class="sq-row-label">Max Loops</div><div class="sq-row-hint">Maximale Anzahl Denkschritte pro Anfrage.</div></div>
                        <input id="sq-master-max-loops" class="sq-field-input" type="number" min="1" max="200" value="${esc(master.max_loops ?? 10)}" style="width:80px;" />
                    </div>
                    <div class="sq-section-row">
                        <div class="sq-row-info"><div class="sq-row-label">Completion Threshold</div><div class="sq-row-hint">Wie viele \u00fcbereinstimmende Schritte als fertig gelten.</div></div>
                        <input id="sq-master-completion-threshold" class="sq-field-input" type="number" min="1" max="10" value="${esc(master.completion_threshold ?? 2)}" style="width:80px;" />
                    </div>
                </div>
                <div class="sq-save-row">
                    <button id="sq-save-master" class="sq-save-btn" ${state.busy.seqMasterSave ? "disabled" : ""}>${state.busy.seqMasterSave ? "Speichere\u2026" : "Master speichern"}</button>
                </div>
            </div>`,
        runtime: `
            <div class="sq-section">
                <div class="sq-section-hdr"><div class="sq-section-title">Runtime Policy</div><div class="sq-section-sub">Feinsteuerung wann Sequential Thinking greift.</div></div>
                <div class="sq-runtime-grid">${runtimeFields}</div>
                <div class="sq-save-row">
                    <button id="sq-save-runtime" class="sq-save-btn" ${state.busy.seqSave ? "disabled" : ""}>${state.busy.seqSave ? "Speichere\u2026" : "Runtime Policy speichern"}</button>
                </div>
            </div>`,
    };

    root.innerHTML = `
        <div class="sq-panel">
            <div class="sq-panel-header">
                <div class="sq-panel-icon">&#129504;</div>
                <div>
                    <div class="sq-panel-name">Sequential Thinking</div>
                    <div class="sq-panel-sub">v2.0 \u2014 Step-by-step reasoning mit CIM-Validierung</div>
                </div>
                <div class="sq-panel-badges">
                    <span class="sq-badge ${selected?.online ? "sq-badge-ok" : "sq-badge-off"}">${selected?.online ? "\u25cf Online" : "\u25cb Offline"}</span>
                    <span class="sq-badge sq-badge-info">Enabled</span>
                    ${master.enabled ? `<span class="sq-badge sq-badge-warn">Master aktiv</span>` : ""}
                </div>
                <button id="sq-run-probe" class="sq-probe-btn" ${probeDisabled ? "disabled" : ""}>${state.busy.seqHealth ? "&#9203; L\u00e4uft\u2026" : "&#9654; Probe starten"}</button>
            </div>
            <div class="sq-panel-tabs">${tabsHtml}</div>
            <div class="sq-panel-body">
                ${tabContent[activeTab] || tabContent.status}
            </div>
        </div>`;

    root.querySelector("#sq-run-probe")?.addEventListener("click", () => { sqRunProbe(); });
    root.querySelector("#sq-save-runtime")?.addEventListener("click", () => { sqSaveRuntime(root); });
    root.querySelector("#sq-save-master")?.addEventListener("click", () => { sqSaveMaster(root); });
    root.querySelectorAll("[data-sq-tab]").forEach(btn => {
        btn.addEventListener("click", () => {
            state.seq.uiTab = String(btn.getAttribute("data-sq-tab") || "status");
            renderDetail();
        });
    });
}

function isSqlMemoryMcp(name) {
    return String(name || "").toLowerCase().replace(/[-_]/g, "") === "sqlmemory";
}

function mmSafeJson(value, maxChars = 12000) {
    let text = "";
    try {
        text = JSON.stringify(value, null, 2);
    } catch {
        text = String(value == null ? "" : value);
    }
    if (text.length <= maxChars) return text;
    return `${text.slice(0, maxChars)}\n... [truncated ${text.length - maxChars} chars]`;
}

function mmExtractToolPayload(result) {
    if (result == null) return null;
    if (typeof result !== "object") return result;
    if (result.structuredContent !== undefined) return result.structuredContent;

    const content = Array.isArray(result.content) ? result.content : [];
    const textItems = content.filter((item) => item && item.type === "text" && typeof item.text === "string");
    if (textItems.length) {
        const joined = textItems.map((item) => item.text).join("\n").trim();
        if (!joined) return result;
        try {
            const parsed = JSON.parse(joined);
            if (parsed && typeof parsed === "object" && parsed.structuredContent !== undefined) return parsed.structuredContent;
            return parsed;
        } catch {
            return { text: joined };
        }
    }
    return result;
}

async function mmCallTool(toolName, args = {}) {
    const response = await apiJson("/mcp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            jsonrpc: "2.0",
            id: Date.now(),
            method: "tools/call",
            params: {
                name: toolName,
                arguments: args,
            },
        }),
    });
    return mmExtractToolPayload(response?.result);
}

function mmEntriesFromPayload(payload) {
    if (Array.isArray(payload)) return payload;
    if (!payload || typeof payload !== "object") return [];
    if (Array.isArray(payload.entries)) return payload.entries;
    if (payload.structuredContent && Array.isArray(payload.structuredContent.entries)) return payload.structuredContent.entries;
    if (Array.isArray(payload.results)) return payload.results;
    if (payload.structuredContent && Array.isArray(payload.structuredContent.results)) return payload.structuredContent.results;
    return [];
}

function mmConversationsFromPayload(payload) {
    if (!payload || typeof payload !== "object") return [];
    if (Array.isArray(payload.conversations)) return payload.conversations;
    if (payload.structuredContent && Array.isArray(payload.structuredContent.conversations)) return payload.structuredContent.conversations;
    return [];
}

function mmSecretsFromPayload(payload) {
    if (!payload || typeof payload !== "object") return [];
    if (Array.isArray(payload.secrets)) return payload.secrets;
    if (payload.structuredContent && Array.isArray(payload.structuredContent.secrets)) return payload.structuredContent.secrets;
    return [];
}

function mmResultKey(item, index) {
    if (item && item.id != null) return `id:${item.id}`;
    if (item && item.node_id != null) return `node:${item.node_id}`;
    return `idx:${index}`;
}

function mmResultLabel(item) {
    if (!item || typeof item !== "object") return "memory-entry";
    if (item.layer) return String(item.layer).toUpperCase();
    if (item.type) return String(item.type);
    if (item.role) return String(item.role);
    return "entry";
}

function mmShort(text, max = 160) {
    const raw = String(text || "").trim();
    if (raw.length <= max) return raw;
    return `${raw.slice(0, max)}…`;
}

function mmFormatDate(value) {
    const raw = String(value || "").trim();
    if (!raw) return "-";
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return raw;
    return d.toLocaleString();
}

function mmSummaryCounts() {
    const maintenance = state.mem.maintenanceStatus?.memory || {};
    const graph = state.mem.graphStats || {};
    return {
        stm: Number(maintenance.stm_entries || 0),
        mtm: Number(maintenance.mtm_entries || 0),
        ltm: Number(maintenance.ltm_entries || 0),
        workspace: Number(state.mem.workspace.length || 0),
        nodes: Number(graph.nodes || maintenance.graph_nodes || 0),
        edges: Number(graph.edges || maintenance.graph_edges || 0),
    };
}

async function mmProbeHealth() {
    setBusy("memAction", true);
    try {
        state.mem.health = await mmCallTool("memory_healthcheck", {});
        setFeedback("SQL Memory Probe erfolgreich.", "ok");
        renderDetail();
    } catch (err) {
        setFeedback(`SQL Memory Probe fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
    }
}

async function mmLoadAll() {
    setBusy("memLoad", true);
    state.mem.loadError = "";
    try {
        const [healthRes, statusRes, graphRes, recentRes, convRes, workspaceRes, embedRes, secretsRes] = await Promise.allSettled([
            mmCallTool("memory_healthcheck", {}),
            apiJson("/api/maintenance/status"),
            mmCallTool("memory_graph_stats", {}),
            mmCallTool("memory_all_recent", { limit: 20 }),
            mmCallTool("memory_list_conversations", { limit: 50 }),
            apiJson("/api/workspace?limit=30"),
            mmCallTool("memory_embedding_version_status", {}),
            mmCallTool("secret_list", {}),
        ]);

        if (healthRes.status === "fulfilled") state.mem.health = healthRes.value || null;
        if (statusRes.status === "fulfilled") state.mem.maintenanceStatus = statusRes.value || null;
        if (graphRes.status === "fulfilled") state.mem.graphStats = graphRes.value || null;
        if (recentRes.status === "fulfilled") state.mem.recents = mmEntriesFromPayload(recentRes.value);
        if (convRes.status === "fulfilled") state.mem.conversations = mmConversationsFromPayload(convRes.value);
        if (workspaceRes.status === "fulfilled") state.mem.workspace = Array.isArray(workspaceRes.value?.entries) ? workspaceRes.value.entries : [];
        if (embedRes.status === "fulfilled") state.mem.embeddings = embedRes.value || null;
        if (secretsRes.status === "fulfilled") state.mem.secrets = mmSecretsFromPayload(secretsRes.value);

        state.mem.loaded = true;
    } catch (err) {
        state.mem.loadError = String(err?.message || err);
    } finally {
        setBusy("memLoad", false);
    }
}

async function mmRefreshAll() {
    state.mem.loaded = false;
    await mmLoadAll();
    renderDetail();
}

async function mmRunSearch() {
    const query = String(state.mem.search.query || "").trim();
    if (!query) {
        state.mem.search.error = "Bitte einen Suchbegriff eingeben.";
        state.mem.search.results = [];
        state.mem.search.raw = "";
        renderDetail();
        return;
    }

    const mode = String(state.mem.search.mode || "fts");
    const limit = Math.max(1, Math.min(100, Number.parseInt(String(state.mem.search.limit || "20"), 10) || 20));
    const conversationId = String(state.mem.search.conversationId || "").trim();
    const args = { query, limit };
    if (conversationId) args.conversation_id = conversationId;

    setBusy("memSearch", true);
    state.mem.search.error = "";
    try {
        let payload = null;
        if (mode === "like") {
            payload = await mmCallTool("memory_search", args);
        } else if (mode === "semantic") {
            payload = await mmCallTool("memory_semantic_search", { ...args, min_similarity: 0.5 });
        } else if (mode === "graph") {
            payload = await mmCallTool("memory_graph_search", { ...args, depth: 2 });
        } else {
            payload = await mmCallTool("memory_search_fts", args);
        }

        const rows = mmEntriesFromPayload(payload);
        state.mem.search.results = rows;
        state.mem.search.raw = mmSafeJson(payload);
        state.mem.search.summary = `${rows.length} Treffer (${mode.toUpperCase()})`;
        state.mem.search.selectedKey = rows.length ? mmResultKey(rows[0], 0) : "";
        setFeedback(`Suche abgeschlossen: ${rows.length} Treffer.`, "ok");
    } catch (err) {
        state.mem.search.error = String(err?.message || err);
        state.mem.search.results = [];
        state.mem.search.raw = mmSafeJson({ error: state.mem.search.error });
        setFeedback(`Suche fehlgeschlagen: ${state.mem.search.error}`, "err");
    } finally {
        setBusy("memSearch", false);
        renderDetail();
    }
}

async function mmDeleteMemoryEntry(id) {
    const numeric = Number.parseInt(String(id || ""), 10);
    if (!Number.isFinite(numeric)) {
        setFeedback("Loeschen nur fuer echte Memory-IDs moeglich.", "warn");
        return;
    }
    setBusy("memAction", true);
    try {
        await mmCallTool("memory_delete", { id: numeric });
        setFeedback(`Memory-Eintrag ${numeric} geloescht.`, "ok");
        if (state.mem.search.query) await mmRunSearch();
    } catch (err) {
        setFeedback(`Loeschen fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
    }
}

async function mmSaveSearchResultToWorkspace(result) {
    const item = result && typeof result === "object" ? result : null;
    if (!item) return;
    const content = String(item.content || "").trim();
    if (!content) {
        setFeedback("Treffer enthaelt keinen speicherbaren Inhalt.", "warn");
        return;
    }
    const conversationId = String(item.conversation_id || "global");
    setBusy("memAction", true);
    try {
        await mmCallTool("workspace_save", {
            conversation_id: conversationId,
            content,
            entry_type: "observation",
            source_layer: "output",
        });
        setFeedback("Treffer im Workspace gespeichert.", "ok");
        const ws = await apiJson("/api/workspace?limit=30");
        state.mem.workspace = Array.isArray(ws?.entries) ? ws.entries : state.mem.workspace;
    } catch (err) {
        setFeedback(`Workspace-Save fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
        renderDetail();
    }
}

function mmReadMaintenanceTasks(root) {
    const box = root.querySelectorAll("[data-mm-task]");
    const next = { duplicates: false, promote: false, summarize: false, graph: false };
    box.forEach((el) => {
        const key = String(el.getAttribute("data-mm-task") || "");
        if (Object.prototype.hasOwnProperty.call(next, key)) next[key] = Boolean(el.checked);
    });
    state.mem.maintenance.tasks = next;
}

function mmPushMaintenanceLog(message) {
    const text = String(message || "").trim();
    if (!text) return;
    state.mem.maintenance.logs.push(text);
    if (state.mem.maintenance.logs.length > 120) state.mem.maintenance.logs.shift();
}

async function mmStartMaintenance(root) {
    if (state.mem.maintenance.running) return;
    mmReadMaintenanceTasks(root);
    const tasks = Object.entries(state.mem.maintenance.tasks)
        .filter(([, enabled]) => Boolean(enabled))
        .map(([k]) => k);
    if (!tasks.length) {
        setFeedback("Bitte mindestens eine Wartungsaufgabe auswaehlen.", "warn");
        return;
    }

    state.mem.maintenance.running = true;
    state.mem.maintenance.progress = 0;
    state.mem.maintenance.phase = "Initialisiere...";
    state.mem.maintenance.logs = [];
    state.mem.maintenance.result = null;
    state.mem.maintenance.error = "";
    state.mem.maintenance.controller = new AbortController();
    renderDetail();

    try {
        const response = await fetch(`${getApiBase()}/api/maintenance/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tasks }),
            signal: state.mem.maintenance.controller.signal,
        });
        if (!response.ok || !response.body) {
            throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                let data = null;
                try {
                    data = JSON.parse(line.slice(6));
                } catch {
                    continue;
                }
                if (!data || typeof data !== "object") continue;
                if (data.type === "stream_end") continue;
                if (data.phase) state.mem.maintenance.phase = String(data.phase);
                if (data.progress != null) state.mem.maintenance.progress = Number(data.progress) || 0;
                if (data.message) mmPushMaintenanceLog(data.message);
                if (data.type === "completed" && data.stats) state.mem.maintenance.result = data.stats;
                renderDetail();
            }
        }

        setFeedback("Maintenance abgeschlossen.", "ok");
        await mmLoadAll();
    } catch (err) {
        if (String(err?.name || "") === "AbortError") {
            mmPushMaintenanceLog("Maintenance abgebrochen.");
            setFeedback("Maintenance abgebrochen.", "warn");
        } else {
            state.mem.maintenance.error = String(err?.message || err);
            setFeedback(`Maintenance fehlgeschlagen: ${state.mem.maintenance.error}`, "err");
        }
    } finally {
        state.mem.maintenance.running = false;
        state.mem.maintenance.controller = null;
        renderDetail();
    }
}

async function mmCancelMaintenance() {
    const ctrl = state.mem.maintenance.controller;
    if (ctrl) ctrl.abort();
    try {
        await apiJson("/api/maintenance/cancel", { method: "POST" });
    } catch {
        // best effort
    }
}

async function mmGraphAction(action) {
    setBusy("memAction", true);
    try {
        let payload = null;
        if (action === "duplicates") payload = await mmCallTool("graph_find_duplicate_nodes", {});
        else if (action === "orphans") payload = await mmCallTool("graph_delete_orphan_nodes", {});
        else if (action === "prune") payload = await mmCallTool("graph_prune_weak_edges", { threshold: 0.3 });
        else if (action === "refresh") payload = await mmCallTool("memory_graph_stats", {});
        if (action === "refresh") state.mem.graphStats = payload || state.mem.graphStats;
        state.mem.graph.actionOutput = mmSafeJson(payload);
        setFeedback("Graph-Operation abgeschlossen.", "ok");
        if (action !== "refresh") {
            const nextStats = await mmCallTool("memory_graph_stats", {});
            state.mem.graphStats = nextStats || state.mem.graphStats;
        }
    } catch (err) {
        setFeedback(`Graph-Operation fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
        renderDetail();
    }
}

async function mmLoadNeighbors(nodeIdRaw) {
    const nodeId = Number.parseInt(String(nodeIdRaw || "").trim(), 10);
    if (!Number.isFinite(nodeId)) {
        setFeedback("Bitte eine gueltige Node-ID eingeben.", "warn");
        return;
    }
    setBusy("memAction", true);
    try {
        const payload = await mmCallTool("memory_graph_neighbors", { node_id: nodeId, direction: "outgoing" });
        const neighbors = Array.isArray(payload?.neighbors) ? payload.neighbors : [];
        state.mem.graph.nodeId = String(nodeId);
        state.mem.graph.neighbors = neighbors;
        state.mem.graph.neighborsRaw = mmSafeJson(payload);
        setFeedback(`${neighbors.length} Nachbarn geladen.`, "ok");
    } catch (err) {
        setFeedback(`Neighbor-Load fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
        renderDetail();
    }
}

async function mmRunBackfill(root) {
    const batchInput = root.querySelector("#mm-backfill-batch");
    const dryInput = root.querySelector("#mm-backfill-dry");
    const batchSize = Math.max(1, Math.min(1000, Number.parseInt(String(batchInput?.value || "100"), 10) || 100));
    const dryRun = Boolean(dryInput?.checked);
    state.mem.embedBackfill.batchSize = batchSize;
    state.mem.embedBackfill.dryRun = dryRun;

    setBusy("memAction", true);
    try {
        const payload = await mmCallTool("memory_embedding_backfill", { batch_size: batchSize, dry_run: dryRun });
        state.mem.embedBackfill.output = mmSafeJson(payload);
        state.mem.embeddings = await mmCallTool("memory_embedding_version_status", {});
        setFeedback(`Embedding Backfill ${dryRun ? "Dry-Run " : ""}ausgefuehrt.`, "ok");
    } catch (err) {
        setFeedback(`Backfill fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
        renderDetail();
    }
}

async function mmSaveSecret(root) {
    const nameEl = root.querySelector("#mm-secret-name");
    const valueEl = root.querySelector("#mm-secret-value");
    const name = String(nameEl?.value || "").trim();
    const value = String(valueEl?.value || "");
    if (!name || !value) {
        setFeedback("Secret Name und Wert sind erforderlich.", "warn");
        return;
    }

    setBusy("memAction", true);
    try {
        const payload = await mmCallTool("secret_save", { name, value });
        state.mem.security.output = mmSafeJson(payload);
        const secretsPayload = await mmCallTool("secret_list", {});
        state.mem.secrets = mmSecretsFromPayload(secretsPayload);
        state.mem.security.newSecretName = "";
        state.mem.security.newSecretValue = "";
        setFeedback(`Secret ${name} gespeichert.`, "ok");
    } catch (err) {
        setFeedback(`Secret save fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
        renderDetail();
    }
}

async function mmDeleteSecret(name) {
    const safeName = String(name || "").trim();
    if (!safeName) return;
    if (!window.confirm(`Secret "${safeName}" wirklich loeschen?`)) return;
    setBusy("memAction", true);
    try {
        const payload = await mmCallTool("secret_delete", { name: safeName });
        state.mem.security.output = mmSafeJson(payload);
        const secretsPayload = await mmCallTool("secret_list", {});
        state.mem.secrets = mmSecretsFromPayload(secretsPayload);
        setFeedback(`Secret ${safeName} geloescht.`, "ok");
    } catch (err) {
        setFeedback(`Secret delete fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
        renderDetail();
    }
}

async function mmResetMemory(root) {
    const confirmText = String(root.querySelector("#mm-reset-confirm")?.value || "").trim();
    state.mem.security.resetConfirm = confirmText;
    if (confirmText !== "RESET MEMORY") {
        setFeedback('Bitte exakt "RESET MEMORY" eingeben.', "warn");
        return;
    }
    if (!window.confirm("Wirklich komplettes SQL-Memory resetten? Das ist irreversibel.")) return;

    setBusy("memAction", true);
    try {
        const payload = await mmCallTool("memory_reset", {});
        state.mem.security.output = mmSafeJson(payload);
        setFeedback("SQL Memory wurde zurueckgesetzt.", "ok");
        await mmLoadAll();
    } catch (err) {
        setFeedback(`Memory reset fehlgeschlagen: ${err.message || err}`, "err");
    } finally {
        setBusy("memAction", false);
        renderDetail();
    }
}

function mmRenderOverview() {
    const counts = mmSummaryCounts();
    const health = state.mem.health || {};
    const worker = state.mem.maintenanceStatus?.worker || {};
    const convos = state.mem.conversations || [];
    const recents = state.mem.recents || [];

    return `
        <div class="mm-cards">
            <article class="mm-card"><h5>STM</h5><strong>${counts.stm}</strong><small>Kurzzeit-Eintraege</small></article>
            <article class="mm-card"><h5>MTM</h5><strong>${counts.mtm}</strong><small>Mittelfristig</small></article>
            <article class="mm-card"><h5>LTM</h5><strong>${counts.ltm}</strong><small>Langzeit-Wissen</small></article>
            <article class="mm-card"><h5>Workspace</h5><strong>${counts.workspace}</strong><small>Editierbare Notizen</small></article>
            <article class="mm-card"><h5>Graph</h5><strong>${counts.nodes} / ${counts.edges}</strong><small>Nodes / Edges</small></article>
            <article class="mm-card"><h5>Conversations</h5><strong>${convos.length}</strong><small>aktive Topics</small></article>
        </div>

        <div class="mm-panels">
            <section class="mm-panel">
                <h5>Status</h5>
                <div class="mm-kv-grid">
                    <div><span>Server</span><strong>${esc(String(health.server || "sql_memory"))}</strong></div>
                    <div><span>Health</span><strong>${esc(String(health.status || "unknown"))}</strong></div>
                    <div><span>Worker</span><strong>${esc(String(worker.state || "idle"))}</strong></div>
                    <div><span>Letztes Update</span><strong>${esc(mmFormatDate(health.timestamp))}</strong></div>
                </div>
                <div class="mm-actions">
                    <button class="mcp-btn" data-mm-action="probe" ${state.busy.memAction ? "disabled" : ""}>Probe ausfuehren</button>
                    <button class="mcp-btn" data-mm-action="refresh" ${state.busy.memLoad ? "disabled" : ""}>Alles neu laden</button>
                </div>
            </section>

            <section class="mm-panel">
                <h5>Letzte Memory-Eintraege</h5>
                <div class="mm-list">
                    ${
                        recents.length
                            ? recents
                                .slice(0, 8)
                                .map(
                                    (row) => `
                            <div class="mm-list-item">
                                <strong>${esc(mmResultLabel(row))}</strong>
                                <small>${esc(mmShort(row.content || "", 140))}</small>
                            </div>
                        `
                                )
                                .join("")
                            : '<div class="mcp-empty-inline">Keine Eintraege gefunden.</div>'
                    }
                </div>
            </section>
        </div>
    `;
}

function mmRenderSearch() {
    const search = state.mem.search;
    const selected = search.results.find((row, idx) => mmResultKey(row, idx) === search.selectedKey) || null;
    return `
        <section class="mm-panel">
            <h5>Suche</h5>
            <div class="mm-search-bar">
                <input id="mm-search-query" class="mm-input" placeholder="Suche in Memory..." value="${esc(search.query)}" />
                <select id="mm-search-mode" class="mm-select">
                    <option value="fts" ${search.mode === "fts" ? "selected" : ""}>FTS</option>
                    <option value="like" ${search.mode === "like" ? "selected" : ""}>LIKE</option>
                    <option value="semantic" ${search.mode === "semantic" ? "selected" : ""}>Semantic</option>
                    <option value="graph" ${search.mode === "graph" ? "selected" : ""}>Graph</option>
                </select>
                <input id="mm-search-conv" class="mm-input" placeholder="conversation_id (optional)" value="${esc(search.conversationId)}" />
                <input id="mm-search-limit" class="mm-input mm-input-sm" type="number" min="1" max="100" value="${esc(search.limit)}" />
                <button class="mcp-btn primary" data-mm-action="run-search" ${state.busy.memSearch ? "disabled" : ""}>${state.busy.memSearch ? "Suche..." : "Suchen"}</button>
            </div>
            ${search.error ? `<p class="mm-error">${esc(search.error)}</p>` : ""}
            <p class="mm-hint">${esc(search.summary || "Noch keine Suche ausgefuehrt.")}</p>
        </section>

        <section class="mm-search-grid">
            <div class="mm-panel">
                <h5>Treffer (${search.results.length})</h5>
                <div class="mm-list mm-results">
                    ${
                        search.results.length
                            ? search.results
                                .map((row, idx) => {
                                    const key = mmResultKey(row, idx);
                                    return `
                                <button class="mm-result-item ${search.selectedKey === key ? "active" : ""}" data-mm-result="${esc(key)}">
                                    <strong>${esc(mmResultLabel(row))}</strong>
                                    <small>${esc(mmShort(row.content || row.text || "", 160))}</small>
                                </button>
                            `;
                                })
                                .join("")
                            : '<div class="mcp-empty-inline">Keine Treffer.</div>'
                    }
                </div>
            </div>

            <div class="mm-panel">
                <h5>Details</h5>
                ${
                    selected
                        ? `
                    <div class="mm-kv-grid">
                        <div><span>ID</span><strong>${esc(String(selected.id ?? selected.node_id ?? "-"))}</strong></div>
                        <div><span>Layer/Typ</span><strong>${esc(mmResultLabel(selected))}</strong></div>
                        <div><span>Conversation</span><strong>${esc(String(selected.conversation_id || "-"))}</strong></div>
                        <div><span>Zeit</span><strong>${esc(mmFormatDate(selected.created_at || selected.timestamp))}</strong></div>
                    </div>
                    <pre class="mm-pre">${esc(mmSafeJson(selected, 2400))}</pre>
                    <div class="mm-actions">
                        <button class="mcp-btn" data-mm-save-workspace="${esc(search.selectedKey)}" ${state.busy.memAction ? "disabled" : ""}>In Workspace speichern</button>
                        ${
                            Number.isFinite(Number(selected.id))
                                ? `<button class="mcp-btn danger" data-mm-delete-id="${esc(String(selected.id))}" ${state.busy.memAction ? "disabled" : ""}>Loeschen</button>`
                                : ""
                        }
                    </div>
                `
                        : '<div class="mcp-empty-inline">Treffer auswaehlen, um Details zu sehen.</div>'
                }
                ${state.mem.mode === "advanced" ? `<details class="mm-raw"><summary>Roh-Output</summary><pre class="mm-pre">${esc(search.raw || "{}")}</pre></details>` : ""}
            </div>
        </section>
    `;
}

function mmRenderMaintenance() {
    const m = state.mem.maintenance;
    const result = m.result?.actions || {};
    const pct = Math.max(0, Math.min(100, Number(m.progress) || 0));
    return `
        <section class="mm-panel">
            <h5>Maintenance Tasks</h5>
            <div class="mm-task-grid">
                <label><input type="checkbox" data-mm-task="duplicates" ${m.tasks.duplicates ? "checked" : ""} ${m.running ? "disabled" : ""}/> Duplicates entfernen</label>
                <label><input type="checkbox" data-mm-task="promote" ${m.tasks.promote ? "checked" : ""} ${m.running ? "disabled" : ""}/> Promoten</label>
                <label><input type="checkbox" data-mm-task="summarize" ${m.tasks.summarize ? "checked" : ""} ${m.running ? "disabled" : ""}/> Cluster zusammenfassen</label>
                <label><input type="checkbox" data-mm-task="graph" ${m.tasks.graph ? "checked" : ""} ${m.running ? "disabled" : ""}/> Graph rebuild</label>
            </div>
            <div class="mm-actions">
                <button class="mcp-btn primary" data-mm-action="start-maintenance" ${m.running ? "disabled" : ""}>${m.running ? "Laeuft..." : "Maintenance starten"}</button>
                <button class="mcp-btn danger" data-mm-action="cancel-maintenance" ${m.running ? "" : "disabled"}>Abbrechen</button>
            </div>
            <div class="mm-progress-wrap">
                <div class="mm-progress-head"><span>${esc(m.phase || "Idle")}</span><strong>${Math.round(pct)}%</strong></div>
                <div class="mm-progress"><div style="width:${pct}%"></div></div>
            </div>
            ${m.error ? `<p class="mm-error">${esc(m.error)}</p>` : ""}
            <div class="mm-log">
                ${
                    m.logs.length
                        ? m.logs.map((line) => `<div>${esc(line)}</div>`).join("")
                        : '<div class="mcp-empty-inline">Noch keine Logs.</div>'
                }
            </div>
            ${
                m.result
                    ? `
                <div class="mm-cards">
                    <article class="mm-card"><h5>Duplicates</h5><strong>${Number(result.duplicates_found || 0)}</strong></article>
                    <article class="mm-card"><h5>Promoted</h5><strong>${Number(result.promoted_to_ltm || 0)}</strong></article>
                    <article class="mm-card"><h5>Summaries</h5><strong>${Number(result.summaries_created || 0)}</strong></article>
                    <article class="mm-card"><h5>Edges Pruned</h5><strong>${Number(result.edges_pruned || 0)}</strong></article>
                </div>
            `
                    : ""
            }
        </section>
    `;
}

function mmRenderGraph() {
    const graph = state.mem.graphStats || {};
    const neighbors = state.mem.graph.neighbors || [];
    return `
        <section class="mm-panel">
            <h5>Graph Overview</h5>
            <div class="mm-cards">
                <article class="mm-card"><h5>Nodes</h5><strong>${Number(graph.nodes || 0)}</strong></article>
                <article class="mm-card"><h5>Edges</h5><strong>${Number(graph.edges || 0)}</strong></article>
                <article class="mm-card"><h5>Edge Types</h5><strong>${Object.keys(graph.edge_types || {}).length}</strong></article>
                <article class="mm-card"><h5>Node Types</h5><strong>${Object.keys(graph.node_types || {}).length}</strong></article>
            </div>
            <div class="mm-actions">
                <button class="mcp-btn" data-mm-graph-action="refresh" ${state.busy.memAction ? "disabled" : ""}>Stats refresh</button>
                <button class="mcp-btn" data-mm-graph-action="duplicates" ${state.busy.memAction ? "disabled" : ""}>Duplicates finden</button>
                <button class="mcp-btn" data-mm-graph-action="orphans" ${state.busy.memAction ? "disabled" : ""}>Orphans loeschen</button>
                <button class="mcp-btn" data-mm-graph-action="prune" ${state.busy.memAction ? "disabled" : ""}>Weak edges prunen</button>
            </div>
        </section>

        <section class="mm-panel">
            <h5>Neighbors by Node-ID</h5>
            <div class="mm-search-bar">
                <input id="mm-node-id" class="mm-input mm-input-sm" type="number" min="1" value="${esc(state.mem.graph.nodeId || "")}" placeholder="node_id" />
                <button class="mcp-btn" data-mm-action="load-neighbors" ${state.busy.memAction ? "disabled" : ""}>Neighbors laden</button>
            </div>
            <div class="mm-list">
                ${
                    neighbors.length
                        ? neighbors
                            .slice(0, 30)
                            .map((n) => `<div class="mm-list-item"><strong>${esc(String(n.target_id ?? n.id ?? "-"))}</strong><small>${esc(mmShort(n.content || n.edge_type || "", 160))}</small></div>`)
                            .join("")
                        : '<div class="mcp-empty-inline">Noch keine Nachbarn geladen.</div>'
                }
            </div>
            ${
                state.mem.mode === "advanced"
                    ? `<details class="mm-raw"><summary>Graph-Output</summary><pre class="mm-pre">${esc(state.mem.graph.actionOutput || state.mem.graph.neighborsRaw || "{}")}</pre></details>`
                    : ""
            }
        </section>
    `;
}

function mmRenderSettings() {
    const sub = String(state.mem.settingsTab || "embeddings");
    const embeddings = state.mem.embeddings || {};
    const secrets = state.mem.secrets || [];
    const embedBody =
        sub === "embeddings"
            ? `
        <section class="mm-panel">
            <h5>Embeddings</h5>
            <p class="mm-hint">Version-Status und Backfill fuer veraltete oder fehlende Embeddings.</p>
            <details class="mm-raw" open>
                <summary>Status</summary>
                <pre class="mm-pre">${esc(mmSafeJson(embeddings, 7000))}</pre>
            </details>
            <div class="mm-search-bar">
                <input id="mm-backfill-batch" class="mm-input mm-input-sm" type="number" min="1" max="1000" value="${esc(state.mem.embedBackfill.batchSize)}" />
                <label class="mm-inline-check"><input id="mm-backfill-dry" type="checkbox" ${state.mem.embedBackfill.dryRun ? "checked" : ""} /> Dry-Run</label>
                <button class="mcp-btn primary" data-mm-action="run-backfill" ${state.busy.memAction ? "disabled" : ""}>Backfill ausfuehren</button>
            </div>
            ${
                state.mem.embedBackfill.output
                    ? `<details class="mm-raw"><summary>Backfill-Output</summary><pre class="mm-pre">${esc(state.mem.embedBackfill.output)}</pre></details>`
                    : ""
            }
        </section>
    `
            : `
        <section class="mm-panel">
            <h5>Security</h5>
            <p class="mm-hint">Secrets werden nur mit Namen angezeigt. Werte werden nie gerendert.</p>
            <div class="mm-search-bar">
                <input id="mm-secret-name" class="mm-input" placeholder="Secret Name" value="${esc(state.mem.security.newSecretName)}" />
                <input id="mm-secret-value" class="mm-input" type="password" placeholder="Secret Value" value="${esc(state.mem.security.newSecretValue)}" />
                <button class="mcp-btn" data-mm-action="save-secret" ${state.busy.memAction ? "disabled" : ""}>Secret speichern</button>
            </div>
            <div class="mm-list">
                ${
                    secrets.length
                        ? secrets
                            .map(
                                (sec) => `
                            <div class="mm-list-item mm-list-item-row">
                                <div>
                                    <strong>${esc(sec.name || "-")}</strong>
                                    <small>updated: ${esc(mmFormatDate(sec.updated_at || sec.created_at))}</small>
                                </div>
                                <button class="mcp-btn danger" data-mm-secret-delete="${esc(sec.name || "")}" ${state.busy.memAction ? "disabled" : ""}>Delete</button>
                            </div>
                        `
                            )
                            .join("")
                        : '<div class="mcp-empty-inline">Keine Secrets vorhanden.</div>'
                }
            </div>
            <div class="mm-danger">
                <h6>Danger Zone</h6>
                <p>Kompletten Memory-Speicher unwiderruflich loeschen.</p>
                <input id="mm-reset-confirm" class="mm-input" placeholder='Tippe "RESET MEMORY"' value="${esc(state.mem.security.resetConfirm)}" />
                <button class="mcp-btn danger" data-mm-action="reset-memory" ${state.busy.memAction ? "disabled" : ""}>Memory reset</button>
            </div>
            ${
                state.mem.security.output
                    ? `<details class="mm-raw"><summary>Security-Output</summary><pre class="mm-pre">${esc(state.mem.security.output)}</pre></details>`
                    : ""
            }
        </section>
    `;

    return `
        <div class="mm-subtabs">
            <button class="mm-subtab ${sub === "embeddings" ? "active" : ""}" data-mm-settings-tab="embeddings">Embeddings</button>
            <button class="mm-subtab ${sub === "security" ? "active" : ""}" data-mm-settings-tab="security">Security</button>
        </div>
        ${embedBody}
    `;
}

function renderSqlMemoryDetail(selected, details, tools) {
    const root = document.getElementById("mcp-detail");
    if (!root) return;

    const tab = String(state.mem.tab || "overview");
    const tabs = [
        { id: "overview", label: "Uebersicht" },
        { id: "search", label: "Suche" },
        { id: "maintenance", label: "Wartung" },
        { id: "graph", label: "Graph" },
        { id: "settings", label: "Einstellungen" },
    ];

    let body = "";
    if (tab === "search") body = mmRenderSearch();
    else if (tab === "maintenance") body = mmRenderMaintenance();
    else if (tab === "graph") body = mmRenderGraph();
    else if (tab === "settings") body = mmRenderSettings();
    else body = mmRenderOverview();

    root.innerHTML = `
        <div class="mcp-detail-block">
            <div class="mcp-kv"><span>Name</span><strong>${esc(details?.name || selected?.name || "sql-memory")}</strong></div>
            <div class="mcp-kv"><span>Status</span><strong>${statusBadge(selected || {})}</strong></div>
            <div class="mcp-kv"><span>Tools</span><strong>${Number(Array.isArray(tools) ? tools.length : 0)}</strong></div>
            <div class="mcp-kv"><span>Mode</span><strong>${esc(state.mem.mode === "advanced" ? "Advanced" : "Basic")}</strong></div>
        </div>

        <div class="mcp-detail-block mm-shell">
            <div class="mm-head">
                <h4>SQL Memory</h4>
                <div class="mm-head-actions">
                    <button class="mcp-btn ${state.mem.mode === "basic" ? "primary" : ""}" data-mm-mode="basic">Basic</button>
                    <button class="mcp-btn ${state.mem.mode === "advanced" ? "primary" : ""}" data-mm-mode="advanced">Advanced</button>
                </div>
            </div>
            <div class="mm-tabs">
                ${tabs
                    .map(
                        (item) => `
                    <button class="mm-tab ${tab === item.id ? "active" : ""}" data-mm-tab="${item.id}">${item.label}</button>
                `
                    )
                    .join("")}
            </div>
            ${state.mem.loadError ? `<p class="mm-error">${esc(state.mem.loadError)}</p>` : ""}
            <div class="mm-body">
                ${body}
            </div>
        </div>
    `;

    root.querySelectorAll("[data-mm-mode]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.mem.mode = String(btn.getAttribute("data-mm-mode") || "basic");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-mm-tab]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.mem.tab = String(btn.getAttribute("data-mm-tab") || "overview");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-mm-settings-tab]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.mem.settingsTab = String(btn.getAttribute("data-mm-settings-tab") || "embeddings");
            renderDetail();
        });
    });

    root.querySelector("[data-mm-action='probe']")?.addEventListener("click", () => {
        mmProbeHealth();
    });
    root.querySelector("[data-mm-action='refresh']")?.addEventListener("click", () => {
        mmRefreshAll();
    });

    root.querySelector("#mm-search-query")?.addEventListener("input", (e) => {
        state.mem.search.query = String(e.target?.value || "");
    });
    root.querySelector("#mm-search-query")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") mmRunSearch();
    });
    root.querySelector("#mm-search-mode")?.addEventListener("change", (e) => {
        state.mem.search.mode = String(e.target?.value || "fts");
    });
    root.querySelector("#mm-search-limit")?.addEventListener("input", (e) => {
        state.mem.search.limit = Number.parseInt(String(e.target?.value || "20"), 10) || 20;
    });
    root.querySelector("#mm-search-conv")?.addEventListener("input", (e) => {
        state.mem.search.conversationId = String(e.target?.value || "");
    });
    root.querySelector("[data-mm-action='run-search']")?.addEventListener("click", () => {
        mmRunSearch();
    });

    root.querySelectorAll("[data-mm-result]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.mem.search.selectedKey = String(btn.getAttribute("data-mm-result") || "");
            renderDetail();
        });
    });
    root.querySelectorAll("[data-mm-delete-id]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const id = String(btn.getAttribute("data-mm-delete-id") || "");
            if (!window.confirm(`Memory-Eintrag ${id} wirklich loeschen?`)) return;
            mmDeleteMemoryEntry(id);
        });
    });
    root.querySelectorAll("[data-mm-save-workspace]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const key = String(btn.getAttribute("data-mm-save-workspace") || "");
            const rows = state.mem.search.results || [];
            const item = rows.find((row, idx) => mmResultKey(row, idx) === key);
            if (item) mmSaveSearchResultToWorkspace(item);
        });
    });

    root.querySelector("[data-mm-action='start-maintenance']")?.addEventListener("click", () => {
        mmStartMaintenance(root);
    });
    root.querySelector("[data-mm-action='cancel-maintenance']")?.addEventListener("click", () => {
        mmCancelMaintenance();
    });

    root.querySelectorAll("[data-mm-graph-action]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const action = String(btn.getAttribute("data-mm-graph-action") || "refresh");
            mmGraphAction(action);
        });
    });
    root.querySelector("[data-mm-action='load-neighbors']")?.addEventListener("click", () => {
        const nodeId = String(root.querySelector("#mm-node-id")?.value || "");
        mmLoadNeighbors(nodeId);
    });

    root.querySelector("[data-mm-action='run-backfill']")?.addEventListener("click", () => {
        mmRunBackfill(root);
    });
    root.querySelector("[data-mm-action='save-secret']")?.addEventListener("click", () => {
        mmSaveSecret(root);
    });
    root.querySelectorAll("[data-mm-secret-delete]").forEach((btn) => {
        btn.addEventListener("click", () => {
            mmDeleteSecret(String(btn.getAttribute("data-mm-secret-delete") || ""));
        });
    });
    root.querySelector("[data-mm-action='reset-memory']")?.addEventListener("click", () => {
        mmResetMemory(root);
    });
}

export function initToolsApp() {
    const root = document.getElementById("app-tools");
    if (!root) return;

    renderLayout(root);
    bindEvents(root);
    renderHeaderActions();
    renderMcpList();
    renderDetailActions();
    renderDetail();

    refreshAll();
}
