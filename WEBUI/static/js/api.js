// api.js - API Communication mit Live Thinking Support

import { log } from "./debug.js";

let API_BASE = "http://192.168.0.226:8100";

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
// CHAT - STREAMING MIT LIVE THINKING
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
                
                // Content-Chunk
                if (data.message?.content) {
                    yield {
                        type: "content",
                        content: data.message.content,
                        done: data.done || false
                    };
                }
                
                // Memory indicator
                if (data.memory_used) {
                    log("info", "Memory was used for this response");
                    yield { type: "memory", used: true };
                }
                
                // Done
                if (data.done) {
                    log("info", `Stream complete, received ${chunkCount} chunks`);
                    yield { type: "done" };
                }
                
            } catch (e) {
                // Nicht-JSON Zeile ignorieren
            }
        }
    }
}
