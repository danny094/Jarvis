/**
 * Ping Test Plugin
 * Simple connectivity test for TRION
 */

import { TRIONPlugin, PluginContext } from '../../runtime/plugin-base.ts';

export default class PingTestPlugin implements TRIONPlugin {
  private ctx: PluginContext;

  constructor(ctx: PluginContext) {
    this.ctx = ctx;
  }

  async init(): Promise<void> {
    console.log('[PingTest] 🏓 Plugin initialized!');
    
    // Listen for ping events
    this.ctx.events.on('ping', this.handlePing.bind(this));
  }

  async destroy(): Promise<void> {
    console.log('[PingTest] ❌ Plugin destroyed');
  }

  private handlePing(data: unknown): void {
    console.log('[PingTest] Received ping:', data);
    
    // Send pong back via panel
    this.ctx.panel.createTab('ping-pong', '🏓 Pong!', 'markdown', {
      autoOpen: true,
      content: '## TRION is alive! 🎉\n\nPing received at: ' + new Date().toISOString() + '\n\nData: ' + JSON.stringify(data)
    });
  }
}
