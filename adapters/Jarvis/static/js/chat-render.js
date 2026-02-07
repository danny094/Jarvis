import { log } from "./debug.js";
import { createInteractiveCodeBlock, initCodeBlock } from "./code-block.js";
import { getModel } from "./chat-state.js";

// ═══════════════════════════════════════════════════════════
// MESSAGE RENDERING
// ═══════════════════════════════════════════════════════════

function escapeHtml(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatContent(text) {
    if (!text) return "";

    // Basic Markdown Formatting
    let html = escapeHtml(text);

    // Bold (**text**)
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Italic (*text*)
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Inline Code (`text`)
    html = html.replace(/`(.*?)`/g, '<code class="bg-dark-bg px-1 rounded text-accent-primary font-mono text-sm">$1</code>');

    // Headers (### text)
    html = html.replace(/^### (.*$)/gm, '<h3 class="text-lg font-bold mt-2 mb-1 text-gray-200">$1</h3>');
    html = html.replace(/^## (.*$)/gm, '<h2 class="text-xl font-bold mt-3 mb-2 text-gray-100">$1</h2>');

    // Lists (- item)
    html = html.replace(/^\- (.*$)/gm, '<li class="ml-4 list-disc text-gray-300">$1</li>');

    // Paragraphs (Double newline)
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/\n/g, '<br>');

    return html;
}

function splitMessageToParts(content) {
    const codeBlockRegex = /```(\w*)\n?([\s\S]*?)```/g;
    const parts = [];
    let lastIndex = 0;
    let match;

    while ((match = codeBlockRegex.exec(content)) !== null) {
        // Text before code block
        if (match.index > lastIndex) {
            parts.push({
                type: 'text',
                content: content.slice(lastIndex, match.index)
            });
        }

        // Code block
        parts.push({
            type: 'code',
            language: match[1] || 'text',
            code: match[2].trim()
        });

        lastIndex = codeBlockRegex.lastIndex;
    }

    // Remaining text
    if (lastIndex < content.length) {
        parts.push({
            type: 'text',
            content: content.slice(lastIndex)
        });
    }

    return parts;
}

function formatContentWithCodeBlocks(text) {
    if (!text) return "";

    const parts = splitMessageToParts(text);
    let html = "";

    parts.forEach(part => {
        if (part.type === 'text') {
            html += formatContent(part.content);
        } else if (part.type === 'code') {
            const { html: codeHtml } = createInteractiveCodeBlock(part.code, part.language);
            html += codeHtml;
        }
    });

    return html;
}

export function renderMessage(role, content, isStreaming = false, executionResults = {}) {
    const messagesList = document.getElementById("messages-list");
    const welcome = document.getElementById("welcome-message");
    if (welcome) welcome.classList.add("hidden");

    const messageId = `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const isUser = role === "user";

    const div = document.createElement("div");
    div.id = messageId;
    div.className = `flex ${isUser ? 'justify-end' : 'justify-start'} mb-6 fade-in group`;

    const avatar = isUser ?
        `<div class="w-8 h-8 rounded-full bg-accent-primary flex items-center justify-center text-white shrink-0 ml-3 mt-1">
            <i data-lucide="user" class="w-5 h-5"></i>
         </div>` :
        `<div class="w-8 h-8 rounded-full bg-accent-secondary flex items-center justify-center text-white shrink-0 mr-3 mt-1">
            <div class="relative">
                <i data-lucide="bot" class="w-5 h-5"></i>
                <div class="absolute -top-1 -right-1 w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
            </div>
         </div>`;

    const cursor = isStreaming ? '<span class="inline-block w-2 H-4 bg-accent-secondary ml-1 animate-pulse">▋</span>' : '';

    const modelBadge = (!isUser && getModel()) ?
        `<div class="text-[10px] text-gray-500 mb-1 ml-1 font-mono opacity-50 group-hover:opacity-100 transition-opacity">
            ${getModel()}
         </div>` : '';

    const contentHtml = isStreaming ?
        formatContent(content) + cursor :
        formatContentWithCodeBlocks(content);

    div.innerHTML = isUser ? `
        <div class="relative max-w-[80%]">
            <div class="bg-accent-primary text-white px-5 py-3 rounded-2xl rounded-tr-sm shadow-lg">
                <div class="whitespace-pre-wrap leading-relaxed">${escapeHtml(content)}</div>
            </div>
            <div class="text-[10px] text-gray-500 mt-1 mr-1 text-right opacity-0 group-hover:opacity-100 transition-opacity">
                ${new Date().toLocaleTimeString()}
            </div>
        </div>
        ${avatar}
    ` : `
        ${avatar}
        <div class="relative max-w-[85%] min-w-[300px]">
             ${modelBadge}
            <div class="bg-dark-card border border-dark-border text-gray-200 px-6 py-4 rounded-2xl rounded-tl-sm shadow-lg">
                <div id="content-${messageId}" class="prose prose-invert prose-sm max-w-none">
                    ${contentHtml}
                </div>
                ${isStreaming ? '' : renderExecutionResults(executionResults)}
            </div>
            <div class="flex items-center gap-2 mt-2 ml-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button class="text-gray-500 hover:text-white transition-colors p-1" title="Copy" onclick="navigator.clipboard.writeText(document.getElementById('content-${messageId}').innerText)">
                    <i data-lucide="copy" class="w-3 h-3"></i>
                </button>
                <span class="text-[10px] text-gray-500">${new Date().toLocaleTimeString()}</span>
            </div>
        </div>
    `;

    messagesList.appendChild(div);

    // Init icons and code blocks
    if (window.lucide) window.lucide.createIcons({ icons: window.lucide.icons, nameAttr: "data-lucide" });
    if (!isStreaming) {
        initCodeBlock(div); // Helper to init event listeners etc
        if (window.Prism) window.Prism.highlightAllUnder(div);
    }

    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;

    return messageId;
}

function renderExecutionResults(results) {
    if (!results || Object.keys(results).length === 0) return "";
    return "";
}

export function updateMessage(messageId, content, isStreaming = false) {
    const contentEl = document.getElementById(`content-${messageId}`);
    if (!contentEl) return;

    const cursor = isStreaming ? '<span class="inline-block w-2 H-4 bg-accent-secondary ml-1 animate-pulse">▋</span>' : '';

    if (isStreaming) {
        contentEl.innerHTML = formatContent(content) + cursor;
    } else {
        contentEl.innerHTML = formatContentWithCodeBlocks(content);

        // Highlight logic
        const msgDiv = document.getElementById(messageId);
        if (msgDiv) {
            // Re-init blocks (e.g. copy buttons)
            const blocks = msgDiv.querySelectorAll('.code-block-interactive');
            blocks.forEach(block => initCodeBlock(block.id));

            if (window.Prism) window.Prism.highlightAllUnder(msgDiv);
        }
    }

    const chatContainer = document.getElementById("chat-container");
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
}
