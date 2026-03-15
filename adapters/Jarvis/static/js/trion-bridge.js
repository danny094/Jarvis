/**
 * TRION Bridge Client v4
 * Connects Browser to Deno Plugin Runtime via nginx proxy
 */

class TRIONBridge {
    constructor() {
        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        const cfg = (window.TRION_BRIDGE_CFG && typeof window.TRION_BRIDGE_CFG === "object")
            ? window.TRION_BRIDGE_CFG
            : {};
        this.maxReconnectAttempts = Number.isFinite(Number(cfg.maxReconnectAttempts))
            ? Number(cfg.maxReconnectAttempts)
            : 0; // 0 => unlimited
        this.baseReconnectDelayMs = Number.isFinite(Number(cfg.baseReconnectDelayMs))
            ? Number(cfg.baseReconnectDelayMs)
            : 1000;
        this.maxReconnectDelayMs = Number.isFinite(Number(cfg.maxReconnectDelayMs))
            ? Number(cfg.maxReconnectDelayMs)
            : 30000;
        this.enableClientHeartbeat = String(cfg.enableClientHeartbeat ?? "true").toLowerCase() !== "false";
        this.clientHeartbeatIntervalMs = Number.isFinite(Number(cfg.clientHeartbeatIntervalMs))
            ? Number(cfg.clientHeartbeatIntervalMs)
            : 30000;
        this.heartbeatTimer = null;
        this.pendingRequests = new Map();
        this.eventHandlers = new Map();
        this.plugins = [];
        this.startEventBroadcaster();
    }

    startEventBroadcaster() {
        window.addEventListener('sse-event', (e) => {
            const detail = e.detail;
            if (!detail) return; console.log("[TRIONBridge] Forwarding SSE event:", detail.type);
            this.request('backend:event', {
                eventType: detail.type,
                data: detail
            }).catch((err) => { console.warn("[TRIONBridge] Event forward failed:", detail.type, err.message); });
        });
    }

    connect(url) {
        if (!url) {
            var wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            url = wsProtocol + "//" + window.location.host + "/trion/";
        }

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            return Promise.resolve();
        }

        var self = this;
        return new Promise(function (resolve, reject) {
            console.log("[TRIONBridge] Connecting to " + url);
            self.ws = new WebSocket(url);

            self.ws.onopen = function () {
                console.log("[TRIONBridge] Connected!");
                self.connected = true;
                self.reconnectAttempts = 0;
                self._startHeartbeat();
                self.emit("connected");
                resolve();
            };

            self.ws.onclose = function (ev) {
                console.log("[TRIONBridge] Disconnected", ev && ev.code, ev && ev.reason);
                self.connected = false;
                self._stopHeartbeat();
                self._rejectPending("Connection closed");
                self.emit("disconnected");
                self.attemptReconnect();
            };

            self.ws.onerror = function (error) {
                console.error("[TRIONBridge] Error:", error);
                reject(error);
            };

            self.ws.onmessage = function (event) {
                try {
                    self.handleMessage(JSON.parse(event.data));
                } catch (err) {
                    console.warn("[TRIONBridge] Invalid message payload:", err && err.message ? err.message : err);
                }
            };
        });
    }

    handleMessage(message) {
        console.log("[TRIONBridge] Received:", message.type);

        if (message.direction === "response") {
            var pending = this.pendingRequests.get(message.id);
            if (pending) {
                this.pendingRequests.delete(message.id);
                if (message.success) {
                    pending.resolve(message.data);
                } else {
                    pending.reject(new Error(message.error || "Unknown error"));
                }
            }
        } else if (message.direction === "event" || !message.direction) {
            this.handleEvent(message);
        }
    }

    handleEvent(event) {
        var p = event.payload;
        
        switch (event.type) {
            case "bridge:ping":
                this._sendBridgePong();
                this.emit("telemetry", { type: "bridge_ping", ts: Date.now() });
                break;

            case "plugin:list":
                this.plugins = p;
                this.emit("plugins:updated", p);
                break;
                
            case "plugin:enabled":
                this.emit("plugin:enabled", p);
                break;
                
            case "plugin:disabled":
                this.emit("plugin:disabled", p);
                break;
                
            case "panel:create":
                console.log("[TRIONBridge] Creating panel tab:", p.tabId);
                if (window.TRIONPanel) {
                    window.TRIONPanel.createTab(p.tabId, p.title, p.contentType, p.options);
                }
                break;
                
            case "panel:update":
                console.log("[TRIONBridge] Updating panel tab:", p.tabId);
                if (window.TRIONPanel) {
                    window.TRIONPanel.updateContent(p.tabId, p.content, p.append);
                }
                break;
                
            case "panel:close":
                console.log("[TRIONBridge] Closing panel tab:", p.tabId);
                if (window.TRIONPanel) {
                    window.TRIONPanel.closeTab(p.tabId);
                }
                break;
                
            default:
                console.log("[TRIONBridge] Unknown event:", event.type);
        }
    }

    request(type, payload) {
        if (!payload) payload = {};
        if (!this.connected) {
            return Promise.reject(new Error("Not connected to TRION"));
        }

        var self = this;
        return new Promise(function (resolve, reject) {
            var id = Math.random().toString(36).substring(2) + Date.now().toString(36);
            self.pendingRequests.set(id, { resolve: resolve, reject: reject });

            setTimeout(function () {
                if (self.pendingRequests.has(id)) {
                    self.pendingRequests.delete(id);
                    reject(new Error("Request timeout"));
                }
            }, 10000);

            self.ws.send(JSON.stringify({
                id: id,
                direction: "request",
                type: type,
                payload: payload,
                timestamp: Date.now()
            }));
        });
    }

    _sendRawRequest(type, payload) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        this.ws.send(JSON.stringify({
            id: Math.random().toString(36).substring(2) + Date.now().toString(36),
            direction: "request",
            type: type,
            payload: payload || {},
            timestamp: Date.now()
        }));
    }

    _sendBridgePong() {
        this._sendRawRequest("bridge:pong", { ts: Date.now() });
    }

    _startHeartbeat() {
        this._stopHeartbeat();
        if (!this.enableClientHeartbeat) return;
        var self = this;
        this.heartbeatTimer = setInterval(function () {
            if (!self.connected) return;
            self._sendBridgePong();
        }, this.clientHeartbeatIntervalMs);
    }

    _stopHeartbeat() {
        if (this.heartbeatTimer) {
            clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }

    _rejectPending(reason) {
        this.pendingRequests.forEach(function (pending, id) {
            try {
                pending.reject(new Error(reason || "Disconnected"));
            } catch (_) {}
        });
        this.pendingRequests.clear();
    }

    getPlugins() { return this.request("plugin:list"); }
    enablePlugin(id) { return this.request("plugin:enable", { id: id }); }
    disablePlugin(id) { return this.request("plugin:disable", { id: id }); }
    getPlugin(id) { return this.request("plugin:get", { id: id }); }

    on(event, handler) {
        if (!this.eventHandlers.has(event)) {
            this.eventHandlers.set(event, new Set());
        }
        this.eventHandlers.get(event).add(handler);
    }

    off(event, handler) {
        if (this.eventHandlers.has(event)) {
            this.eventHandlers.get(event).delete(handler);
        }
    }

    emit(event, data) {
        if (this.eventHandlers.has(event)) {
            this.eventHandlers.get(event).forEach(function (handler) {
                try { handler(data); } catch (e) { console.error(e); }
            });
        }
    }

    attemptReconnect() {
        if (this.maxReconnectAttempts > 0 && this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error("[TRIONBridge] Max reconnect attempts reached");
            this.emit("telemetry", { type: "reconnect_giveup", attempts: this.reconnectAttempts, ts: Date.now() });
            return;
        }
        this.reconnectAttempts++;
        var raw = Math.min(this.baseReconnectDelayMs * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelayMs);
        var jitter = Math.floor(Math.random() * Math.max(100, Math.floor(raw * 0.2)));
        var delay = raw + jitter;
        console.log("[TRIONBridge] Reconnecting in " + delay + "ms");
        this.emit("telemetry", { type: "reconnect_attempt", attempts: this.reconnectAttempts, delay_ms: delay, ts: Date.now() });
        var self = this;
        setTimeout(function () { self.connect(); }, delay);
    }
}

window.TRIONBridge = new TRIONBridge();

document.addEventListener("DOMContentLoaded", function () {
    window.TRIONBridge.connect().catch(function (err) {
        console.warn("[TRIONBridge] Initial connection failed:", err.message);
    });
});

console.log("[TRIONBridge] Client loaded (v4 - panel events fixed)");
