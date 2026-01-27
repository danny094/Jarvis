// code-block.js - Interaktive Code-Blöcke im Chat

import { log } from "./debug.js";

// Globaler Zähler für eindeutige IDs
let codeBlockCounter = 0;

// Sprach-Mapping
const LANGUAGE_INFO = {
    python: { icon: "🐍", name: "Python", color: "text-yellow-400" },
    javascript: { icon: "📜", name: "JavaScript", color: "text-yellow-300" },
    js: { icon: "📜", name: "JavaScript", color: "text-yellow-300" },
    bash: { icon: "💻", name: "Bash", color: "text-green-400" },
    sh: { icon: "💻", name: "Shell", color: "text-green-400" },
    typescript: { icon: "📘", name: "TypeScript", color: "text-blue-400" },
    ts: { icon: "📘", name: "TypeScript", color: "text-blue-400" },
    default: { icon: "📄", name: "Code", color: "text-gray-400" }
};

/**
 * Erstellt einen interaktiven Code-Block mit Run-Button
 */
export function createInteractiveCodeBlock(code, language = "python", executionResult = null) {
    const blockId = `code-block-${++codeBlockCounter}`;
    const langInfo = LANGUAGE_INFO[language] || LANGUAGE_INFO.default;

    const hasResult = executionResult !== null;
    const exitCode = executionResult?.exit_code ?? null;
    const stdout = executionResult?.stdout || "";
    const stderr = executionResult?.stderr || "";
    const runtime = executionResult?.runtime || null;
    const error = executionResult?.error || null;

    const isSuccess = exitCode === 0;
    const statusColor = error ? "bg-red-500" : (isSuccess ? "bg-green-500" : "bg-yellow-500");
    const statusText = error ? "Error" : (isSuccess ? "Success" : `Exit: ${exitCode}`);

    const html = `
        <div id="${blockId}" class="code-block-interactive bg-dark-bg border border-dark-border rounded-xl overflow-hidden my-3" data-language="${language}" data-code="${encodeURIComponent(code)}">
            <!-- Header -->
            <div class="flex items-center justify-between px-3 py-2 bg-dark-hover border-b border-dark-border">
                <div class="flex items-center gap-2 text-sm">
                    <span>${langInfo.icon}</span>
                    <span class="${langInfo.color}">${langInfo.name}</span>
                </div>
                <div class="flex items-center gap-2">
                    <button class="code-copy-btn p-1.5 text-gray-400 hover:text-white hover:bg-dark-border rounded transition-colors" title="Copy">
                        <i data-lucide="copy" class="w-4 h-4"></i>
                    </button>
                </div>
            </div>
            
            <!-- Code Editor -->
            <div class="code-editor-container relative">
                <pre class="p-4 text-sm overflow-x-auto"><code class="language-${language} text-gray-200" contenteditable="true" spellcheck="false">${escapeHtml(code)}</code></pre>
                <div class="absolute top-2 right-2 text-xs text-gray-500 pointer-events-none">Editierbar</div>
            </div>
            
            <!-- Output Section (Removed Legacy Logic) -->
        </div>
    `;

    return { html, blockId };
}

/**
 * Initialisiert Event-Listener für einen Code-Block
 */
export function initCodeBlock(blockId) {
    const block = document.getElementById(blockId);
    if (!block) return;

    const copyBtn = block.querySelector(".code-copy-btn");
    const codeEl = block.querySelector("code");

    // Copy Button
    copyBtn?.addEventListener("click", () => {
        const code = codeEl.textContent;
        navigator.clipboard.writeText(code);

        // Visual feedback
        const icon = copyBtn.querySelector("i");
        icon.setAttribute("data-lucide", "check");
        lucide.createIcons();

        setTimeout(() => {
            icon.setAttribute("data-lucide", "copy");
            lucide.createIcons();
        }, 2000);

        log("info", "Code copied to clipboard");
    });

    // Lucide Icons für diesen Block
    lucide.createIcons();
}

/**
 * Führt Code in einem Block aus und aktualisiert die Anzeige
 */


/**
 * Parst eine Nachricht und ersetzt Code-Blöcke durch interaktive Versionen
 */
export function parseMessageForCodeBlocks(content) {
    const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
    let match;
    let result = content;
    const blockIds = [];

    while ((match = codeBlockRegex.exec(content)) !== null) {
        const language = match[1] || "text";
        const code = match[2].trim();
        const fullMatch = match[0];

        const { html, blockId } = createInteractiveCodeBlock(code, language);
        result = result.replace(fullMatch, html);
        blockIds.push(blockId);
    }

    return { content: result, blockIds };
}

/**
 * Escape HTML für sichere Anzeige
 */
function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
