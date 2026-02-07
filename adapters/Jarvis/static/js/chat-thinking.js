import { log } from "./debug.js";

// ═══════════════════════════════════════════════════════════
// THINKING / CONTROL BOX (with configurable label)
// ═══════════════════════════════════════════════════════════

export function createThinkingBox(messageId, label = "Control", icon = "shield-check") {
    const container = document.getElementById("messages-list");
    const welcome = document.getElementById("welcome-message");
    if (welcome) welcome.classList.add("hidden");

    const thinkingId = `thinking-${messageId}`;

    const div = document.createElement("div");
    div.id = thinkingId;
    div.className = "fade-in mb-2";

    div.innerHTML = `
        <details open class="bg-dark-card border border-dark-border rounded-xl overflow-hidden">
            <summary class="px-4 py-2 cursor-pointer hover:bg-dark-hover flex items-center gap-2 text-sm text-gray-400">
                <i data-lucide="${icon}" class="w-4 h-4 text-accent-secondary animate-pulse"></i>
                <span>${label}...</span>
                <span id="${thinkingId}-status" class="text-xs text-gray-500 ml-auto"></span>
            </summary>
            <div class="border-t border-dark-border">
                <div id="${thinkingId}-stream" class="px-4 py-3 text-sm text-gray-400 font-mono text-xs leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap"></div>
                <div id="${thinkingId}-meta" class="hidden px-4 py-3 border-t border-dark-border text-sm space-y-2"></div>
                <div id="${thinkingId}-container" class="hidden px-4 py-3 border-t border-dark-border"></div>
            </div>
        </details>
    `;

    container.appendChild(div);
    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });

    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;

    return thinkingId;
}

export function updateThinkingStream(thinkingId, chunk) {
    const streamEl = document.getElementById(`${thinkingId}-stream`);
    if (streamEl) {
        streamEl.textContent += chunk;
        streamEl.scrollTop = streamEl.scrollHeight;
    }

    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
}

export function finalizeThinking(thinkingId, thinking) {
    const box = document.getElementById(thinkingId);
    if (!box) return;

    const summary = box.querySelector("summary");
    const icon = summary.querySelector("svg") || summary.querySelector("i");

    if (icon) {
        icon.classList.remove("animate-pulse");
    }

    const riskColors = {
        low: "text-green-400",
        medium: "text-yellow-400",
        high: "text-red-400"
    };
    const risk = thinking.hallucination_risk || "medium";
    const riskColor = riskColors[risk] || "text-gray-400";

    const statusEl = document.getElementById(`${thinkingId}-status`);
    if (statusEl) {
        statusEl.innerHTML = `Risk: <span class="${riskColor}">${risk.toUpperCase()}</span>`;
    }

    const metaEl = document.getElementById(`${thinkingId}-meta`);
    if (metaEl) {
        metaEl.classList.remove("hidden");
        let metaHtml = "";
        if (thinking.intent) {
            metaHtml += `<div class="flex justify-between text-gray-500"><span>Intent:</span> <span class="text-gray-300">${thinking.intent}</span></div>`;
        }
        metaEl.innerHTML = metaHtml;
    }

    // Auto close low risk
    if (risk === "low" && !thinking.needs_memory) {
        setTimeout(() => {
            const details = box.querySelector("details");
            if (details) details.open = false;
        }, 1000);
    }
}

/**
 * Simple finalize for thinking boxes without a full plan object.
 * Used for seq_thinking_done which only has total_length.
 */
export function finalizeThinkingSimple(thinkingId) {
    const box = document.getElementById(thinkingId);
    if (!box) return;

    const summary = box.querySelector("summary");
    const icon = summary.querySelector("svg") || summary.querySelector("i");

    if (icon) icon.classList.remove("animate-pulse");

    // Update label to show it's done
    const labelSpan = summary.querySelector("span");
    if (labelSpan) labelSpan.textContent = "Thinking Complete";

    // Auto-collapse after 1.5s
    setTimeout(() => {
        const details = box.querySelector("details");
        if (details) details.open = false;
    }, 1500);
}

// ═══════════════════════════════════════════════════════════
// CONTROL LAYER UI
// ═══════════════════════════════════════════════════════════

export function createControlBox(messageId) {
    const container = document.getElementById("messages-list");
    const controlId = `control-${messageId}`;

    const div = document.createElement("div");
    div.id = controlId;
    div.className = "fade-in mb-2";

    div.innerHTML = `
        <div class="bg-dark-card border border-dark-border rounded-xl px-4 py-2 flex items-center gap-3">
             <i data-lucide="shield-check" class="w-4 h-4 text-accent-primary animate-pulse"></i>
             <span class="text-sm text-gray-400">Control Layer verifying...</span>
        </div>
    `;

    container.appendChild(div);
    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });

    return controlId;
}

export function finalizeControl(controlId, controlData) {
    const box = document.getElementById(controlId);
    if (!box) return;

    if (controlData.skipped) {
        box.remove();
        return;
    }

    const approved = controlData.approved;
    const color = approved ? "text-green-400" : "text-red-400";
    const icon = approved ? "check-circle" : "alert-triangle";
    const text = approved ? "Approved" : "Rejected";

    box.innerHTML = `
        <div class="bg-dark-card border border-dark-border rounded-xl px-4 py-2 flex items-center gap-3">
             <i data-lucide="${icon}" class="${color} w-4 h-4"></i>
             <span class="text-sm text-gray-400">Control Layer: <span class="${color} font-medium">${text}</span></span>
        </div>
    `;
    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });

    if (approved) {
        setTimeout(() => {
            box.classList.add("opacity-50");
        }, 3000);
    }
}

// ═══════════════════════════════════════════════════════════
// CONTAINER STATUS UI
// ═══════════════════════════════════════════════════════════

export function showContainerStart(thinkingId, container, task) {
    const containerEl = document.getElementById(`${thinkingId}-container`);
    if (containerEl) {
        containerEl.classList.remove("hidden");
        const entry = document.createElement("div");
        entry.className = "flex items-center gap-2 text-xs text-blue-400 mt-1";
        entry.innerHTML = `<i data-lucide="play" class="w-3 h-3"></i> <span>Running: ${container} (${task})</span>`;
        containerEl.appendChild(entry);
        if (window.lucide) window.lucide.createIcons();
    }
}

export function showContainerDone(thinkingId, result) {
    const containerEl = document.getElementById(`${thinkingId}-container`);
    if (containerEl) {
        const entry = document.createElement("div");
        const color = result.success ? "text-green-400" : "text-red-400";
        const icon = result.success ? "check" : "x";
        entry.className = `flex items-center gap-2 text-xs ${color} mt-1`;
        entry.innerHTML = `<i data-lucide="${icon}" class="w-3 h-3"></i> <span>Finished: ${result.container}</span>`;
        containerEl.appendChild(entry);
        if (window.lucide) window.lucide.createIcons();
    }
}
