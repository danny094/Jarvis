// app.js - Main Application mit Settings & Debug

import { getModels, checkHealth, setApiBase } from "./api.js";
import { setModel, handleUserMessage, clearChat, setHistoryLimit, getMessageCount } from "./chat.js";
import { log, clearLogs, setVerbose } from "./debug.js";

// ═══════════════════════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════════════════════
const DEFAULT_SETTINGS = {
    historyLength: 10,
    apiBase: "http://192.168.0.226:8100",
    verbose: false
};

let settings = { ...DEFAULT_SETTINGS };

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
    document.getElementById("history-length").value = settings.historyLength;
    document.getElementById("history-length-value").textContent = settings.historyLength;
    document.getElementById("history-limit-display").textContent = settings.historyLength;
    document.getElementById("history-status-limit").textContent = settings.historyLength;
    
    // API Base
    setApiBase(settings.apiBase);
    document.getElementById("api-base-input").value = settings.apiBase;
    
    // Verbose
    setVerbose(settings.verbose);
    updateVerboseToggle();
    
    log("info", `Settings applied: history=${settings.historyLength}, verbose=${settings.verbose}`);
}

function updateVerboseToggle() {
    const btn = document.getElementById("verbose-toggle");
    const knob = btn.querySelector("span");
    
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
    
    // Load settings first
    loadSettings();
    
    // Init Lucide icons
    lucide.createIcons();
    
    // Setup event listeners
    setupEventListeners();
    
    // Check connection & load models
    await checkConnection();
    await loadModels();
    
    log("info", "Jarvis WebUI ready!");
}

async function checkConnection() {
    const statusEl = document.getElementById("connection-status");
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
    const dropdown = document.getElementById("model-dropdown");
    const nameEl = document.getElementById("model-name");
    
    if (models.length === 0) {
        nameEl.textContent = "Keine Models";
        log("warn", "No models found");
        return;
    }
    
    dropdown.innerHTML = models.map(m => `
        <button class="w-full px-4 py-2 text-left hover:bg-dark-hover transition-colors text-sm"
                data-model="${m}">
            ${m}
        </button>
    `).join("");
    
    // Select first model
    const firstModel = models[0];
    nameEl.textContent = firstModel;
    setModel(firstModel);
    log("info", `Loaded ${models.length} models, selected: ${firstModel}`);
    
    // Model click handlers
    dropdown.querySelectorAll("button").forEach(btn => {
        btn.addEventListener("click", () => {
            const model = btn.dataset.model;
            nameEl.textContent = model;
            setModel(model);
            dropdown.classList.add("hidden");
            log("info", `Model changed to: ${model}`);
        });
    });
}

// ═══════════════════════════════════════════════════════════
// EVENT LISTENERS
// ═══════════════════════════════════════════════════════════
function setupEventListeners() {
    // Model dropdown
    document.getElementById("model-selector-btn").addEventListener("click", () => {
        document.getElementById("model-dropdown").classList.toggle("hidden");
    });
    
    // Close dropdown on outside click
    document.addEventListener("click", (e) => {
        if (!e.target.closest("#model-selector-btn") && !e.target.closest("#model-dropdown")) {
            document.getElementById("model-dropdown").classList.add("hidden");
        }
    });
    
    // Send message
    document.getElementById("send-btn").addEventListener("click", sendMessage);
    document.getElementById("user-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // Debug panel toggle
    document.getElementById("debug-toggle-btn").addEventListener("click", () => {
        const panel = document.getElementById("debug-panel");
        panel.classList.toggle("hidden");
        log("debug", "Debug panel toggled");
    });
    
    // Clear logs
    document.getElementById("clear-logs-btn").addEventListener("click", clearLogs);
    
    // Settings modal
    document.getElementById("settings-btn").addEventListener("click", () => {
        document.getElementById("settings-modal").classList.remove("hidden");
    });
    
    document.getElementById("close-settings-btn").addEventListener("click", () => {
        document.getElementById("settings-modal").classList.add("hidden");
    });
    
    // Click outside modal to close
    document.getElementById("settings-modal").addEventListener("click", (e) => {
        if (e.target.id === "settings-modal") {
            document.getElementById("settings-modal").classList.add("hidden");
        }
    });
    
    // History length slider
    document.getElementById("history-length").addEventListener("input", (e) => {
        document.getElementById("history-length-value").textContent = e.target.value;
    });
    
    // Verbose toggle
    document.getElementById("verbose-toggle").addEventListener("click", () => {
        settings.verbose = !settings.verbose;
        updateVerboseToggle();
    });
    
    // Save settings
    document.getElementById("save-settings-btn").addEventListener("click", () => {
        settings.historyLength = parseInt(document.getElementById("history-length").value);
        settings.apiBase = document.getElementById("api-base-input").value;
        saveSettings();
        document.getElementById("settings-modal").classList.add("hidden");
        log("info", "Settings saved");
        
        // Reconnect with new API base
        checkConnection();
    });
    
    // Reset settings
    document.getElementById("reset-settings-btn").addEventListener("click", () => {
        settings = { ...DEFAULT_SETTINGS };
        applySettings();
        log("info", "Settings reset to defaults");
    });
}

function sendMessage() {
    const input = document.getElementById("user-input");
    const text = input.value.trim();
    
    if (text) {
        handleUserMessage(text);
        input.value = "";
        input.style.height = "auto";
    }
}
