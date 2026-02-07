/**
 * Code Beautifier Plugin
 * Formats code using Deno's built-in formatter or internal logic
 */

import { TRIONPlugin, PluginContext } from '../../runtime/plugin-base.ts';

export default class CodeBeautifierPlugin implements TRIONPlugin {
    private ctx: PluginContext;

    constructor(ctx: PluginContext) {
        this.ctx = ctx;
    }

    async init(): Promise<void> {
        console.log('[CodeBeautifier] Initializing...');

        // Listen for format requests
        this.ctx.events.on('code:format', this.handleFormat.bind(this));
    }

    async destroy(): Promise<void> {
        console.log('[CodeBeautifier] Destroying...');
    }

    private async handleFormat(data: { code: string, language: string, id: string }): Promise<void> {
        console.log(`[CodeBeautifier] Formatting ${data.language}...`);

        let formatted = data.code;

        try {
            if (data.language === 'json') {
                formatted = JSON.stringify(JSON.parse(data.code), null, 2);
            }
            // Add more languages here or use Deno.Command if permission allowed
            // For now, we stick to safe JSON formatting as a proof of concept

            this.ctx.events.emit('code:formatted', {
                id: data.id,
                code: formatted,
                language: data.language
            });

        } catch (e) {
            console.error('[CodeBeautifier] Error:', e);
            this.ctx.events.emit('code:error', {
                id: data.id,
                error: e instanceof Error ? e.message : String(e)
            });
        }
    }

    getSettings() {
        return [
            {
                key: 'indentSize',
                label: 'Indentation Size',
                type: 'number' as const,
                default: 2
            }
        ];
    }
}
