// chat.js - Main Controller (Fixed v3: correct box types + thought field)
import { streamChat, getApiBase, submitDeepChatJob, waitForDeepChatJob } from "./api.js";
import { log } from "./debug.js";

// Modules
import * as UI from "./chat-ui.js";
import * as State from "./chat-state.js";
import * as Render from "./chat-render.js";
import * as Thinking from "./chat-thinking.js";
import * as Sequential from "./chat-sequential.js";

// Proxied Exports (State Access)
export { setModel, getModel, isLoading, setHistoryLimit, getMessageCount } from "./chat-state.js";

// ═══════════════════════════════════════════════════════════
// HISTORY DISPLAY
// ═══════════════════════════════════════════════════════════

function updateHistoryDisplay(count, sent) {
    const countEl = document.getElementById("history-count");
    const sentEl = document.getElementById("history-sent");
    const statusCountEl = document.getElementById("history-status-count");

    if (countEl) countEl.textContent = count;
    if (sentEl) sentEl.textContent = sent;
    if (statusCountEl) statusCountEl.textContent = count;
}

// ═══════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════

export function initChatFromStorage() {
    if (State.loadChatFromStorage()) {
        const messages = State.getMessages();
        if (messages.length > 0) {
            const welcome = document.getElementById("welcome-message");
            if (welcome) welcome.classList.add("hidden");

            messages.forEach(msg => {
                Render.renderMessage(msg.role, msg.content, false);
            });

            UI.scrollToBottom();
            updateHistoryDisplay(messages.length, Math.min(messages.length, 20));
        }
    }
}

export function clearChat() {
    State.clearStorage();
    document.getElementById("messages-list").innerHTML = "";
    const welcome = document.getElementById("welcome-message");
    if (welcome) welcome.classList.remove("hidden");

    updateHistoryDisplay(0, 0);
    log("info", "Chat cleared (Controller)");
}

// ═══════════════════════════════════════════════════════════
// HANDLE USER MESSAGE (v3: 3 box types, thought field fix)
// ═══════════════════════════════════════════════════════════

export async function handleUserMessage(text, options = {}) {
    if (!text.trim() || State.isLoading()) return;

    const model = State.getModel();
    if (!model) {
        alert("Bitte wähle zuerst ein Model aus!");
        return;
    }

    State.setProcessing(true);
    UI.updateUIState(true);

    // Add User Message
    Render.renderMessage("user", text, false);
    State.addMessage({ role: "user", content: text });
    State.saveChatToStorage();

    // Prepare for backend
    const messagesToSend = State.getMessagesForBackend();
    const conversationId = State.getConversationId();
    updateHistoryDisplay(State.getMessageCount(), messagesToSend.length);

    log("info", `Sending message with ${messagesToSend.length} messages in history`);

    // === State tracking ===
    const baseMsgId = Date.now();
    const useDeepJob = Boolean(options.deepJob);
    let controlThinkingId = null;  // Box 1: "Control" (classifier plan)
    let seqThinkingId = null;      // Box 2: "Thinking" (deepseek thinking stream)
    let currentSeqId = null;       // Box 3: "Sequential Thinking" (structured steps)
    let botMsgId = null;
    let fullResponse = "";
    let usedModel = model;
    let controlBlockId = null;

    try {
        if (useDeepJob) {
            if (!botMsgId) {
                botMsgId = Render.renderMessage("assistant", "", true);
            }

            const deepIntro = "Deep job wird gestartet…";
            Render.updateMessage(botMsgId, deepIntro, true);
            log("info", `Starting deep chat job for conversation=${conversationId}`);

            const job = await submitDeepChatJob(model, messagesToSend, conversationId);
            const jobId = job?.job_id;
            if (!jobId) {
                throw new Error("Deep job submit returned no job_id");
            }

            const status = await waitForDeepChatJob(jobId, {
                pollIntervalMs: 1500,
                timeoutMs: 15 * 60 * 1000,
                onProgress: (st) => {
                    const phase = String(st?.status || "queued");
                    const duration = Number(st?.duration_ms || 0);
                    const sec = duration > 0 ? Math.round(duration / 1000) : 0;
                    const progress = sec > 0
                        ? `Deep job ${phase} · ${sec}s`
                        : `Deep job ${phase}…`;
                    Render.updateMessage(botMsgId, progress, true);
                },
            });

            const result = status?.result || {};
            const resultContent = String(result?.message?.content || "").trim();
            usedModel = result?.model || usedModel;
            fullResponse = resultContent || "Deep job completed without response content.";

            Render.updateMessage(botMsgId, fullResponse, false);
            State.addMessage({ role: "assistant", content: fullResponse });
            State.saveChatToStorage();

            fetch(`${getApiBase()}/api/protocol/append`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    user_message: text,
                    ai_response: fullResponse,
                    timestamp: new Date().toISOString(),
                    conversation_id: conversationId,
                })
            }).catch(err => console.warn("[Chat] Protocol append failed:", err));

            updateHistoryDisplay(State.getMessageCount(), messagesToSend.length);
            log("info", `Deep response complete, total messages: ${State.getMessageCount()}, model: ${usedModel}`);
            return;
        }

        for await (const chunk of streamChat(model, messagesToSend, conversationId)) {

            // ═══════════════════════════════════════════
            // BOX 1: CONTROL (Classifier / Thinking Plan)
            // Label: "Control", Icon: shield-check
            // ═══════════════════════════════════════════

            if (chunk.type === "thinking_stream") {
                if (!controlThinkingId) {
                    controlThinkingId = Thinking.createThinkingBox(baseMsgId, "Control", "shield-check");
                }
                Thinking.updateThinkingStream(controlThinkingId, chunk.chunk);
                continue;
            }

            // ═══════════════════════════════════════════
            // CONTEXT COMPRESSION — Triangle Loading
            // ═══════════════════════════════════════════

            if (chunk.type === "compression_start") {
                const tokK = Math.round((chunk.token_count || 0) / 1000);
                const modeLabel = chunk.mode === "async" ? " (async)" : "";
                if (!botMsgId) botMsgId = Render.renderMessage("assistant", "", true);
                const comprEl = document.createElement("div");
                comprEl.id = `compression-${baseMsgId}`;
                comprEl.className = "compression-indicator";
                comprEl.innerHTML = `
                    <div class="compression-triangle">▲</div>
                    <span class="compression-text">Summarizing conversation${modeLabel} · ${tokK}k tokens…</span>
                `;
                const msgEl = document.getElementById(botMsgId);
                if (msgEl) msgEl.parentElement.insertBefore(comprEl, msgEl);
                continue;
            }

            if (chunk.type === "compression_done") {
                const comprEl = document.getElementById(`compression-${baseMsgId}`);
                if (comprEl) {
                    const phase = chunk.phase || "";
                    const label = phase === "phase2" ? "Deep compression done ▲" :
                                  phase === "async_started" ? "Summarizing in background ▲" :
                                  "Summary updated ▲";
                    comprEl.querySelector(".compression-text").textContent = label;
                    comprEl.classList.add("compression-done");
                    setTimeout(() => comprEl.remove(), 3000);
                }
                continue;
            }

            if (chunk.type === "thinking_done") {
                if (controlThinkingId) {
                    Thinking.finalizeThinking(controlThinkingId, chunk.thinking);
                }
                if (chunk.memory_used) {
                    UI.showMemoryIndicator();
                }
                continue;
            }

            // ═══════════════════════════════════════════
            // BOX 2: THINKING (DeepSeek thinking stream)
            // Label: "Thinking", Icon: brain
            // ═══════════════════════════════════════════

            if (chunk.type === "seq_thinking_stream") {
                if (!seqThinkingId) {
                    seqThinkingId = Thinking.createThinkingBox("seq-" + baseMsgId, "Thinking", "brain");
                }
                Thinking.updateThinkingStream(seqThinkingId, chunk.chunk);
                continue;
            }

            if (chunk.type === "seq_thinking_done") {
                if (seqThinkingId) {
                    Thinking.finalizeThinkingSimple(seqThinkingId);
                }
                continue;
            }

            // ═══════════════════════════════════════════
            // BOX 3: SEQUENTIAL THINKING (Structured Steps)
            // Label: "Sequential Thinking", Icon: zap
            // ═══════════════════════════════════════════

            if (chunk.type === "sequential_start") {
                if (!currentSeqId) {
                    currentSeqId = Sequential.createSequentialBox(baseMsgId);
                }
                log("info", `Sequential started: ${chunk.task_id || ''}`);
                continue;
            }

            // ✅ FIX: Backend sends "thought" not "content"!
            if (chunk.type === "sequential_step") {
                if (!currentSeqId) {
                    currentSeqId = Sequential.createSequentialBox(baseMsgId);
                }
                Sequential.addCompleteStep(
                    currentSeqId,
                    chunk.step_number || chunk.step_num || chunk.step || "?",
                    chunk.title || "",
                    chunk.thought || chunk.content || chunk.text || ""
                );
                continue;
            }

            if (chunk.type === "sequential_done") {
                if (currentSeqId) {
                    Sequential.finalizeSequentialBox(currentSeqId, chunk.summary || `${(chunk.steps || []).length} steps completed`);
                    currentSeqId = null;
                }
                continue;
            }

            if (chunk.type === "sequential_error") {
                if (currentSeqId) {
                    Sequential.finalizeSequentialBox(currentSeqId, `❌ Error: ${chunk.error || 'Unknown'}`);
                    currentSeqId = null;
                }
                continue;
            }

            // ═══════════════════════════════════════════
            // OTHER EVENTS
            // ═══════════════════════════════════════════

            // Control Layer (approval/rejection)
            if (chunk.type === "control") {
                if (!controlBlockId) controlBlockId = Thinking.createControlBox(botMsgId || baseMsgId);
                Thinking.finalizeControl(controlBlockId, chunk);
                continue;
            }

            // Container Start
            if (chunk.type === "container_start") {
                if (controlThinkingId) {
                    Thinking.showContainerStart(controlThinkingId, chunk.container, chunk.task);
                }
                UI.showContainerIndicator(true);
                continue;
            }

            // Container Done
            if (chunk.type === "container_done") {
                if (controlThinkingId) {
                    Thinking.showContainerDone(controlThinkingId, chunk.result);
                }
                UI.showContainerIndicator(false);
                continue;
            }

            // Plugin Events (MCP, Panel - NOT sequential)
            const pluginEvents = [
                "mcp_call", "mcp_result",
                "cim_store", "memory_update",
                "panel_create_tab", "panel_update", "panel_close_tab", "panel_control",
                "workspace_update"
            ];

            if (pluginEvents.includes(chunk.type)) {
                console.log("[Chat] Dispatching plugin event:", chunk.type);
                window.dispatchEvent(new CustomEvent("sse-event", { detail: chunk }));
                continue;
            }

            // Regular Content
            if (chunk.type === "content" && chunk.content) {
                if (!botMsgId) {
                    botMsgId = Render.renderMessage("assistant", "", true);
                }
                fullResponse += chunk.content;
                Render.updateMessage(botMsgId, fullResponse, !chunk.done);
                if (chunk.model) usedModel = chunk.model;
                continue;
            }

            // Memory Indicator
            if (chunk.type === "memory") {
                UI.showMemoryIndicator();
                continue;
            }

            // Done
            if (chunk.type === "done") {
                if (chunk.model) usedModel = chunk.model;
                if (chunk.code_model_used) UI.showCodeModelIndicator();
                break;
            }
        }

        // Finalize
        if (botMsgId) {
            Render.updateMessage(botMsgId, fullResponse, false);
        }
        if (fullResponse) {
            State.addMessage({ role: "assistant", content: fullResponse });
            State.saveChatToStorage();

            // Auto-append to daily protocol (fire and forget)
            fetch(`${getApiBase()}/api/protocol/append`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    user_message: text,
                    ai_response: fullResponse,
                    timestamp: new Date().toISOString(),
                    conversation_id: conversationId,
                })
            }).catch(err => console.warn("[Chat] Protocol append failed:", err));
        }

        updateHistoryDisplay(State.getMessageCount(), messagesToSend.length);
        log("info", `Response complete, total messages: ${State.getMessageCount()}, model: ${usedModel}`);

    } catch (error) {
        log("error", `Chat error: ${error.message}`);
        if (!botMsgId) {
            botMsgId = Render.renderMessage("assistant", "", false);
        }
        Render.updateMessage(botMsgId, `❌ Fehler: ${error.message}`, false);
    } finally {
        State.setProcessing(false);
        UI.updateUIState(false);
    }
}
