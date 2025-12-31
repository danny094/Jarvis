// code-block.js - Interaktive Code-Blöcke im Chat

import { executeCode } from "./api.js";
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
                    <button class="code-run-btn px-3 py-1 bg-accent-primary hover:bg-blue-600 text-white text-xs rounded-lg flex items-center gap-1.5 transition-colors" title="Run">
                        <i data-lucide="play" class="w-3 h-3"></i>
                        <span>Run</span>
                    </button>
                </div>
            </div>
            
            <!-- Code Editor -->
            <div class="code-editor-container relative">
                <pre class="p-4 text-sm overflow-x-auto"><code class="language-${language} text-gray-200" contenteditable="true" spellcheck="false">${escapeHtml(code)}</code></pre>
                <div class="absolute top-2 right-2 text-xs text-gray-500 pointer-events-none">Editierbar</div>
            </div>
            
            <!-- Output Section (hidden if no result) -->
            <div class="code-output-section ${hasResult ? '' : 'hidden'} border-t border-dark-border">
                <!-- Output Header -->
                <div class="flex items-center justify-between px-3 py-2 bg-dark-card">
                    <span class="text-xs text-gray-400 flex items-center gap-2">
                        <i data-lucide="terminal" class="w-3 h-3"></i>
                        Output
                    </span>
                    <div class="flex items-center gap-2 text-xs">
                        ${runtime ? `<span class="text-gray-500">⏱️ ${runtime}</span>` : ''}
                        <span class="code-status px-2 py-0.5 rounded ${statusColor} text-white">${statusText}</span>
                    </div>
                </div>
                
                <!-- Stdout -->
                <div class="code-stdout ${stdout ? '' : 'hidden'} px-4 py-3 bg-dark-bg font-mono text-sm text-green-400 whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto">${escapeHtml(stdout)}</div>
                
                <!-- Stderr -->
                <div class="code-stderr ${stderr ? '' : 'hidden'} px-4 py-3 bg-dark-bg border-t border-dark-border font-mono text-sm text-red-400 whitespace-pre-wrap overflow-x-auto max-h-32 overflow-y-auto">${escapeHtml(stderr)}</div>
                
                <!-- Error -->
                <div class="code-error ${error ? '' : 'hidden'} px-4 py-3 bg-red-900/20 text-red-400 text-sm">${escapeHtml(error || '')}</div>
            </div>
            
            <!-- Loading Indicator (hidden by default) -->
            <div class="code-loading hidden border-t border-dark-border px-4 py-3 flex items-center gap-2 text-sm text-gray-400">
                <i data-lucide="loader" class="w-4 h-4 animate-spin"></i>
                <span>Running in sandbox...</span>
            </div>
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
    
    const runBtn = block.querySelector(".code-run-btn");
    const copyBtn = block.querySelector(".code-copy-btn");
    const codeEl = block.querySelector("code");
    
    // Run Button
    runBtn?.addEventListener("click", async () => {
        const code = codeEl.textContent;
        const language = block.dataset.language;
        
        await runCodeBlock(blockId, code, language);
    });
    
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
async function runCodeBlock(blockId, code, language) {
    const block = document.getElementById(blockId);
    if (!block) return;
    
    const runBtn = block.querySelector(".code-run-btn");
    const outputSection = block.querySelector(".code-output-section");
    const loadingEl = block.querySelector(".code-loading");
    const stdoutEl = block.querySelector(".code-stdout");
    const stderrEl = block.querySelector(".code-stderr");
    const errorEl = block.querySelector(".code-error");
    const statusEl = block.querySelector(".code-status");
    
    // Loading state
    runBtn.disabled = true;
    runBtn.innerHTML = '<i data-lucide="loader" class="w-3 h-3 animate-spin"></i><span>Running...</span>';
    loadingEl.classList.remove("hidden");
    outputSection.classList.add("hidden");
    
    lucide.createIcons();
    log("info", `Running code block ${blockId}`, { language, codeLength: code.length });
    
    try {
        const result = await executeCode(code, language, "code-sandbox");
        
        // Update output
        outputSection.classList.remove("hidden");
        loadingEl.classList.add("hidden");
        
        if (result.error) {
            // API Error
            errorEl.textContent = result.error;
            errorEl.classList.remove("hidden");
            stdoutEl.classList.add("hidden");
            stderrEl.classList.add("hidden");
            statusEl.textContent = "Error";
            statusEl.className = "code-status px-2 py-0.5 rounded bg-red-500 text-white";
        } else {
            // Execution result
            errorEl.classList.add("hidden");
            
            const stdout = result.stdout || "";
            const stderr = result.stderr || "";
            const exitCode = result.exit_code ?? -1;
            
            // Stdout
            if (stdout) {
                stdoutEl.textContent = stdout;
                stdoutEl.classList.remove("hidden");
            } else {
                stdoutEl.classList.add("hidden");
            }
            
            // Stderr
            if (stderr) {
                stderrEl.textContent = stderr;
                stderrEl.classList.remove("hidden");
            } else {
                stderrEl.classList.add("hidden");
            }
            
            // Status
            const isSuccess = exitCode === 0;
            statusEl.textContent = isSuccess ? "Success" : `Exit: ${exitCode}`;
            statusEl.className = `code-status px-2 py-0.5 rounded ${isSuccess ? 'bg-green-500' : 'bg-yellow-500'} text-white`;
        }
        
    } catch (err) {
        loadingEl.classList.add("hidden");
        outputSection.classList.remove("hidden");
        errorEl.textContent = err.message;
        errorEl.classList.remove("hidden");
        stdoutEl.classList.add("hidden");
        stderrEl.classList.add("hidden");
        statusEl.textContent = "Error";
        statusEl.className = "code-status px-2 py-0.5 rounded bg-red-500 text-white";
        
        log("error", `Code execution failed: ${err.message}`);
    } finally {
        runBtn.disabled = false;
        runBtn.innerHTML = '<i data-lucide="play" class="w-3 h-3"></i><span>Run</span>';
        lucide.createIcons();
    }
}

/**
 * Parst eine Nachricht und ersetzt Code-Blöcke durch interaktive Versionen
 */
export function parseMessageForCodeBlocks(content, executionResults = {}) {
    const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
    let match;
    let result = content;
    const blockIds = [];
    
    while ((match = codeBlockRegex.exec(content)) !== null) {
        const language = match[1] || "text";
        const code = match[2].trim();
        const fullMatch = match[0];
        
        // Prüfe ob es eine ausführbare Sprache ist
        const executableLanguages = ["python", "javascript", "js", "bash", "sh", "typescript", "ts"];
        
        if (executableLanguages.includes(language.toLowerCase())) {
            // Hole execution result wenn vorhanden
            const execResult = executionResults[code] || null;
            
            const { html, blockId } = createInteractiveCodeBlock(code, language, execResult);
            result = result.replace(fullMatch, html);
            blockIds.push(blockId);
        }
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
