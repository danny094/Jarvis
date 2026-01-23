# 🏗️ JARVIS TRION - System Architecture (v5.0)

**Stand:** 2026-01-21  
**Status:** Production mit bekannten Einschränkungen  
**Autor:** Danny + Claude

---

## 📋 Inhaltsverzeichnis

1. [Executive Summary](#1-executive-summary)
2. [Aktuelle Systemarchitektur](#2-aktuelle-systemarchitektur)
3. [Container & Services](#3-container--services)
4. [Core Layer System](#4-core-layer-system)
5. [Intelligence Modules (Frank's CIM)](#5-intelligence-modules-franks-cim)
6. [MCP Server Architektur](#6-mcp-server-architektur)
7. [Frontend (WebUI)](#7-frontend-webui)
8. [Datenfluss](#8-datenfluss)
9. [Was funktioniert ✅](#9-was-funktioniert-)
10. [Was fehlt ❌](#10-was-fehlt-)
11. [Nächste Schritte](#11-nächste-schritte)

---

## 1. Executive Summary

JARVIS TRION ist ein Multi-Layer AI-Reasoning-System mit:
- **3-Layer Core**: Thinking → Control → Output
- **Frank's CIM**: Causal Intelligence Module für Bias-Erkennung
- **Sequential Thinking**: Schrittweises Reasoning mit CIM-Validierung
- **TRION Panel**: Observability-Sidepanel für Transparenz

### Aktueller Stand (Kurzfassung)

| Komponente | Status | Anmerkung |
|------------|--------|-----------|
| Core Layers | ✅ 90% | Output-Layer braucht Sequential-Integration |
| CIM Server | ✅ 100% | Vollständig, RAG funktioniert |
| Sequential v3.0 | ✅ 80% | 1-Call Architektur, aber kein Streaming |
| TRION Panel | ⚠️ 70% | Panel öffnet, Steps kommen zu spät |
| Inline Thinking | ❌ 0% | Noch nicht implementiert |
| Finale Antwort | ❌ Bug | Wird nicht im Chat angezeigt |

---

## 2. Aktuelle Systemarchitektur

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

---

## 3. Container & Services

### Aktive Container

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

### Docker Compose Abhängigkeiten

```yaml
jarvis-admin-api:
  depends_on:
    - ollama
    - mcp-sql-memory
    - cim-server
    - sequential-thinking

jarvis-webui:
  depends_on:
    - jarvis-admin-api
```

---

## 4. Core Layer System

### Dateien

```
/DATA/AppData/MCP/Jarvis/Jarvis/core/
├── bridge.py              # Hauptorchestrator (27KB)
├── models.py              # Request/Response Models
├── persona.py             # Persona System
├── sequential_cache.py    # Cache für Sequential
├── sequential_registry.py # Task Registry
└── layers/
    ├── thinking.py        # Layer 1: Intent Analysis (13KB)
    ├── thinking_extended.py # Extended Thinking
    ├── control.py         # Layer 2: Verification + Sequential (15KB)
    └── output.py          # Layer 3: Response Generation (16KB)
```

### Layer 1: ThinkingLayer

**Datei:** `core/layers/thinking.py`  
**Model:** DeepSeek-R1 (8b oder 14b)  
**Aufgabe:** Intent-Analyse, Komplexitätsbewertung

**Output:**
```python
{
    "intent": "Kausalanalyse von X und Y",
    "needs_memory": False,
    "hallucination_risk": "medium",
    "needs_sequential_thinking": True,  # ← Trigger!
    "complexity": 7,
    "cim_modes": ["heavy", "temporal"],
    "reasoning_type": "causal"
}
```

### Layer 2: ControlLayer

**Datei:** `core/layers/control.py`  
**Model:** Qwen 2.5 (14b) + LightCIM  
**Aufgabe:** Verifikation, Sequential Thinking Trigger

**Wichtige Methode:**
```python
async def _check_sequential_thinking_stream(user_text, thinking_plan):
    """Ruft Sequential Thinking MCP auf und streamt Events"""
    # Yielded: sequential_start, sequential_step, sequential_done
```

### Layer 3: OutputLayer

**Datei:** `core/layers/output.py`  
**Model:** Llama 3.2 (3b)  
**Aufgabe:** Finale Antwort generieren

**AKTUELLER BUG:** 
- `_sequential_result` wird in `verified_plan` übergeben
- OutputLayer hat Code um es zu nutzen (Zeile 77-110)
- Aber Antwort erscheint nicht im Chat!

---

## 5. Intelligence Modules (Frank's CIM)

### Verzeichnisstruktur

```
/DATA/AppData/MCP/Jarvis/Jarvis/intelligence_modules/
├── cim.py                    # CLI Interface
├── local_graph_builders/     # 5 GraphBuilder Klassen
│   ├── base_builder.py
│   ├── graph_selector.py     # Wählt Builder automatisch
│   ├── light_graph_builder.py
│   ├── heavy_graph_builder.py
│   ├── strategic_graph_builder.py
│   ├── temporal_graph_builder.py
│   └── simulation_graph_builder.py
├── code_tools/
│   ├── causal_controller.py
│   ├── causal_math_tools.py
│   ├── context_builder.py
│   └── prompt_engineer.py    # Generiert REASONING ROADMAP
├── knowledge_rag/
│   ├── cognitive_priors_v2.csv    # 40 Cognitive Priors
│   └── domain_graphs.csv          # 5 Domain DAGs
├── procedural_rag/
│   ├── anti_patterns.csv              # 25 Bias-Muster
│   ├── causal_reasoning_procedures_v2.csv  # 20 Procedures
│   └── discovery_procedures.csv       # 10 Discovery Algos
├── executable_rag/
│   ├── ability_injectors_v2.csv   # 29 Behavioral Controls
│   └── causal_math_registry.csv   # 20 Math Tools
└── docs_frank/                    # Dokumentation
```

### RAG Layer Zusammenfassung

| Layer | Datei | Einträge | Zweck |
|-------|-------|----------|-------|
| Knowledge | cognitive_priors_v2.csv | 40 | First Principles |
| Knowledge | domain_graphs.csv | 5 | Domain-spezifische DAGs |
| Procedural | anti_patterns.csv | 25 | Fallacy Detection |
| Procedural | causal_reasoning_procedures_v2.csv | 20 | Step-by-Step Procedures |
| Procedural | discovery_procedures.csv | 10 | Causal Discovery |
| Executable | ability_injectors_v2.csv | 29 | LLM Behavior Control |
| Executable | causal_math_registry.csv | 20 | Deterministic Math |

### CIM Server Tools

| Tool | Funktion |
|------|----------|
| `analyze` | Baut Causal Graph, generiert REASONING ROADMAP |
| `validate_before` | Pre-Execution Bias Check |
| `validate_after` | Post-Execution Validation |
| `store_temporal` | Speichert in Temporal Graph |
| `retrieve` | Holt aus Temporal Storage |
| `health` | Health Check |

---

## 6. MCP Server Architektur

### Sequential Thinking v3.0

**Datei:** `mcp-servers/sequential-thinking/sequential_thinking.py`  
**Port:** 8085  
**Version:** 3.0.0 (Single-Call Architecture)

**Architektur:**
```python
async def think(message, steps, mode, use_cim):
    # 1. CIM.analyze() → Holt REASONING ROADMAP aus RAG
    analysis = await cim.analyze(message, mode)
    causal_prompt = analysis.get("causal_prompt", "")
    
    # 2. SINGLE Ollama Call → Folgt dem ROADMAP
    full_response = await call_ollama(prompt, causal_prompt)
    
    # 3. Parse Response → Strukturierte Steps
    parsed_steps = parse_steps(full_response)
    
    # 4. Optional: Validate Steps
    for step in parsed_steps:
        validation = await cim.validate_after(...)
    
    return {"success": True, "steps": parsed_steps, "full_response": full_response}
```

**Vorher (v2.1 - FALSCH):**
- 8 Ollama Calls (pro Step)
- 16 CIM Calls
- ~8 Minuten Laufzeit

**Nachher (v3.0 - RICHTIG):**
- 1 Ollama Call
- 1-2 CIM Calls
- ~1 Minute Laufzeit

### CIM Server

**Datei:** `mcp-servers/cim-server/cim_server.py`  
**Port:** 8086

**Flow:**
```
Query → GraphSelector.select_builder()
      → HeavyGraphBuilder.build_graph()
         ├── retrieve_priors()
         ├── retrieve_domain_graphs()
         ├── retrieve_procedures()  # ← Holt PROC001 mit Steps!
         └── retrieve_anti_patterns()
      → CausalPromptEngineer.engineer_prompt()
      → Return: causal_prompt mit REASONING ROADMAP
```

### SQL Memory MCP

**Port:** 8082  
**Tools:** 23 (memory_*, search_*, fact_*)

---

## 7. Frontend (WebUI)

### Dateien

```
/DATA/AppData/MCP/Jarvis/Jarvis/adapters/Jarvis/static/
├── js/
│   ├── api.js              # API Calls, SSE Parsing
│   ├── chat.js             # Chat Logic, Event Dispatcher
│   ├── trion-panel.js      # TRION Sidepanel (23KB)
│   ├── sequential-plugin.js # Sequential Plugin (7KB)
│   ├── app.js              # Main App
│   ├── settings.js         # Settings Page
│   └── ui.js               # UI Helpers
├── css/
│   └── trion-panel.css     # Panel Styling
└── index.html              # Main HTML
```

### TRION Panel System

**Architektur:**
```
Backend Events (SSE)
       │
       ▼
┌──────────────────────────────────┐
│ chat.js - Event Dispatcher       │
│                                  │
│ if (pluginEvents.includes(type)) │
│   dispatchEvent('sse-event')     │
└──────────────────┬───────────────┘
                   │
                   ▼
┌──────────────────────────────────┐
│ sequential-plugin.js             │
│                                  │
│ addEventListener('sse-event')    │
│ → handleStart()                  │
│ → handleStep()                   │
│ → handleDone()                   │
└──────────────────┬───────────────┘
                   │
                   ▼
┌──────────────────────────────────┐
│ trion-panel.js                   │
│                                  │
│ TRIONPanel.createTab()           │
│ TRIONPanel.updateContent()       │
│ TRIONPanel.closeTab()            │
└──────────────────────────────────┘
```

### Event Types

| Event | Wann | Daten |
|-------|------|-------|
| `sequential_start` | Task beginnt | task_id, complexity |
| `sequential_step` | Step fertig | step_num, title, content |
| `sequential_done` | Task fertig | summary, total_steps |
| `sequential_error` | Fehler | error message |

---

## 8. Datenfluss

### Kompletter Request Flow

```
1. User: "Warum führt Werbung nicht immer zu Umsatz?"
   │
   ▼
2. jarvis-admin-api (main.py)
   │ → Parse Request
   │ → Route to Bridge
   │
   ▼
3. CoreBridge.process_stream()
   │
   ├─► LAYER 1: ThinkingLayer
   │   │ → DeepSeek analysiert Intent
   │   │ → Erkennt: complexity=7, needs_sequential=True
   │   │ → Output: thinking_plan
   │   │
   │   ▼
   ├─► LAYER 2: ControlLayer
   │   │ → IF needs_sequential:
   │   │   │
   │   │   ▼
   │   │   _check_sequential_thinking_stream()
   │   │   │ → yield {"type": "sequential_start"}
   │   │   │ → MCPHub.call_tool("think", {...})
   │   │   │   │
   │   │   │   ▼
   │   │   │   Sequential Thinking MCP (:8085)
   │   │   │   │ → CIM.analyze()
   │   │   │   │   │
   │   │   │   │   ▼
   │   │   │   │   CIM Server (:8086)
   │   │   │   │   │ → GraphSelector → HeavyGraphBuilder
   │   │   │   │   │ → RAG: Priors, Procedures, Anti-Patterns
   │   │   │   │   │ → CausalPromptEngineer
   │   │   │   │   │ ← Return: causal_prompt (ROADMAP)
   │   │   │   │   │
   │   │   │   │ ← causal_prompt
   │   │   │   │ → Ollama (1x!) mit ROADMAP
   │   │   │   │ ← full_response (alle Steps)
   │   │   │   │ → parse_steps()
   │   │   │   │
   │   │   │   ▼
   │   │   │   Return: {success, steps[], full_response}
   │   │   │
   │   │   ▼
   │   │   → yield {"type": "sequential_step", ...} × N
   │   │   → yield {"type": "sequential_done", ...}
   │   │   → thinking_plan["_sequential_result"] = result
   │   │
   │   ▼
   │   → LightCIM validation
   │   → Output: verified_plan
   │
   ▼
4. LAYER 3: OutputLayer
   │ → Liest verified_plan["_sequential_result"]  ← BUG: Passiert nicht?
   │ → Generiert finale Antwort
   │ → Streamt via SSE
   │
   ▼
5. Frontend
   │ → api.js parsed SSE
   │ → chat.js dispatched events
   │ → sequential-plugin.js → TRION Panel
   │ → Chat Bubble (finale Antwort) ← FEHLT!
```

---

## 9. Was funktioniert ✅

### Backend
- ✅ 3-Layer System (Thinking → Control → Output)
- ✅ ThinkingLayer erkennt Sequential Bedarf (complexity>5)
- ✅ ControlLayer triggert Sequential Thinking
- ✅ CIM Server funktioniert (HeavyGraphBuilder, RAG)
- ✅ Sequential v3.0 macht 1 Ollama Call statt 8
- ✅ Steps werden korrekt geparsed
- ✅ Events werden emitted (sequential_start/step/done)
- ✅ MCP Hub verbindet alle Services

### Frontend
- ✅ TRION Panel öffnet automatisch
- ✅ Tab wird erstellt
- ✅ Steps werden angezeigt (am Ende)
- ✅ Event-Dispatcher funktioniert
- ✅ SSE Streaming funktioniert

### Infrastructure
- ✅ Docker Compose orchestriert alles
- ✅ Ollama mit allen Models
- ✅ PostgreSQL für Memory
- ✅ Alle Container laufen

---

## 10. Was fehlt ❌

### Kritisch (Blocking)

| Problem | Beschreibung | Ort | Aufwand |
|---------|--------------|-----|---------|
| **Finale Antwort fehlt** | Chat zeigt keine Antwort nach Sequential | output.py / bridge.py | 1-2h Debug |
| **Steps nicht progressiv** | Alle Steps kommen auf einmal, nicht live | sequential_thinking.py | 2h |

### Wichtig (Funktionalität)

| Feature | Beschreibung | Ort | Aufwand |
|---------|--------------|-----|---------|
| **Inline Thinking Block** | Claude-Style "▼ Thinking..." im Chat | chat.js + CSS | 3h |
| **Streaming Steps** | Ollama stream + Parse "## Step N:" | sequential_thinking.py | 2h |
| **task_id undefined** | Sidepanel zeigt task_id: undefined | api.js / main.py | 1h |

### Nice-to-Have

| Feature | Beschreibung | Aufwand |
|---------|--------------|---------|
| Mermaid Diagrams | CIM Graph visualisieren | 2h |
| Step Timing | Dauer pro Step anzeigen | 1h |
| Cancel Button | Laufende Tasks abbrechen | 2h |
| Mobile Layout | Panel responsive | 1h |

---

## 11. Nächste Schritte

### Phase 1: Bug Fixes (Prio 1) - 3h

1. **Debug: Warum keine finale Antwort?**
   - Checke ob `_sequential_result` in `verified_plan` ist
   - Checke ob OutputLayer es verwendet
   - Checke ob Stream ans Frontend kommt

2. **Fix: OutputLayer Sequential Integration**
   - Stelle sicher dass `full_response` im System-Prompt ist
   - Teste mit einfacher Frage

### Phase 2: Progressive Steps (Prio 2) - 4h

1. **Backend: Ollama Streaming**
   ```python
   async def think_stream(message, ...):
       async for chunk in call_ollama_stream(...):
           if "## Step" in accumulated:
               yield {"type": "thinking_step", ...}
   ```

2. **Frontend: Live Updates**
   - Event handler für `thinking_chunk`
   - Accumulator im Plugin

### Phase 3: Inline Thinking Block (Prio 2) - 3h

1. **HTML Component**
   ```html
   <div class="thinking-block">
     <div class="thinking-header">▼ Thinking... ◐</div>
     <div class="thinking-content"><!-- stream here --></div>
   </div>
   ```

2. **CSS Animation**
   - Spinner
   - Expand/Collapse
   - Step checkmarks

3. **Integration in chat.js**
   - Neuer Message-Typ
   - State Management

### Phase 4: Sidepanel als Kontexthalter (Prio 3) - 4h

1. **State File System**
   - `/tmp/sequential_state.md`
   - Live Updates

2. **LLM Context Injection**
   - State in System-Prompt
   - Kontext-Refresh bei langen Tasks

---

## Anhang: Wichtige Code-Locations

### Sequential Thinking Bug debuggen

```bash
# 1. Logs checken
sudo docker logs -f jarvis-admin-api 2>&1 | grep -E 'sequential|output'

# 2. Output Layer
vim /DATA/AppData/MCP/Jarvis/Jarvis/core/layers/output.py
# Zeile 77-110: Sequential Integration

# 3. Bridge
vim /DATA/AppData/MCP/Jarvis/Jarvis/core/bridge.py
# Zeile 457-467: Sequential Stream
# Zeile 500-525: Layer 3 Output

# 4. Control Layer
vim /DATA/AppData/MCP/Jarvis/Jarvis/core/layers/control.py
# _check_sequential_thinking_stream()
```

### Frontend Events debuggen

```javascript
// Browser Console
localStorage.debug = 'trion:*';

// Event listener hinzufügen
window.addEventListener('sse-event', (e) => {
    console.log('SSE Event:', e.detail);
});
```

---

**Letzte Aktualisierung:** 2026-01-21 04:30 UTC  
**Nächste Review:** Nach Phase 1 Completion
