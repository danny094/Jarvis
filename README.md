<img width="1866" height="913" alt="Bildschirmfoto 2026-01-27 um 02 50 07" src="https://github.com/user-attachments/assets/aa1cd753-9d8a-4257-91b7-c0d80e51f77e" />


```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACES                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │ LobeChat UI  │    │ Jarvis WebUI │    │   API/CLI    │                   │
│  │   :3210      │    │    :8400     │    │    :8200     │                   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                   │
│         │                   │                   │                            │
│         └───────────────────┼───────────────────┘                            │
│                             ▼                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                           ADAPTERS                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    lobechat-adapter (:8100)                            │ │
│  │                 Übersetzt LobeChat → Jarvis Format                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                             │                                                │
│                             ▼                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    jarvis-admin-api (:8200)                            │ │
│  │              Main Entry Point, SSE Streaming, Routing                  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                             │                                                │
│                             ▼                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                         CORE BRIDGE                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      core/bridge.py                                    │ │
│  │                                                                        │ │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐               │ │
│  │  │   LAYER 1    │ → │   LAYER 2    │ → │   LAYER 3    │               │ │
│  │  │   Thinking   │   │   Control    │   │    Output    │               │ │
│  │  │  (DeepSeek)  │   │  (Qwen/CIM)  │   │   (Llama)    │               │ │
│  │  └──────────────┘   └──────────────┘   └──────────────┘               │ │
│  │         │                  │                   │                       │ │
│  │         │                  │                   ▼                       │ │
│  │         │                  │           SSE Stream → User               │ │
│  │         │                  │                                           │ │
│  │         │                  ▼                                           │ │
│  │         │     ┌─────────────────────┐                                  │ │
│  │         │     │ Sequential Thinking │                                  │ │
│  │         │     │ (wenn complexity>5) │                                  │ │
│  │         │     └──────────┬──────────┘                                  │ │
│  │         │                │                                             │ │
│  │         │                ▼                                             │ │
│  └─────────┼────────────────────────────────────────────────────────────┘ │
│            │                │                                              │
├────────────┼────────────────┼──────────────────────────────────────────────┤
│            │                │          MCP SERVERS                         │
├────────────┼────────────────┼──────────────────────────────────────────────┤
│            │                │                                              │
│            ▼                ▼                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                   │
│  │  sql-memory  │   │  sequential  │   │  cim-server  │                   │
│  │    (:8082)   │   │   (:8085)    │   │   (:8086)    │                   │
│  │              │   │              │   │              │                   │
│  │ 23 Tools:    │   │ 3 Tools:     │   │ 6 Tools:     │                   │
│  │ - memory_*   │   │ - think      │   │ - analyze    │                   │
│  │ - search_*   │   │ - think_sim  │   │ - validate_* │                   │
│  │ - fact_*     │   │ - health     │   │ - store_*    │                   │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                   │
│         │                  │                   │                           │
│         │                  └───────────────────┤                           │
│         │                                      │                           │
│         ▼                                      ▼                           │
│  ┌──────────────┐                    ┌────────────────────────┐           │
│  │  PostgreSQL  │                    │  Intelligence Modules  │           │
│  │   (Memory)   │                    │  (Frank's RAG System)  │           │
│  └──────────────┘                    └────────────────────────┘           │
│                                                                            │
├────────────────────────────────────────────────────────────────────────────┤
│                              OLLAMA (:11434)                               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                   │
│  │  deepseek-r1 │   │   qwen2.5    │   │  llama3.2    │                   │
│  │   (8b/14b)   │   │    (14b)     │   │    (3b)      │                   │
│  │   Thinking   │   │   Control    │   │    Output    │                   │
│  └──────────────┘   └──────────────┘   └──────────────┘                   │
└────────────────────────────────────────────────────────────────────────────┘

```


### Installation
```
git clone https://github.com/danny094/Jarvis.git
cd Jarvis
docker compose build
docker compose up -d
```
open `localhost:8400`

___

### Website overdrive

Apps menu
<img width="1866" height="958" alt="Bildschirmfoto 2026-01-27 um 03 27 52" src="https://github.com/user-attachments/assets/a7e7e11f-961c-4a5c-8ec3-fd5a1e0b0c80" />

settings
<img width="1866" height="913" alt="Bildschirmfoto 2026-01-27 um 03 24 39" src="https://github.com/user-attachments/assets/ace414ad-1bc0-49a5-96d3-cb21f991a3fa" />

MCP installer
<img width="1915" height="961" alt="Bildschirmfoto 2026-01-26 um 16 47 50" src="https://github.com/user-attachments/assets/205170ee-927b-4eca-be3f-695838767d11" />




### Ports


| Container | Port | Funktion | Status |
|-----------|------|----------|--------|
| `ollama` | 11434 | LLM Runtime (DeepSeek, Qwen, Llama) | ✅ Running |
| `jarvis-admin-api` | 8200 | Main API, Bridge, SSE Streaming | ✅ Running |
| `jarvis-webui` | 8400 | Custom WebUI mit TRION Panel | ⚠️ Unhealthy |
| `lobechat-adapter` | 8100 | LobeChat → Jarvis Adapter | ✅ Running |
| `cim-server` | 8086 | Causal Intelligence MCP | ✅ Running |
| `sequential-thinking` | 8085 | Sequential Reasoning MCP | ✅ Running |
| `mcp-sql-memory` | 8082 | Memory System MCP | ✅ Running |
| `validator-service` | 8300 | Claim Validator | ✅ Running |

## 🆕 TRION Panel System

**Location:** `/adapters/Jarvis/static/js/trion-panel.js`

### Features:

- **3-State Panel:** Closed, Half-width, Full-width
- **Tab Management:** Create, update, close, switch tabs
- **Renderers:** Markdown, JSON, HTML
- **Download:** Export tab content to files
- **Keyboard Shortcuts:** Toggle panel, switch tabs

### Usage:

```javascript
// Create tab
window.TRIONPanel.createTab(
  'task-123',              // Tab ID
  'Sequential Thinking',   // Tab title
  'markdown',              // Content type
  initialContent           // Initial content
);

// Update content
window.TRIONPanel.updateContent(
  'task-123',
  '\n## New Section\nContent...',
  true  // append = true
);

// Download tab
window.TRIONPanel.downloadTab('task-123');
```

---

## 🔧 Deployment Workflows

### Frontend Changes (WEBUI):

```bash
# 1. Edit source file
vim /DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/static/js/chat.js

# 2. Deploy to container
sudo docker cp \
  /DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/static/js/chat.js \
  jarvis-webui:/usr/share/nginx/html/static/js/chat.js

# 3. Verify deployment
sudo docker exec jarvis-webui \
  ls -lh /usr/share/nginx/html/static/js/chat.js

# 4. Browser refresh (HARD!)
# Ctrl + Shift + F5
# OR: DevTools → Application → Clear Storage → Clear site data
```

### Backend Changes (ADMIN-API):

```bash
# 1. Edit source file (auto-reflects in container)
vim /DATA/AppData/MCP/Jarvis/Jarvis/core/bridge.py

# 2. Syntax check (optional but recommended)
sudo python3 -m py_compile /DATA/AppData/MCP/Jarvis/Jarvis/core/bridge.py

# 3. Restart container (only if needed)
sudo docker restart jarvis-admin-api

# 4. Check logs
sudo docker logs --tail 50 jarvis-admin-api
```

---

## 🐛 Troubleshooting

### Issue: "Changes not reflecting in browser"

**Cause:** Browser cache or file not deployed to container

**Fix:**
```bash
# 1. Verify file in container
sudo docker exec jarvis-webui \
  cat /usr/share/nginx/html/static/js/chat.js | head -20

# 2. Check timestamps
sudo docker exec jarvis-webui \
  ls -lh /usr/share/nginx/html/static/js/chat.js

# 3. Clear browser cache completely
# DevTools → Application → Clear Storage → Clear site data

# 4. Hard refresh
# Ctrl + Shift + F5
```

### Issue: "Sequential events not appearing"

**Cause:** Old Sequential system still active or Event Dispatcher not working

**Debug:**
```javascript
// 1. Check console for events
[Chat] Dispatching event: sequential_start

// 2. Check if plugin loaded
window.sequentialPlugin  // Should be object

// 3. Check panel exists
window.TRIONPanel  // Should be object

// 4. Backend logs
sudo docker logs jarvis-admin-api | grep Sequential
```

### Issue: "task_id is undefined"

**Cause:** Event format mismatch between backend and frontend

**Debug:**
```bash
# 1. Check backend emits task_id
sudo docker logs jarvis-admin-api | grep task_id

# 2. Check frontend receives it
# Console: [API] Flat event: sequential_start {task_id: "..."}

# 3. Verify api.js has flat event handler
grep "Flat event" /DATA/.../static/js/api.js
```

---



