import { log } from "./debug.js";

const planState = new Map(); // planId -> { count: number, hasError: boolean, finished: boolean }

function esc(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function toText(payload) {
    if (!payload || typeof payload !== "object") return "";
    const lines = [];
    for (const [key, value] of Object.entries(payload)) {
        if (value === undefined || value === null || value === "") continue;
        if (typeof value === "object") {
            try {
                lines.push(`${key}: ${JSON.stringify(value)}`);
            } catch {
                lines.push(`${key}: [object]`);
            }
            continue;
        }
        lines.push(`${key}: ${String(value)}`);
    }
    return lines.join("\n");
}

function buildEventView(eventType, payload) {
    const p = payload && typeof payload === "object" ? payload : {};
    if (eventType === "planning_start") {
        return {
            title: "Master Planning gestartet",
            badge: "start",
            detail: toText({
                objective: p.objective,
                max_loops: p.max_loops,
                state: p.state,
                planning_mode: p.planning_mode,
                summary: p.summary,
            }),
        };
    }
    if (eventType === "planning_step") {
        return {
            title: p.phase ? `Master Schritt (${p.phase})` : "Master Schritt",
            badge: "step",
            detail: toText({
                loop: p.loop,
                decision: p.decision,
                action: p.action,
                next_action: p.next_action,
                reason: p.reason,
                summary: p.summary,
            }),
        };
    }
    if (eventType === "planning_done") {
        return {
            title: "Master Planning abgeschlossen",
            badge: "done",
            detail: toText({
                loops_executed: p.loops_executed,
                steps_completed: p.steps_completed,
                final_state: p.final_state,
                stop_reason: p.stop_reason,
                summary: p.summary,
            }),
        };
    }
    if (eventType === "planning_error") {
        return {
            title: "Master Planning Fehler",
            badge: "error",
            detail: toText({
                phase: p.phase,
                error: p.error,
                error_code: p.error_code,
                action: p.action,
                stop_reason: p.stop_reason,
                summary: p.summary,
            }),
        };
    }
    if (eventType === "sequential_start") {
        return {
            title: "Sequential gestartet",
            badge: "start",
            detail: toText({
                task_id: p.task_id,
                complexity: p.complexity,
                reasoning_type: p.reasoning_type,
            }),
        };
    }
    if (eventType === "sequential_step") {
        return {
            title: `Sequential Step ${p.step_number || p.step_num || p.step || "?"}`,
            badge: "step",
            detail: toText({
                title: p.title,
                thought: p.thought || p.content || p.text,
            }),
        };
    }
    if (eventType === "sequential_done") {
        return {
            title: "Sequential abgeschlossen",
            badge: "done",
            detail: toText({
                task_id: p.task_id,
                summary: p.summary,
                steps: Array.isArray(p.steps) ? p.steps.length : undefined,
            }),
        };
    }
    if (eventType === "sequential_error") {
        return {
            title: "Sequential Fehler",
            badge: "error",
            detail: toText({
                task_id: p.task_id,
                error: p.error,
            }),
        };
    }
    if (eventType === "loop_trace_started") {
        return {
            title: "Loop-Trace gestartet",
            badge: "start",
            detail: toText({
                objective: p.objective,
                intent: p.intent,
                resolution_strategy: p.resolution_strategy,
                suggested_tools: p.suggested_tools,
                needs_memory: p.needs_memory,
                needs_sequential_thinking: p.needs_sequential_thinking,
            }),
        };
    }
    if (eventType === "loop_trace_plan_normalized") {
        return {
            title: "Plan normalisiert",
            badge: "step",
            detail: toText({
                mode: p.mode,
                reason: p.reason,
                resolution_strategy: p.resolution_strategy,
                suggested_tools: p.suggested_tools,
                needs_memory: p.needs_memory,
                corrections: p.corrections,
            }),
        };
    }
    if (eventType === "loop_trace_step_started") {
        return {
            title: p.phase ? `Loop-Schritt (${p.phase})` : "Loop-Schritt",
            badge: "step",
            detail: toText({
                summary: p.summary,
                details: p.details,
            }),
        };
    }
    if (eventType === "loop_trace_correction") {
        return {
            title: "Korrektur angewendet",
            badge: "step",
            detail: toText({
                stage: p.stage,
                summary: p.summary,
                reasons: p.reasons,
                details: p.details,
            }),
        };
    }
    if (eventType === "loop_trace_completed") {
        return {
            title: "Loop-Trace abgeschlossen",
            badge: "done",
            detail: toText({
                response_mode: p.response_mode,
                model: p.model,
                correction_count: p.correction_count,
                summary: p.summary,
            }),
        };
    }
    if (eventType === "task_loop_update") {
        const state = p.state || "";
        const stepIndex = p.task_loop?.step_index ?? "";
        const pendingStep = p.task_loop?.pending_step || "";
        const doneReason = p.done_reason || "";
        const isFinal = Boolean(p.is_final);

        const badge = isFinal
            ? (doneReason === "task_loop_completed" ? "done" : "warn")
            : "step";

        const title = isFinal
            ? (doneReason === "task_loop_completed"
                ? "Task-Loop abgeschlossen"
                : `Task-Loop gestoppt (${doneReason})`)
            : stepIndex !== ""
                ? `Schritt ${stepIndex}`
                : "Task-Loop läuft";

        return {
            title,
            badge,
            detail: toText({
                state,
                pending_step: pendingStep || undefined,
                done_reason: doneReason || undefined,
            }),
        };
    }
    return {
        title: eventType || "plan_event",
        badge: "step",
        detail: toText(p),
    };
}

function badgeClass(type) {
    if (type === "done") return "text-green-400";
    if (type === "error") return "text-red-400";
    if (type === "start") return "text-blue-400";
    return "text-gray-400";
}

function ensureAutoScroll() {
    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
}

function updateHeader(planId) {
    const state = planState.get(planId);
    if (!state) return;
    const statusEl = document.getElementById(`${planId}-status`);
    const titleEl = document.getElementById(`${planId}-title`);
    if (!statusEl || !titleEl) return;
    const stepText = `${state.count} Schritt${state.count === 1 ? "" : "e"}`;
    if (state.hasError) {
        statusEl.innerHTML = `${stepText} · <span class="text-red-400">Fehler</span>`;
    } else if (state.finished) {
        statusEl.innerHTML = `${stepText} · <span class="text-green-400">Fertig</span>`;
    } else {
        statusEl.textContent = stepText;
    }
}

export function createPlanBox(messageId) {
    const container = document.getElementById("messages-list");
    const welcome = document.getElementById("welcome-message");
    if (!container) return null;
    if (welcome) welcome.classList.add("hidden");

    const planId = `plan-${messageId}`;
    planState.set(planId, { count: 0, hasError: false, finished: false });

    const div = document.createElement("div");
    div.id = planId;
    div.className = "fade-in mb-2";
    div.innerHTML = `
        <details open class="bg-dark-card border border-dark-border rounded-xl overflow-hidden">
            <summary class="px-4 py-2 cursor-pointer hover:bg-dark-hover flex items-center gap-2 text-sm text-gray-300">
                <i data-lucide="route" class="w-4 h-4 text-cyan-400 animate-pulse"></i>
                <span id="${planId}-title">Planmodus (live)</span>
                <span id="${planId}-status" class="text-xs text-gray-500 ml-auto">0 Schritte</span>
            </summary>
            <div class="border-t border-dark-border">
                <div id="${planId}-steps" class="px-3 py-3 space-y-2 max-h-96 overflow-y-auto"></div>
            </div>
        </details>
    `;

    container.appendChild(div);
    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });
    ensureAutoScroll();
    log("info", `Plan box created: ${planId}`);
    return planId;
}

export function appendPlanEvent(planId, eventType, payload = {}) {
    if (!planId) return;
    const state = planState.get(planId);
    const stepsEl = document.getElementById(`${planId}-steps`);
    if (!state || !stepsEl) return;

    const stepNo = state.count + 1;
    state.count = stepNo;
    if (
        eventType === "planning_error"
        || eventType === "sequential_error"
        || (
            eventType === "task_loop_update"
            && Boolean(payload?.is_final)
            && String(payload?.done_reason || "") !== "task_loop_completed"
        )
    ) {
        state.hasError = true;
    }
    if (
        eventType === "planning_done"
        || eventType === "loop_trace_completed"
        || (eventType === "task_loop_update" && Boolean(payload?.is_final))
    ) {
        state.finished = true;
    }

    const view = buildEventView(eventType, payload);
    const detail = String(view.detail || "").trim() || "Keine Details";

    const block = document.createElement("details");
    block.className = "bg-dark-hover/60 border border-dark-border rounded-lg";
    block.innerHTML = `
        <summary class="px-3 py-2 cursor-pointer hover:bg-dark-hover text-xs flex items-center gap-2">
            <span class="text-gray-500">#${stepNo}</span>
            <span class="${badgeClass(view.badge)}">${esc(view.title)}</span>
            <span class="text-gray-600 ml-auto">${esc(eventType)}</span>
        </summary>
        <div class="px-3 pb-3">
            <pre class="text-xs text-gray-300 whitespace-pre-wrap break-words font-mono leading-relaxed">${esc(detail)}</pre>
        </div>
    `;
    stepsEl.appendChild(block);

    updateHeader(planId);
    ensureAutoScroll();
}

export function finalizePlanBox(planId, summary = "") {
    if (!planId) return;
    const state = planState.get(planId);
    if (!state) return;
    state.finished = true;

    const titleEl = document.getElementById(`${planId}-title`);
    if (titleEl) {
        titleEl.textContent = state.hasError ? "Planmodus (mit Fehlern)" : "Planmodus abgeschlossen";
    }

    const icon = document.querySelector(`#${planId} summary [data-lucide]`);
    if (icon) {
        icon.classList.remove("animate-pulse");
        icon.setAttribute("data-lucide", state.hasError ? "alert-triangle" : "check-circle");
    }

    if (summary) {
        appendPlanEvent(planId, "planning_done", { summary });
    } else {
        updateHeader(planId);
    }

    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });
    log("info", `Plan box finalized: ${planId}`);
}
