// chat.js - Chat Logic mit LIVE Thinking, Container Status & Interactive Code Blocks

import { streamChat } from "./api.js";
import { log } from "./debug.js";
import { parseMessageForCodeBlocks, initCodeBlock } from "./code-block.js";
import { terminal } from "./terminal.js";

let currentModel = null;
let messages = [];
let conversationId = `webui-${Date.now()}`;
let isProcessing = false;
let historyLimit = 10;

// ═══════════════════════════════════════════════════════════
// SETTERS & GETTERS
// ═══════════════════════════════════════════════════════════
export function setModel(model) {
    currentModel = model;
    log("debug", `Model set to: ${model}`);
}

export function getModel() {
    return currentModel;
}

export function isLoading() {
    return isProcessing;
}

export function setHistoryLimit(limit) {
    historyLimit = limit;
    log("debug", `History limit set to: ${limit}`);
}

export function getMessageCount() {
    return messages.length;
}

// ═══════════════════════════════════════════════════════════
// UPDATE HISTORY DISPLAY
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
// GET MESSAGES FOR BACKEND (with limit)
// ═══════════════════════════════════════════════════════════
function getMessagesForBackend() {
    if (historyLimit === 0) {
        const last = messages[messages.length - 1];
        return last ? [last] : [];
    }
    
    const maxMessages = historyLimit * 2;
    const toSend = messages.slice(-maxMessages);
    
    log("debug", `Preparing messages for backend: ${toSend.length} of ${messages.length} (limit: ${historyLimit})`);
    
    return toSend;
}

// ═══════════════════════════════════════════════════════════
// LIVE THINKING DISPLAY MIT CONTAINER STATUS
// ═══════════════════════════════════════════════════════════
function createThinkingBox(messageId) {
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
                <i data-lucide="brain" class="w-4 h-4 text-accent-secondary animate-pulse"></i>
                <span>Thinking...</span>
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
    lucide.createIcons({ icons: lucide.icons, nameAttr: "data-lucide" });
    
    const chatContainer = document.getElementById("chat-container");
    chatContainer.scrollTop = chatContainer.scrollHeight;
    
    return thinkingId;
}

function updateThinkingStream(thinkingId, chunk) {
    const streamEl = document.getElementById(`${thinkingId}-stream`);
    if (streamEl) {
        streamEl.textContent += chunk;
        streamEl.scrollTop = streamEl.scrollHeight;
    }
    
    const chatContainer = document.getElementById("chat-container");
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function finalizeThinking(thinkingId, thinking) {
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
        let statusParts = [`<span class="${riskColor}">Risk: ${risk}</span>`];
        
        // Code-Model Anzeige
        if (thinking.use_code_model) {
            statusParts.push('<span class="text-accent-primary">🤖 Code-Model</span>');
        }
        
        // Container Anzeige
        if (thinking.needs_container) {
            statusParts.push(`<span class="text-accent-secondary">📦 ${thinking.container_name}</span>`);
        }
        
        statusEl.innerHTML = statusParts.join(' | ');
    }
    
    summary.querySelector("span").textContent = "Thinking";
    
    const metaEl = document.getElementById(`${thinkingId}-meta`);
    if (metaEl && thinking.intent) {
        metaEl.classList.remove("hidden");
        metaEl.innerHTML = `
            <div class="flex items-start gap-2">
                <span class="text-gray-500 min-w-[100px]">Intent:</span>
                <span class="text-gray-300">${thinking.intent || '-'}</span>
            </div>
            <div class="flex items-start gap-2">
                <span class="text-gray-500 min-w-[100px]">Memory:</span>
                <span class="text-gray-300">
                    ${thinking.needs_memory ? '✅ Benötigt' : '❌ Nicht benötigt'}
                    ${thinking.memory_keys?.length ? `(${thinking.memory_keys.join(', ')})` : ''}
                </span>
            </div>
            <div class="flex items-start gap-2">
                <span class="text-gray-500 min-w-[100px]">Chat-History:</span>
                <span class="text-gray-300">
                    ${thinking.needs_chat_history ? '✅ Wird genutzt' : '❌ Nicht benötigt'}
                </span>
            </div>
            ${thinking.needs_container ? `
            <div class="flex items-start gap-2">
                <span class="text-gray-500 min-w-[100px]">Container:</span>
                <span class="text-gray-300">📦 ${thinking.container_name} (${thinking.container_task || 'execute'})</span>
            </div>
            ` : ''}
            ${thinking.use_code_model ? `
            <div class="flex items-start gap-2">
                <span class="text-gray-500 min-w-[100px]">Code-Model:</span>
                <span class="text-accent-primary">✅ Aktiviert ${thinking.code_language ? `(${thinking.code_language})` : ''}</span>
            </div>
            ` : ''}
            <div class="flex items-start gap-2">
                <span class="text-gray-500 min-w-[100px]">Reasoning:</span>
                <span class="text-gray-300">${thinking.reasoning || '-'}</span>
            </div>
        `;
    }
    
    const details = box.querySelector("details");
    if (details) {
        details.open = false;
    }
}

// ═══════════════════════════════════════════════════════════
// CONTAINER STATUS IN THINKING BOX
// ═══════════════════════════════════════════════════════════
function showContainerStart(thinkingId, container, task) {
    const containerEl = document.getElementById(`${thinkingId}-container`);
    if (!containerEl) return;
    
    containerEl.classList.remove("hidden");
    containerEl.innerHTML = `
        <div class="flex items-center gap-3 text-sm">
            <div class="flex items-center gap-2">
                <i data-lucide="container" class="w-4 h-4 text-accent-secondary animate-pulse"></i>
                <span class="text-accent-secondary font-medium">${container}</span>
            </div>
            <span class="text-gray-500">|</span>
            <span class="text-gray-400">${task}</span>
            <span class="text-gray-500">|</span>
            <span class="text-yellow-400 flex items-center gap-1">
                <i data-lucide="loader" class="w-3 h-3 animate-spin"></i>
                Running...
            </span>
        </div>
    `;
    lucide.createIcons();
    log("info", `Container started: ${container} (${task})`);
}

function showContainerDone(thinkingId, result) {
    const containerEl = document.getElementById(`${thinkingId}-container`);
    if (!containerEl) return;
    
    const exitCode = result?.exit_code ?? -1;
    const isSuccess = exitCode === 0;
    const hasError = result?.error;
    
    const statusColor = hasError ? "text-red-400" : (isSuccess ? "text-green-400" : "text-yellow-400");
    const statusIcon = hasError ? "x-circle" : (isSuccess ? "check-circle" : "alert-circle");
    const statusText = hasError ? result.error : (isSuccess ? "Success" : `Exit: ${exitCode}`);
    
    containerEl.innerHTML = `
        <div class="space-y-2">
            <div class="flex items-center gap-3 text-sm">
                <div class="flex items-center gap-2">
                    <i data-lucide="container" class="w-4 h-4 text-accent-secondary"></i>
                    <span class="text-accent-secondary font-medium">code-sandbox</span>
                </div>
                <span class="text-gray-500">|</span>
                <span class="${statusColor} flex items-center gap-1">
                    <i data-lucide="${statusIcon}" class="w-3 h-3"></i>
                    ${statusText}
                </span>
            </div>
            ${result?.stdout ? `
            <div class="bg-dark-bg rounded p-2 font-mono text-xs text-green-400 max-h-24 overflow-y-auto whitespace-pre-wrap">
                ${escapeHtml(result.stdout)}
            </div>
            ` : ''}
            ${result?.stderr ? `
            <div class="bg-dark-bg rounded p-2 font-mono text-xs text-red-400 max-h-24 overflow-y-auto whitespace-pre-wrap">
                ${escapeHtml(result.stderr)}
            </div>
            ` : ''}
        </div>
    `;
    lucide.createIcons();
    log("info", `Container done: exit=${exitCode}`, result);
}

// ═══════════════════════════════════════════════════════════
// MESSAGE RENDERING MIT INTERACTIVE CODE BLOCKS
// ═══════════════════════════════════════════════════════════
export function renderMessage(role, content, isStreaming = false, executionResults = {}) {
    const container = document.getElementById("messages-list");
    const welcome = document.getElementById("welcome-message");
    if (welcome) welcome.classList.add("hidden");
    
    const messageId = `msg-${Date.now()}`;
    const isUser = role === "user";
    
    const div = document.createElement("div");
    div.id = messageId;
    div.className = `flex gap-3 fade-in ${isUser ? 'justify-end' : 'justify-start'}`;
    
    const avatar = isUser 
        ? `<div class="w-8 h-8 bg-accent-primary rounded-lg flex items-center justify-center flex-shrink-0">
               <i data-lucide="user" class="w-4 h-4"></i>
           </div>`
        : `<div class="w-8 h-8 bg-gradient-to-br from-accent-primary to-accent-secondary rounded-lg flex items-center justify-center flex-shrink-0">
               <i data-lucide="bot" class="w-4 h-4"></i>
           </div>`;
    
    // Parse content für interaktive Code-Blöcke (nur bei Assistant)
    let formattedContent = formatContent(content);
    let codeBlockIds = [];
    
    if (!isUser && !isStreaming) {
        const parsed = parseMessageForCodeBlocks(content, executionResults);
        formattedContent = formatContentWithCodeBlocks(parsed.content);
        codeBlockIds = parsed.blockIds;
    }
    
    const bubble = `
        <div class="max-w-[80%] ${isUser ? 'bg-accent-primary' : 'bg-dark-card border border-dark-border'} 
                    px-4 py-3 rounded-2xl ${isUser ? 'rounded-br-md' : 'rounded-bl-md'}">
            <div class="message-content text-sm leading-relaxed">
                ${formattedContent}${isStreaming ? '<span class="typing-cursor">▋</span>' : ''}
            </div>
        </div>
    `;
    
    div.innerHTML = isUser 
        ? `${bubble}${avatar}`
        : `${avatar}${bubble}`;
    
    container.appendChild(div);
    lucide.createIcons({ icons: lucide.icons, nameAttr: "data-lucide" });
    
    // Initialisiere Code-Blöcke
    codeBlockIds.forEach(id => initCodeBlock(id));
    
    const chatContainer = document.getElementById("chat-container");
    chatContainer.scrollTop = chatContainer.scrollHeight;
    
    return messageId;
}

export function updateMessage(messageId, content, isStreaming = false) {
    const msg = document.getElementById(messageId);
    if (!msg) return;
    
    const contentDiv = msg.querySelector(".message-content");
    if (contentDiv) {
        if (isStreaming) {
            // Während des Streamings: einfaches Format
            contentDiv.innerHTML = formatContent(content) + '<span class="typing-cursor">▋</span>';
        } else {
            // Nach dem Streaming: interaktive Code-Blöcke
            const parsed = parseMessageForCodeBlocks(content);
            contentDiv.innerHTML = formatContentWithCodeBlocks(parsed.content);
            
            // Initialisiere Code-Blöcke
            parsed.blockIds.forEach(id => initCodeBlock(id));
            lucide.createIcons();
        }
    }
    
    const chatContainer = document.getElementById("chat-container");
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function formatContent(text) {
    if (!text) return "";
    
    return text
        .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
}

function formatContentWithCodeBlocks(text) {
    if (!text) return "";
    
    // Code-Blöcke werden bereits von parseMessageForCodeBlocks ersetzt
    // Hier nur noch Inline-Formatierung
    return text
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
}

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// ═══════════════════════════════════════════════════════════
// SEND MESSAGE
// ═══════════════════════════════════════════════════════════
export async function handleUserMessage(text) {
    if (isProcessing || !text.trim()) return;
    if (!currentModel) {
        alert("Bitte wähle zuerst ein Model aus!");
        return;
    }
    
    isProcessing = true;
    updateUIState(true);
    
    // User message
    renderMessage("user", text);
    messages.push({ role: "user", content: text });
    
    // Update history display
    const messagesToSend = getMessagesForBackend();
    updateHistoryDisplay(messages.length, messagesToSend.length);
    
    log("info", `Sending message with ${messagesToSend.length} messages in history`);
    
    // State
    const baseMsgId = Date.now();
    let thinkingId = null;
    let thinkingCreated = false;
    let botMsgId = null;
    let fullResponse = "";
    let containerResult = null;
    let usedModel = currentModel;
    
    try {
        for await (const chunk of streamChat(currentModel, messagesToSend, conversationId)) {
            
            // Live Thinking Stream
            if (chunk.type === "thinking_stream") {
                if (!thinkingCreated) {
                    thinkingId = createThinkingBox(baseMsgId);
                    thinkingCreated = true;
                }
                updateThinkingStream(thinkingId, chunk.chunk);
                continue;
            }
            
            // Thinking Done
            if (chunk.type === "thinking_done") {
                if (thinkingId) {
                    finalizeThinking(thinkingId, chunk.thinking);
                }
                if (chunk.memory_used) {
                    showMemoryIndicator();
                }
                continue;
            }
            
            // Container Start
            if (chunk.type === "container_start") {
                console.log("[Chat] container_start received:", chunk);
                if (thinkingId) {
                    showContainerStart(thinkingId, chunk.container, chunk.task);
                }
                showContainerIndicator(true);
                
                // Terminal aktualisieren (mit Session-Info wenn vorhanden)
                terminal.onContainerStart(chunk.container, chunk.task, chunk.session);
                continue;
            }
            
            // Container Done
            if (chunk.type === "container_done") {
                console.log("[Chat] container_done received:", chunk);
                containerResult = chunk.result;
                if (thinkingId) {
                    showContainerDone(thinkingId, chunk.result);
                }
                showContainerIndicator(false);
                
                // Terminal aktualisieren
                terminal.onContainerDone(chunk.result);
                continue;
            }
            
            // Content Stream
            if (chunk.type === "content") {
                if (!botMsgId) {
                    botMsgId = renderMessage("assistant", "", true);
                }
                fullResponse += chunk.content;
                updateMessage(botMsgId, fullResponse, !chunk.done);
                
                // Track used model
                if (chunk.model) usedModel = chunk.model;
            }
            
            // Memory
            if (chunk.type === "memory") {
                showMemoryIndicator();
            }
            
            // Done
            if (chunk.type === "done") {
                // Update with model info
                if (chunk.model) usedModel = chunk.model;
                if (chunk.code_model_used) {
                    showCodeModelIndicator();
                }
                break;
            }
        }
        
        // Final update with interactive code blocks
        if (botMsgId) {
            updateMessage(botMsgId, fullResponse, false);
        }
        messages.push({ role: "assistant", content: fullResponse });
        
        // Update history display
        updateHistoryDisplay(messages.length, messagesToSend.length);
        
        log("info", `Response complete, total messages: ${messages.length}, model: ${usedModel}`);
        
    } catch (error) {
        log("error", `Chat error: ${error.message}`);
        if (!botMsgId) {
            botMsgId = renderMessage("assistant", "", false);
        }
        updateMessage(botMsgId, `❌ Fehler: ${error.message}`, false);
    } finally {
        isProcessing = false;
        updateUIState(false);
    }
}

// ═══════════════════════════════════════════════════════════
// UI HELPERS
// ═══════════════════════════════════════════════════════════
function updateUIState(loading) {
    const sendBtn = document.getElementById("send-btn");
    const input = document.getElementById("user-input");
    
    sendBtn.disabled = loading;
    input.disabled = loading;
    
    if (!loading) input.focus();
}

function showMemoryIndicator() {
    const memoryStatus = document.getElementById("memory-status");
    if (memoryStatus) {
        memoryStatus.classList.remove("opacity-0");
        memoryStatus.classList.add("opacity-100");
        setTimeout(() => {
            memoryStatus.classList.remove("opacity-100");
            memoryStatus.classList.add("opacity-0");
        }, 3000);
    }
}

function showContainerIndicator(active) {
    // Optional: Container-Status in Status-Bar anzeigen
    const statusBar = document.getElementById("status-bar");
    let containerIndicator = document.getElementById("container-indicator");
    
    if (active) {
        if (!containerIndicator) {
            containerIndicator = document.createElement("div");
            containerIndicator.id = "container-indicator";
            containerIndicator.className = "flex items-center gap-1 text-accent-secondary transition-opacity";
            containerIndicator.innerHTML = `
                <i data-lucide="container" class="w-3 h-3"></i>
                <span>Container running...</span>
            `;
            statusBar?.querySelector(".flex")?.appendChild(containerIndicator);
            lucide.createIcons();
        }
    } else {
        containerIndicator?.remove();
    }
}

function showCodeModelIndicator() {
    const memoryStatus = document.getElementById("memory-status");
    if (memoryStatus) {
        memoryStatus.innerHTML = `
            <i data-lucide="code" class="w-3 h-3"></i>
            <span>Code-Model used</span>
        `;
        memoryStatus.classList.remove("opacity-0");
        memoryStatus.classList.add("opacity-100");
        lucide.createIcons();
        setTimeout(() => {
            memoryStatus.classList.remove("opacity-100");
            memoryStatus.classList.add("opacity-0");
            memoryStatus.innerHTML = `
                <i data-lucide="database" class="w-3 h-3"></i>
                <span>Memory used</span>
            `;
        }, 3000);
    }
}

export function clearChat() {
    messages = [];
    conversationId = `webui-${Date.now()}`;
    document.getElementById("messages-list").innerHTML = "";
    const welcome = document.getElementById("welcome-message");
    if (welcome) welcome.classList.remove("hidden");
    
    updateHistoryDisplay(0, 0);
    log("info", "Chat cleared");
}
