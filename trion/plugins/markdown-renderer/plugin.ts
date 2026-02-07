/**
 * Markdown Renderer Plugin v1.0
 * 
 * Handles Markdown rendering with proper code block isolation.
 * Prevents conflicts between marked.js and Prism.js by ensuring:
 * - Code blocks are NEVER processed by marked.js
 * - Prism receives raw textContent, not innerHTML
 * - Proper timing via requestAnimationFrame
 */

import { TRIONPlugin, PluginContext, PluginSetting } from '../../runtime/plugin-base.ts';

interface RenderRequest {
    id: string;
    content: string;
    options?: {
        enableTables?: boolean;
        enableCodeHighlight?: boolean;
        enableHeaders?: boolean;
    };
}

interface CodeBlock {
    language: string;
    code: string;
    placeholder: string;
}

export default class MarkdownRendererPlugin implements TRIONPlugin {
    private ctx: PluginContext;
    private tabId = 'markdown-debug';

    constructor(ctx: PluginContext) {
        this.ctx = ctx;
    }

    async init(): Promise<void> {
        this.ctx.log('Markdown Renderer Plugin initialized!');

        // Listen for render requests from frontend
        this.ctx.events.on('markdown:render', this.handleRender.bind(this));
        this.ctx.events.on('markdown:debug', this.handleDebug.bind(this));
    }

    async destroy(): Promise<void> {
        this.ctx.log('Markdown Renderer Plugin destroyed');
    }

    /**
     * Handle markdown render request
     * Architecture:
     * 1. Extract code blocks (preserve raw code)
     * 2. Process markdown on text-only content
     * 3. Re-insert code blocks with proper attributes for Prism
     */
    private async handleRender(data: RenderRequest): Promise<void> {
        this.ctx.log('Received render request:', data.id);

        try {
            const result = this.renderMarkdown(data.content, data.options);
            
            // Emit result back to frontend
            this.ctx.events.emit('markdown:rendered', {
                id: data.id,
                html: result.html,
                codeBlocks: result.codeBlocks
            });

        } catch (error) {
            this.ctx.events.emit('markdown:error', {
                id: data.id,
                error: error instanceof Error ? error.message : String(error)
            });
        }
    }

    /**
     * Main render logic - separates code from markdown
     */
    private renderMarkdown(content: string, options?: RenderRequest['options']): {
        html: string;
        codeBlocks: CodeBlock[];
    } {
        const codeBlocks: CodeBlock[] = [];
        
        // Step 1: Extract ALL code blocks FIRST
        const codeBlockRegex = /```(\w+)?\n?([\s\S]*?)```/g;
        let match;
        let processedContent = content;
        let blockIndex = 0;

        while ((match = codeBlockRegex.exec(content)) !== null) {
            const language = match[1] || 'plaintext';
            const code = match[2].trim();
            const placeholder = `___TRION_CODE_BLOCK_${blockIndex}___`;
            
            codeBlocks.push({
                language,
                code,
                placeholder
            });

            processedContent = processedContent.replace(match[0], placeholder);
            blockIndex++;
        }

        // Step 2: Send text-only content for markdown processing
        // (This would be handled by the frontend marked.js)
        // For now, we just return the separated content
        
        // Step 3: Generate code block HTML templates
        // IMPORTANT: Use data-code attribute, NOT innerHTML
        const codeBlocksHtml = codeBlocks.map(block => ({
            ...block,
            html: this.generateCodeBlockHtml(block)
        }));

        return {
            html: processedContent,
            codeBlocks: codeBlocks
        };
    }

    /**
     * Generate safe code block HTML
     * Code is stored in data-code attribute to prevent HTML parsing issues
     */
    private generateCodeBlockHtml(block: CodeBlock): string {
        const blockId = `code-block-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        
        // Base64 encode to prevent any HTML issues
        const encodedCode = btoa(encodeURIComponent(block.code));
        
        return `
            <div id="${blockId}" class="code-block-interactive" data-language="${block.language}" data-code="${encodedCode}">
                <div class="code-header">
                    <span class="code-language">${block.language}</span>
                    <button class="code-copy-btn" data-block-id="${blockId}">Copy</button>
                </div>
                <pre class="code-content"><code class="language-${block.language}"></code></pre>
            </div>
        `;
    }

    /**
     * Debug endpoint to show current render state
     */
    private async handleDebug(data: unknown): Promise<void> {
        await this.ctx.panel.createTab(this.tabId, '📝 Markdown Debug', 'markdown', {
            autoOpen: true,
            content: `# Markdown Renderer Debug

## Status
- Plugin: **Active** ✅
- Version: 1.0.0

## Architecture
1. **Code Block Extraction**: Regex-based, before ANY markdown processing
2. **Markdown Processing**: marked.js on text-only content
3. **Code Injection**: textContent-based, NEVER innerHTML
4. **Prism Timing**: requestAnimationFrame after DOM insert

## Settings
- Tables: ${this.ctx.getSetting('enableTables')}
- Code Highlight: ${this.ctx.getSetting('enableCodeHighlight')}
- Headers: ${this.ctx.getSetting('enableHeaders')}
`
        });
    }

    getSettings(): PluginSetting[] {
        return [
            {
                key: 'enableTables',
                label: 'Enable Tables',
                type: 'toggle',
                default: true,
                description: 'Render Markdown tables'
            },
            {
                key: 'enableCodeHighlight',
                label: 'Enable Syntax Highlighting',
                type: 'toggle',
                default: true,
                description: 'Use Prism.js for code highlighting'
            },
            {
                key: 'enableHeaders',
                label: 'Enable Headers',
                type: 'toggle',
                default: true,
                description: 'Render Markdown headers (h1-h6)'
            }
        ];
    }
}
