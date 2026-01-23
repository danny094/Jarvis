// maintenance.js - Memory Maintenance UI Logic

import { log } from "./debug.js";
import { getApiBase } from "./api.js";

let isRunning = false;
let eventSource = null;

// ═══════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════
export function initMaintenance() {
    // Modal öffnen
    document.getElementById("maintenance-btn").addEventListener("click", async () => {
        document.getElementById("maintenance-modal").classList.remove("hidden");
        await loadStatus();
        lucide.createIcons();
    });
    
    // Modal schließen
    document.getElementById("close-maintenance-btn").addEventListener("click", () => {
        if (!isRunning) {
            document.getElementById("maintenance-modal").classList.add("hidden");
        }
    });
    
    document.getElementById("maintenance-modal").addEventListener("click", (e) => {
        if (e.target.id === "maintenance-modal" && !isRunning) {
            document.getElementById("maintenance-modal").classList.add("hidden");
        }
    });
    
    // Start Button
    document.getElementById("maintenance-start-btn").addEventListener("click", startMaintenance);
    
    // Cancel Button
    document.getElementById("maintenance-cancel-btn").addEventListener("click", cancelMaintenance);
}

// ═══════════════════════════════════════════════════════════
// LOAD STATUS
// ═══════════════════════════════════════════════════════════
async function loadStatus() {
    try {
        const res = await fetch(`${getApiBase()}/api/maintenance/status`);
        const data = await res.json();
        
        // Update Stats
        const memory = data.memory || {};
        document.getElementById("stat-stm").textContent = memory.stm_entries || 0;
        document.getElementById("stat-mtm").textContent = memory.mtm_entries || 0;
        document.getElementById("stat-ltm").textContent = memory.ltm_entries || 0;
        document.getElementById("stat-nodes").textContent = memory.graph_nodes || 0;
        document.getElementById("stat-edges").textContent = memory.graph_edges || 0;
        
        log("info", "Memory status loaded", memory);
        
    } catch (error) {
        log("error", `Failed to load status: ${error.message}`);
    }
}

// ═══════════════════════════════════════════════════════════
// START MAINTENANCE
// ═══════════════════════════════════════════════════════════
async function startMaintenance() {
    if (isRunning) return;
    
    // Sammle ausgewählte Tasks
    const tasks = [];
    if (document.getElementById("task-duplicates").checked) tasks.push("duplicates");
    if (document.getElementById("task-promote").checked) tasks.push("promote");
    if (document.getElementById("task-summarize").checked) tasks.push("summarize");
    if (document.getElementById("task-graph").checked) tasks.push("graph");
    
    if (tasks.length === 0) {
        addLog("⚠️ Keine Tasks ausgewählt", "warn");
        return;
    }
    
    isRunning = true;
    updateUIState(true);
    clearLog();
    addLog("🚀 Maintenance gestartet...");
    log("info", `Starting maintenance with tasks: ${tasks.join(", ")}`);
    
    try {
        const res = await fetch(`${getApiBase()}/api/maintenance/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tasks })
        });
        
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";
            
            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleUpdate(data);
                    } catch (e) {
                        // Ignore parse errors
                    }
                }
            }
        }
        
    } catch (error) {
        log("error", `Maintenance error: ${error.message}`);
        addLog(`❌ Fehler: ${error.message}`, "error");
    } finally {
        isRunning = false;
        updateUIState(false);
    }
}

// ═══════════════════════════════════════════════════════════
// HANDLE UPDATES
// ═══════════════════════════════════════════════════════════
function handleUpdate(data) {
    log("debug", "Maintenance update", data);
    
    switch (data.type) {
        case "started":
            addLog(`📋 Tasks: ${data.tasks.join(", ")}`);
            break;
            
        case "status":
            addLog(`📊 ${data.message}`);
            break;
            
        case "task_start":
            addLog(`🔄 ${data.message}`);
            document.getElementById("maintenance-task").textContent = data.message;
            break;
            
        case "task_progress":
            addLog(`   → ${data.message}`);
            if (data.progress !== undefined) {
                updateProgress(data.progress);
            }
            if (data.sub_progress !== undefined) {
                document.getElementById("maintenance-task").textContent = data.message;
            }
            break;
            
        case "task_error":
            addLog(`❌ ${data.task}: ${data.message}`, "error");
            break;
            
        case "completed":
            addLog(`✅ Maintenance abgeschlossen!`, "success");
            updateProgress(100);
            showResults(data.stats);
            break;
            
        case "cancelled":
            addLog(`⚠️ ${data.message}`, "warn");
            break;
            
        case "error":
            addLog(`❌ ${data.message}`, "error");
            break;
            
        case "stream_end":
            // Stream beendet
            break;
    }
}

// ═══════════════════════════════════════════════════════════
// UI HELPERS
// ═══════════════════════════════════════════════════════════
function updateUIState(running) {
    const startBtn = document.getElementById("maintenance-start-btn");
    const cancelBtn = document.getElementById("maintenance-cancel-btn");
    const progressContainer = document.getElementById("maintenance-progress-container");
    const checkboxes = document.querySelectorAll("#maintenance-modal input[type=checkbox]");
    
    if (running) {
        startBtn.classList.add("hidden");
        cancelBtn.classList.remove("hidden");
        progressContainer.classList.remove("hidden");
        checkboxes.forEach(cb => cb.disabled = true);
    } else {
        startBtn.classList.remove("hidden");
        cancelBtn.classList.add("hidden");
        checkboxes.forEach(cb => cb.disabled = false);
    }
}

function updateProgress(percent) {
    const bar = document.getElementById("maintenance-progress-bar");
    const percentEl = document.getElementById("maintenance-percent");
    
    bar.style.width = `${percent}%`;
    percentEl.textContent = `${Math.round(percent)}%`;
}

function showResults(stats) {
    const resultsEl = document.getElementById("maintenance-results");
    resultsEl.classList.remove("hidden");
    
    const actions = stats?.actions || {};
    
    document.getElementById("result-duplicates-found").textContent = actions.duplicates_found || 0;
    document.getElementById("result-duplicates-merged").textContent = actions.duplicates_merged || 0;
    document.getElementById("result-promoted").textContent = actions.promoted_to_ltm || 0;
    document.getElementById("result-summaries").textContent = actions.summaries_created || 0;
    document.getElementById("result-deleted").textContent = actions.entries_deleted || 0;
    document.getElementById("result-edges").textContent = actions.edges_pruned || 0;
}

function addLog(message, type = "info") {
    const logEl = document.getElementById("maintenance-log");
    const entry = document.createElement("div");
    
    const colors = {
        info: "text-gray-300",
        warn: "text-yellow-400",
        error: "text-red-400",
        success: "text-green-400"
    };
    
    entry.className = colors[type] || "text-gray-300";
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    
    logEl.appendChild(entry);
    logEl.scrollTop = logEl.scrollHeight;
}

function clearLog() {
    const logEl = document.getElementById("maintenance-log");
    logEl.innerHTML = "";
}

// ═══════════════════════════════════════════════════════════
// CANCEL
// ═══════════════════════════════════════════════════════════
async function cancelMaintenance() {
    try {
        await fetch(`${getApiBase()}/api/maintenance/cancel`, {
            method: "POST"
        });
        addLog("⏹️ Abbruch angefordert...", "warn");
    } catch (error) {
        log("error", `Cancel failed: ${error.message}`);
    }
}
