/**
 * ═══════════════════════════════════════════════════════════════
 * CODE BEAUTIFIER PLUGIN v1.0
 * Syntax Highlighting & Code Styling for Chat
 * ═══════════════════════════════════════════════════════════════
 */

const MANIFEST = {
    id: 'code-beautifier',
    name: 'Code Beautifier',
    version: '1.0.0',
    description: 'Syntax highlighting, themes & copy button for code blocks',
    author: 'Jarvis Team',
    icon: 'code-2'
};

// Themes
const THEMES = {
    dracula: {
        name: 'Dracula',
        bg: '#282a36',
        text: '#f8f8f2',
        comment: '#6272a4',
        keyword: '#ff79c6',
        string: '#f1fa8c',
        number: '#bd93f9',
        function: '#50fa7b',
        operator: '#ff79c6',
        class: '#8be9fd',
        variable: '#f8f8f2'
    },
    monokai: {
        name: 'Monokai',
        bg: '#272822',
        text: '#f8f8f2',
        comment: '#75715e',
        keyword: '#f92672',
        string: '#e6db74',
        number: '#ae81ff',
        function: '#a6e22e',
        operator: '#f92672',
        class: '#66d9ef',
        variable: '#f8f8f2'
    },
    github: {
        name: 'GitHub Dark',
        bg: '#0d1117',
        text: '#c9d1d9',
        comment: '#8b949e',
        keyword: '#ff7b72',
        string: '#a5d6ff',
        number: '#79c0ff',
        function: '#d2a8ff',
        operator: '#ff7b72',
        class: '#7ee787',
        variable: '#ffa657'
    },
    nord: {
        name: 'Nord',
        bg: '#2e3440',
        text: '#d8dee9',
        comment: '#616e88',
        keyword: '#81a1c1',
        string: '#a3be8c',
        number: '#b48ead',
        function: '#88c0d0',
        operator: '#81a1c1',
        class: '#8fbcbb',
        variable: '#d8dee9'
    },
    synthwave: {
        name: 'Synthwave',
        bg: '#262335',
        text: '#ffffff',
        comment: '#848bbd',
        keyword: '#fede5d',
        string: '#ff7edb',
        number: '#f97e72',
        function: '#36f9f6',
        operator: '#fede5d',
        class: '#ff7edb',
        variable: '#ffffff'
    }
};

// Language patterns for syntax highlighting
const PATTERNS = {
    comment: /\/\/.*$|\/\*[\s\S]*?\*\/|#.*$/gm,
    string: /(["'`])(?:(?!\1)[^\\]|\\.)*\1/g,
    keyword: /\b(const|let|var|function|return|if|else|for|while|class|import|export|from|async|await|try|catch|throw|new|this|super|extends|static|get|set|typeof|instanceof|in|of|true|false|null|undefined|def|self|lambda|yield|with|as|elif|except|finally|raise|pass|break|continue|and|or|not|is|None|True|False)\b/g,
    number: /\b\d+\.?\d*\b/g,
    function: /\b([a-zA-Z_]\w*)\s*(?=\()/g,
    class: /\b([A-Z][a-zA-Z0-9_]*)\b/g,
    operator: /[+\-*/%=<>!&|^~?:]+/g,
    variable: /\b([a-zA-Z_]\w*)\b/g
};

class CodeBeautifierPlugin extends PluginBase {
    constructor(panel, manager) {
        super(panel, manager);
        this.settings = {
            theme: 'dracula',
            lineNumbers: true,
            showLanguage: true,
            copyButton: true
        };
        this.observer = null;
        this.styleElement = null;
    }
    
    init() {
        console.log('[CodeBeautifier] Initializing...');
        
        // Inject styles
        this.injectStyles();
        
        // Process existing code blocks
        this.processAllCodeBlocks();
        
        // Watch for new code blocks
        this.startObserver();
        
        console.log('[CodeBeautifier] Ready with theme:', this.settings.theme);
    }
    
    destroy() {
        console.log('[CodeBeautifier] Destroying...');
        
        // Stop observer
        if (this.observer) {
            this.observer.disconnect();
            this.observer = null;
        }
        
        // Remove styles
        if (this.styleElement) {
            this.styleElement.remove();
            this.styleElement = null;
        }
        
        // Remove beautified wrappers (restore original)
        document.querySelectorAll('.code-beautified').forEach(wrapper => {
            const pre = wrapper.querySelector('pre');
            if (pre && wrapper.parentNode) {
                wrapper.parentNode.replaceChild(pre.cloneNode(true), wrapper);
            }
        });
    }
    
    getSettings() {
        return [
            {
                key: 'theme',
                label: 'Color Theme',
                type: 'select',
                default: 'dracula',
                options: Object.entries(THEMES).map(([id, t]) => ({
                    value: id,
                    label: t.name
                }))
            },
            {
                key: 'lineNumbers',
                label: 'Show Line Numbers',
                type: 'toggle',
                default: true,
                description: 'Display line numbers on the left side'
            },
            {
                key: 'showLanguage',
                label: 'Show Language Badge',
                type: 'toggle',
                default: true,
                description: 'Show detected language in top-right corner'
            },
            {
                key: 'copyButton',
                label: 'Copy Button',
                type: 'toggle',
                default: true,
                description: 'Add a copy-to-clipboard button'
            }
        ];
    }
    
    onSettingChange(key, value) {
        this.settings[key] = value;
        console.log(`[CodeBeautifier] Setting changed: ${key} = ${value}`);
        
        // Re-apply styles and re-process
        this.injectStyles();
        this.reprocessAllCodeBlocks();
    }
    
    injectStyles() {
        const theme = THEMES[this.settings.theme] || THEMES.dracula;
        
        const css = `
            .code-beautified {
                position: relative;
                margin: 1rem 0;
                border-radius: 8px;
                overflow: hidden;
                background: ${theme.bg};
                border: 1px solid rgba(255,255,255,0.1);
                font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Consolas', monospace;
            }
            
            .code-beautified-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 12px;
                background: rgba(0,0,0,0.3);
                border-bottom: 1px solid rgba(255,255,255,0.05);
            }
            
            .code-beautified-lang {
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: ${theme.function};
                font-weight: 600;
            }
            
            .code-beautified-copy {
                display: flex;
                align-items: center;
                gap: 4px;
                padding: 4px 8px;
                font-size: 11px;
                color: ${theme.text};
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 4px;
                cursor: pointer;
                transition: all 0.2s;
            }
            
            .code-beautified-copy:hover {
                background: rgba(255,255,255,0.1);
                border-color: ${theme.function};
                color: ${theme.function};
            }
            
            .code-beautified-copy.copied {
                background: rgba(80, 250, 123, 0.2);
                border-color: #50fa7b;
                color: #50fa7b;
            }
            
            .code-beautified-body {
                display: flex;
                overflow-x: auto;
            }
            
            .code-beautified-lines {
                padding: 12px 0;
                text-align: right;
                user-select: none;
                background: rgba(0,0,0,0.2);
                border-right: 1px solid rgba(255,255,255,0.05);
            }
            
            .code-beautified-line-num {
                display: block;
                padding: 0 12px;
                font-size: 12px;
                line-height: 1.6;
                color: ${theme.comment};
            }
            
            .code-beautified pre {
                flex: 1;
                margin: 0;
                padding: 12px 16px;
                overflow-x: auto;
                background: transparent !important;
                border: none !important;
            }
            
            .code-beautified code {
                font-size: 13px;
                line-height: 1.6;
                color: ${theme.text};
                background: transparent !important;
            }
            
            /* Syntax Colors */
            .code-beautified .cb-comment { color: ${theme.comment}; font-style: italic; }
            .code-beautified .cb-string { color: ${theme.string}; }
            .code-beautified .cb-keyword { color: ${theme.keyword}; font-weight: 600; }
            .code-beautified .cb-number { color: ${theme.number}; }
            .code-beautified .cb-function { color: ${theme.function}; }
            .code-beautified .cb-class { color: ${theme.class}; }
            .code-beautified .cb-operator { color: ${theme.operator}; }
            .code-beautified .cb-variable { color: ${theme.variable}; }
        `;
        
        if (this.styleElement) {
            this.styleElement.textContent = css;
        } else {
            this.styleElement = document.createElement('style');
            this.styleElement.id = 'code-beautifier-styles';
            this.styleElement.textContent = css;
            document.head.appendChild(this.styleElement);
        }
    }
    
    startObserver() {
        const chatContainer = document.getElementById('chat-messages') || document.body;
        
        this.observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === 1) {
                        const codeBlocks = node.querySelectorAll ? 
                            node.querySelectorAll('pre:not(.code-beautified-processed)') : [];
                        codeBlocks.forEach(pre => this.beautifyCodeBlock(pre));
                        
                        if (node.tagName === 'PRE' && !node.classList.contains('code-beautified-processed')) {
                            this.beautifyCodeBlock(node);
                        }
                    }
                }
            }
        });
        
        this.observer.observe(chatContainer, {
            childList: true,
            subtree: true
        });
    }
    
    processAllCodeBlocks() {
        document.querySelectorAll('pre:not(.code-beautified-processed)').forEach(pre => {
            this.beautifyCodeBlock(pre);
        });
    }
    
    reprocessAllCodeBlocks() {
        // Remove old wrappers first
        document.querySelectorAll('.code-beautified').forEach(wrapper => {
            const code = wrapper.querySelector('code');
            if (code) {
                const pre = document.createElement('pre');
                const newCode = document.createElement('code');
                newCode.textContent = code.textContent;
                newCode.className = code.dataset.originalClass || '';
                pre.appendChild(newCode);
                wrapper.parentNode.replaceChild(pre, wrapper);
            }
        });
        
        // Process again
        this.processAllCodeBlocks();
    }
    
    beautifyCodeBlock(pre) {
        if (pre.closest('.code-beautified')) return;
        
        const code = pre.querySelector('code') || pre;
        const rawCode = code.textContent || '';
        
        if (!rawCode.trim()) return;
        
        // Detect language
        const lang = this.detectLanguage(code, rawCode);
        
        // Apply syntax highlighting
        const highlighted = this.highlight(rawCode);
        
        // Count lines
        const lines = rawCode.split('\n');
        const lineCount = lines.length;
        
        // Build wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'code-beautified';
        
        // Header
        if (this.settings.showLanguage || this.settings.copyButton) {
            const header = document.createElement('div');
            header.className = 'code-beautified-header';
            
            if (this.settings.showLanguage) {
                const langBadge = document.createElement('span');
                langBadge.className = 'code-beautified-lang';
                langBadge.textContent = lang;
                header.appendChild(langBadge);
            } else {
                header.appendChild(document.createElement('span'));
            }
            
            if (this.settings.copyButton) {
                const copyBtn = document.createElement('button');
                copyBtn.className = 'code-beautified-copy';
                copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> Copy';
                copyBtn.onclick = () => this.copyCode(rawCode, copyBtn);
                header.appendChild(copyBtn);
            }
            
            wrapper.appendChild(header);
        }
        
        // Body
        const body = document.createElement('div');
        body.className = 'code-beautified-body';
        
        // Line numbers
        if (this.settings.lineNumbers) {
            const linesDiv = document.createElement('div');
            linesDiv.className = 'code-beautified-lines';
            for (let i = 1; i <= lineCount; i++) {
                const lineNum = document.createElement('span');
                lineNum.className = 'code-beautified-line-num';
                lineNum.textContent = i;
                linesDiv.appendChild(lineNum);
            }
            body.appendChild(linesDiv);
        }
        
        // Code content
        const newPre = document.createElement('pre');
        newPre.className = 'code-beautified-processed';
        const newCode = document.createElement('code');
        newCode.innerHTML = highlighted;
        newCode.dataset.originalClass = code.className;
        newPre.appendChild(newCode);
        body.appendChild(newPre);
        
        wrapper.appendChild(body);
        
        // Replace
        pre.classList.add('code-beautified-processed');
        pre.parentNode.replaceChild(wrapper, pre);
    }
    
    detectLanguage(codeEl, content) {
        // Check class name first
        const className = codeEl.className || '';
        const langMatch = className.match(/language-(\w+)|lang-(\w+)|(\w+)/);
        if (langMatch) {
            const lang = langMatch[1] || langMatch[2] || langMatch[3];
            if (lang && lang !== 'code') return lang;
        }
        
        // Auto-detect from content
        if (/^\s*<[!?]?[a-zA-Z]/.test(content)) return 'html';
        if (/^\s*(import|from|def |class |if __name__)/.test(content)) return 'python';
        if (/^\s*(const|let|var|function|import|export|=>)/.test(content)) return 'javascript';
        if (/^\s*(package|func |import "|var |type )/.test(content)) return 'go';
        if (/^\s*(fn |let |use |impl |struct |enum )/.test(content)) return 'rust';
        if (/^\s*(public|private|class|interface|void|int|String)/.test(content)) return 'java';
        if (/^\s*(\$|echo|if \[)/.test(content) || content.startsWith("#!")) return "bash";
        if (/^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|FROM|WHERE)/i.test(content)) return 'sql';
        if (/^\s*[\{\[]/.test(content) && /[\}\]]$/.test(content.trim())) return 'json';
        if (/^\s*---/.test(content) || /:\s*\n\s+-/.test(content)) return 'yaml';
        if (/^\s*(body|div|\.[\w-]+|#[\w-]+)\s*\{/.test(content)) return 'css';
        
        return 'code';
    }
    
    highlight(code) {
        // Escape HTML first
        let html = this.escapeHtml(code);
        
        // Temporary placeholders to avoid double-matching
        const placeholders = [];
        const placeholder = (match, className) => {
            const idx = placeholders.length;
            placeholders.push(`<span class="${className}">${match}</span>`);
            return `\x00${idx}\x00`;
        };
        
        // Apply patterns in order (comments & strings first to avoid conflicts)
        html = html.replace(PATTERNS.comment, m => placeholder(m, 'cb-comment'));
        html = html.replace(PATTERNS.string, m => placeholder(m, 'cb-string'));
        html = html.replace(PATTERNS.keyword, m => placeholder(m, 'cb-keyword'));
        html = html.replace(PATTERNS.number, m => placeholder(m, 'cb-number'));
        html = html.replace(PATTERNS.function, (m, name) => placeholder(name, 'cb-function') + '(');
        
        // Restore placeholders
        html = html.replace(/\x00(\d+)\x00/g, (_, idx) => placeholders[idx]);
        
        return html;
    }
    
    escapeHtml(str) {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
    
    copyCode(code, btn) {
        navigator.clipboard.writeText(code).then(() => {
            const originalHTML = btn.innerHTML;
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg> Copied!';
            btn.classList.add('copied');
            
            setTimeout(() => {
                btn.innerHTML = originalHTML;
                btn.classList.remove('copied');
            }, 2000);
        });
    }
}

// Register
if (window.PluginManager) {
    window.PluginManager.registerBuiltIn(MANIFEST, CodeBeautifierPlugin);
} else {
    window.addEventListener('DOMContentLoaded', () => {
        if (window.PluginManager) {
            window.PluginManager.registerBuiltIn(MANIFEST, CodeBeautifierPlugin);
        }
    });
}
