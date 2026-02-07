import { log } from "./debug.js";

// ═══════════════════════════════════════════════════════════
// UI HELPERS
// ═══════════════════════════════════════════════════════════

export function updateUIState(loading) {
    const sendBtn = document.getElementById("send-btn");
    const input = document.getElementById("user-input");

    if (sendBtn) sendBtn.disabled = loading;
    if (input) {
        input.disabled = loading;
        if (!loading) input.focus();
    }
}

export function scrollToBottom() {
    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
}

export function showMemoryIndicator() {
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

export function showContainerIndicator(active) {
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
            if (window.lucide) window.lucide.createIcons();
        }
    } else {
        containerIndicator?.remove();
    }
}

export function showCodeModelIndicator() {
    const memoryStatus = document.getElementById("memory-status");
    if (memoryStatus) {
        memoryStatus.innerHTML = `
            <i data-lucide="code" class="w-3 h-3"></i>
            <span>Code-Model used</span>
        `;
        memoryStatus.classList.remove("opacity-0");
        memoryStatus.classList.add("opacity-100");
        if (window.lucide) window.lucide.createIcons();

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
