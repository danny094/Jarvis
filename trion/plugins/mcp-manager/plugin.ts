/**
 * MCP Manager Plugin
 * Manages system-level MCP servers using 'uv'
 * Tier: 3 (System) - Requires 'allow-run' permission (if enforced)
 */

import { TRIONPlugin, PluginContext } from '../../runtime/plugin-base.ts';

// Define response types
interface CommandResult {
    stdout: string;
    stderr: string;
    code: number;
}

export default class MCPManagerPlugin implements TRIONPlugin {
    private ctx: PluginContext;

    constructor(ctx: PluginContext) {
        this.ctx = ctx;
    }

    async init(): Promise<void> {
        console.log('[MCPManager] Initializing System Tool Manager...');

        this.ctx.events.on('mcp:install', this.handleInstall.bind(this));
        this.ctx.events.on('mcp:list', this.handleList.bind(this));
    }

    async destroy(): Promise<void> {
        console.log('[MCPManager] Destroying...');
    }

    private async handleInstall(data: { package: string }): Promise<void> {
        console.log(`[MCPManager] Installing ${data.package}...`);

        try {
            // Using Deno.Command to call 'uv'
            // Note: The Runtime must be started with --allow-run
            const command = new Deno.Command("uv", {
                args: ["pip", "install", data.package],
                stdout: "piped",
                stderr: "piped",
            });

            const output = await command.output();
            const result = this.decodeResult(output);

            if (result.code === 0) {
                this.ctx.log(`Successfully installed ${data.package}`);
                this.ctx.events.emit('mcp:install_success', { package: data.package, logs: result.stdout });
            } else {
                this.ctx.log(`Failed to install ${data.package}`, result.stderr);
                this.ctx.events.emit('mcp:install_error', { package: data.package, error: result.stderr });
            }

        } catch (e) {
            console.error('[MCPManager] Execution error:', e);
            this.ctx.events.emit('mcp:install_error', { package: data.package, error: String(e) });
        }
    }

    private async handleList(): Promise<void> {
        try {
            const command = new Deno.Command("uv", {
                args: ["pip", "list"],
                stdout: "piped",
                stderr: "piped",
            });
            const output = await command.output();
            const result = this.decodeResult(output);

            this.ctx.events.emit('mcp:list_result', { packages: result.stdout });
        } catch (e) {
            console.error('[MCPManager] List error:', e);
        }
    }

    private decodeResult(output: Deno.CommandOutput): CommandResult {
        return {
            stdout: new TextDecoder().decode(output.stdout),
            stderr: new TextDecoder().decode(output.stderr),
            code: output.code
        };
    }

    getSettings() {
        return [];
    }
}
