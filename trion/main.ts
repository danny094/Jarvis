/**
 * TRION - Plugin Runtime for Jarvis
 * Main Entry Point
 */

import { startBridge } from './bridge/websocket-server.ts';

console.log(`
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║   ████████╗██████╗ ██╗ ██████╗ ███╗   ██╗                 ║
║   ╚══██╔══╝██╔══██╗██║██╔═══██╗████╗  ██║                 ║
║      ██║   ██████╔╝██║██║   ██║██╔██╗ ██║                 ║
║      ██║   ██╔══██╗██║██║   ██║██║╚██╗██║                 ║
║      ██║   ██║  ██║██║╚██████╔╝██║ ╚████║                 ║
║      ╚═╝   ╚═╝  ╚═╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝                 ║
║                                                            ║
║   Plugin Runtime v1.0.0                                    ║
║   Secure • Sandboxed • Fast                                ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
`);

console.log('[TRION] Starting...');
console.log('[TRION] Vault: /DATA/AppData/MCP/Jarvis/vault');
console.log('[TRION] Plugins: /DATA/AppData/MCP/Jarvis/trion/plugins');
console.log('');

// Start the WebSocket bridge
await startBridge();
