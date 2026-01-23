# Jarvis Admin UI - Architecture Documentation

**Last Updated:** 2026-01-19  
**Version:** 2.0 (Post-Cleanup)

---

## 🏗️ System Overview

Jarvis Admin UI consists of **two main containers** that work together to provide the chat interface and backend processing:

```
┌─────────────────────────────────────────────────────────────┐
│                         USER BROWSER                         │
│                     http://192.168.0.226:8400                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    JARVIS-WEBUI (Nginx)                      │
│                         Port 8400                             │
│                                                               │
│  Serves:                                                      │
│  • index.html                                                 │
│  • static/js/*.js (chat.js, api.js, trion-panel.js, etc.)   │
│  • static/css/*.css                                           │
│                                                               │
│  NO VOLUME MOUNTS - Files copied at build time               │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ /api/chat (SSE Stream)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 JARVIS-ADMIN-API (FastAPI)                   │
│                         Port 8200                             │
│                                                               │
│  Architecture:                                                │
│  1. ThinkingLayer (analyze user intent)                      │
│  2. ControlLayer (validation, sequential thinking)           │
│  3. OutputLayer (LLM response generation)                    │
│                                                               │
│  VOLUME MOUNTED - Auto-reload on file changes                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Ollama (LLMs)   │
                    │  Port 11434      │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  MCP Servers     │
                    │  (Memory, etc.)  │
                    └──────────────────┘
```

---

## 📁 Container Details

### 🎨 **JARVIS-WEBUI** (Frontend Container)

**Image:** `jarvis-jarvis-webui`  
**Port:** `8400` → `80` (nginx)  
**Technology:** Nginx static file server  

#### File Structure (Inside Container):
```
/usr/share/nginx/html/
├── index.html                     # Main HTML entry point
├── 50x.html                       # Error page
└── static/
    ├── css/
    │   ├── styles.css
    │   ├── dark-theme.css
    │   └── trion-panel.css        # 🆕 TRION Panel styling
    ├── js/
    │   ├── chat.js                # Main chat logic
    │   ├── api.js                 # API communication layer
    │   ├── trion-panel.js         # 🆕 TRION Panel core
    │   ├── sequential-plugin.js   # 🆕 Sequential Thinking plugin
    │   ├── debug.js
    │   ├── markdown.js
    │   └── utils.js
    └── img/
        └── *.png
```

#### Source Location (Host):
```
/DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/
├── index.html
└── static/
    ├── css/
    └── js/
```

#### ⚠️ CRITICAL: No Volume Mounts!

**This container does NOT have volume mounts!**  
Files are copied into the container at **build time** or via `docker cp`.

**Deployment Process:**
```bash
# Step 1: Edit source file
vim /DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/static/js/chat.js

# Step 2: Copy into container
sudo docker cp /DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/static/js/chat.js \
    jarvis-webui:/usr/share/nginx/html/static/js/chat.js

# Step 3: Browser hard refresh
# Ctrl + Shift + F5 (or clear browser cache)
```

**File Sizes (Reference):**
```
index.html             41KB
chat.js                26KB
api.js                 15KB
trion-panel.js         23KB
sequential-plugin.js   7.1KB
trion-panel.css        11KB
```

---

### 🔧 **JARVIS-ADMIN-API** (Backend Container)

**Image:** `jarvis-jarvis-admin-api`  
**Port:** `8200`  
**Technology:** FastAPI (Python + Uvicorn)  

#### Volume Mounts (Auto-reload enabled!):
```
Host                                    → Container
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/DATA/.../Jarvis/core/                  → /app/core/
/DATA/.../Jarvis/mcp/                   → /app/mcp/
/DATA/.../Jarvis/adapters/admin-api/    → /app/adapters/admin-api/
/DATA/.../Jarvis/personas/              → /app/personas/
/DATA/.../Jarvis/intelligence_modules/  → /app/intelligence_modules/
/DATA/.../Jarvis/mcp_registry.py        → /app/mcp_registry.py
```

#### ✅ Auto-Reload Enabled!

**Changes to these files are immediately active:**
- `core/bridge.py`
- `core/layers/thinking.py`
- `core/layers/control.py`
- `core/layers/output.py`
- `adapters/admin-api/main.py`

**Only restart needed for:**
- New Python dependencies
- Environment variable changes
- Config file changes

**Restart Command:**
```bash
sudo docker restart jarvis-admin-api
```

#### Architecture Layers:

```
┌─────────────────────────────────────────┐
│         /api/chat Endpoint              │
│         (adapters/admin-api/main.py)    │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│           CoreBridge                     │
│         (core/bridge.py)                 │
│                                          │
│  Routes request through 3 layers:        │
└─────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ LAYER 1  │  │ LAYER 2  │  │ LAYER 3  │
│ Thinking │  │ Control  │  │ Output   │
└──────────┘  └──────────┘  └──────────┘
     │             │             │
     ▼             ▼             ▼
  Analyze      Validate      Generate
  Intent       Safety        Response
              Sequential
              Thinking
```

---

## 🔄 Data Flow: User Question → Response

### End-to-End Request Flow:

```
1. USER TYPES QUESTION
   ↓
2. chat.js captures input
   ↓
3. chat.js calls sendMessage()
   ↓
4. api.js sends POST to /api/chat (SSE stream)
   ↓
5. ADMIN-API receives request
   ↓
6. main.py routes to CoreBridge.process_stream()
   ↓
7. LAYER 1: ThinkingLayer.analyze_stream()
   • Analyzes user intent
   • Determines if Sequential Thinking needed
   • Emits: thinking_stream, thinking_done
   ↓
8. LAYER 2: ControlLayer (conditional)
   • If needs_sequential_thinking = true:
     └→ _check_sequential_thinking_stream()
        • Calls MCP Sequential Server
        • Emits: sequential_start, sequential_step, sequential_done
   • Validates response safety
   ↓
9. LAYER 3: OutputLayer.stream()
   • Generates LLM response via Ollama
   • Streams content chunks
   ↓
10. main.py converts to SSE NDJSON format
   ↓
11. api.js parses SSE stream
   • thinking_stream → console.log
   • sequential_start → Event Dispatcher
   • sequential_step → Event Dispatcher
   • content → renderMessage()
   ↓
12. Event Dispatcher (chat.js)
   • Dispatches CustomEvent('sse-event')
   ↓
13. sequential-plugin.js listens
   • sequential_start → Creates TRION Panel tab
   • sequential_step → Updates tab content
   • sequential_done → Marks complete
   ↓
14. trion-panel.js renders UI
   • Opens panel (half-width)
   • Displays tab with content
   • Shows download button
```

---

## 🎯 Event System Architecture

### Event Types:

```javascript
// Thinking Events
{
  type: "thinking_stream",
  chunk: "analyzing intent..."
}
{
  type: "thinking_done",
  plan: {
    intent: "...",
    needs_sequential_thinking: true,
    complexity: 6
  }
}

// Sequential Events (NEW SYSTEM)
{
  type: "sequential_start",
  task_id: "seq-abc12345",
  complexity: 6,
  cim_modes: ["temporal", "strategic"],
  reasoning_type: "causal"
}
{
  type: "sequential_step",
  task_id: "seq-abc12345",
  step_number: 1,
  label: "Step 1: Analysis",
  thought: "First, we analyze..."
}
{
  type: "sequential_done",
  task_id: "seq-abc12345",
  steps: [{...}, {...}],
  summary: "Analysis complete"
}

// Content Events
{
  type: "content",
  chunk: "Response text..."
}
```

### Event Dispatcher (chat.js):

```javascript
// Known event types
const pluginEvents = [
  'sequential_start', 'sequential_step', 'sequential_done',
  'mcp_call', 'mcp_result',
  'cim_store', 'memory_update',
  'panel_create_tab', 'panel_update', 'panel_close_tab'
];

// Dispatch to plugins
if (pluginEvents.includes(chunk.type)) {
  window.dispatchEvent(new CustomEvent('sse-event', {
    detail: chunk
  }));
}
```

### Plugin System (sequential-plugin.js):

```javascript
class SequentialThinkingPlugin {
  init() {
    // Listen for events
    window.addEventListener('sse-event', (e) => {
      switch(e.detail.type) {
        case 'sequential_start':
          this.handleStart(e.detail);
          break;
        case 'sequential_step':
          this.handleStep(e.detail);
          break;
        case 'sequential_done':
          this.handleDone(e.detail);
          break;
      }
    });
  }
  
  handleStart(event) {
    // Create TRION Panel tab
    this.panel.createTab(
      event.task_id,
      `Sequential (${event.complexity} steps)`,
      'markdown',
      initialContent
    );
  }
}
```

---

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

## 📊 File Manifest

### Active Files (Post-Cleanup):

```
✅ KEEP - New System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Frontend:
  /adapters/Jarvis/static/js/sequential-plugin.js
  /adapters/Jarvis/static/js/trion-panel.js
  /adapters/Jarvis/static/css/trion-panel.css

Backend:
  /core/layers/control.py → _check_sequential_thinking_stream()
  /core/sequential_registry.py
  /core/sequential_cache.py

MCP:
  /mcp-servers/sequential-thinking/

❌ REMOVED - Old System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Container:
  sequential-thinking (Port 8085) - STOPPED & DELETED

Frontend:
  /adapters/Jarvis/static/js/sequential.js
  /adapters/Jarvis/static/js/sequential-sidebar.js
  /adapters/Jarvis/static/css/sequential-ui.css

Backend:
  /adapters/Jarvis/main.py → /chat/sequential (DISABLED)
  /adapters/Jarvis/main.py → /sequential/status (DISABLED)
  /adapters/admin-api/sequential_routes.py (DELETED)

Directories:
  /Sequential Thinking/ (DELETED)
  /modules/sequential_thinking (DELETED)
```

---

## 🔐 Security Notes

### CORS Configuration:

```python
# main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### SSE Stream Security:

- No authentication on `/api/chat` (internal network only)
- Events are plain JSON (no encryption)
- Rate limiting: None (add if needed)

---

## 📈 Performance Considerations

### WEBUI (Nginx):

- Static file serving: Very fast
- No compute overhead
- Bottleneck: Network transfer

### ADMIN-API (FastAPI):

- SSE Streaming: Low latency
- ThinkingLayer: ~200-500ms
- Sequential Thinking: ~2-5 seconds (depends on MCP)
- LLM Generation: ~1-10 seconds (depends on model)

### Browser:

- JavaScript parsing: Minimal
- Event dispatching: < 1ms
- Panel rendering: ~10-50ms

---

## 🎯 Next Steps / Roadmap

### Phase 3: Enhanced Renderers
- [ ] Add marked.js for full Markdown support
- [ ] Syntax highlighting (highlight.js)
- [ ] Mermaid diagram support

### Phase 4: Live Step Streaming
- [ ] Real-time step updates during execution
- [ ] Progress indicators
- [ ] Cancellation support

### Phase 5: MCP Plugin System
- [ ] MCP Debug Plugin
- [ ] Memory Graph Visualization
- [ ] Extension API documentation

### Phase 6: Polish
- [ ] Download all tabs
- [ ] More keyboard shortcuts
- [ ] Mobile optimization
- [ ] Tab persistence (localStorage)

---

## 📚 Additional Resources

**Documentation:**
- Main README: `/documentation/README.md`
- TRION Panel: `/documentation/TRION_PANEL_README.md`
- Sequential Thinking: `/documentation/features/sequential-ui-roadmap.md`

**Tests:**
- Sequential UI Test: `/tests/test_sequential_ui.js`
- TRION Panel Test: Browser console → `window.TRIONPanel`

**Backups:**
- All `.backup-*` files contain previous working versions
- Restore if needed: `cp file.backup-name file`

---

**Last Updated:** 2026-01-19 21:00 UTC  
**Maintainer:** Claude + User  
**Status:** Active Development - Phase 2.5 Complete
