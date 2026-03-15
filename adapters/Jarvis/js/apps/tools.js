/**
 * tools.js - MCP Manager App (Modern V1)
 * Features:
 * - MCP list with search and status badges
 * - MCP detail panel on click
 * - Enable/Disable (custom MCPs)
 * - Restart/reload MCP hub
 * - Config editor for custom MCPs
 */

function getApiBase() {
    if (typeof window.getApiBase === "function") {
        return window.getApiBase();
    }
    if (window.location.port === "3000" || window.location.port === "80" || window.location.port === "") {
        return "";
    }
    return `${window.location.protocol}//${window.location.hostname}:8200`;
}

function esc(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
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
        sbSave: false,
        sbLoadDisks: false,
        sbAction: false,
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
    // Storage Broker specific state
    sb: {
        settings: null,
        disks: [],
        summary: null,
        audit: [],
        managedPaths: [],
        activeTab: "overview",   // overview | setup | disks | managed_paths | policies | audit
        mode: "basic",           // basic | advanced
        loaded: false,
        selectedDiskId: "",
        expanded: {},
        diskSearch: "",
        diskFilter: "all",       // all | recommended | protected | managed
        diskTab: "details",      // details | partition | rechte | ordner | sicherheit
        auditFilter: "all",      // all | allowed | blocked | provisioning | mount | format
        setup: {
            open: false,
            flow: "",            // backup | services | existing_path | import_ro
            step: 1,
            values: {},
            result: "",
        },
        preview: null,
    },
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
    const toggleDisabled = state.busy.toggle || !isEditable || isCoreProtected;
    const deleteDisabled = state.busy.deleteMcp || !isEditable || isCoreProtected;
    const enableLabel = selected.enabled ? "Disable" : "Enable";

    el.innerHTML = `
        <button id="mcp-toggle-btn" class="mcp-btn" ${toggleDisabled ? "disabled" : ""}>${state.busy.toggle ? "Working..." : enableLabel}</button>
        <button id="mcp-delete-btn" class="mcp-btn danger" ${deleteDisabled ? "disabled" : ""}>${state.busy.deleteMcp ? "Deleting..." : "Delete"}</button>
    `;

    document.getElementById("mcp-toggle-btn")?.addEventListener("click", toggleSelectedMcp);
    document.getElementById("mcp-delete-btn")?.addEventListener("click", deleteSelectedMcp);
}

function renderDetail() {
    const root = document.getElementById("mcp-detail");
    const appRoot = document.getElementById("app-tools");
    if (!root) return;

    const selected = state.mcps.find((m) => String(m.name || "") === state.selected);
    if (!selected) {
        if (appRoot) appRoot.setAttribute("data-sb-focus", "0");
        root.innerHTML = `<div class="mcp-empty">Select an MCP from the left to view details and settings.</div>`;
        return;
    }

    if (appRoot) {
        const focused = isStorageBroker(state.selected) || isSqlMemoryMcp(state.selected);
        appRoot.setAttribute("data-sb-focus", focused ? "1" : "0");
    }

    // Storage Broker gets its own rich settings panel
    if (isStorageBroker(state.selected)) {
        if (!state.sb.loaded) {
            sbLoadAll().then(() => renderDetail());
            root.innerHTML = `<div class="mcp-empty">Storage Broker wird geladen...</div>`;
            return;
        }
        if (!state.sb.disks.length && !state.busy.sbLoadDisks) {
            sbLoadDisks();
        }
        renderStorageBrokerDetail();
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
    const rows = Array.isArray(data?.mcps) ? data.mcps : [];
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

function isCoreProtectedMcp(name) {
    return CORE_PROTECTED_MCPS.has(String(name || "").trim().toLowerCase());
}

function isTimeMcp(name) {
    return String(name || "").toLowerCase().replace(/[-_]/g, "") === "timemcp";
}

function tmDefaultConfig() {
    return {
        name: "time-mcp",
        tier: "simple",
        url: "http://localhost:8090",
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
    if (!String(nextConfig.url || "").trim()) nextConfig.url = "http://localhost:8090";
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
    const saveRuntimeDisabled = state.busy.seqSave || state.busy.seqLoad;
    const saveMasterDisabled = state.busy.seqMasterSave || state.busy.seqLoad;
    const probeDisabled = state.busy.seqHealth || !Boolean(selected?.online);
    const probeText = String(state.seq.probeOutput || "").trim();
    const probeSummary = String(state.seq.probeSummary || "").trim();

    root.innerHTML = `
        <div class="mcp-detail-block">
            <div class="mcp-kv"><span>Name</span><strong>${esc(details?.name || selected?.name || "sequential-thinking")}</strong></div>
            <div class="mcp-kv"><span>Status</span><strong>${statusBadge(selected || {})}</strong></div>
            <div class="mcp-kv"><span>Tools</span><strong>${Number(Array.isArray(tools) ? tools.length : 0)}</strong></div>
            <div class="mcp-kv"><span>Planning Readiness</span><strong>${planning.sequential_thinking ? "ready" : "missing"} / workspace=${planning.workspace_event_save && planning.workspace_event_list ? "ready" : "missing"}</strong></div>
        </div>

        <div class="mcp-detail-block sq-panel">
            <div class="sq-head">
                <h4>Sequential Readiness</h4>
                <button id="sq-run-probe" class="mcp-btn" ${probeDisabled ? "disabled" : ""}>${state.busy.seqHealth ? "Pruefe..." : "Probe (think_simple)"}</button>
            </div>
            <div class="sq-health-grid">
                <div><span>MCP Online</span><strong>${selected?.online ? "ja" : "nein"}</strong></div>
                <div><span>Planning Tools</span><strong>${planningAll ? "vollstaendig" : "teilweise"}</strong></div>
                <div><span>Sequential Tool</span><strong>${planning.sequential_thinking ? "bereit" : "fehlt"}</strong></div>
                <div><span>Workspace Save</span><strong>${planning.workspace_event_save ? "bereit" : "fehlt"}</strong></div>
                <div><span>Workspace List</span><strong>${planning.workspace_event_list ? "bereit" : "fehlt"}</strong></div>
                <div><span>Master Thinking</span><strong>${master.use_thinking_layer ? "aktiv" : "inaktiv"}</strong></div>
            </div>
            ${state.seq.probeError ? `<p class="sq-error">Probe error: ${esc(state.seq.probeError)}</p>` : ""}
            <p class="sq-probe-summary">
                ${esc(probeSummary || 'Noch keine Probe ausgefuehrt. "Probe (think_simple)" startet einen kurzen E2E-Test ueber den Sequential-Toolpfad.')}
            </p>
            ${
                probeText
                    ? `
                <details class="sq-probe-raw">
                    <summary>Probe-Rohdaten anzeigen${state.seq.probeTruncated ? " (gekuerzt)" : ""}</summary>
                    <pre class="sq-probe-output">${esc(probeText)}</pre>
                </details>
            `
                    : ""
            }
        </div>

        <div class="mcp-detail-block sq-panel">
            <h4>Master Orchestrator</h4>
            <div class="sq-master-grid">
                <label class="sq-toggle"><input id="sq-master-enabled" type="checkbox" ${master.enabled ? "checked" : ""} /> <span>Master aktiviert</span></label>
                <label class="sq-toggle"><input id="sq-master-thinking" type="checkbox" ${master.use_thinking_layer ? "checked" : ""} /> <span>Thinking Layer nutzen</span></label>
                <label class="sq-row">
                    <span class="sq-field-label">Max Loops</span>
                    <input id="sq-master-max-loops" class="sq-input" type="number" min="1" max="200" value="${esc(master.max_loops ?? 10)}" />
                </label>
                <label class="sq-row">
                    <span class="sq-field-label">Completion Threshold</span>
                    <input id="sq-master-completion-threshold" class="sq-input" type="number" min="1" max="10" value="${esc(master.completion_threshold ?? 2)}" />
                </label>
            </div>
            <div class="sq-actions">
                <button id="sq-save-master" class="mcp-btn primary" ${saveMasterDisabled ? "disabled" : ""}>${state.busy.seqMasterSave ? "Speichere..." : "Master speichern"}</button>
            </div>
        </div>

        <div class="mcp-detail-block sq-panel">
            <h4>Sequential Runtime Policy</h4>
            <p class="sq-hint">Diese Werte steuern, wann Sequential aktiviert wird und wie aggressiv Budget/Loop-Regeln greifen.</p>
            <div class="sq-runtime-grid">
                ${SQ_RUNTIME_FIELDS.map((field) => sqRenderRuntimeField(field)).join("")}
            </div>
            <div class="sq-actions">
                <button id="sq-save-runtime" class="mcp-btn primary" ${saveRuntimeDisabled ? "disabled" : ""}>${state.busy.seqSave ? "Speichere..." : "Runtime Policy speichern"}</button>
            </div>
        </div>
    `;

    root.querySelector("#sq-run-probe")?.addEventListener("click", () => {
        sqRunProbe();
    });
    root.querySelector("#sq-save-runtime")?.addEventListener("click", () => {
        sqSaveRuntime(root);
    });
    root.querySelector("#sq-save-master")?.addEventListener("click", () => {
        sqSaveMaster(root);
    });
}

// ══════════════════════════════════════════════════════════
// SQL MEMORY MCP — Operations Panel
// ══════════════════════════════════════════════════════════

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

// ══════════════════════════════════════════════════════════
// STORAGE BROKER — Custom Settings Panel
// ══════════════════════════════════════════════════════════

function isStorageBroker(name) {
    return String(name || "").toLowerCase().replace(/[-_]/g, "") === "storagebroker";
}

const SB_NAV_ITEMS = [
    { id: "overview", label: "Uebersicht" },
    { id: "setup", label: "Einrichtung" },
    { id: "disks", label: "Datentraeger" },
    { id: "managed_paths", label: "Verwaltete Pfade" },
    { id: "policies", label: "Richtlinien" },
    { id: "audit", label: "Audit" },
];

const SB_POLICY_META = {
    blocked: { label: "Geschuetzt", className: "sb-policy-blocked", description: "Nicht nutzbar fuer TRION." },
    read_only: { label: "Nur Lesen", className: "sb-policy-ro", description: "Sicher lesbar, keine Schreibrechte." },
    managed_rw: { label: "Von TRION verwaltet", className: "sb-policy-rw", description: "Schreiben nur in freigegebenen Bereichen." },
};

const SB_ZONE_META = {
    system: "Systemspeicher",
    managed_services: "Service-Speicher",
    backup: "Backup-Speicher",
    external: "Externer Datentraeger",
    docker_runtime: "Docker-Laufzeit",
    unzoned: "Noch nicht eingerichtet",
};

const SB_RISK_META = {
    critical: { label: "Kritisch", className: "sb-risk-critical" },
    caution: { label: "Vorsicht", className: "sb-risk-caution" },
    safe: { label: "Sicher", className: "sb-risk-safe" },
};

const SB_SETUP_FLOW_META = {
    backup: { label: "Backup-Speicher", zone: "backup", policy_state: "managed_rw", service_name: "backup", profile: "backup" },
    services: { label: "Container-Speicher", zone: "managed_services", policy_state: "managed_rw", service_name: "containers", profile: "standard" },
    existing_path: { label: "Bestehenden Pfad freigeben", zone: "managed_services", policy_state: "managed_rw", service_name: "service", profile: "standard" },
    import_ro: { label: "Nur-Lesen Import", zone: "external", policy_state: "read_only", service_name: "import", profile: "minimal" },
};

function sbLabelPolicy(policy) {
    const meta = SB_POLICY_META[String(policy || "").trim()] || null;
    return meta ? meta.label : (policy || "Unbekannt");
}

function sbLabelZone(zone) {
    return SB_ZONE_META[String(zone || "").trim()] || (zone || "Unbekannt");
}

function sbSafeIso(ts) {
    const raw = String(ts || "").trim();
    if (!raw) return "-";
    return raw.slice(0, 19).replace("T", " ");
}

function sbRiskBadge(risk) {
    const key = String(risk || "caution").trim();
    const meta = SB_RISK_META[key] || SB_RISK_META.caution;
    return `<span class="sb-badge ${meta.className}">${esc(meta.label)}</span>`;
}

function sbPolicyBadge(policy) {
    const key = String(policy || "blocked").trim();
    const meta = SB_POLICY_META[key] || SB_POLICY_META.blocked;
    return `<span class="sb-badge ${meta.className}" title="${esc(key)}">${esc(meta.label)}</span>`;
}

function sbFormatBytes(b) {
    if (!b) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = Number(b);
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${v.toFixed(1)} ${units[i]}`;
}

function sbParentDevice(device, id) {
    const dev = String(device || "").trim() || `/dev/${String(id || "").trim()}`;
    if (/^\/dev\/nvme\d+n\d+p\d+$/.test(dev) || /^\/dev\/mmcblk\d+p\d+$/.test(dev)) {
        return dev.replace(/p\d+$/, "");
    }
    if (/^\/dev\/[a-z]+[0-9]+$/.test(dev)) {
        return dev.replace(/[0-9]+$/, "");
    }
    return "";
}

function sbBuildDiskTree(disks) {
    const items = Array.isArray(disks) ? disks : [];
    const roots = items.filter((d) => String(d.disk_type || "") === "disk");
    const rootByDevice = new Map(roots.map((r) => [String(r.device || ""), r]));
    const childrenByRootId = new Map(roots.map((r) => [String(r.id || ""), []]));
    const orphans = [];

    items
        .filter((d) => String(d.disk_type || "") !== "disk")
        .forEach((part) => {
            const parentDevice = sbParentDevice(part.device, part.id);
            const parent = rootByDevice.get(parentDevice);
            if (!parent) {
                orphans.push(part);
                return;
            }
            const key = String(parent.id || "");
            const list = childrenByRootId.get(key) || [];
            list.push(part);
            childrenByRootId.set(key, list);
        });

    roots.sort((a, b) => String(a.device || a.id || "").localeCompare(String(b.device || b.id || "")));
    for (const list of childrenByRootId.values()) {
        list.sort((a, b) => String(a.device || a.id || "").localeCompare(String(b.device || b.id || "")));
    }
    orphans.sort((a, b) => String(a.device || a.id || "").localeCompare(String(b.device || b.id || "")));
    return { roots, childrenByRootId, orphans };
}

function sbDiskHumanSummary(disk) {
    if (!disk) return "Kein Datentraeger ausgewaehlt.";
    if (disk.is_system) {
        return "Diese Festplatte gehoert zum Host-System und bleibt dauerhaft geschuetzt.";
    }
    if (String(disk.policy_state || "") === "managed_rw") {
        return "Diese Festplatte ist fuer TRION freigegeben. Schreibzugriffe sind auf verwaltete Bereiche beschraenkt.";
    }
    if (String(disk.policy_state || "") === "read_only") {
        return "Diese Festplatte ist erkannt und aktuell nur lesbar. Du kannst sie sicher fuer Setup-Schritte vorbereiten.";
    }
    return "Diese Festplatte ist aktuell geschuetzt. Du kannst sie pruefen und gezielt konfigurieren.";
}

function sbDiskRecommendedRole(disk) {
    if (!disk || disk.is_system) return "Geschuetzt";
    if (disk.is_external || disk.is_removable) return "Backup-Ziel";
    if (String(disk.policy_state || "") === "managed_rw") return "Service-Speicher";
    return "Zur Einrichtung pruefen";
}

function sbDiskAllowedActions(disk) {
    if (!disk) return [];
    if (disk.is_system) return ["Pruefen", "Audit anzeigen"];
    const actions = ["Pruefen", "Rolle zuweisen", "Dry-Run starten"];
    if (String(disk.policy_state || "") === "managed_rw") actions.push("Verwalteten Ordner erstellen");
    return actions;
}

function sbDiskFilterMatch(disk, filter) {
    const f = String(filter || "all");
    if (f === "recommended") return !disk.is_system && (disk.policy_state === "read_only" || disk.zone === "unzoned");
    if (f === "protected") return Boolean(disk.is_system || disk.policy_state === "blocked");
    if (f === "managed") return String(disk.policy_state || "") === "managed_rw";
    return true;
}

function sbDiskSearchMatch(disk, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return true;
    const hay = [
        disk.id, disk.device, disk.device_path, disk.label, disk.model, disk.device_model,
        disk.filesystem, disk.zone, disk.policy_state, disk.mountpoint, disk.mount_path,
    ].map((v) => String(v || "").toLowerCase()).join(" ");
    return hay.includes(q);
}

function sbDefaultSetupValues(flow) {
    const meta = SB_SETUP_FLOW_META[flow] || SB_SETUP_FLOW_META.services;
    return {
        disk_id: state.sb.selectedDiskId || "",
        zone: meta.zone,
        policy_state: meta.policy_state,
        service_name: meta.service_name,
        profile: meta.profile,
        existing_path: "",
        do_format: false,
        filesystem: "ext4",
        label: "",
        do_mount: false,
        mountpoint: "",
        mount_options: "",
    };
}

function sbOpenSetup(flow, preset = {}) {
    const values = { ...sbDefaultSetupValues(flow), ...preset };
    state.sb.setup = {
        open: true,
        flow,
        step: 1,
        values,
        result: "",
    };
    state.sb.activeTab = "setup";
    renderDetail();
}

function sbCloseSetup() {
    state.sb.setup = {
        open: false,
        flow: "",
        step: 1,
        values: {},
        result: "",
    };
    renderDetail();
}

function sbReadSetupFields(root) {
    if (!state.sb.setup?.open) return;
    const values = { ...(state.sb.setup.values || {}) };
    root.querySelectorAll("[data-sb-field]").forEach((el) => {
        const key = String(el.getAttribute("data-sb-field") || "").trim();
        if (!key) return;
        if (el.type === "checkbox") {
            values[key] = Boolean(el.checked);
        } else {
            values[key] = String(el.value || "");
        }
    });
    state.sb.setup.values = values;
}

function sbFindDiskById(diskId) {
    const id = String(diskId || "").trim();
    return (state.sb.disks || []).find((d) => String(d.id || "") === id) || null;
}

function sbBuildSetupPreview() {
    const flow = String(state.sb.setup?.flow || "");
    const values = state.sb.setup?.values || {};
    const disk = sbFindDiskById(values.disk_id);
    let risk = "Low";
    if (values.do_format) risk = "High";
    else if (values.do_mount) risk = "Medium";
    const target = flow === "existing_path"
        ? (values.existing_path || "-")
        : (disk?.device || disk?.id || "-");
    const actionLabel = SB_SETUP_FLOW_META[flow]?.label || "Einrichtung";
    return {
        target,
        actionLabel,
        writeScope: flow === "import_ro" ? "Keine Schreibrechte auf Datentraeger" : "Nur verwaltete Zielpfade",
        formatting: values.do_format ? `Ja (${values.filesystem || "ext4"})` : "Nein",
        mountChange: values.do_mount ? `Ja (${values.mountpoint || "ohne Ziel"})` : "Nein",
        risk,
    };
}

function sbResultLabel(result) {
    const r = result?.result || result || {};
    if (r.error) return `Fehler: ${r.error}`;
    if (r.ok === true && r.executed) return "Erfolgreich ausgefuehrt";
    if (r.ok === true && r.dry_run) return "Dry-Run Vorschau bereit";
    if (r.ok === true) return "Erfolgreich";
    return "Unbekanntes Ergebnis";
}

async function sbLoadAll() {
    try {
        const [settingsRes, summaryRes, auditRes, managedRes] = await Promise.allSettled([
            apiJson("/api/storage-broker/settings"),
            apiJson("/api/storage-broker/summary"),
            apiJson("/api/storage-broker/audit?limit=80"),
            apiJson("/api/storage-broker/managed-paths"),
        ]);
        if (settingsRes.status === "fulfilled") state.sb.settings = settingsRes.value?.settings || null;
        if (summaryRes.status === "fulfilled") state.sb.summary = summaryRes.value?.summary || null;
        if (auditRes.status === "fulfilled") state.sb.audit = auditRes.value?.entries || [];
        if (managedRes.status === "fulfilled") state.sb.managedPaths = managedRes.value?.managed_paths || [];
        state.sb.loaded = true;
        renderDetail();
    } catch (e) {
        setFeedback(`Storage Broker Ladefehler: ${e.message}`, "err");
    }
}

async function sbLoadDisks() {
    setBusy("sbLoadDisks", true);
    try {
        const data = await apiJson("/api/storage-broker/disks");
        state.sb.disks = data?.disks || data?.result?.disks || [];
        const hasSelected = state.sb.disks.some((d) => String(d.id || "") === state.sb.selectedDiskId);
        if (!hasSelected) {
            const firstDisk = state.sb.disks.find((d) => String(d.disk_type || "") === "disk") || state.sb.disks[0];
            state.sb.selectedDiskId = String(firstDisk?.id || "");
        }
        renderDetail();
    } catch (e) {
        setFeedback(`Datentraeger konnten nicht geladen werden: ${e.message}`, "err");
    } finally {
        setBusy("sbLoadDisks", false);
    }
}

async function sbSaveSettings(updates) {
    setBusy("sbSave", true);
    try {
        const data = await apiJson("/api/storage-broker/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updates),
        });
        state.sb.settings = data?.settings || state.sb.settings;
        setFeedback("Storage Broker Einstellungen gespeichert", "ok");
        renderDetail();
    } catch (e) {
        setFeedback(`Speichern fehlgeschlagen: ${e.message}`, "err");
    } finally {
        setBusy("sbSave", false);
    }
}

async function sbSaveDiskPolicy(diskId, updates) {
    const id = String(diskId || "").trim();
    if (!id) return { ok: false, error: "disk_id fehlt" };
    const data = await apiJson(`/api/storage-broker/disks/${encodeURIComponent(id)}/policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates || {}),
    });
    if (data?.ok === false) {
        const msg = Array.isArray(data?.errors) && data.errors.length ? data.errors.join("; ") : "Datentraeger-Update fehlgeschlagen";
        throw new Error(msg);
    }
    return data;
}

async function sbValidatePath(path) {
    return apiJson("/api/storage-broker/validate-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
    });
}

async function sbProvisionServiceDir(args) {
    return apiJson("/api/storage-broker/provision/service-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbMountDevice(args) {
    return apiJson("/api/storage-broker/mount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbFormatDevice(args) {
    return apiJson("/api/storage-broker/format", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args || {}),
    });
}

async function sbExecuteSetup(dryRun) {
    const flow = String(state.sb.setup?.flow || "");
    const values = state.sb.setup?.values || {};
    const disk = sbFindDiskById(values.disk_id);
    const messages = [];

    setBusy("sbAction", true);
    try {
        if (flow === "existing_path") {
            const path = String(values.existing_path || "").trim();
            if (!path) throw new Error("Bitte einen Pfad angeben.");
            const validation = await sbValidatePath(path);
            const vr = validation?.validation || {};
            messages.push(`Pfadpruefung: ${vr.valid ? "ok" : "blockiert"} (${vr.reason || "kein Grund"})`);
            if (!dryRun) {
                const existing = Array.isArray(state.sb.settings?.managed_bases) ? [...state.sb.settings.managed_bases] : [];
                if (!existing.includes(path)) existing.push(path);
                await sbSaveSettings({ managed_bases: existing });
                messages.push("Pfad in managed_bases aufgenommen.");
            }
        } else {
            if (!disk) throw new Error("Bitte einen Datentraeger waehlen.");
            if (disk.is_system) throw new Error("Systemdatentraeger kann nicht neu zugewiesen werden.");

            if (!dryRun) {
                await sbSaveDiskPolicy(String(disk.id || ""), {
                    zone: values.zone || "managed_services",
                    policy_state: values.policy_state || "managed_rw",
                });
                messages.push(`Disk ${disk.id}: zone=${values.zone} policy=${values.policy_state} gesetzt.`);
            } else {
                messages.push(`Vorschau: Disk ${disk.id} -> zone=${values.zone}, policy=${values.policy_state}`);
            }

            if (values.do_format) {
                const formatRes = await sbFormatDevice({
                    device: disk.device,
                    filesystem: values.filesystem || "ext4",
                    label: values.label || "",
                    dry_run: dryRun,
                });
                messages.push(`Format: ${sbResultLabel(formatRes)}`);
            }

            if (values.do_mount) {
                const mountpoint = String(values.mountpoint || "").trim();
                if (!mountpoint) {
                    messages.push("Mount uebersprungen: mountpoint fehlt.");
                } else {
                    const mountRes = await sbMountDevice({
                        device: disk.device,
                        mountpoint,
                        filesystem: "",
                        options: values.mount_options || "",
                        dry_run: dryRun,
                    });
                    messages.push(`Mount: ${sbResultLabel(mountRes)}`);
                }
            }

            if (flow !== "import_ro") {
                const serviceName = String(values.service_name || "").trim() || "service";
                const provisionRes = await sbProvisionServiceDir({
                    service_name: serviceName,
                    zone: values.zone || "managed_services",
                    profile: values.profile || "standard",
                    dry_run: dryRun,
                });
                const pr = provisionRes?.result || {};
                if (pr?.errors?.length) {
                    messages.push(`Provisioning: Fehler (${pr.errors.join("; ")})`);
                } else {
                    const createdCount = Array.isArray(pr.created) ? pr.created.length : 0;
                    const planCount = Array.isArray(pr.paths_to_create) ? pr.paths_to_create.length : 0;
                    messages.push(`Provisioning: ${dryRun ? "Vorschau" : "Fertig"} (${dryRun ? planCount : createdCount} Pfad(e)).`);
                }
            }
        }

        state.sb.setup.step = 5;
        state.sb.setup.result = messages.join("\n");
        await Promise.all([sbLoadAll(), sbLoadDisks()]);
        setFeedback(dryRun ? "Dry-Run abgeschlossen" : "Einrichtung angewendet", "ok");
    } catch (e) {
        setFeedback(`Einrichtung fehlgeschlagen: ${e.message}`, "err");
        state.sb.setup.step = 5;
        state.sb.setup.result = `Fehler: ${e.message}`;
    } finally {
        setBusy("sbAction", false);
        renderDetail();
    }
}

function sbRenderOverview(disks, summary, managedPaths) {
    const tree = sbBuildDiskTree(disks);
    const physicalDisks = tree.roots;
    const systemCount = physicalDisks.filter((d) => d.is_system).length;
    const availableCount = physicalDisks.filter((d) => !d.is_system).length;
    const warnings = physicalDisks.filter((d) => !d.is_system && String(d.risk_level || "") !== "safe").length;
    const managedCount = managedPaths.length || Number(summary.managed_rw_count || 0);

    const recent = (state.sb.audit || []).slice(0, 4);

    return `
        <section class="sb-view-head">
            <h4>Speicher-Uebersicht</h4>
            <p>So sieht TRION auf einen Blick, was sicher nutzbar ist.</p>
        </section>

        <div class="sb-summary-grid">
            <article class="sb-summary-card">
                <h5>System geschuetzt</h5>
                <strong>${systemCount}</strong>
                <small>Host-Speicher hart blockiert</small>
            </article>
            <article class="sb-summary-card">
                <h5>Verfuegbare Datentraeger</h5>
                <strong>${availableCount}</strong>
                <small>Erkannt und pruefbar</small>
            </article>
            <article class="sb-summary-card">
                <h5>Verwalteter Speicher</h5>
                <strong>${managedCount}</strong>
                <small>Verwaltete Pfade / RW-Eintraege</small>
            </article>
            <article class="sb-summary-card">
                <h5>Warnungen</h5>
                <strong>${warnings}</strong>
                <small>Bitte pruefen</small>
            </article>
        </div>

        <div class="sb-recommended">
            <h5>Empfohlene naechste Schritte</h5>
            <div class="sb-chip-row">
                <button class="sb-btn" data-sb-setup-start="backup">Backup-Ziel einrichten</button>
                <button class="sb-btn" data-sb-setup-start="services">Container-Speicher vorbereiten</button>
                <button class="sb-btn" data-sb-nav="disks">Datentraeger-Sicherheit pruefen</button>
            </div>
        </div>

        <div class="sb-overview-grid">
            <article class="sb-summary-panel">
                <h5>Datentraeger-Status</h5>
                <ul>
                    <li>Systemdatentraeger-Schutz ist aktiv.</li>
                    <li>${availableCount} Datentraeger fuer gefuehrtes Setup verfuegbar.</li>
                    <li>Keine unbeschraenkten Schreibrechte ausserhalb verwalteter Bereiche.</li>
                </ul>
            </article>
            <article class="sb-summary-panel">
                <h5>Letzte Aktivitaet</h5>
                ${recent.length ? `
                    <ul>
                        ${recent.map((e) => `<li>${esc(e.operation || "op")} auf <code>${esc(e.target || "-")}</code> (${esc(e.error ? "blockiert" : (e.result || "ok"))})</li>`).join("")}
                    </ul>
                ` : `<p class="sb-hint">Keine aktuellen Audit-Eintraege.</p>`}
            </article>
        </div>
    `;
}

function sbRenderSetupWizard(disks) {
    const setup = state.sb.setup || {};
    const values = setup.values || {};
    const flow = String(setup.flow || "");
    const step = Number(setup.step || 1);
    const preview = sbBuildSetupPreview();
    const diskOptions = (disks || [])
        .filter((d) => String(d.disk_type || "") === "disk")
        .map((d) => `<option value="${esc(d.id)}" ${String(values.disk_id || "") === String(d.id || "") ? "selected" : ""}>${esc(d.id)} · ${esc(d.device)} · ${sbFormatBytes(d.size_bytes)}</option>`)
        .join("");

    return `
        <section class="sb-wizard">
            <header class="sb-wizard-head">
                <div>
                    <h5>${esc(SB_SETUP_FLOW_META[flow]?.label || "Einrichtung")}</h5>
                    <small>Schritt ${step} von 5</small>
                </div>
                <button class="sb-btn" data-sb-setup-cancel="1">Schliessen</button>
            </header>

            <div class="sb-wizard-steps">
                <span class="${step >= 1 ? "active" : ""}">1 Auswahl</span>
                <span class="${step >= 2 ? "active" : ""}">2 Sicherheit</span>
                <span class="${step >= 3 ? "active" : ""}">3 Konfiguration</span>
                <span class="${step >= 4 ? "active" : ""}">4 Vorschau</span>
                <span class="${step >= 5 ? "active" : ""}">5 Ausfuehren</span>
            </div>

            <div class="sb-wizard-body">
                ${step === 1 ? `
                    ${flow === "existing_path" ? `
                        <label>Pfad freigeben</label>
                        <input class="sb-input" data-sb-field="existing_path" value="${esc(values.existing_path || "")}" placeholder="/mnt/trion-data" />
                    ` : `
                        <label>Datentraeger waehlen</label>
                        <select data-sb-field="disk_id">
                            <option value="">Bitte waehlen</option>
                            ${diskOptions}
                        </select>
                    `}
                ` : ""}

                ${step === 2 ? `
                    <div class="sb-safety-review">
                        <p>Systemdatentraeger? <strong>${sbFindDiskById(values.disk_id)?.is_system ? "ja (blockiert)" : "nein"}</strong></p>
                        <p>Aktuelle Richtlinie: <strong>${esc(sbLabelPolicy(sbFindDiskById(values.disk_id)?.policy_state || values.policy_state))}</strong></p>
                        <p>Formatierung noetig? <strong>${values.do_format ? "ja" : "optional / nein"}</strong></p>
                        <p>Mount-Aenderung noetig? <strong>${values.do_mount ? "ja" : "nein"}</strong></p>
                    </div>
                ` : ""}

                ${step === 3 ? `
                    <div class="sb-form sb-form-compact">
                        ${flow !== "existing_path" ? `
                            <div class="sb-form-row">
                                <label>Zone</label>
                                <select data-sb-field="zone">
                                    ${["managed_services", "backup", "external", "unzoned"].map((z) => `<option value="${z}" ${values.zone === z ? "selected" : ""}>${esc(sbLabelZone(z))}</option>`).join("")}
                                </select>
                            </div>
                            <div class="sb-form-row">
                                <label>Richtlinie</label>
                                <select data-sb-field="policy_state">
                                    ${["blocked", "read_only", "managed_rw"].map((p) => `<option value="${p}" ${values.policy_state === p ? "selected" : ""}>${esc(sbLabelPolicy(p))}</option>`).join("")}
                                </select>
                            </div>
                        ` : ""}
                        ${flow !== "import_ro" && flow !== "existing_path" ? `
                            <div class="sb-form-row">
                                <label>Service-Name</label>
                                <input class="sb-input" data-sb-field="service_name" value="${esc(values.service_name || "")}" />
                            </div>
                            <div class="sb-form-row">
                                <label>Profil</label>
                                <select data-sb-field="profile">
                                    ${["standard", "full", "minimal", "backup"].map((p) => `<option value="${p}" ${values.profile === p ? "selected" : ""}>${esc(p)}</option>`).join("")}
                                </select>
                            </div>
                        ` : ""}
                        ${flow !== "existing_path" ? `
                            <div class="sb-form-row sb-toggle-row">
                                <label>Vor Nutzung formatieren</label>
                                <label class="sb-toggle">
                                    <input type="checkbox" data-sb-field="do_format" ${values.do_format ? "checked" : ""} />
                                    <span class="sb-toggle-slider"></span>
                                </label>
                            </div>
                            ${values.do_format ? `
                                <div class="sb-form-row">
                                    <label>Filesystem</label>
                                    <select data-sb-field="filesystem">
                                        ${["ext4", "xfs", "vfat", "btrfs"].map((fs) => `<option value="${fs}" ${values.filesystem === fs ? "selected" : ""}>${fs}</option>`).join("")}
                                    </select>
                                </div>
                                <div class="sb-form-row">
                                    <label>Label</label>
                                    <input class="sb-input" data-sb-field="label" value="${esc(values.label || "")}" />
                                </div>
                            ` : ""}
                            <div class="sb-form-row sb-toggle-row">
                                <label>Nach Setup mounten</label>
                                <label class="sb-toggle">
                                    <input type="checkbox" data-sb-field="do_mount" ${values.do_mount ? "checked" : ""} />
                                    <span class="sb-toggle-slider"></span>
                                </label>
                            </div>
                            ${values.do_mount ? `
                                <div class="sb-form-row">
                                    <label>Mountpoint</label>
                                    <input class="sb-input" data-sb-field="mountpoint" value="${esc(values.mountpoint || "")}" placeholder="/mnt/trion-data" />
                                </div>
                                <div class="sb-form-row">
                                    <label>Mount Options</label>
                                    <input class="sb-input" data-sb-field="mount_options" value="${esc(values.mount_options || "")}" placeholder="rw,noexec" />
                                </div>
                            ` : ""}
                        ` : ""}
                    </div>
                ` : ""}

                ${step === 4 ? `
                    <div class="sb-preview-card">
                        <h6>Sicherheits-Vorschau</h6>
                        <p><strong>Ziel:</strong> ${esc(preview.target)}</p>
                        <p><strong>Geplante Aktion:</strong> ${esc(preview.actionLabel)}</p>
                        <p><strong>Schreibzugriff nach Aktion:</strong> ${esc(preview.writeScope)}</p>
                        <p><strong>Formatierung:</strong> ${esc(preview.formatting)}</p>
                        <p><strong>Mount-Aenderung:</strong> ${esc(preview.mountChange)}</p>
                        <p><strong>Risiko:</strong> ${esc(preview.risk)}</p>
                        <p><strong>Audit-Eintrag:</strong> Ja</p>
                    </div>
                ` : ""}

                ${step === 5 ? `
                    <div class="sb-exec-result">
                        <h6>Ausfuehrungsergebnis</h6>
                        <pre>${esc(setup.result || "Noch kein Ergebnis.")}</pre>
                    </div>
                ` : ""}
            </div>

            <footer class="sb-wizard-actions">
                ${step > 1 && step < 5 ? `<button class="sb-btn" data-sb-setup-back="1">Zurueck</button>` : `<span></span>`}
                <div class="sb-wizard-actions-right">
                    ${step < 4 ? `<button class="sb-btn primary" data-sb-setup-next="1">Weiter</button>` : ""}
                    ${step === 4 ? `
                        <button class="sb-btn" data-sb-setup-run="dry">Dry-Run starten</button>
                        <button class="sb-btn primary" data-sb-setup-run="apply" ${state.busy.sbAction ? "disabled" : ""}>Jetzt anwenden</button>
                    ` : ""}
                    ${step === 5 ? `<button class="sb-btn primary" data-sb-setup-done="1">Fertig</button>` : ""}
                </div>
            </footer>
        </section>
    `;
}

function sbRenderSetup(disks) {
    const setupOpen = Boolean(state.sb.setup?.open);
    return `
        <section class="sb-view-head">
            <h4>Speicher-Einrichtung</h4>
            <p>Waehle eine Aufgabe, statt rohe Policy-Werte manuell zu setzen.</p>
        </section>
        <div class="sb-setup-grid">
            <article class="sb-setup-card">
                <h5>Backup-Speicher einrichten</h5>
                <p>Datentraeger oder Ordner fuer Backups vorbereiten.</p>
                <button class="sb-btn" data-sb-setup-start="backup">Starten</button>
            </article>
            <article class="sb-setup-card">
                <h5>Container-Speicher vorbereiten</h5>
                <p>Verwaltete Service-Struktur erstellen.</p>
                <button class="sb-btn" data-sb-setup-start="services">Starten</button>
            </article>
            <article class="sb-setup-card">
                <h5>Bestehenden Pfad freigeben</h5>
                <p>Einen vorhandenen Pfad sicher erlauben.</p>
                <button class="sb-btn" data-sb-setup-start="existing_path">Starten</button>
            </article>
            <article class="sb-setup-card">
                <h5>Nur-Lesen Importquelle</h5>
                <p>Datentraeger ohne Schreibrechte einbinden.</p>
                <button class="sb-btn" data-sb-setup-start="import_ro">Starten</button>
            </article>
        </div>
        ${setupOpen ? sbRenderSetupWizard(disks) : ""}
    `;
}

function sbDiskDevicePath(disk) {
    return String(disk?.device_path || disk?.device || "").trim() || `/dev/${String(disk?.id || "-").trim()}`;
}

function sbDiskSizeLabel(disk) {
    const direct = String(disk?.size_human || "").trim();
    if (direct) return direct;
    return sbFormatBytes(disk?.size_bytes || 0);
}

function sbDiskDisplayName(disk) {
    const explicit = String(disk?.model || disk?.device_model || disk?.label || "").trim();
    if (explicit) return explicit;
    const device = sbDiskDevicePath(disk);
    const short = device.split("/").filter(Boolean).pop();
    return short || String(disk?.id || "Unbekannt");
}

function sbDiskPolicyKey(disk) {
    return String(disk?.policy_state || "").trim() || (disk?.is_system ? "blocked" : "read_only");
}

function sbDiskStatusClass(disk) {
    const policy = sbDiskPolicyKey(disk);
    if (policy === "blocked") return "protected";
    if (policy === "managed_rw") return "managed";
    return "readonly";
}

function sbDiskStatusLabel(disk) {
    const policy = sbDiskPolicyKey(disk);
    if (policy === "blocked") return "Geschützt";
    if (policy === "managed_rw") return "Verwaltet";
    return "Nur Lesen";
}

function sbDiskIconClass(disk) {
    const policy = sbDiskPolicyKey(disk);
    if (disk?.is_system || String(disk?.zone || "") === "system" || policy === "blocked") return "system";
    if (policy === "managed_rw") return "managed";
    return "external";
}

function sbLocaleInt(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return "-";
    return num.toLocaleString("de-DE");
}

function sbPartitionListForDisk(selectedDisk, tree) {
    if (!selectedDisk) return [];
    if (Array.isArray(selectedDisk.partitions) && selectedDisk.partitions.length) {
        return selectedDisk.partitions;
    }
    return tree.childrenByRootId.get(String(selectedDisk.id || "")) || [];
}

function sbRenderDisks(disks) {
    const query = String(state.sb.diskSearch || "").trim().toLowerCase();
    const mode = String(state.sb.mode || "basic");
    const tree = sbBuildDiskTree(disks);
    const filteredRoots = tree.roots.filter((d) => sbDiskFilterMatch(d, state.sb.diskFilter) && sbDiskSearchMatch(d, query));
    const selectedDisk = filteredRoots.find((d) => String(d.id || "") === String(state.sb.selectedDiskId || ""))
        || filteredRoots[0]
        || tree.roots.find((d) => String(d.id || "") === String(state.sb.selectedDiskId || ""))
        || tree.roots[0]
        || null;

    if (selectedDisk && String(state.sb.selectedDiskId || "") !== String(selectedDisk.id || "")) {
        state.sb.selectedDiskId = String(selectedDisk.id || "");
    }

    const diskTab = String(state.sb.diskTab || "details");
    const filterLabel = (f) => (f === "all" ? "Alle" : f === "recommended" ? "Empfohlen" : f === "protected" ? "Geschützt" : "Verwaltet");
    const policyKey = selectedDisk ? sbDiskPolicyKey(selectedDisk) : "blocked";
    const isSystemDisk = Boolean(selectedDisk?.is_system || String(selectedDisk?.zone || "") === "system" || policyKey === "blocked");
    const partitionRows = sbPartitionListForDisk(selectedDisk, tree);
    const partitionPalette = ["#22c55e", "#38bdf8", "#a78bfa", "#f59e0b", "#ef4444", "#14b8a6"];
    const rawManaged = Array.from(new Set([...(state.sb.summary?.managed_paths || []), ...(state.sb.managedPaths || [])]));
    const mountpoint = String(selectedDisk?.mountpoint || selectedDisk?.mount_path || "").trim();
    const managedForDisk = rawManaged.filter((path) => {
        const p = String(path || "").trim();
        if (!p) return false;
        if (mountpoint && mountpoint !== "/" && p.startsWith(mountpoint)) return true;
        if (selectedDisk?.id && p.includes(String(selectedDisk.id))) return true;
        const devToken = sbDiskDevicePath(selectedDisk).replace("/dev/", "");
        return devToken && p.includes(devToken);
    });
    const securityRows = [
        { label: "System-Disk", ok: isSystemDisk },
        { label: "Schreibschutz aktiv", ok: policyKey !== "managed_rw" },
        { label: "Pfad-Escape blockiert", ok: true },
        { label: "Audit-Logging", ok: true },
    ];
    const diskAudit = (state.sb.audit || []).filter((entry) => {
        const target = String(entry?.target || "").toLowerCase();
        const dev = sbDiskDevicePath(selectedDisk).toLowerCase();
        const id = String(selectedDisk?.id || "").toLowerCase();
        const mount = String(mountpoint || "").toLowerCase();
        if (!target) return false;
        return (dev && target.includes(dev)) || (id && target.includes(id)) || (mount && mount !== "/" && target.includes(mount));
    }).slice(0, 8);
    const statusBadgeClass = sbDiskStatusClass(selectedDisk);
    const encryptionLabel = String(selectedDisk?.encryption || selectedDisk?.crypto || "").trim()
        || (String(selectedDisk?.filesystem || "").toLowerCase().includes("luks") ? "LUKS" : "Keine");
    const tableType = String(selectedDisk?.partition_table || selectedDisk?.partition_type || selectedDisk?.table_type || "gpt");
    const sectorCount = sbLocaleInt(selectedDisk?.sectors || selectedDisk?.sector_count || 0);
    const sectorSize = String(selectedDisk?.sector_size || selectedDisk?.logical_sector_size || "512 B");
    const detailsCards = [
        { label: "Gerät", value: `<code>${esc(sbDiskDevicePath(selectedDisk))}</code>` },
        { label: "Größe", value: esc(sbDiskSizeLabel(selectedDisk)) },
        { label: "Typ", value: esc(tableType || "-") },
        { label: "Sektoren", value: esc(sectorCount) },
        { label: "Sektorgröße", value: esc(sectorSize) },
        { label: "Zone", value: esc(sbLabelZone(selectedDisk?.zone)) },
        { label: "Richtlinie", value: esc(sbLabelPolicy(policyKey)) },
        { label: "Risiko", value: esc((SB_RISK_META[String(selectedDisk?.risk_level || "").trim()] || SB_RISK_META.caution).label) },
    ];

    if (mode === "advanced") {
        detailsCards.push(
            { label: "Raw Zone-ID", value: `<code>${esc(String(selectedDisk?.zone || "-"))}</code>` },
            { label: "Raw Policy-ID", value: `<code>${esc(String(policyKey || "-"))}</code>` },
        );
    }

    const detailsTabBody = `
        <div class="sb-gd-info-grid">
            ${detailsCards.map((row) => `
                <article class="sb-gd-info-card">
                    <span class="sb-gd-info-label">${esc(row.label)}</span>
                    <div class="sb-gd-info-value">${row.value}</div>
                </article>
            `).join("")}
        </div>
        ${isSystemDisk ? `
            <div class="sb-gd-system-notice">
                Systemspeicher — dauerhaft geschützt, keine Änderungen möglich.
            </div>
        ` : `
            <div class="sb-gd-actions">
                <button class="sb-btn primary" data-sb-setup-start="backup" data-sb-disk="${esc(selectedDisk?.id || "")}">Als Backup nutzen</button>
                <button class="sb-btn" data-sb-setup-start="services" data-sb-disk="${esc(selectedDisk?.id || "")}">Für Services vorbereiten</button>
            </div>
        `}
    `;

    const opPreviewBlock = state.sb.preview ? `
        <div class="sb-gd-op-result">
            <h5>Letztes Ergebnis</h5>
            <pre>${esc(String(state.sb.preview || ""))}</pre>
        </div>
    ` : "";
    const partitionOpsPanel = selectedDisk ? `
        <div class="sb-gd-action-grid">
            <article class="sb-gd-action-card">
                <h5>Formatieren</h5>
                <p>Nur mit Bestätigung ausführen. Dry-Run wird empfohlen.</p>
                <div class="sb-gd-inline-fields">
                    <select id="sb-gd-format-fs" class="sb-input">
                        ${["ext4", "xfs", "vfat", "btrfs"].map((fs) => `<option value="${fs}">${fs}</option>`).join("")}
                    </select>
                    <input id="sb-gd-format-label" class="sb-input" placeholder="Label (optional)" />
                </div>
                <div class="sb-gd-actions">
                    <button class="sb-btn" data-sb-disk-op="format_dry" ${isSystemDisk ? "disabled" : ""}>Dry-Run</button>
                    <button class="sb-btn primary" data-sb-disk-op="format_apply" ${isSystemDisk ? "disabled" : ""}>Format anwenden</button>
                </div>
            </article>
            <article class="sb-gd-action-card">
                <h5>Mount setzen</h5>
                <p>Mountpoint definieren und optional mit Dry-Run prüfen.</p>
                <div class="sb-gd-inline-fields">
                    <input id="sb-gd-mountpoint" class="sb-input" placeholder="/mnt/trion-data" />
                    <input id="sb-gd-mountopts" class="sb-input" placeholder="rw,noexec (optional)" />
                </div>
                <div class="sb-gd-actions">
                    <button class="sb-btn" data-sb-disk-op="mount_dry" ${isSystemDisk ? "disabled" : ""}>Dry-Run</button>
                    <button class="sb-btn primary" data-sb-disk-op="mount_apply" ${isSystemDisk ? "disabled" : ""}>Mount anwenden</button>
                </div>
            </article>
        </div>
        ${isSystemDisk ? `
            <div class="sb-gd-system-notice">
                System-Datenträger können nicht formatiert oder gemountet werden.
            </div>
        ` : ""}
        ${opPreviewBlock}
    ` : "";
    const partitionTabBody = partitionRows.length ? `
        <div class="sb-gd-partition-bar">
            ${partitionRows.map((part, idx) => {
                const size = Math.max(1, Number(part?.size_bytes || 0));
                const total = Math.max(1, partitionRows.reduce((acc, p) => acc + Math.max(1, Number(p?.size_bytes || 0)), 0));
                const width = Math.max(6, Math.round((size / total) * 100));
                return `
                    <div
                        class="sb-gd-partition-seg"
                        style="width:${width}%; background:${partitionPalette[idx % partitionPalette.length]};"
                        title="${esc(part?.device || part?.id || `Partition ${idx + 1}`)} · ${esc(part?.filesystem || "-")} · ${esc(sbFormatBytes(part?.size_bytes || 0))}">
                    </div>
                `;
            }).join("")}
        </div>
        <div class="sb-advanced-table-wrap">
            <table class="sb-advanced-table">
                <thead>
                    <tr>
                        <th>Partition</th>
                        <th>Typ</th>
                        <th>Mount</th>
                        <th>Label</th>
                        <th>Größe</th>
                        <th>Belegt</th>
                        ${mode === "advanced" ? "<th>UUID</th><th>Mount-Optionen</th>" : ""}
                    </tr>
                </thead>
                <tbody>
                    ${partitionRows.map((part) => `
                        <tr>
                            <td><code>${esc(part?.device || part?.id || "-")}</code></td>
                            <td>${esc(part?.filesystem || part?.fs_type || "-")}</td>
                            <td><code>${esc(part?.mountpoint || part?.mount_path || "-")}</code></td>
                            <td>${esc(part?.label || "-")}</td>
                            <td>${esc(part?.size_human || sbFormatBytes(part?.size_bytes || 0))}</td>
                            <td>${esc(part?.used_human || sbFormatBytes(part?.used_bytes || 0))}</td>
                            ${mode === "advanced" ? `<td><code>${esc(part?.uuid || "-")}</code></td><td><code>${esc(part?.mount_options || "-")}</code></td>` : ""}
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
        ${partitionOpsPanel}
    ` : `
        <div class="sb-gd-empty-state">
            <p><strong>Partitionsinformationen nicht verfügbar</strong></p>
            <p>Die API liefert für diesen Datenträger derzeit keine Partitionen.</p>
        </div>
        ${partitionOpsPanel}
    `;

    const canWrite = !isSystemDisk && policyKey === "managed_rw";
    const rightsRows = [
        { label: "Schreibzugriff", ok: canWrite, on: "Erlaubt", off: "Blockiert" },
        { label: "TRION darf ändern", ok: canWrite, on: "Ja", off: "Nein" },
        { label: "Format erlaubt", ok: false, on: "Ja", off: "Nein" },
        { label: "Mount ändern", ok: false, on: "Ja", off: "Nein" },
    ];
    const rightsTabBody = `
        <div class="sb-gd-policy-info">
            <h4>Aktuelle Richtlinie: ${esc(sbLabelPolicy(policyKey))}</h4>
            <p>Zone: ${esc(sbLabelZone(selectedDisk?.zone))}</p>
        </div>
        <div class="sb-gd-permission-list">
            ${rightsRows.map((row) => `
                <div class="sb-gd-perm-row">
                    <span>${esc(row.label)}</span>
                    <span class="sb-gd-perm-state ${row.ok ? "ok" : "off"}">${row.ok ? "●" : "○"} ${esc(row.ok ? row.on : row.off)}</span>
                </div>
            `).join("")}
        </div>
        ${!isSystemDisk ? `
            <div class="sb-gd-action-card">
                <h5>Rechte ändern</h5>
                <div class="sb-gd-inline-fields">
                    <select id="sb-gd-rights-zone" class="sb-input">
                        ${["managed_services", "backup", "external", "unzoned", "docker_runtime"]
                            .map((z) => `<option value="${z}" ${selectedDisk?.zone === z ? "selected" : ""}>${esc(sbLabelZone(z))}</option>`).join("")}
                    </select>
                    <select id="sb-gd-rights-policy" class="sb-input">
                        ${["blocked", "read_only", "managed_rw"]
                            .map((p) => `<option value="${p}" ${policyKey === p ? "selected" : ""}>${esc(sbLabelPolicy(p))}</option>`).join("")}
                    </select>
                </div>
                <div class="sb-gd-actions">
                    <button id="sb-gd-rights-save" class="sb-btn primary" ${state.busy.sbSave ? "disabled" : ""}>Rechte speichern</button>
                </div>
            </div>
        ` : `
            <div class="sb-gd-system-notice">
                Systemspeicher — Rechte können hier nicht verändert werden.
            </div>
        `}
        ${opPreviewBlock}
    `;

    const foldersTabBody = `
        ${managedForDisk.length ? `
            <div class="sb-gd-folder-list">
                ${managedForDisk.map((path) => `
                    <div class="sb-gd-folder-item">
                        <span class="sb-gd-folder-icon">📁</span>
                        <code>${esc(path)}</code>
                        <span class="sb-badge sb-policy-rw">Verwaltet</span>
                    </div>
                `).join("")}
            </div>
        ` : `
            <div class="sb-gd-empty-state">
                <p><strong>Noch keine verwalteten Ordner</strong></p>
                <p>Richte zuerst einen Backup- oder Service-Speicher ein.</p>
                <button class="sb-btn primary" data-sb-setup-start="services" data-sb-disk="${esc(selectedDisk?.id || "")}">
                    Pfad einrichten
                </button>
            </div>
        `}
        <div class="sb-gd-action-card">
            <h5>Ordner für Service vorbereiten</h5>
            <div class="sb-gd-inline-fields">
                <input id="sb-gd-folder-service" class="sb-input" placeholder="service-name" value="${esc(String(selectedDisk?.id || "service").replace(/[^a-zA-Z0-9._-]/g, "-"))}" />
                <select id="sb-gd-folder-profile" class="sb-input">
                    ${["standard", "full", "minimal", "backup"].map((p) => `<option value="${p}">${p}</option>`).join("")}
                </select>
            </div>
            <div class="sb-gd-actions">
                <button class="sb-btn" data-sb-folder-op="dry">Dry-Run</button>
                <button class="sb-btn primary" data-sb-folder-op="apply">Pfad erstellen</button>
            </div>
        </div>
        ${opPreviewBlock}
    `;

    const securityTabBody = `
        <div class="sb-gd-security-grid">
            <article class="sb-gd-security-card">
                <h4>Verschlüsselung</h4>
                <p>${esc(encryptionLabel)}</p>
                <div class="sb-gd-actions">
                    <button class="sb-btn" data-sb-encryption-info="1">Verschlüsselung einrichten</button>
                </div>
            </article>
            <article class="sb-gd-security-card">
                <h4>Audit-Status</h4>
                <p>${esc(sbLabelPolicy(policyKey))}</p>
            </article>
            <article class="sb-gd-security-card">
                <h4>Sicherheits-Übersicht</h4>
                ${securityRows.map((row) => `
                    <div class="sb-gd-perm-row">
                        <span>${esc(row.label)}</span>
                        <span class="sb-gd-perm-state ${row.ok ? "ok" : "off"}">${row.ok ? "● Ja" : "● Nein"}</span>
                    </div>
                `).join("")}
            </article>
        </div>
        <div class="sb-gd-empty-state">
            <p><strong>Hinweis zur Verschlüsselung</strong></p>
            <p>Der Storage-Broker unterstützt aktuell noch keine direkte LUKS-Erstellung per API. Format/Mount ist verfügbar, Verschlüsselung folgt als nächster Schritt.</p>
        </div>
        ${opPreviewBlock}
        ${mode === "advanced" ? `
            <div class="sb-raw-block">
                <h5>Audit-Einträge für diesen Datenträger</h5>
                <pre>${esc(JSON.stringify(diskAudit, null, 2))}</pre>
            </div>
            <details class="sb-tech-details">
                <summary>Disk-Rohdaten anzeigen</summary>
                <pre>${esc(JSON.stringify(selectedDisk, null, 2))}</pre>
            </details>
        ` : ""}
    `;

    const tabContent = {
        details: detailsTabBody,
        partition: partitionTabBody,
        rechte: rightsTabBody,
        ordner: foldersTabBody,
        sicherheit: securityTabBody,
    };

    return `
        <section class="sb-view-head">
            <h4>Datenträger</h4>
            <p>Sichere Erkennung und geführte Zuweisung für TRION.</p>
        </section>

        <div class="sb-toolbar">
            <input id="sb-disk-search" class="sb-input" value="${esc(state.sb.diskSearch || "")}" placeholder="Datenträger suchen..." />
            <div class="sb-filter-row">
                ${["all", "recommended", "protected", "managed"].map((f) => `
                    <button class="sb-filter-btn ${state.sb.diskFilter === f ? "active" : ""}" data-sb-disk-filter="${f}">
                        ${filterLabel(f)}
                    </button>
                `).join("")}
            </div>
            <button class="sb-btn" data-sb-refresh="disks" ${state.busy.sbLoadDisks ? "disabled" : ""}>
                ${state.busy.sbLoadDisks ? "Lädt..." : "Erkennung aktualisieren"}
            </button>
        </div>

        <div class="sb-gd-layout">
            <aside class="sb-gd-dev-list">
                <div class="sb-gd-dev-title">Geräte</div>
                ${filteredRoots.length ? filteredRoots.map((disk) => {
                    const active = String(disk?.id || "") === String(selectedDisk?.id || "");
                    return `
                        <button class="sb-gd-dev-item ${active ? "active" : ""}" data-sb-select="${esc(disk?.id || "")}">
                            <span class="sb-gd-dev-icon ${sbDiskIconClass(disk)}">
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <rect x="3" y="5" width="18" height="14" rx="2"></rect>
                                    <line x1="7" y1="15" x2="17" y2="15"></line>
                                    <circle cx="8" cy="11" r="1"></circle>
                                    <circle cx="16" cy="11" r="1"></circle>
                                </svg>
                            </span>
                            <span class="sb-gd-dev-info">
                                <span class="sb-gd-dev-name">${esc(sbDiskDisplayName(disk))}</span>
                                <span class="sb-gd-dev-sub">${esc(sbDiskDevicePath(disk))} · ${esc(sbDiskSizeLabel(disk))}</span>
                            </span>
                        </button>
                    `;
                }).join("") : `<p class="sb-hint">Keine Datenträger für den Filter gefunden.</p>`}
            </aside>

            <section class="sb-gd-detail">
                ${selectedDisk ? `
                    <header class="sb-gd-detail-header">
                        <h3>${esc(sbDiskDisplayName(selectedDisk))}</h3>
                        <span class="sb-gd-status ${statusBadgeClass}">${esc(sbDiskStatusLabel(selectedDisk))}</span>
                        <span class="sb-gd-size">${esc(sbDiskSizeLabel(selectedDisk))}</span>
                    </header>
                    <div class="sb-gd-tabs">
                        ${[
                            ["details", "Details"],
                            ["partition", "Partition"],
                            ["rechte", "Rechte"],
                            ["ordner", "Ordner"],
                            ["sicherheit", "Sicherheit"],
                        ].map(([tabId, label]) => `
                            <button class="sb-gd-tab ${diskTab === tabId ? "active" : ""}" data-sb-disk-tab="${tabId}">
                                ${label}
                            </button>
                        `).join("")}
                    </div>
                    <div class="sb-gd-tab-body">
                        ${tabContent[diskTab] || tabContent.details}
                    </div>
                ` : `
                    <div class="sb-gd-empty-state">
                        <p><strong>Keine Datenträger gefunden</strong></p>
                        <p>Bitte aktualisiere die Erkennung oder passe den Filter an.</p>
                    </div>
                `}
            </section>
        </div>
    `;
}

function sbRenderManagedPaths(summary) {
    const merged = Array.from(new Set([...(summary.managed_paths || []), ...(state.sb.managedPaths || [])]));
    return `
        <section class="sb-view-head">
            <h4>Verwaltete Pfade</h4>
            <p>Alle von TRION verwalteten Speicherorte im Ueberblick.</p>
        </section>
        ${merged.length ? `
            <div class="sb-advanced-table-wrap">
                <table class="sb-advanced-table">
                    <thead>
                        <tr>
                            <th>Pfad</th>
                            <th>Rolle</th>
                            <th>Zugriff</th>
                            <th>Service</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${merged.map((p) => {
                            const role = p.includes("backup") ? "Backup-Ziel" : "Service-Speicher";
                            const service = p.split("/").filter(Boolean).slice(-1)[0] || "unbekannt";
                            return `
                                <tr>
                                    <td><code>${esc(p)}</code></td>
                                    <td>${esc(role)}</td>
                                    <td>${esc(sbLabelPolicy("managed_rw"))}</td>
                                    <td>${esc(service)}</td>
                                </tr>
                            `;
                        }).join("")}
                    </tbody>
                </table>
            </div>
        ` : `
            <article class="sb-empty-state">
                <h5>Noch keine verwalteten Pfade</h5>
                <p>Richte zuerst einen Backup- oder Service-Speicher ein. Danach erscheinen die Pfade hier automatisch.</p>
                <div class="sb-chip-row">
                    <button class="sb-btn primary" data-sb-setup-start="services">Ersten Service-Pfad einrichten</button>
                    <button class="sb-btn" data-sb-setup-start="backup">Backup-Ziel einrichten</button>
                </div>
            </article>
        `}
    `;
}

function sbRenderPolicies(summary) {
    const s = state.sb.settings || {};
    return `
        <section class="sb-view-head">
            <h4>Sicherheitsrichtlinien</h4>
            <p>Verstaendliche Regeln mit erweiterten Einstellungen.</p>
        </section>

        <div class="sb-policy-cards">
            <article class="sb-policy-card">
                <h5>System geschuetzt</h5>
                <p>Host- und Systemspeicher sind dauerhaft blockiert und in der UI nicht aenderbar.</p>
            </article>
            <article class="sb-policy-card">
                <h5>Nur-Lesen Speicher</h5>
                <p>Datentraeger koennen sicher geprueft werden, ohne Schreibzugriff.</p>
            </article>
            <article class="sb-policy-card">
                <h5>Verwalteter Speicher</h5>
                <p>TRION darf nur in freigegebenen verwalteten Pfaden schreiben.</p>
            </article>
            <article class="sb-policy-card">
                <h5>Gesperrte Pfade</h5>
                <p>Diese Pfade sind niemals gueltige Provisioning-Ziele.</p>
            </article>
        </div>

        <div class="sb-form">
            <div class="sb-form-row">
                <label>Standard fuer externe Datentraeger</label>
                <select id="sb-ext-policy">
                    ${["blocked", "read_only", "managed_rw"].map((p) => `<option value="${p}" ${s.external_default_policy === p ? "selected" : ""}>${esc(sbLabelPolicy(p))}</option>`).join("")}
                </select>
            </div>
            <div class="sb-form-row">
                <label>Standard fuer unbekannte Mounts</label>
                <select id="sb-unknown-policy">
                    ${["blocked", "read_only"].map((p) => `<option value="${p}" ${s.unknown_mount_default === p ? "selected" : ""}>${esc(sbLabelPolicy(p))}</option>`).join("")}
                </select>
            </div>
            <div class="sb-form-row sb-toggle-row">
                <label>Dry-Run standardmaessig aktiv</label>
                <label class="sb-toggle">
                    <input type="checkbox" id="sb-dry-run" ${s.dry_run_default ? "checked" : ""}>
                    <span class="sb-toggle-slider"></span>
                </label>
            </div>
            <div class="sb-form-row sb-toggle-row">
                <label>Freigabe fuer Schreibzugriffe erzwingen</label>
                <label class="sb-toggle">
                    <input type="checkbox" id="sb-req-approval" ${s.requires_approval_for_writes ? "checked" : ""}>
                    <span class="sb-toggle-slider"></span>
                </label>
            </div>

            <h5 class="sb-section-title">Gesperrte Pfade</h5>
            <ul class="sb-path-list">
                ${(s.blacklist_extra || []).map((p, i) => `
                    <li class="sb-path sb-removable">
                        <code>${esc(p)}</code>
                        <button class="sb-btn-xs danger" data-sb-remove-bl="${i}">x</button>
                    </li>
                `).join("") || '<li class="sb-hint">Keine zusaetzlichen gesperrten Pfade.</li>'}
            </ul>
            <div class="sb-add-row">
                <input id="sb-bl-input" type="text" placeholder="/pfad/zum-sperren" class="sb-input" />
                <button id="sb-bl-add-btn" class="sb-btn">Hinzufuegen</button>
            </div>
            <div class="sb-form-actions">
                <button id="sb-save-btn" class="sb-btn primary" ${state.busy.sbSave ? "disabled" : ""}>
                    ${state.busy.sbSave ? "Speichert..." : "Richtlinien speichern"}
                </button>
            </div>
        </div>

        ${state.sb.mode === "advanced" ? `
            <div class="sb-raw-block">
                <h5>Erweiterte Rohdaten</h5>
                <pre>${esc(JSON.stringify({ settings: s, zones: summary.zones || {} }, null, 2))}</pre>
            </div>
        ` : ""}
    `;
}

function sbAuditMatch(entry, filter) {
    const op = String(entry?.operation || "").toLowerCase();
    const hasError = Boolean(entry?.error);
    if (filter === "allowed") return !hasError;
    if (filter === "blocked") return hasError || String(entry?.result || "").toLowerCase().includes("blocked");
    if (filter === "provisioning") return op.includes("service") || op.includes("provision");
    if (filter === "mount") return op.includes("mount");
    if (filter === "format") return op.includes("format");
    return true;
}

function sbRenderAudit() {
    const filter = String(state.sb.auditFilter || "all");
    const entries = (state.sb.audit || []).filter((e) => sbAuditMatch(e, filter));
    const filterLabel = (f) => ({
        all: "Alle",
        allowed: "Erlaubt",
        blocked: "Blockiert",
        provisioning: "Provisioning",
        mount: "Mount",
        format: "Format",
    }[f] || f);
    return `
        <section class="sb-view-head">
            <h4>Audit</h4>
            <p>Nachvollziehen, welche Speicheraktionen erlaubt oder blockiert wurden.</p>
        </section>
        <div class="sb-filter-row">
            ${["all", "allowed", "blocked", "provisioning", "mount", "format"].map((f) => `
                <button class="sb-filter-btn ${filter === f ? "active" : ""}" data-sb-audit-filter="${f}">
                    ${esc(filterLabel(f))}
                </button>
            `).join("")}
        </div>
        <div class="sb-advanced-table-wrap">
            <table class="sb-advanced-table">
                <thead>
                    <tr>
                        <th>Zeit</th>
                        <th>Aktion</th>
                        <th>Ziel</th>
                        <th>Ergebnis</th>
                        <th>Grund</th>
                    </tr>
                </thead>
                <tbody>
                    ${entries.length ? entries.map((e) => `
                        <tr>
                            <td>${esc(sbSafeIso(e.created_at))}</td>
                            <td>${esc(e.operation || "-")}</td>
                            <td><code>${esc(e.target || "-")}</code></td>
                            <td class="${e.error ? "sb-txt-danger" : "sb-txt-ok"}">${esc(e.error ? "blockiert" : (e.result || "ok"))}</td>
                            <td>${esc(e.error || e.after_state || "-")}</td>
                        </tr>
                    `).join("") : `<tr><td colspan="5">Keine Audit-Eintraege vorhanden.</td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function renderStorageBrokerDetail() {
    const root = document.getElementById("mcp-detail");
    if (!root) return;

    const mode = String(state.sb.mode || "basic");
    const summary = state.sb.summary || {};
    const disks = Array.isArray(state.sb.disks) ? state.sb.disks : [];

    if (!disks.length && !state.busy.sbLoadDisks) {
        sbLoadDisks();
    }

    const body = sbRenderDisks(disks);

    root.innerHTML = `
        <div class="sb-panel sb-panel-modern">
            <div class="sb-header">
                <span class="sb-icon">SB</span>
                <div>
                    <small class="sb-breadcrumb">MCP Tools / Storage Broker</small>
                    <h3 class="sb-title">Storage Broker</h3>
                    <small class="sb-subtitle">Sichere Speicherverwaltung f\u00fcr TRION</small>
                </div>
                <span class="sb-status-badge ${state.sb.loaded ? "online" : "offline"}">
                    ${state.sb.loaded ? "Online" : "L\u00e4dt..."}
                </span>
                <button id="sb-exit-btn" class="sb-btn" type="button">Zur\u00fcck zu MCP Tools</button>
                <div class="sb-mode-toggle">
                    <button class="sb-mode-btn ${mode === "basic" ? "active" : ""}" data-sb-mode="basic">Basis</button>
                    <button class="sb-mode-btn ${mode === "advanced" ? "active" : ""}" data-sb-mode="advanced">Erweitert</button>
                </div>
            </div>

            <main class="sb-body" style="padding: 0;">
                ${body}
            </main>
        </div>
    `;

    root.querySelector("#sb-exit-btn")?.addEventListener("click", () => {
        state.selected = "";
        state.details = null;
        state.tools = [];
        state.configEditable = false;
        state.configText = "";
        state.sb.setup = { open: false, flow: "", step: 1, values: {}, result: "" };
        renderMcpList();
        renderDetailActions();
        renderDetail();
    });

    root.querySelectorAll("[data-sb-mode]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.sb.mode = String(btn.getAttribute("data-sb-mode") || "basic");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-sb-select]").forEach((el) => {
        el.addEventListener("click", () => {
            state.sb.selectedDiskId = String(el.getAttribute("data-sb-select") || "");
            state.sb.diskTab = "details";
            state.sb.preview = null;
            renderDetail();
        });
    });

    root.querySelectorAll("[data-sb-disk-tab]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.sb.diskTab = String(btn.getAttribute("data-sb-disk-tab") || "details");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-sb-refresh]").forEach((btn) => {
        btn.addEventListener("click", () => {
            sbLoadAll();
            sbLoadDisks();
        });
    });

    root.querySelector("#sb-disk-search")?.addEventListener("input", (e) => {
        state.sb.diskSearch = String(e.target?.value || "");
        renderDetail();
    });

    root.querySelectorAll("[data-sb-disk-filter]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.sb.diskFilter = String(btn.getAttribute("data-sb-disk-filter") || "all");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-sb-audit-filter]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.sb.auditFilter = String(btn.getAttribute("data-sb-audit-filter") || "all");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-sb-setup-start]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const flow = String(btn.getAttribute("data-sb-setup-start") || "services");
            const diskId = String(btn.getAttribute("data-sb-disk") || state.sb.selectedDiskId || "");
            sbOpenSetup(flow, { disk_id: diskId });
        });
    });

    root.querySelector("#sb-gd-rights-save")?.addEventListener("click", () => {
        const selectedDisk = sbFindDiskById(state.sb.selectedDiskId);
        if (!selectedDisk) return;
        const zone = String(root.querySelector("#sb-gd-rights-zone")?.value || "").trim();
        const policy_state = String(root.querySelector("#sb-gd-rights-policy")?.value || "").trim();
        if (!zone && !policy_state) {
            setFeedback("Bitte Zone oder Richtlinie wählen.", "warn");
            return;
        }
        setBusy("sbSave", true);
        sbSaveDiskPolicy(String(selectedDisk.id || ""), { zone, policy_state })
            .then((res) => {
                state.sb.preview = JSON.stringify(res, null, 2);
                setFeedback(`Rechte für ${selectedDisk.id} gespeichert`, "ok");
                return Promise.all([sbLoadDisks(), sbLoadAll()]);
            })
            .catch((e) => setFeedback(`Rechte konnten nicht gespeichert werden: ${e.message}`, "err"))
            .finally(() => {
                setBusy("sbSave", false);
                renderDetail();
            });
    });

    root.querySelectorAll("[data-sb-folder-op]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const selectedDisk = sbFindDiskById(state.sb.selectedDiskId);
            const modeValue = String(btn.getAttribute("data-sb-folder-op") || "dry");
            const dryRun = modeValue !== "apply";
            const serviceName = String(root.querySelector("#sb-gd-folder-service")?.value || "").trim() || "service";
            const profile = String(root.querySelector("#sb-gd-folder-profile")?.value || "standard").trim() || "standard";
            const zone = String(selectedDisk?.zone || "") === "backup" ? "backup" : "managed_services";
            setBusy("sbAction", true);
            sbProvisionServiceDir({
                service_name: serviceName,
                zone,
                profile,
                dry_run: dryRun,
            })
                .then((res) => {
                    state.sb.preview = JSON.stringify(res, null, 2);
                    setFeedback(dryRun ? "Ordner-Dry-Run abgeschlossen" : "Ordner erstellt", "ok");
                    if (!dryRun) return Promise.all([sbLoadAll(), sbLoadDisks()]);
                    return null;
                })
                .catch((e) => setFeedback(`Ordner-Aktion fehlgeschlagen: ${e.message}`, "err"))
                .finally(() => {
                    setBusy("sbAction", false);
                    renderDetail();
                });
        });
    });

    root.querySelectorAll("[data-sb-disk-op]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const selectedDisk = sbFindDiskById(state.sb.selectedDiskId);
            if (!selectedDisk) return;
            const op = String(btn.getAttribute("data-sb-disk-op") || "").trim();
            const device = sbDiskDevicePath(selectedDisk);
            const fs = String(root.querySelector("#sb-gd-format-fs")?.value || "ext4").trim() || "ext4";
            const label = String(root.querySelector("#sb-gd-format-label")?.value || "").trim();
            const mountpoint = String(root.querySelector("#sb-gd-mountpoint")?.value || "").trim();
            const options = String(root.querySelector("#sb-gd-mountopts")?.value || "").trim();
            const dryRun = op.endsWith("_dry");
            setBusy("sbAction", true);

            let task = Promise.resolve(null);
            if (op.startsWith("format")) {
                task = sbFormatDevice({ device, filesystem: fs, label, dry_run: dryRun });
            } else if (op.startsWith("mount")) {
                if (!mountpoint) {
                    setBusy("sbAction", false);
                    setFeedback("Bitte Mountpoint angeben.", "warn");
                    return;
                }
                task = sbMountDevice({ device, mountpoint, filesystem: "", options, dry_run: dryRun });
            }

            task
                .then((res) => {
                    state.sb.preview = JSON.stringify(res, null, 2);
                    setFeedback(dryRun ? "Operation als Dry-Run ausgeführt" : "Operation ausgeführt", "ok");
                    if (!dryRun) return Promise.all([sbLoadAll(), sbLoadDisks()]);
                    return null;
                })
                .catch((e) => setFeedback(`Disk-Operation fehlgeschlagen: ${e.message}`, "err"))
                .finally(() => {
                    setBusy("sbAction", false);
                    renderDetail();
                });
        });
    });

    root.querySelectorAll("[data-sb-encryption-info]").forEach((btn) => {
        btn.addEventListener("click", () => {
            state.sb.preview = "Verschlüsselung via API ist aktuell noch nicht implementiert (kein LUKS-Endpoint verfügbar).";
            setFeedback("Verschlüsselung folgt als nächster Backend-Schritt.", "warn");
            renderDetail();
        });
    });

    root.querySelectorAll("[data-sb-quick]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const flow = String(btn.getAttribute("data-sb-quick") || "services");
            const diskId = String(btn.getAttribute("data-sb-disk") || state.sb.selectedDiskId || "");
            sbOpenSetup(flow, { disk_id: diskId });
        });
    });

    root.querySelector("[data-sb-setup-cancel]")?.addEventListener("click", () => { sbCloseSetup(); });
    root.querySelector("[data-sb-setup-back]")?.addEventListener("click", () => {
        sbReadSetupFields(root);
        state.sb.setup.step = Math.max(1, Number(state.sb.setup.step || 1) - 1);
        renderDetail();
    });
    root.querySelector("[data-sb-setup-next]")?.addEventListener("click", () => {
        sbReadSetupFields(root);
        state.sb.setup.step = Math.min(4, Number(state.sb.setup.step || 1) + 1);
        renderDetail();
    });
    root.querySelectorAll("[data-sb-setup-run]").forEach((btn) => {
        btn.addEventListener("click", () => {
            sbReadSetupFields(root);
            const modeValue = String(btn.getAttribute("data-sb-setup-run") || "dry");
            sbExecuteSetup(modeValue !== "apply");
        });
    });
    root.querySelector("[data-sb-setup-done]")?.addEventListener("click", () => { sbCloseSetup(); });

    root.querySelectorAll("[data-sb-toggle]").forEach((btn) => {
        btn.addEventListener("click", (ev) => {
            ev.preventDefault(); ev.stopPropagation();
            const id = String(btn.getAttribute("data-sb-toggle") || "").trim();
            if (!id) return;
            state.sb.expanded[id] = !state.sb.expanded[id];
            renderDetail();
        });
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
