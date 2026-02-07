/**
 * TRION WebSocket Bridge Server
 */

import { pluginHost } from '../runtime/plugin-host.ts';
import { BridgeMessage, BridgeResponse, createResponse, createEvent } from './message-types.ts';

const PORT = 8401;
const clients = new Set<WebSocket>();

function broadcast(msg: unknown) {
  const json = JSON.stringify(msg);
  clients.forEach(c => c.readyState === WebSocket.OPEN && c.send(json));
}

async function handleMsg(ws: WebSocket, msg: BridgeMessage) {
  console.log('[Bridge] Handling:', msg.type);
  let resp: BridgeResponse;
  
  try {
    switch (msg.type) {
      case 'plugin:list': 
        resp = createResponse(msg.id, msg.type, true, pluginHost.getAll()); 
        break;
        
      case 'plugin:enable': {
        const {id} = msg.payload as {id:string};
        const success = await pluginHost.enablePlugin(id);
        resp = createResponse(msg.id, msg.type, success);
        break;
      }
      
      case 'plugin:disable': {
        const {id} = msg.payload as {id:string};
        const success = await pluginHost.disablePlugin(id);
        resp = createResponse(msg.id, msg.type, success);
        break;
      }
      
      case 'backend:event': {
        const { eventType, data } = msg.payload as { eventType: string, data: unknown };
        console.log('[Bridge] Dispatching backend event:', eventType);
        pluginHost.dispatchBackendEvent(eventType, data);
        resp = createResponse(msg.id, msg.type, true);
        break;
      }
      
      default: 
        console.log('[Bridge] Unknown message type:', msg.type);
        resp = createResponse(msg.id, msg.type, false, undefined, 'Unknown message type: ' + msg.type);
    }
  } catch(e) { 
    console.error('[Bridge] Error handling message:', e);
    resp = createResponse(msg.id, msg.type, false, undefined, String(e)); 
  }
  
  ws.send(JSON.stringify(resp));
}

export async function startBridge(): Promise<void> {
  await pluginHost.loadAll();
  pluginHost.setBridgeCallback(broadcast);
  
  console.log('[Bridge] Starting server...');
  
  Deno.serve({ port: PORT, hostname: '0.0.0.0' }, (req) => {
    const upgrade = req.headers.get('upgrade');
    console.log('[Bridge] Request, upgrade:', upgrade);
    
    if (upgrade?.toLowerCase() !== 'websocket') {
      return new Response('TRION Bridge - WebSocket endpoint', { status: 200 });
    }
    
    const { socket, response } = Deno.upgradeWebSocket(req);
    
    socket.onopen = () => {
      console.log('[Bridge] Client connected');
      clients.add(socket);
      socket.send(JSON.stringify(createEvent('plugin:list', pluginHost.getAll())));
    };
    
    socket.onmessage = async (e) => {
      try { 
        await handleMsg(socket, JSON.parse(e.data)); 
      } catch(err) { 
        console.error('[Bridge] Parse error:', err); 
      }
    };
    
    socket.onclose = () => { 
      clients.delete(socket); 
      console.log('[Bridge] Client disconnected'); 
    };
    
    socket.onerror = (e) => { 
      console.error('[Bridge] Socket error:', e); 
      clients.delete(socket); 
    };
    
    return response;
  });
  
  console.log('[Bridge] ✅ Running on ws://0.0.0.0:' + PORT);
}

if (import.meta.main) { startBridge(); }
