import { log } from "./debug.js";

// ═══════════════════════════════════════════════════════════
// SEQUENTIAL THINKING (Fixed: stream content per step, not per word)
// ═══════════════════════════════════════════════════════════

// Track active steps per sequential box to APPEND content instead of creating new steps
const activeSteps = new Map(); // seqId -> { currentStepNum, stepElements: Map<stepNum, element> }

export function createSequentialBox(messageId) {
    const container = document.getElementById("messages-list");
    const welcome = document.getElementById("welcome-message");
    if (welcome) welcome.classList.add("hidden");

    const seqId = `sequential-${messageId}`;

    // Reset tracking for this box
    activeSteps.set(seqId, { currentStepNum: null, stepElements: new Map() });

    const div = document.createElement("div");
    div.id = seqId;
    div.className = "fade-in mb-2";

    div.innerHTML = `
        <details open class="bg-dark-card border border-dark-border rounded-xl overflow-hidden">
            <summary class="px-4 py-2 cursor-pointer hover:bg-dark-hover flex items-center gap-2 text-sm text-gray-400">
                <i data-lucide="zap" class="w-4 h-4 text-yellow-400 animate-pulse"></i>
                <span>Sequential Thinking...</span>
                <span id="${seqId}-count" class="text-xs text-gray-500 ml-auto">0 steps</span>
            </summary>
            <div class="border-t border-dark-border">
                <div id="${seqId}-steps" class="px-4 py-3 space-y-3 max-h-96 overflow-y-auto">
                </div>
            </div>
        </details>
    `;

    container.appendChild(div);
    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });

    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;

    log("info", `Sequential thinking box created: ${seqId}`);
    return seqId;
}

/**
 * Add or APPEND content to a sequential step.
 * ✅ FIX: If same step_num arrives again, APPEND content instead of creating a new DOM element.
 *    This fixes the "one word per step" bug where streamed tokens each created a new step.
 */
export function addSequentialStep(seqId, stepNum, title, content) {
    const tracking = activeSteps.get(seqId);
    if (!tracking) return;

    const stepsEl = document.getElementById(`${seqId}-steps`);
    const countEl = document.getElementById(`${seqId}-count`);
    if (!stepsEl) return;

    // Check if this step already exists
    const existingStep = tracking.stepElements.get(String(stepNum));

    if (existingStep) {
        // ✅ APPEND content to existing step
        const contentEl = existingStep.querySelector(".seq-step-content");
        if (contentEl) {
            contentEl.textContent += content;
        }
        // Update title if it changed from "Thinking..."
        if (title && title !== "Thinking...") {
            const titleEl = existingStep.querySelector(".seq-step-title");
            if (titleEl) titleEl.textContent = title;
        }
    } else {
        // Create NEW step element
        const stepDiv = document.createElement("div");
        stepDiv.className = "border-l-2 border-yellow-400 pl-3 fade-in";
        stepDiv.innerHTML = `
            <div class="flex items-center gap-2 mb-1">
                <span class="text-yellow-400 font-semibold text-sm">Step ${stepNum}</span>
                <span class="seq-step-title text-gray-400 text-sm">${title || ''}</span>
            </div>
            <div class="seq-step-content text-gray-300 text-sm whitespace-pre-wrap leading-relaxed">${content || ''}</div>
        `;
        stepsEl.appendChild(stepDiv);
        tracking.stepElements.set(String(stepNum), stepDiv);

        // Update step count
        if (countEl) {
            const totalSteps = tracking.stepElements.size;
            countEl.textContent = `${totalSteps} step${totalSteps > 1 ? 's' : ''}`;
        }
    }

    // Scroll to bottom
    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
}

/**
 * Add a COMPLETE step (from sequential_step events, not streamed).
 * Used for the finalized step results that come as complete blocks.
 */
export function addCompleteStep(seqId, stepNum, title, content) {
    const tracking = activeSteps.get(seqId);
    if (!tracking) return;

    const stepsEl = document.getElementById(`${seqId}-steps`);
    const countEl = document.getElementById(`${seqId}-count`);
    if (!stepsEl) return;

    const stepDiv = document.createElement("div");
    stepDiv.className = "border-l-2 border-green-400 pl-3 fade-in";
    stepDiv.innerHTML = `
        <div class="flex items-center gap-2 mb-1">
            <span class="text-green-400 font-semibold text-sm">Step ${stepNum}</span>
            <span class="text-gray-300 text-sm font-medium">${title || ''}</span>
        </div>
        <div class="text-gray-400 text-sm whitespace-pre-wrap leading-relaxed">${content || ''}</div>
    `;
    stepsEl.appendChild(stepDiv);
    tracking.stepElements.set(`complete-${stepNum}`, stepDiv);

    if (countEl) {
        const totalSteps = tracking.stepElements.size;
        countEl.textContent = `${totalSteps} step${totalSteps > 1 ? 's' : ''}`;
    }

    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
}

export function finalizeSequentialBox(seqId, summary) {
    const box = document.getElementById(seqId);
    if (!box) {
        log("error", `Sequential box not found: ${seqId}`);
        return;
    }

    const summaryEl = box.querySelector("summary");
    const icon = summaryEl.querySelector("svg") || summaryEl.querySelector("i");

    if (icon) {
        icon.classList.remove("animate-pulse");
        icon.setAttribute("data-lucide", "check-circle");
    }

    summaryEl.querySelector("span").textContent = "Sequential Thinking Complete";

    // Add summary if provided
    if (summary) {
        const stepsEl = document.getElementById(`${seqId}-steps`);
        if (stepsEl) {
            const summaryDiv = document.createElement("div");
            summaryDiv.className = "border-t border-dark-border pt-3 mt-3";
            summaryDiv.innerHTML = `
                <div class="text-green-400 font-semibold text-sm mb-2">✅ Summary</div>
                <div class="text-gray-300 text-sm whitespace-pre-wrap leading-relaxed">${summary}</div>
            `;
            stepsEl.appendChild(summaryDiv);
        }
    }

    // Auto-collapse after 2 seconds
    setTimeout(() => {
        const details = box.querySelector("details");
        if (details) details.open = false;
    }, 2000);

    // Cleanup tracking
    activeSteps.delete(seqId);

    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });
    log("info", `Sequential thinking box finalized: ${seqId}`);
}
