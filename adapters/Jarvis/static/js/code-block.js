// code-block.js - Clean Code Blocks v3 (Prism-Fixed)

import { log } from "./debug.js";

let codeBlockCounter = 0;

const LANGUAGE_INFO = {
    python: { icon: "🐍", name: "Python" },
    javascript: { icon: "JS", name: "JavaScript" },
    js: { icon: "JS", name: "JavaScript" },
    bash: { icon: "$", name: "Bash" },
    sh: { icon: "$", name: "Shell" },
    typescript: { icon: "TS", name: "TypeScript" },
    ts: { icon: "TS", name: "TypeScript" },
    json: { icon: "{}", name: "JSON" },
    html: { icon: "<>", name: "HTML" },
    css: { icon: "#", name: "CSS" },
    sql: { icon: "DB", name: "SQL" },
    yaml: { icon: "📋", name: "YAML" },
    markdown: { icon: "MD", name: "Markdown" },
    md: { icon: "MD", name: "Markdown" },
    default: { icon: "📄", name: "Code" }
};

export function createInteractiveCodeBlock(code, language = "text") {
    const blockId = `code-block-${++codeBlockCounter}`;
    const langInfo = LANGUAGE_INFO[language] || LANGUAGE_INFO.default;
    
    console.log("[CodeBlock] Code has", (code.match(/\\n/g) || []).length, "newlines, language:", language);

    // WICHTIG: Code wird als data-attribute gespeichert (Base64)
    const encodedCode = btoa(unescape(encodeURIComponent(code)));

    const html = `
        <div id="${blockId}" class="code-block-interactive" data-language="${language}" data-code="${encodedCode}">
            <div class="code-header">
                <span class="code-lang">${langInfo.icon} ${langInfo.name}</span>
                <button class="code-copy-btn" title="Copy">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                </button>
            </div>
            <pre class="code-content"><code class="language-${language}"></code></pre>
        </div>
    `;

    return { html, blockId, code };
}

export function initCodeBlock(blockId) {
    const block = document.getElementById(blockId);
    if (!block) {
        console.warn("[CodeBlock] Block not found:", blockId);
        return;
    }

    const copyBtn = block.querySelector(".code-copy-btn");
    const codeEl = block.querySelector("code");
    
    if (!codeEl) {
        console.warn("[CodeBlock] Code element not found in:", blockId);
        return;
    }

    // WICHTIG: Code aus data-attribute laden und via textContent setzen
    const encodedCode = block.getAttribute("data-code");
    if (encodedCode) {
        try {
            const rawCode = decodeURIComponent(escape(atob(encodedCode)));
            codeEl.textContent = rawCode;  // textContent, NICHT innerHTML!
            console.log("[CodeBlock] Set textContent for", blockId, "length:", rawCode.length);
        } catch (e) {
            console.error("[CodeBlock] Failed to decode code:", e);
        }
    }

    // Copy-Button
    copyBtn?.addEventListener("click", () => {
        const code = codeEl.textContent;
        navigator.clipboard.writeText(code);
        copyBtn.classList.add("copied");
        
        setTimeout(() => {
            copyBtn.classList.remove("copied");
        }, 2000);

        log("info", "Code copied");
    });

    // Syntax highlighting mit requestAnimationFrame
    if (window.Prism && codeEl) {
        requestAnimationFrame(() => {
            console.log("[CodeBlock] Calling Prism.highlightElement for", blockId);
            Prism.highlightElement(codeEl);
        });
    } else {
        console.warn("[CodeBlock] Prism not available!");
    }
}

export function initCodeFormatting() {
    // Placeholder for future formatting features
}

export function parseMessageForCodeBlocks(content) {
    const codeBlockRegex = /```(\w*)\n?([\s\S]*?)```/g;
    let match;
    let result = content;
    const blockIds = [];
    const blockData = [];

    while ((match = codeBlockRegex.exec(content)) !== null) {
        const language = match[1] || "text";
        const code = match[2].trim();
        const fullMatch = match[0];
        
        console.log("[CodeBlock] Found code block, language:", language, "length:", code.length);

        const { html, blockId } = createInteractiveCodeBlock(code, language);
        result = result.replace(fullMatch, html);
        blockIds.push(blockId);
        blockData.push({ blockId, code, language });
    }

    return { content: result, blockIds, blockData };
}
