import { log } from "./debug.js";

// Storage Keys
const CHAT_STORAGE_KEY = 'jarvis-chat-messages';
const CONV_STORAGE_KEY = 'jarvis-conversation-id';

// State
let state = {
    currentModel: null,
    messages: [],
    conversationId: `webui-${Date.now()}`,
    isProcessing: false,
    historyLimit: 10
};

function syncGlobalConversationId() {
    if (typeof window !== "undefined") {
        window.currentConversationId = state.conversationId;
    }
}

// ═══════════════════════════════════════════════════════════
// GETTERS & SETTERS
// ═══════════════════════════════════════════════════════════

export function setModel(model) {
    state.currentModel = model;
    log("info", `Model set to: ${model}`);
}

export function getModel() {
    return state.currentModel;
}

export function setProcessing(status) {
    state.isProcessing = status;
}

export function isLoading() {
    return state.isProcessing;
}

export function setHistoryLimit(limit) {
    state.historyLimit = limit;
    log("debug", `History limit set to: ${limit}`);
}

export function getModels() {
    // Falls benötigt, aber messages Zugriff gibt es unten
}

export function getMessages() {
    return state.messages;
}

export function addMessage(message) {
    state.messages.push(message);
}

export function setMessages(newMessages) {
    state.messages = newMessages;
}

export function getConversationId() {
    return state.conversationId;
}

export function setConversationId(id) {
    state.conversationId = id;
    syncGlobalConversationId();
}

export function getMessageCount() {
    return state.messages.length;
}

// ═══════════════════════════════════════════════════════════
// STORAGE
// ═══════════════════════════════════════════════════════════

export function saveChatToStorage() {
    try {
        localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(state.messages));
        localStorage.setItem(CONV_STORAGE_KEY, state.conversationId);
        log("debug", `Chat saved: ${state.messages.length} messages`);
    } catch (e) {
        log("error", `Failed to save chat: ${e.message}`);
    }
}

export function loadChatFromStorage() {
    try {
        const savedMessages = localStorage.getItem(CHAT_STORAGE_KEY);
        const savedConvId = localStorage.getItem(CONV_STORAGE_KEY);

        if (savedMessages) {
            state.messages = JSON.parse(savedMessages);
            log("info", `Chat restored: ${state.messages.length} messages`);
        }
        if (savedConvId) {
            state.conversationId = savedConvId;
        }
        syncGlobalConversationId();
        return true;
    } catch (e) {
        log("error", `Failed to load chat: ${e.message}`);
        state.messages = [];
        return false;
    }
}

export function clearStorage() {
    state.messages = [];
    state.conversationId = `webui-${Date.now()}`;
    localStorage.removeItem(CHAT_STORAGE_KEY);
    localStorage.removeItem(CONV_STORAGE_KEY);
    syncGlobalConversationId();
    log("info", "Storage cleared");
}

export function getMessagesForBackend() {
    if (state.historyLimit === 0) {
        const last = state.messages[state.messages.length - 1];
        return last ? [last] : [];
    }

    const maxMessages = state.historyLimit * 2;
    const toSend = state.messages.slice(-maxMessages);

    log("debug", `Preparing messages for backend: ${toSend.length} of ${state.messages.length} (limit: ${state.historyLimit})`);

    return toSend;
}

syncGlobalConversationId();
