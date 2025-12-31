// api.js - API Communication mit Live Thinking + Container Support

import { log } from "./debug.js";

// Auto-detect API base URL
// - In Docker: nginx proxies /api/* to lobechat-adapter → use relative URL
// - Direct access: use full URL with port 8100
function detectApiBase() {
    // If we're on port 3000 (nginx/docker), use relative URLs
    if (window.location.port === '3000' || window.location.port === '80' || window.location.port === '') {
        return '';  // Relative - nginx will proxy
    }
    // Otherwise use the same host but port 8100
    return `http://${window.location.hostname}:8100`;
}

let API_BASE = detectApiBase();
log("debug", `Auto-detected API base: ${API_BASE || '(relative)'}`);

export function setApiBase(url) {
    API_BASE = url;
    log("debug", `API base set to: ${url}`);
}

export function getApiBase() {
    return API_BASE;
}

// ═══════════════════════════════════════════════════════════
// MODEL LIST
// ═══════════════════════════════════════════════════════════
export async function getModels() {
    try {
        log("debug", `Fetching models from ${API_BASE}/api/tags`);
        const res = await fetch(`${API_BASE}/api/tags`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        
        const data = await res.json();
        const models = data.models?.map(m => m.name) || [];
        log("debug", `Found ${models.length} models`, models);
        return models;
    } catch (error) {
        log("error", `getModels error: ${error.message}`);
        return [];
    }
}

// ═══════════════════════════════════════════════════════════
// HEALTH CHECK
// ═══════════════════════════════════════════════════════════
export async function checkHealth() {
    try {
        const res = await fetch(`${API_BASE}/api/tags`, { 
            method: 'GET',
            signal: AbortSignal.timeout(5000)
        });
        return res.ok;
    } catch {
        return false;
    }
}

// ═══════════════════════════════════════════════════════════
// DIRECT CODE EXECUTION (für Run-Button im Code-Block)
// ═══════════════════════════════════════════════════════════
export async function executeCode(code, language = "python", container = "code-sandbox") {
    log("info", `Executing code in ${container}`, { language, codeLength: code.length });
    
    try {
        const res = await fetch(`${API_BASE}/api/execute`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                code: code,
                language: language,
                container: container
            })
        });
        
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        
        const result = await res.json();
        log("info", `Execution complete`, result);
        return result;
        
    } catch (error) {
        log("error", `Execute error: ${error.message}`);
        return { error: error.message };
    }
}

// ═══════════════════════════════════════════════════════════
// CHAT - STREAMING MIT LIVE THINKING + CONTAINER
// ═══════════════════════════════════════════════════════════
export async function* streamChat(model, messages, conversationId = "webui-default") {
    log("info", `Sending chat request`, {
        model,
        messageCount: messages.length,
        conversationId
    });
    
    // Log the actual messages being sent
    log("debug", "Messages being sent to backend:", messages.map(m => ({
        role: m.role,
        content: m.content.substring(0, 100) + (m.content.length > 100 ? "..." : "")
    })));
    
    const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            model: model,
            messages: messages,
            stream: true,
            conversation_id: conversationId
        })
    });

    if (!res.ok) {
        log("error", `Chat request failed: HTTP ${res.status}`);
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }

    log("debug", "Stream started, reading chunks...");
    
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let chunkCount = 0;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (!line.trim()) continue;
            
            try {
                const data = JSON.parse(line);
                chunkCount++;
                
                // Live Thinking Stream
                if (data.thinking_stream !== undefined) {
                    log("debug", `Thinking chunk: ${data.thinking_stream.substring(0, 50)}...`);
                    yield {
                        type: "thinking_stream",
                        chunk: data.thinking_stream
                    };
                    continue;
                }
                
                // Thinking Done (mit Plan)
                if (data.thinking) {
                    log("info", "Thinking complete", data.thinking);
                    yield {
                        type: "thinking_done",
                        thinking: data.thinking,
                        memory_used: data.memory_used || false
                    };
                    continue;
                }
                
                // Container Start
                if (data.container_start) {
                    console.log("[API] container_start parsed:", data.container_start);
                    log("info", `Container starting: ${data.container_start.container}`, data.container_start);
                    yield {
                        type: "container_start",
                        container: data.container_start.container,
                        task: data.container_start.task
                    };
                    continue;
                }
                
                // Container Done
                if (data.container_done) {
                    console.log("[API] container_done parsed:", data.container_done);
                    log("info", "Container execution complete", data.container_done);
                    yield {
                        type: "container_done",
                        result: data.container_done.result
                    };
                    continue;
                }
                
                // Content-Chunk (mit Model-Info)
                if (data.message?.content) {
                    yield {
                        type: "content",
                        content: data.message.content,
                        done: data.done || false,
                        model: data.model || null,
                        code_model_used: data.code_model_used || false
                    };
                }
                
                // Memory indicator
                if (data.memory_used) {
                    log("info", "Memory was used for this response");
                    yield { type: "memory", used: true };
                }
                
                // Done (mit erweiterten Infos)
                if (data.done) {
                    log("info", `Stream complete, received ${chunkCount} chunks`);
                    yield { 
                        type: "done",
                        model: data.model || null,
                        code_model_used: data.code_model_used || false,
                        container_used: data.container_used || false
                    };
                }
                
            } catch (e) {
                // Nicht-JSON Zeile ignorieren
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════
// USER-SANDBOX CONTROL
// ═══════════════════════════════════════════════════════════

/**
 * Startet die User-Sandbox.
 * @param {string} containerName - Container-Name (default: "code-sandbox")
 * @param {string} preferredModel - Bevorzugtes Code-Model (optional)
 * @returns {Promise<object>} - Sandbox-Info mit session_id, ttyd_port etc.
 */
export async function startUserSandbox(containerName = "code-sandbox", preferredModel = null) {
    log("info", `Starting User-Sandbox: ${containerName}`);
    
    try {
        const res = await fetch(`${API_BASE}/api/sandbox/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                container_name: containerName,
                preferred_model: preferredModel
            })
        });
        
        const result = await res.json();
        
        if (res.ok) {
            log("info", "User-Sandbox started", result);
        } else {
            log("warn", "User-Sandbox start failed", result);
        }
        
        return { ...result, ok: res.ok, status: res.status };
        
    } catch (error) {
        log("error", `Sandbox start error: ${error.message}`);
        return { error: error.message, ok: false };
    }
}

/**
 * Stoppt die User-Sandbox.
 * @param {boolean} force - Force kill wenn nötig
 * @returns {Promise<object>} - Stop-Result
 */
export async function stopUserSandbox(force = false) {
    log("info", `Stopping User-Sandbox (force=${force})`);
    
    try {
        const res = await fetch(`${API_BASE}/api/sandbox/stop`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force })
        });
        
        const result = await res.json();
        
        if (res.ok) {
            log("info", "User-Sandbox stopped", result);
        } else {
            log("warn", "User-Sandbox stop failed", result);
        }
        
        return { ...result, ok: res.ok, status: res.status };
        
    } catch (error) {
        log("error", `Sandbox stop error: ${error.message}`);
        return { error: error.message, ok: false };
    }
}

/**
 * Holt Status der User-Sandbox.
 * @returns {Promise<object>} - Status mit active, ttyd_port, uptime etc.
 */
export async function getUserSandboxStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/sandbox/status`);
        const result = await res.json();
        
        return { ...result, ok: res.ok };
        
    } catch (error) {
        log("error", `Sandbox status error: ${error.message}`);
        return { error: error.message, ok: false, active: false };
    }
}
