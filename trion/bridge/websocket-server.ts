/**
 * TRION WebSocket Bridge Server
 */

import { pluginHost } from '../runtime/plugin-host.ts';
import { BridgeMessage, BridgeResponse, createResponse, createEvent } from './message-types.ts';

const PORT = 8401;
const clients = new Set<WebSocket>();
type ClientMeta = {
  clientId: string;
  connectedAtMs: number;
  lastSeenMs: number;
  lastPingMs: number;
  lastPongMs: number;
};
const clientMeta = new Map<WebSocket, ClientMeta>();

function _envInt(name: string, fallback: number): number {
  const raw = Deno.env.get(name);
  const parsed = Number.parseInt(String(raw ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

const WS_IDLE_TIMEOUT_S = _envInt("TRION_BRIDGE_WS_IDLE_TIMEOUT_S", 180);
const HEARTBEAT_ENABLE = String(Deno.env.get("TRION_BRIDGE_HEARTBEAT_ENABLE") ?? "true").toLowerCase() !== "false";
const HEARTBEAT_INTERVAL_MS = _envInt("TRION_BRIDGE_HEARTBEAT_INTERVAL_MS", 25000);
const HEARTBEAT_TIMEOUT_MS = _envInt("TRION_BRIDGE_HEARTBEAT_TIMEOUT_MS", 90000);
let heartbeatTimer: number | null = null;

function _dropClient(ws: WebSocket) {
  clients.delete(ws);
  clientMeta.delete(ws);
}

function _ensureHeartbeatLoop() {
  if (!HEARTBEAT_ENABLE || heartbeatTimer !== null) return;
  const tickMs = Math.max(1000, Math.floor(HEARTBEAT_INTERVAL_MS / 2));
  heartbeatTimer = setInterval(() => {
    const now = Date.now();
    clients.forEach((ws) => {
      if (ws.readyState !== WebSocket.OPEN) {
        _dropClient(ws);
        return;
      }
      const meta = clientMeta.get(ws);
      if (!meta) return;
      if ((now - meta.lastPongMs) > HEARTBEAT_TIMEOUT_MS) {
        console.warn(
          `[Bridge] Heartbeat timeout client=${meta.clientId} ` +
          `idle_ms=${now - meta.lastPongMs} timeout_ms=${HEARTBEAT_TIMEOUT_MS}`,
        );
        try {
          ws.close(4000, "heartbeat_timeout");
        } catch {
          // ignore close race
        }
        _dropClient(ws);
        return;
      }
      if ((now - meta.lastPingMs) >= HEARTBEAT_INTERVAL_MS) {
        meta.lastPingMs = now;
        try {
          ws.send(JSON.stringify(createEvent("bridge:ping", { ts: now })));
        } catch (err) {
          console.warn("[Bridge] Heartbeat ping send failed:", err);
          _dropClient(ws);
        }
      }
    });
    if (clients.size === 0 && heartbeatTimer !== null) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }, tickMs);
}

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

      case 'bridge:pong': {
        const meta = clientMeta.get(ws);
        if (meta) {
          meta.lastSeenMs = Date.now();
          meta.lastPongMs = meta.lastSeenMs;
        }
        resp = createResponse(msg.id, msg.type, true, { ok: true });
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
    
    const { socket, response } = Deno.upgradeWebSocket(req, { idleTimeout: WS_IDLE_TIMEOUT_S });
    
    socket.onopen = () => {
      const now = Date.now();
      const meta: ClientMeta = {
        clientId: crypto.randomUUID(),
        connectedAtMs: now,
        lastSeenMs: now,
        lastPingMs: now,
        lastPongMs: now,
      };
      console.log('[Bridge] Client connected', meta.clientId);
      clients.add(socket);
      clientMeta.set(socket, meta);
      _ensureHeartbeatLoop();
      socket.send(JSON.stringify(createEvent('plugin:list', pluginHost.getAll())));
    };
    
    socket.onmessage = async (e) => {
      const meta = clientMeta.get(socket);
      if (meta) meta.lastSeenMs = Date.now();
      try { 
        await handleMsg(socket, JSON.parse(e.data)); 
      } catch(err) { 
        console.error('[Bridge] Parse error:', err); 
      }
    };
    
    socket.onclose = (ev) => { 
      const meta = clientMeta.get(socket);
      _dropClient(socket);
      if (meta) {
        console.log(
          `[Bridge] Client disconnected ${meta.clientId} code=${ev.code} reason=${ev.reason || "n/a"}`,
        );
      } else {
        console.log('[Bridge] Client disconnected');
      }
    };
    
    socket.onerror = (e) => { 
      console.error('[Bridge] Socket error:', e); 
      _dropClient(socket); 
    };
    
    return response;
  });
  
  console.log('[Bridge] ✅ Running on ws://0.0.0.0:' + PORT);
}

if (import.meta.main) { startBridge(); }
