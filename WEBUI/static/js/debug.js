// debug.js - Debug Logging System

let verbose = false;

export function setVerbose(v) {
    verbose = v;
}

export function log(level, message, data = null) {
    const timestamp = new Date().toLocaleTimeString();
    const logsEl = document.getElementById("debug-logs");
    
    // Skip debug messages if not verbose
    if (level === "debug" && !verbose) {
        return;
    }
    
    // Console log
    const consoleMethod = level === "error" ? "error" : level === "warn" ? "warn" : "log";
    console[consoleMethod](`[${level.toUpperCase()}] ${message}`, data || "");
    
    // UI log
    if (logsEl) {
        const entry = document.createElement("div");
        entry.className = `log-${level} border-b border-dark-border/50 pb-1 mb-1`;
        
        let html = `<span class="text-gray-500">${timestamp}</span> `;
        html += `<span class="log-${level}">[${level.toUpperCase()}]</span> `;
        html += `<span class="text-gray-300">${escapeHtml(message)}</span>`;
        
        if (data) {
            const dataStr = typeof data === "object" ? JSON.stringify(data, null, 2) : String(data);
            html += `<pre class="text-gray-500 mt-1 text-[10px] overflow-x-auto">${escapeHtml(dataStr)}</pre>`;
        }
        
        entry.innerHTML = html;
        logsEl.appendChild(entry);
        
        // Auto-scroll
        logsEl.scrollTop = logsEl.scrollHeight;
        
        // Limit logs
        while (logsEl.children.length > 100) {
            logsEl.removeChild(logsEl.firstChild);
        }
    }
}

export function clearLogs() {
    const logsEl = document.getElementById("debug-logs");
    if (logsEl) {
        logsEl.innerHTML = "";
    }
    log("info", "Logs cleared");
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// Convenience methods
export const logInfo = (msg, data) => log("info", msg, data);
export const logWarn = (msg, data) => log("warn", msg, data);
export const logError = (msg, data) => log("error", msg, data);
export const logDebug = (msg, data) => log("debug", msg, data);
