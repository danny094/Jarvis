// terminal.js - Live Terminal für Container-Ausgabe + ttyd Integration + User-Sandbox

import { startUserSandbox, stopUserSandbox, getUserSandboxStatus } from './api.js';

let terminalVisible = false;
let terminalHistory = [];
let currentSession = null;
let liveTerminalActive = false;

// ═══════════════════════════════════════════════════════════
// USER-SANDBOX STATE
// ═══════════════════════════════════════════════════════════
let userSandboxActive = false;
let userSandboxInfo = null;
let sandboxStatusInterval = null;

// ═══════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════
export function initTerminal() {
    const toggleBtn = document.getElementById("terminal-toggle-btn");
    const closeBtn = document.getElementById("terminal-close-btn");
    const clearBtn = document.getElementById("terminal-clear-btn");
    
    toggleBtn?.addEventListener("click", toggleTerminal);
    closeBtn?.addEventListener("click", () => setTerminalVisible(false));
    clearBtn?.addEventListener("click", clearTerminal);
    
    // Sandbox Control Buttons
    const sandboxStartBtn = document.getElementById("sandbox-start-btn");
    const sandboxStopBtn = document.getElementById("sandbox-stop-btn");
    
    sandboxStartBtn?.addEventListener("click", handleSandboxStart);
    sandboxStopBtn?.addEventListener("click", handleSandboxStop);
    
    // Initial Status Check
    checkSandboxStatus();
    
    console.log("[Terminal] Initialized with User-Sandbox support");
}

// ═══════════════════════════════════════════════════════════
// VISIBILITY
// ═══════════════════════════════════════════════════════════
export function toggleTerminal() {
    setTerminalVisible(!terminalVisible);
}

export function setTerminalVisible(visible) {
    terminalVisible = visible;
    
    const terminalPanel = document.getElementById("terminal-panel");
    const chatContainer = document.getElementById("chat-container");
    const toggleBtn = document.getElementById("terminal-toggle-btn");
    const mainContent = document.getElementById("main-content");
    
    if (visible) {
        // Terminal einblenden
        terminalPanel?.classList.remove("hidden");
        mainContent?.classList.add("terminal-open");
        toggleBtn?.classList.add("text-accent-primary");
        toggleBtn?.classList.remove("text-gray-400");
        
        // Scroll to bottom
        scrollTerminalToBottom();
    } else {
        // Terminal ausblenden
        terminalPanel?.classList.add("hidden");
        mainContent?.classList.remove("terminal-open");
        toggleBtn?.classList.remove("text-accent-primary");
        toggleBtn?.classList.add("text-gray-400");
    }
}

export function isTerminalVisible() {
    return terminalVisible;
}

// Auto-Show wenn Container startet
export function autoShowOnContainerStart() {
    if (!terminalVisible) {
        setTerminalVisible(true);
    }
}

// ═══════════════════════════════════════════════════════════
// TERMINAL OUTPUT
// ═══════════════════════════════════════════════════════════
export function clearTerminal() {
    const output = document.getElementById("terminal-output");
    if (output) {
        output.innerHTML = `<div class="text-gray-500 text-xs">Terminal bereit. Warte auf Code-Ausführung...</div>`;
    }
    terminalHistory = [];
    updateTerminalStatus("idle");
}

export function writeLine(text, type = "stdout") {
    const output = document.getElementById("terminal-output");
    if (!output) return;
    
    // Remove "waiting" message on first write
    const waiting = output.querySelector(".text-gray-500");
    if (waiting && terminalHistory.length === 0) {
        waiting.remove();
    }
    
    const line = document.createElement("div");
    line.className = getLineClass(type);
    
    // ANSI-Codes und Formatierung
    line.innerHTML = formatTerminalText(text, type);
    
    output.appendChild(line);
    terminalHistory.push({ text, type, timestamp: Date.now() });
    
    scrollTerminalToBottom();
}

export function writeCommand(cmd) {
    writeLine(`$ ${cmd}`, "command");
}

export function writeOutput(stdout, stderr) {
    if (stdout) {
        stdout.split("\n").forEach(line => {
            if (line.trim()) writeLine(line, "stdout");
        });
    }
    if (stderr) {
        stderr.split("\n").forEach(line => {
            if (line.trim()) writeLine(line, "stderr");
        });
    }
}

export function writeSeparator() {
    const output = document.getElementById("terminal-output");
    if (!output) return;
    
    const sep = document.createElement("div");
    sep.className = "border-t border-dark-border my-2";
    output.appendChild(sep);
}

function getLineClass(type) {
    const base = "font-mono text-sm leading-relaxed";
    switch (type) {
        case "command": return `${base} text-blue-400`;
        case "stdout": return `${base} text-green-400`;
        case "stderr": return `${base} text-red-400`;
        case "info": return `${base} text-gray-400`;
        case "success": return `${base} text-green-500 font-medium`;
        case "error": return `${base} text-red-500 font-medium`;
        default: return `${base} text-gray-300`;
    }
}

function formatTerminalText(text, type) {
    // Escape HTML
    let escaped = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    
    // Simple ANSI color support
    escaped = escaped
        .replace(/\x1b\[32m/g, '<span class="text-green-400">')  // Green
        .replace(/\x1b\[31m/g, '<span class="text-red-400">')    // Red
        .replace(/\x1b\[33m/g, '<span class="text-yellow-400">') // Yellow
        .replace(/\x1b\[34m/g, '<span class="text-blue-400">')   // Blue
        .replace(/\x1b\[0m/g, '</span>')                          // Reset
        .replace(/\x1b\[\d+m/g, '');                              // Remove other codes
    
    return escaped;
}

function scrollTerminalToBottom() {
    const output = document.getElementById("terminal-output");
    if (output) {
        output.scrollTop = output.scrollHeight;
    }
}

// ═══════════════════════════════════════════════════════════
// STATUS BAR
// ═══════════════════════════════════════════════════════════
export function updateTerminalStatus(status, details = {}) {
    const statusEl = document.getElementById("terminal-status");
    const containerEl = document.getElementById("terminal-container-name");
    const runtimeEl = document.getElementById("terminal-runtime");
    
    if (containerEl && details.container) {
        containerEl.textContent = details.container;
        containerEl.classList.remove("hidden");
    }
    
    if (runtimeEl && details.runtime) {
        runtimeEl.textContent = `⏱️ ${details.runtime}`;
        runtimeEl.classList.remove("hidden");
    }
    
    if (statusEl) {
        switch (status) {
            case "idle":
                statusEl.innerHTML = `<span class="text-gray-500">● Idle</span>`;
                break;
            case "starting":
                statusEl.innerHTML = `<span class="text-yellow-400 animate-pulse">● Starting...</span>`;
                break;
            case "running":
                statusEl.innerHTML = `<span class="text-blue-400 animate-pulse">● Running...</span>`;
                break;
            case "success":
                statusEl.innerHTML = `<span class="text-green-400">● Exit: ${details.exitCode ?? 0}</span>`;
                break;
            case "error":
                statusEl.innerHTML = `<span class="text-red-400">● Error: ${details.exitCode ?? 1}</span>`;
                break;
            default:
                statusEl.innerHTML = `<span class="text-gray-500">● ${status}</span>`;
        }
    }
}

// ═══════════════════════════════════════════════════════════
// LIVE TERMINAL (ttyd)
// ═══════════════════════════════════════════════════════════
export function showLiveTerminal(ttydUrl, sessionId) {
    const output = document.getElementById("terminal-output");
    if (!output) return;
    
    currentSession = sessionId;
    liveTerminalActive = true;
    
    // Live terminal iframe einfügen
    output.innerHTML = `
        <div class="flex flex-col h-full">
            <div class="bg-dark-tertiary p-2 flex items-center justify-between rounded-t border-b border-dark-border">
                <span class="text-green-400 text-xs flex items-center gap-2">
                    <span class="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                    Live Terminal (Session: ${sessionId?.slice(0, 8) || 'unknown'})
                </span>
                <div class="flex gap-2">
                    <button onclick="window.terminalModule.extendSession()" 
                            class="text-xs bg-dark-secondary hover:bg-dark-border px-2 py-1 rounded">
                        +5 Min
                    </button>
                    <button onclick="window.terminalModule.closeLiveTerminal()" 
                            class="text-xs bg-red-600 hover:bg-red-700 px-2 py-1 rounded">
                        Close
                    </button>
                </div>
            </div>
            <iframe 
                src="${ttydUrl}" 
                class="flex-1 w-full border-0 rounded-b bg-black"
                style="min-height: 300px;"
                id="ttyd-frame"
            ></iframe>
        </div>
    `;
    
    updateTerminalStatus("live", { container: "Live Session" });
    writeLine(`🔴 Live terminal connected`, "success");
}

export function closeLiveTerminal() {
    if (!currentSession) return;
    
    // Session schließen via API
    fetch(`/api/sessions/${currentSession}`, { method: 'DELETE' })
        .then(res => res.json())
        .then(data => {
            console.log("[Terminal] Session closed:", data);
            writeLine(`Session closed`, "info");
        })
        .catch(err => {
            console.error("[Terminal] Failed to close session:", err);
        });
    
    currentSession = null;
    liveTerminalActive = false;
    clearTerminal();
}

export async function extendSession() {
    if (!currentSession) return;
    
    try {
        const res = await fetch(`/api/sessions/${currentSession}/extend`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ extend_seconds: 300 })
        });
        
        const data = await res.json();
        writeLine(`⏰ Session extended by 5 minutes (TTL: ${data.new_ttl}s)`, "success");
    } catch (err) {
        console.error("[Terminal] Failed to extend session:", err);
        writeLine(`Failed to extend session`, "error");
    }
}

export function isLiveTerminalActive() {
    return liveTerminalActive;
}

// ═══════════════════════════════════════════════════════════
// SESSION INFO DISPLAY
// ═══════════════════════════════════════════════════════════
export function showSessionInfo(session) {
    const sessionBar = document.getElementById("terminal-session-bar");
    if (!sessionBar) return;
    
    if (session && session.persistent) {
        currentSession = session.session_id;
        sessionBar.innerHTML = `
            <div class="flex items-center justify-between bg-dark-tertiary px-3 py-1 text-xs">
                <span class="text-gray-400">
                    🔄 Session: ${session.session_id?.slice(0, 8)} | 
                    TTL: ${session.remaining_seconds || session.ttl_seconds}s
                </span>
                <div class="flex gap-2">
                    <button onclick="window.terminalModule.extendSession()" 
                            class="text-blue-400 hover:text-blue-300">
                        Extend +5min
                    </button>
                    <button onclick="window.terminalModule.closeLiveTerminal()" 
                            class="text-red-400 hover:text-red-300">
                        Close
                    </button>
                </div>
            </div>
        `;
        sessionBar.classList.remove("hidden");
    } else {
        sessionBar.classList.add("hidden");
        currentSession = null;
    }
}

// ═══════════════════════════════════════════════════════════
// CONTAINER EVENTS (called from chat.js)
// ═══════════════════════════════════════════════════════════
export function onContainerStart(container, task, session = null) {
    console.log("[Terminal] onContainerStart called:", container, task, session);
    autoShowOnContainerStart();
    writeSeparator();
    writeLine(`🚀 Starting container: ${container}`, "info");
    writeLine(`   Task: ${task}`, "info");
    updateTerminalStatus("starting", { container });
    
    // Session Info anzeigen wenn vorhanden
    if (session) {
        showSessionInfo(session);
        
        // Live Terminal wenn ttyd_url vorhanden
        if (session.ttyd_url) {
            writeLine(`🔴 Live terminal available`, "info");
            // Kurz warten bis Container bereit ist
            setTimeout(() => {
                showLiveTerminal(session.ttyd_url, session.session_id);
            }, 1000);
        }
    }
}

export function onContainerRunning(container) {
    console.log("[Terminal] onContainerRunning called:", container);
    updateTerminalStatus("running", { container });
    writeLine(`⏳ Executing code...`, "info");
}

export function onContainerDone(result) {
    console.log("[Terminal] onContainerDone called:", result);
    
    const exitCode = result?.exit_code ?? -1;
    const stdout = result?.stdout || "";
    const stderr = result?.stderr || "";
    const error = result?.error;
    
    console.log("[Terminal] Parsed result:", { exitCode, stdout, stderr, error });
    
    if (error) {
        writeLine(`❌ Error: ${error}`, "error");
        updateTerminalStatus("error", { exitCode: 1 });
        return;
    }
    
    // Output anzeigen
    if (stdout) {
        writeLine(`📤 Output:`, "info");
        writeOutput(stdout, null);
    }
    
    if (stderr) {
        writeLine(`⚠️ Stderr:`, "info");
        writeOutput(null, stderr);
    }
    
    // Status
    const isSuccess = exitCode === 0;
    if (isSuccess) {
        writeLine(`✅ Completed successfully (exit: ${exitCode})`, "success");
        updateTerminalStatus("success", { exitCode });
    } else {
        writeLine(`❌ Failed (exit: ${exitCode})`, "error");
        updateTerminalStatus("error", { exitCode });
    }
}

// ═══════════════════════════════════════════════════════════
// USER-SANDBOX CONTROL
// ═══════════════════════════════════════════════════════════

/**
 * Prüft den aktuellen Sandbox-Status und aktualisiert UI.
 */
export async function checkSandboxStatus() {
    try {
        const status = await getUserSandboxStatus();
        
        userSandboxActive = status.active === true;
        userSandboxInfo = status.active ? status : null;
        
        updateSandboxUI();
        
        return status;
    } catch (e) {
        console.error("[Terminal] Sandbox status check failed:", e);
        return { active: false, error: e.message };
    }
}

/**
 * Startet die User-Sandbox.
 */
async function handleSandboxStart() {
    const startBtn = document.getElementById("sandbox-start-btn");
    const stopBtn = document.getElementById("sandbox-stop-btn");
    
    // UI: Loading state
    if (startBtn) {
        startBtn.disabled = true;
        startBtn.innerHTML = `<i data-lucide="loader" class="w-4 h-4 animate-spin"></i>`;
    }
    
    writeLine(`🚀 Starte User-Sandbox...`, "info");
    
    try {
        const result = await startUserSandbox("code-sandbox");
        
        if (result.ok) {
            userSandboxActive = true;
            userSandboxInfo = result;
            
            writeLine(`✅ User-Sandbox gestartet!`, "success");
            writeLine(`   Session: ${result.session_id?.slice(0, 8)}`, "info");
            
            if (result.ttyd_port) {
                writeLine(`   Terminal-Port: ${result.ttyd_port}`, "info");
                
                // ttyd Terminal nach kurzer Verzögerung zeigen
                setTimeout(() => {
                    showUserSandboxTerminal(result.ttyd_port);
                }, 1500);
            }
            
            // Status-Polling starten
            startSandboxStatusPolling();
            
        } else {
            writeLine(`❌ Sandbox-Start fehlgeschlagen: ${result.error || 'Unbekannt'}`, "error");
            if (result.hint) {
                writeLine(`   💡 ${result.hint}`, "info");
            }
        }
        
    } catch (e) {
        writeLine(`❌ Fehler: ${e.message}`, "error");
    }
    
    updateSandboxUI();
    
    // Lucide Icons neu rendern
    if (window.lucide) lucide.createIcons();
}

/**
 * Stoppt die User-Sandbox.
 */
async function handleSandboxStop() {
    const stopBtn = document.getElementById("sandbox-stop-btn");
    
    // UI: Loading state
    if (stopBtn) {
        stopBtn.disabled = true;
        stopBtn.innerHTML = `<i data-lucide="loader" class="w-4 h-4 animate-spin"></i>`;
    }
    
    writeLine(`🛑 Stoppe User-Sandbox...`, "info");
    
    try {
        const result = await stopUserSandbox(false);
        
        if (result.ok) {
            userSandboxActive = false;
            userSandboxInfo = null;
            
            writeLine(`✅ User-Sandbox gestoppt.`, "success");
            
            // ttyd iframe entfernen
            hideSandboxTerminal();
            
            // Status-Polling stoppen
            stopSandboxStatusPolling();
            
        } else {
            writeLine(`❌ Stop fehlgeschlagen: ${result.error || 'Unbekannt'}`, "error");
        }
        
    } catch (e) {
        writeLine(`❌ Fehler: ${e.message}`, "error");
    }
    
    updateSandboxUI();
    
    // Lucide Icons neu rendern
    if (window.lucide) lucide.createIcons();
}

/**
 * Zeigt das ttyd Terminal im iframe.
 */
function showUserSandboxTerminal(port) {
    const output = document.getElementById("terminal-output");
    if (!output) return;
    
    // Docker Host IP ermitteln (für Zugriff von außen)
    const dockerHost = window.location.hostname;
    const ttydUrl = `http://${dockerHost}:${port}`;
    
    liveTerminalActive = true;
    
    output.innerHTML = `
        <div class="flex flex-col h-full">
            <div class="bg-dark-tertiary p-2 flex items-center justify-between rounded-t border-b border-dark-border">
                <span class="text-green-400 text-xs flex items-center gap-2">
                    <span class="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                    User-Sandbox Terminal (Port: ${port})
                </span>
                <span class="text-gray-500 text-xs">
                    Du kannst hier pip install, apt install etc. ausführen
                </span>
            </div>
            <iframe 
                src="${ttydUrl}" 
                class="flex-1 w-full border-0 rounded-b bg-black"
                style="min-height: 300px;"
                id="sandbox-ttyd-frame"
            ></iframe>
        </div>
    `;
    
    updateTerminalStatus("live", { container: "User-Sandbox" });
}

/**
 * Versteckt das ttyd Terminal.
 */
function hideSandboxTerminal() {
    liveTerminalActive = false;
    clearTerminal();
}

/**
 * Aktualisiert die Sandbox Control Buttons.
 */
function updateSandboxUI() {
    const startBtn = document.getElementById("sandbox-start-btn");
    const stopBtn = document.getElementById("sandbox-stop-btn");
    const statusEl = document.getElementById("sandbox-status");
    
    if (userSandboxActive) {
        // Sandbox läuft
        if (startBtn) {
            startBtn.classList.add("hidden");
        }
        if (stopBtn) {
            stopBtn.classList.remove("hidden");
            stopBtn.disabled = false;
            stopBtn.innerHTML = `<i data-lucide="square" class="w-4 h-4"></i>`;
        }
        if (statusEl) {
            const uptime = userSandboxInfo?.uptime || "...";
            statusEl.innerHTML = `<span class="text-green-400">● Aktiv</span> <span class="text-gray-500 text-xs">${uptime}</span>`;
            statusEl.classList.remove("hidden");
        }
    } else {
        // Sandbox inaktiv
        if (startBtn) {
            startBtn.classList.remove("hidden");
            startBtn.disabled = false;
            startBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4"></i>`;
        }
        if (stopBtn) {
            stopBtn.classList.add("hidden");
        }
        if (statusEl) {
            statusEl.innerHTML = `<span class="text-gray-500">● Inaktiv</span>`;
        }
    }
    
    // Lucide Icons neu rendern
    if (window.lucide) lucide.createIcons();
}

/**
 * Startet Status-Polling für Uptime-Anzeige.
 */
function startSandboxStatusPolling() {
    stopSandboxStatusPolling();  // Erst stoppen falls läuft
    
    sandboxStatusInterval = setInterval(async () => {
        if (userSandboxActive) {
            await checkSandboxStatus();
        } else {
            stopSandboxStatusPolling();
        }
    }, 10000);  // Alle 10 Sekunden
}

/**
 * Stoppt Status-Polling.
 */
function stopSandboxStatusPolling() {
    if (sandboxStatusInterval) {
        clearInterval(sandboxStatusInterval);
        sandboxStatusInterval = null;
    }
}

/**
 * Gibt zurück ob User-Sandbox aktiv ist.
 */
export function isUserSandboxActive() {
    return userSandboxActive;
}

/**
 * Gibt User-Sandbox Info zurück.
 */
export function getUserSandboxInfo() {
    return userSandboxInfo;
}

// ═══════════════════════════════════════════════════════════
// EXPORT für direkten Zugriff
// ═══════════════════════════════════════════════════════════
export const terminal = {
    init: initTerminal,
    toggle: toggleTerminal,
    show: () => setTerminalVisible(true),
    hide: () => setTerminalVisible(false),
    isVisible: isTerminalVisible,
    clear: clearTerminal,
    writeLine,
    writeCommand,
    writeOutput,
    writeSeparator,
    updateStatus: updateTerminalStatus,
    onContainerStart,
    onContainerRunning,
    onContainerDone,
    // Live Terminal
    showLiveTerminal,
    closeLiveTerminal,
    extendSession,
    isLiveTerminalActive,
    showSessionInfo,
    // User-Sandbox
    checkSandboxStatus,
    isUserSandboxActive,
    getUserSandboxInfo,
};

// Global für onclick Handler
window.terminalModule = terminal;
