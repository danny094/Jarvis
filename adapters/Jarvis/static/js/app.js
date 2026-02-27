// app.js - Main Application mit Settings & Debug

import { getModels, checkHealth, setApiBase, getApiBase } from "./api.js";

// Expose getApiBase to window for non-module scripts
window.getApiBase = getApiBase;
import { setModel, handleUserMessage, clearChat, setHistoryLimit, getMessageCount, initChatFromStorage } from "./chat.js?v=1771975000";
import { log, clearLogs, setVerbose } from "./debug.js";
// NOTE: Settings UI is handled exclusively by js/apps/settings.js (lazy-loaded by shell.js).
// Do NOT call initSettings() from static/js/settings.js here — it would create a second controller.
import { initMaintenance } from "./maintenance.js";

// ═══════════════════════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════════════════════
const DEFAULT_SETTINGS = {
    historyLength: 10,
    apiBase: window.location.protocol + "//" + window.location.hostname + ":8200",  // Updated: admin-api port
    verbose: false,
    deepJobMode: false
};

let settings = { ...DEFAULT_SETTINGS };
let chatModelNames = [];

function loadSettings() {
    try {
        const saved = localStorage.getItem("jarvis-settings");
        if (saved) {
            settings = { ...DEFAULT_SETTINGS, ...JSON.parse(saved) };
        }
    } catch (e) {
        console.error("Failed to load settings:", e);
    }
    applySettings();
}

function saveSettings() {
    try {
        localStorage.setItem("jarvis-settings", JSON.stringify(settings));
    } catch (e) {
        console.error("Failed to save settings:", e);
    }
    applySettings();
}

function applySettings() {
    // History Limit
    setHistoryLimit(settings.historyLength);

    const histLen = document.getElementById("history-length");
    if (histLen) histLen.value = settings.historyLength;

    const histLenVal = document.getElementById("history-length-value");
    if (histLenVal) histLenVal.textContent = settings.historyLength;

    const histLimitDisp = document.getElementById("history-limit-display");
    if (histLimitDisp) histLimitDisp.textContent = settings.historyLength;

    const histStatus = document.getElementById("history-status-limit");
    if (histStatus) histStatus.textContent = settings.historyLength;

    // API Base
    setApiBase(settings.apiBase);
    const apiInput = document.getElementById("api-base-input");
    if (apiInput) apiInput.value = settings.apiBase;

    // Verbose
    setVerbose(settings.verbose);
    updateVerboseToggle();

    // Deep Job toggle
    const deepJobToggle = document.getElementById("deep-job-toggle");
    if (deepJobToggle) {
        deepJobToggle.checked = Boolean(settings.deepJobMode);
    }

    log("info", `Settings applied: history=${settings.historyLength}, verbose=${settings.verbose}`);
}

function updateVerboseToggle() {
    const btn = document.getElementById("verbose-toggle");
    if (!btn) return; // Graceful fallback if button doesn't exist
    const knob = btn.querySelector("span");
    if (!knob) return; // Graceful fallback if knob doesn't exist

    if (settings.verbose) {
        btn.classList.add("bg-accent-primary");
        btn.classList.remove("bg-dark-border");
        knob.classList.add("translate-x-6");
        knob.classList.add("bg-white");
        knob.classList.remove("bg-gray-400");
    } else {
        btn.classList.remove("bg-accent-primary");
        btn.classList.add("bg-dark-border");
        knob.classList.remove("translate-x-6");
        knob.classList.remove("bg-white");
        knob.classList.add("bg-gray-400");
    }
}

// ═══════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════
export async function initApp() {
    log("info", "Jarvis WebUI starting...");

    // Init Lucide icons first (no dependencies)
    lucide.createIcons();

    // Load settings from localStorage ONLY (no API calls yet)
    loadSettings();

    // Check connection FIRST (before anything needs API)
    await checkConnection();

    // Settings UI is initialized by shell.js via js/apps/settings.js (lazy-loaded on panel open).

    // Load models (now connection is verified)
    await loadModels();

    // Setup event listeners
    setupEventListeners();
    
    // Restore chat from localStorage
    initChatFromStorage();
    
    // Init Maintenance UI
    initMaintenance();

    // Init Sequential Thinking Mode
    if (typeof SequentialThinking !== "undefined") {
        if (!window.sequentialThinking) {
            window.sequentialThinking = new SequentialThinking();
            window.sequentialThinking.initUI();
            log("info", "Sequential Thinking Mode initialized from app.js");
        } else {
            log("info", "Sequential Thinking Mode already initialized");
        }
    } else {
        log("warn", "Sequential Thinking not available");
    }

    // Initialize Sequential Sidebar
    if (typeof SequentialSidebar !== 'undefined') {
        window.sequentialSidebar = new SequentialSidebar();
        log("info", "Sequential Sidebar initialized");
    }

    log("info", "Jarvis WebUI ready!");
}
async function checkConnection() {
    const statusEl = document.getElementById("connection-status");
    if (!statusEl) {
        // Status element not in DOM - check health silently
        const isConnected = await checkHealth();
        log("info", isConnected ? "API connected" : "API offline");
        return;
    }
    const dot = statusEl.querySelector("span");

    const isConnected = await checkHealth();

    if (isConnected) {
        dot.className = "w-2 h-2 bg-green-500 rounded-full";
        statusEl.innerHTML = `<span class="w-2 h-2 bg-green-500 rounded-full"></span> Verbunden`;
        log("info", `Connected to ${settings.apiBase}`);
    } else {
        dot.className = "w-2 h-2 bg-red-500 rounded-full";
        statusEl.innerHTML = `<span class="w-2 h-2 bg-red-500 rounded-full"></span> Offline`;
        log("error", `Failed to connect to ${settings.apiBase}`);
    }
}

async function loadModels() {
    log("debug", "Loading models...");

    const models = await getModels();
    chatModelNames = [...models];
    const dropdown = document.getElementById("model-dropdown");
    const nameEl = document.getElementById("model-name");

    if (models.length === 0) {
        nameEl.textContent = "Keine Models";
        log("warn", "No models found");
        return;
    }

    const outputModel = await loadEffectiveOutputModel();
    const allModels = [...models];
    if (outputModel && !allModels.includes(outputModel)) {
        allModels.unshift(outputModel);
        chatModelNames = [...allModels];
    }

    dropdown.innerHTML = allModels.map(m => `
        <button class="w-full px-4 py-2 text-left hover:bg-dark-hover transition-colors text-sm"
                data-model="${m}">
            ${m}
        </button>
    `).join("");

    // Select OUTPUT_MODEL from effective settings when available.
    const selectedModel = outputModel || allModels[0];
    setActiveChatModel(selectedModel);
    log("info", `Loaded ${allModels.length} models, selected: ${selectedModel}`);

    // Model click handlers
    dropdown.querySelectorAll("button").forEach(btn => {
        btn.addEventListener("click", async () => {
            const model = btn.dataset.model;
            setActiveChatModel(model);
            await persistOutputModelSelection(model);
            window.dispatchEvent(new CustomEvent("jarvis:model-settings-updated", {
                detail: { OUTPUT_MODEL: model, source: "chat-quick-select" }
            }));
            dropdown.classList.add("hidden");
            log("info", `Model changed to: ${model}`);
        });
    });
}

function setActiveChatModel(model) {
    if (!model) return;
    const nameEl = document.getElementById("model-name");
    if (nameEl) nameEl.textContent = model;
    setModel(model);
}

async function loadEffectiveOutputModel() {
    try {
        const res = await fetch(`${getApiBase()}/api/settings/models/effective`);
        if (!res.ok) return "";
        const data = await res.json();
        return data?.effective?.OUTPUT_MODEL?.value || "";
    } catch (e) {
        log("warn", `Failed to load effective OUTPUT_MODEL: ${e.message}`);
        return "";
    }
}

async function persistOutputModelSelection(model) {
    try {
        const res = await fetch(`${getApiBase()}/api/settings/models`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ OUTPUT_MODEL: model })
        });
        if (!res.ok) {
            const err = await res.text().catch(() => "");
            log("warn", `Quick model sync failed: HTTP ${res.status} ${err}`.trim());
        }
    } catch (e) {
        log("warn", `Quick model sync failed: ${e.message}`);
    }
}

function ensureChatModelInDropdown(model) {
    if (!model) return;
    const dropdown = document.getElementById("model-dropdown");
    if (!dropdown) return;
    if (chatModelNames.includes(model)) return;

    chatModelNames.unshift(model);
    const btn = document.createElement("button");
    btn.className = "w-full px-4 py-2 text-left hover:bg-dark-hover transition-colors text-sm";
    btn.dataset.model = model;
    btn.textContent = model;
    btn.addEventListener("click", async () => {
        setActiveChatModel(model);
        await persistOutputModelSelection(model);
        window.dispatchEvent(new CustomEvent("jarvis:model-settings-updated", {
            detail: { OUTPUT_MODEL: model, source: "chat-quick-select" }
        }));
        dropdown.classList.add("hidden");
        log("info", `Model changed to: ${model}`);
    });
    dropdown.prepend(btn);
}

// ═══════════════════════════════════════════════════════════
// EVENT LISTENERS
// ═══════════════════════════════════════════════════════════
function setupEventListeners() {
    // Send message
    const sendBtn = document.getElementById("send-btn");
    const userInput = document.getElementById("user-input");

    if (sendBtn) {
        sendBtn.addEventListener("click", sendMessage);
    }

    if (userInput) {
        userInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Debug panel toggle
    const debugToggleBtn = document.getElementById("debug-toggle-btn");
    if (debugToggleBtn) {
        debugToggleBtn.addEventListener("click", () => {
            const panel = document.getElementById("debug-panel");
            if (panel) {
                panel.classList.toggle("hidden");
                log("debug", "Debug panel toggled");
            }
        });
    }

    // Clear logs
    const clearLogsBtn = document.getElementById("clear-logs-btn");
    if (clearLogsBtn) {
        clearLogsBtn.addEventListener("click", clearLogs);
    }

    // Model dropdown
    const modelSelectorBtn = document.getElementById("model-selector-btn");
    const modelDropdown = document.getElementById("model-dropdown");

    if (modelSelectorBtn && modelDropdown) {
        modelSelectorBtn.addEventListener("click", () => {
            modelDropdown.classList.toggle("hidden");
        });

        // Close dropdown on outside click
        document.addEventListener("click", (e) => {
            if (!e.target.closest("#model-selector-btn") && !e.target.closest("#model-dropdown")) {
                modelDropdown.classList.add("hidden");
            }
        });
    }

    // Keep chat quick selector synchronized with Settings > Models.
    window.addEventListener("jarvis:model-settings-updated", (event) => {
        const nextOutputModel = event?.detail?.OUTPUT_MODEL;
        if (!nextOutputModel) return;
        ensureChatModelInDropdown(nextOutputModel);
        setActiveChatModel(nextOutputModel);
    });

    // Deep job mode quick toggle
    const deepJobToggle = document.getElementById("deep-job-toggle");
    if (deepJobToggle) {
        deepJobToggle.addEventListener("change", () => {
            settings.deepJobMode = Boolean(deepJobToggle.checked);
            saveSettings();
            log("info", `Deep job mode: ${settings.deepJobMode ? "on" : "off"}`);
        });
    }

    // NOTE: Settings and Maintenance buttons are handled by their respective modules
    // settings.js handles: settings-btn, close-settings-btn, etc.
    // maintenance.js handles: maintenance-btn, maintenance-start-btn, etc.
}

function sendMessage() {
    const input = document.getElementById("user-input");
    const deepJobToggle = document.getElementById("deep-job-toggle");
    const text = input.value.trim();

    if (text) {
        const deepJob = deepJobToggle ? Boolean(deepJobToggle.checked) : Boolean(settings.deepJobMode);
        handleUserMessage(text, { deepJob });
        input.value = "";
        input.style.height = "auto";
    }
}

// ═══════════════════════════════════════════════════════════
// LOAD TOOLS
// ═══════════════════════════════════════════════════════════
async function loadTools() {
    const contentEl = document.getElementById("tools-content");

    try {
        log("debug", "Loading tools...");
        const res = await fetch(`${getApiBase()}/api/tools`);

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        log("info", `Loaded ${data.total_tools} tools from ${data.total_mcps} MCPs`);

        // Render MCPs
        // Render MCPs via ZIP Upload
        let html = `
            <div class="mb-6 p-4 border border-dark-border rounded-lg bg-dark-card/30">
                <div class="flex items-center justify-between mb-2">
                    <h3 class="font-medium text-sm">Neues MCP Installieren (ZIP)</h3>
                    <span class="text-xs text-gray-500">Tier 1 (Simple Python)</span>
                </div>
                <div class="flex gap-3 items-center">
                    <input type="file" id="mcp-zip-input" accept=".zip" class="text-sm text-gray-400 file:mr-4 file:py-1 file:px-3 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-accent-primary file:text-white hover:file:bg-accent-secondary"/>
                    <button id="btn-upload-mcp" class="px-3 py-1 bg-accent-primary text-white text-xs rounded hover:bg-accent-secondary transition-colors" onclick="uploadMcp()">
                        Installieren
                    </button>
                    <span id="upload-status" class="text-xs"></span>
                </div>
            </div>
        `;

        for (const mcp of data.mcps) {
            const statusColor = mcp.online ? "bg-green-500" : "bg-red-500";
            const statusText = mcp.online ? "Online" : "Offline";

            html += `
                <div class="mb-4 border border-dark-border rounded-lg overflow-hidden">
                    <div class="px-4 py-3 bg-dark-hover flex items-center justify-between">
                        <div class="flex items-center gap-2">
                            <span class="w-2 h-2 ${statusColor} rounded-full"></span>
                            <span class="font-medium">${mcp.name}</span>
                            <span class="text-xs text-gray-500">(${mcp.transport})</span>
                        </div>
                        <span class="text-xs text-gray-400">${mcp.tools_count} tools</span>
                    </div>
                    <div class="px-4 py-2 text-sm text-gray-400">
                        ${mcp.description || 'Keine Beschreibung'}
                    </div>
                </div>
            `;
        }

        // Tool Liste
        html += `<h3 class="font-medium mt-6 mb-3">Alle Tools (${data.total_tools})</h3>`;
        html += `<div class="space-y-2">`;

        for (const tool of data.tools) {
            const desc = tool.description || 'Keine Beschreibung';
            const shortDesc = desc.length > 100 ? desc.substring(0, 100) + '...' : desc;

            html += `
                <details class="border border-dark-border rounded-lg">
                    <summary class="px-3 py-2 cursor-pointer hover:bg-dark-hover text-sm">
                        <span class="font-mono text-accent-primary">${tool.name}</span>
                    </summary>
                    <div class="px-3 py-2 border-t border-dark-border text-xs text-gray-400">
                        ${desc}
                    </div>
                </details>
            `;
        }

        html += `</div>`;

        contentEl.innerHTML = html;
        lucide.createIcons();

    } catch (error) {
        log("error", `Failed to load tools: ${error.message}`);
        contentEl.innerHTML = `
            <div class="text-red-400 text-center py-8">
                <i data-lucide="alert-circle" class="w-8 h-8 mx-auto mb-2"></i>
                Fehler: ${error.message}
            </div>
        `;
        lucide.createIcons();
    }
}

// ==========================================
// MCP UPLOAD LOGIC
// ==========================================
window.uploadMcp = async function() {
    const input = document.getElementById("mcp-zip-input");
    const status = document.getElementById("upload-status");
    
    if (!input.files || input.files.length === 0) {
        alert("Bitte eine ZIP-Datei auswählen!");
        return;
    }
    
    const file = input.files[0];
    const formData = new FormData();
    formData.append("file", file);
    
    status.textContent = "Upload läuft...";
    status.className = "text-xs text-blue-400";
    
    try {
        const res = await fetch(`${getApiBase()}/api/mcp/install`, {
            method: "POST",
            body: formData
        });
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Upload fehlgeschlagen");
        }
        
        const data = await res.json();
        status.textContent = "✅ Installiert!";
        status.className = "text-xs text-green-400";
        
        // Reload list after 1s
        setTimeout(() => {
            if (typeof loadTools === "function") loadTools();
            status.textContent = "";
            input.value = ""; // Reset input
        }, 1500);
        
    } catch (e) {
        status.textContent = `❌ Fehler: ${e.message}`;
        status.className = "text-xs text-red-400";
        console.error(e);
    }
};
