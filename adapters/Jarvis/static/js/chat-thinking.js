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
                <div id="${thinkingId}-stream-label" class="px-4 pt-3 text-[11px] uppercase tracking-wide text-gray-500">Live Trace</div>
                <div id="${thinkingId}-stream" class="px-4 py-3 text-sm text-gray-400 font-mono text-xs leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap"></div>
                <div id="${thinkingId}-meta-label" class="hidden px-4 pt-3 border-t border-dark-border text-[11px] uppercase tracking-wide text-gray-500">Thinking Summary</div>
                <div id="${thinkingId}-meta" class="hidden px-4 py-3 text-sm space-y-2"></div>
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

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
}

function renderMetaRow(label, value, valueClass = "text-gray-300") {
    return `<div class="flex justify-between gap-4 text-gray-500"><span>${escapeHtml(label)}:</span> <span class="${valueClass} text-right">${escapeHtml(value)}</span></div>`;
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
    const metaLabelEl = document.getElementById(`${thinkingId}-meta-label`);
    const streamEl = document.getElementById(`${thinkingId}-stream`);
    if (metaEl) {
        metaEl.classList.remove("hidden");
        if (metaLabelEl) metaLabelEl.classList.remove("hidden");
        const summary = box.querySelector("summary");
        const labelSpan = summary ? summary.querySelector("span") : null;
        if (labelSpan) {
            labelSpan.textContent = "Thinking Plan";
        }

        const memoryKeys = Array.isArray(thinking.memory_keys) ? thinking.memory_keys.filter(Boolean) : [];
        const suggestedTools = Array.isArray(thinking.suggested_tools) ? thinking.suggested_tools.filter(Boolean) : [];
        const finalExecutionTools = Array.isArray(thinking.final_execution_tools) ? thinking.final_execution_tools.filter(Boolean) : [];
        const strategyHints = Array.isArray(thinking.strategy_hints) ? thinking.strategy_hints.filter(Boolean) : [];
        const requiredTools = Array.isArray(thinking.skill_catalog_required_tools) ? thinking.skill_catalog_required_tools.filter(Boolean) : [];
        const forceSections = Array.isArray(thinking.skill_catalog_force_sections) ? thinking.skill_catalog_force_sections.filter(Boolean) : [];
        const metaRows = [];

        if (thinking.intent) {
            metaRows.push(renderMetaRow("Intent", thinking.intent));
        }
        if (thinking.resolution_strategy) {
            metaRows.push(renderMetaRow("Strategy", thinking.resolution_strategy, "text-sky-300"));
        }
        if (memoryKeys.length) {
            metaRows.push(renderMetaRow("Memory", memoryKeys.join(", ")));
        }
        if (suggestedTools.length) {
            metaRows.push(renderMetaRow("Tools", suggestedTools.join(", ")));
        }
        if (finalExecutionTools.length) {
            metaRows.push(renderMetaRow("Exec Tools", finalExecutionTools.join(", "), "text-sky-300"));
        }
        if (strategyHints.length) {
            metaRows.push(renderMetaRow("Hints", strategyHints.join(", ")));
        }
        const catalogHints = Array.isArray(thinking.skill_catalog_hints) ? thinking.skill_catalog_hints.filter(Boolean) : [];
        const catalogDocs = Array.isArray(thinking.skill_catalog_docs) ? thinking.skill_catalog_docs.filter(Boolean) : [];
        if (catalogHints.length) {
            metaRows.push(renderMetaRow("Catalog Hints", catalogHints.join(", ")));
        }
        if (catalogDocs.length) {
            metaRows.push(renderMetaRow("Addon Docs", catalogDocs.join(", ")));
        }
        if (thinking.skill_catalog_strict_mode) {
            metaRows.push(renderMetaRow("Inventory Mode", thinking.skill_catalog_strict_mode, "text-sky-300"));
        }
        if (thinking.skill_catalog_postcheck) {
            metaRows.push(renderMetaRow("Postcheck", thinking.skill_catalog_postcheck, "text-amber-300"));
        }
        if (thinking.skill_catalog_policy_mode) {
            metaRows.push(renderMetaRow("Policy", thinking.skill_catalog_policy_mode, "text-sky-300"));
        }
        if (requiredTools.length) {
            metaRows.push(renderMetaRow("Required Tools", requiredTools.join(", "), "text-sky-300"));
        }
        if (forceSections.length) {
            metaRows.push(renderMetaRow("Sections", forceSections.join(", "), "text-sky-300"));
        }
        if (thinking.skill_catalog_tool_route) {
            metaRows.push(renderMetaRow("Tool Route", thinking.skill_catalog_tool_route, "text-sky-300"));
        }
        if (thinking.skill_catalog_tool_route_reason && thinking.skill_catalog_tool_route_reason !== "none") {
            metaRows.push(renderMetaRow("Route Reason", thinking.skill_catalog_tool_route_reason, "text-amber-300"));
        }
        if (thinking.loop_trace_mode) {
            metaRows.push(renderMetaRow("Loop Mode", thinking.loop_trace_mode, "text-cyan-300"));
        }
        if (thinking.loop_trace_reason) {
            metaRows.push(renderMetaRow("Loop Reason", thinking.loop_trace_reason, "text-amber-300"));
        }
        if (Array.isArray(thinking.loop_trace_corrections) && thinking.loop_trace_corrections.length) {
            metaRows.push(renderMetaRow("Plan Fixes", `${thinking.loop_trace_corrections.length}`, "text-cyan-300"));
        }
        metaRows.push(renderMetaRow("Fact Query", thinking.is_fact_query ? "yes" : "no"));
        metaRows.push(renderMetaRow("Uses History", thinking.needs_chat_history ? "yes" : "no"));
        if (thinking.response_length_hint) {
            metaRows.push(renderMetaRow("Response", thinking.response_length_hint));
        }
        if (thinking.cached) {
            metaRows.push(renderMetaRow("Source", "cache", "text-emerald-300"));
        } else if (thinking.source) {
            metaRows.push(renderMetaRow("Source", thinking.source, "text-emerald-300"));
        }
        if (thinking.skipped) {
            metaRows.push(renderMetaRow("Status", "skipped", "text-amber-300"));
        }
        if (thinking.reason) {
            metaRows.push(renderMetaRow("Reason", thinking.reason, "text-amber-300"));
        }
        metaEl.innerHTML = metaRows.join("");
    }

    if (streamEl && thinking && thinking.source === "trace_final") {
        const finalTrace = {
            intent: thinking.intent || "unknown",
            resolution_strategy: thinking.resolution_strategy || null,
            strategy_hints: Array.isArray(thinking.strategy_hints) ? thinking.strategy_hints : [],
            suggested_tools: Array.isArray(thinking.suggested_tools) ? thinking.suggested_tools : [],
            final_execution_tools: Array.isArray(thinking.final_execution_tools) ? thinking.final_execution_tools : [],
            needs_sequential_thinking: Boolean(thinking.needs_sequential_thinking),
            needs_chat_history: Boolean(thinking.needs_chat_history),
            is_fact_query: Boolean(thinking.is_fact_query),
            skill_catalog_hints: Array.isArray(thinking.skill_catalog_hints) ? thinking.skill_catalog_hints : [],
            skill_catalog_docs: Array.isArray(thinking.skill_catalog_docs) ? thinking.skill_catalog_docs : [],
            skill_catalog_postcheck: thinking.skill_catalog_postcheck || null,
            skill_catalog_policy_mode: thinking.skill_catalog_policy_mode || null,
            skill_catalog_required_tools: Array.isArray(thinking.skill_catalog_required_tools) ? thinking.skill_catalog_required_tools : [],
            skill_catalog_force_sections: Array.isArray(thinking.skill_catalog_force_sections) ? thinking.skill_catalog_force_sections : [],
            skill_catalog_tool_route: thinking.skill_catalog_tool_route || null,
            skill_catalog_tool_route_reason: thinking.skill_catalog_tool_route_reason || null,
            loop_trace_mode: thinking.loop_trace_mode || null,
            loop_trace_reason: thinking.loop_trace_reason || null,
            loop_trace_corrections: Array.isArray(thinking.loop_trace_corrections) ? thinking.loop_trace_corrections : [],
            source: thinking.source,
        };
        streamEl.textContent = JSON.stringify(finalTrace, null, 2);
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

    const decisionClass = controlData.decision_class || (controlData.approved ? "allow" : "hard_block");
    const colorMap = {
        allow:        "text-green-400",
        warn:         "text-yellow-400",
        routing_block:"text-orange-400",
        hard_block:   "text-red-400",
    };
    const iconMap = {
        allow:        "check-circle",
        warn:         "alert-triangle",
        routing_block:"git-branch",
        hard_block:   "x-circle",
    };
    const textMap = {
        allow:        "Approved",
        warn:         "Approved (Warning)",
        routing_block:"Routing Block",
        hard_block:   "Rejected",
    };
    const color = colorMap[decisionClass] || "text-gray-400";
    const icon  = iconMap[decisionClass]  || "alert-triangle";
    const text  = textMap[decisionClass]  || decisionClass;

    box.innerHTML = `
        <div class="bg-dark-card border border-dark-border rounded-xl px-4 py-2 flex items-center gap-3">
             <i data-lucide="${icon}" class="${color} w-4 h-4"></i>
             <span class="text-sm text-gray-400">Control Layer: <span class="${color} font-medium">${text}</span></span>
        </div>
    `;
    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });

    if (decisionClass === "allow" || decisionClass === "warn") {
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
