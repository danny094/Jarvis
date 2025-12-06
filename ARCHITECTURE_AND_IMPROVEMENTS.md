# Assistant Proxy - Architektur & Verbesserungsvorschläge

## Inhaltsverzeichnis

1. [Projektübersicht](#projektübersicht)
2. [Architektur](#architektur)
3. [Technologie-Stack](#technologie-stack)
4. [Datenfluss](#datenfluss)
5. [Verbesserungsvorschläge](#verbesserungsvorschläge)
6. [Code-Beispiele](#code-beispiele)
7. [Best Practices](#best-practices)
8. [Roadmap](#roadmap)

---

## Projektübersicht

Das **Assistant Proxy** ist ein Multi-Layer AI System, das als intelligenter Proxy zwischen Chat-UIs (LobeChat, OpenWebUI) und verschiedenen LLM-Backends fungiert. Das System implementiert eine innovative 3-Layer-Architektur zur Verbesserung der Antwortqualität und Reduzierung von Halluzinationen.

### Hauptkomponenten

```
assistant-proxy/
├── assistant-proxy/          # Core Bridge Application
│   ├── adapters/             # Chat-UI Adapter (LobeChat, OpenWebUI)
│   ├── core/                 # 3-Layer Architektur
│   │   ├── bridge.py         # Orchestrator
│   │   ├── layers/
│   │   │   ├── thinking.py   # Layer 1: Intent-Analyse
│   │   │   ├── control.py    # Layer 2: Verifikation
│   │   │   └── output.py     # Layer 3: Antwortgenerierung
│   │   ├── models.py         # Datenmodelle
│   │   └── persona.py        # Persona-Management
│   ├── mcp/                  # MCP Hub & Clients
│   │   ├── hub.py            # Tool-Management
│   │   ├── client.py         # Tool-Aufrufe
│   │   └── transports/       # HTTP, SSE, STDIO
│   ├── classifier/           # Message-Klassifizierung
│   └── utils/                # Logging, Streaming, Prompts
├── sql-memory/               # Persistentes Gedächtnissystem
│   ├── memory_mcp/           # Memory Tools
│   ├── vector_store.py       # Embedding-basierte Suche
│   └── graph/                # Knowledge Graph
├── validator-service/        # Qualitätssicherung
│   └── main.py               # Embedding & LLM-Validierung
└── Sequential Thinking/      # Reasoning MCP
    └── mcp-sequential/       # Sequential Reasoning Tools
```

### Statistiken

- **Codebase**: ~6.735 Zeilen Python-Code (Core)
- **Services**: 4 Haupt-Services (Bridge, Memory, Validator, Sequential Thinking)
- **Adapter**: 2 Chat-UI-Adapter (LobeChat, OpenWebUI)
- **MCP Transports**: 3 Protokolle (HTTP, SSE, STDIO)
- **Datenbank**: SQLite mit FTS5 (Full-Text-Search) und Vector Store

---

## Architektur

### 1. Systemarchitektur

```
┌─────────────────────────────────────────────────────────────────┐
│                        Chat UI Layer                            │
│                  (LobeChat / OpenWebUI)                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Adapter Layer                              │
│  ┌──────────────────┐              ┌──────────────────┐        │
│  │  LobeChat        │              │  OpenWebUI       │        │
│  │  Adapter         │              │  Adapter         │        │
│  └──────────────────┘              └──────────────────┘        │
│         │ Transform Request/Response │                          │
└─────────┴───────────────────────────┴──────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Core Bridge Layer                          │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Layer 1: Thinking (DeepSeek-R1:8b)                   │    │
│  │  • Intent-Analyse                                      │    │
│  │  • Hallucination-Risk-Assessment                       │    │
│  │  • Memory-Need-Detection                               │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Memory Retrieval (Optional)                           │    │
│  │  • Facts (SQL)                                         │    │
│  │  • Embeddings (Vector Search)                          │    │
│  │  • Knowledge Graph                                     │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Layer 2: Control (Qwen3:4b)                          │    │
│  │  • Fact-Checking                                       │    │
│  │  • Hallucination-Detection                             │    │
│  │  • Correction-Generation                               │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Layer 3: Output (Llama3.1:8b)                        │    │
│  │  • Final-Response-Generation                           │    │
│  │  • Persona-Application                                 │    │
│  │  • Streaming-Support                                   │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Memory Save (Optional)                                │    │
│  │  • Extract & Save Facts                                │    │
│  │  • Update Knowledge Graph                              │    │
│  │  • Generate Embeddings                                 │    │
│  └───────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ SQL Memory   │  │  Validator   │  │   MCP Hub    │
│   Service    │  │   Service    │  │   (Tools)    │
└──────────────┘  └──────────────┘  └──────────────┘
```

### 2. 3-Layer-Architektur im Detail

#### Layer 1: Thinking Layer (Intent & Risk Analysis)

**Zweck**: Analysiert die User-Anfrage und bewertet Komplexität

**Model**: DeepSeek-R1:8b (Reasoning-optimiert)

**Output**:
```json
{
  "thinking": "<internal reasoning process>",
  "plan": {
    "needs_memory": true,
    "needs_tools": false,
    "search_queries": ["user preferences", "previous context"],
    "hallucination_risk": "low|medium|high"
  }
}
```

**Entscheidungslogik**:
- `hallucination_risk == "low"` → Control-Layer überspringen
- `needs_memory == true` → Memory-Retrieval aktivieren
- `needs_tools == true` → MCP-Tools bereitstellen

#### Layer 2: Control Layer (Verification & Correction)

**Zweck**: Fact-Checking und Halluzination-Prävention

**Model**: Qwen3:4b (Effizient & Präzise)

**Input**: Original-Anfrage + Memory-Kontext

**Output**:
```json
{
  "verification": {
    "facts_correct": true,
    "hallucinations_found": [],
    "corrections": [],
    "confidence": 0.95
  }
}
```

**Wird übersprungen wenn**:
- `hallucination_risk == "low"` (z.B. einfache Fragen)
- `ENABLE_CONTROL_LAYER == false` (Config)

#### Layer 3: Output Layer (Final Response)

**Zweck**: Generiert finale, persona-konforme Antwort

**Model**: Llama3.1:8b (Kreativ & Natürlich)

**Input**:
- Original-Anfrage
- Memory-Kontext
- Control-Layer-Feedback
- Persona-Definition (YAML)

**Output**: Streaming-fähige Chat-Antwort

**Features**:
- Persona-Anwendung (Tone, Style, Constraints)
- Markdown-Formatierung
- Streaming-Support für UX

### 3. MCP Hub Architektur

```
┌─────────────────────────────────────────────────────────┐
│                      MCP Hub                            │
│                                                         │
│  ┌───────────────────────────────────────────────┐    │
│  │  Auto-Discovery & Registration                │    │
│  │  • Scanne mcp_registry.py                     │    │
│  │  │  Erkenne Transport-Type (HTTP/SSE/STDIO)    │    │
│  │  • Registriere Tools im Knowledge Graph       │    │
│  └────────────────┬──────────────────────────────┘    │
│                   ▼                                     │
│  ┌───────────────────────────────────────────────┐    │
│  │  Transport Layer (Pluggable)                  │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐     │    │
│  │  │   HTTP   │ │   SSE    │ │  STDIO   │     │    │
│  │  │ Transport│ │ Transport│ │ Transport│     │    │
│  │  └──────────┘ └──────────┘ └──────────┘     │    │
│  └────────────────┬──────────────────────────────┘    │
│                   ▼                                     │
│  ┌───────────────────────────────────────────────┐    │
│  │  Tool Execution                               │    │
│  │  • Format Request                             │    │
│  │  • Call MCP Server                            │    │
│  │  • Parse Response                             │    │
│  │  • Error Handling                             │    │
│  └───────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              External MCP Servers                       │
│  • sql-memory (STDIO)                                   │
│  • Sequential Thinking (STDIO)                          │
│  • Custom Tools (HTTP/SSE)                              │
└─────────────────────────────────────────────────────────┘
```

### 4. Memory-System Architektur

```
┌─────────────────────────────────────────────────────────┐
│                    SQL Memory Service                   │
│                                                         │
│  ┌───────────────────────────────────────────────┐    │
│  │  Facts Database (SQLite)                      │    │
│  │  • Strukturierte Fakten (Key-Value)           │    │
│  │  • Per Conversation isoliert                  │    │
│  │  • FTS5 Volltextsuche                         │    │
│  │  • Kategorisierung (person, preference, etc.) │    │
│  └────────────────┬──────────────────────────────┘    │
│                   │                                     │
│  ┌────────────────┴──────────────────────────────┐    │
│  │  Vector Store (Embeddings)                    │    │
│  │  • mxbai-embed-large-v1:f16                   │    │
│  │  • Cosine Similarity Search                   │    │
│  │  • Top-K Retrieval                            │    │
│  └────────────────┬──────────────────────────────┘    │
│                   │                                     │
│  ┌────────────────┴──────────────────────────────┐    │
│  │  Knowledge Graph                              │    │
│  │  • Entity-Relationship-Mapping                │    │
│  │  • Tool-Beschreibungen                        │    │
│  │  • Cross-Reference-Suche                      │    │
│  └───────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Memory-Retrieval-Strategie**:

1. **Facts**: Exakte Key-Matches + FTS5-Suche
2. **Embeddings**: Top-5 semantisch ähnliche Einträge
3. **Graph**: Verknüpfte Entitäten + Tool-Kontext

**Memory-Save-Strategie**:

1. **Extraction**: LLM extrahiert strukturierte Fakten
2. **Categorization**: Automatische Kategorisierung
3. **Embedding**: Generierung von Vektor-Repräsentationen
4. **Graph-Update**: Verknüpfungen aktualisieren

---

## Technologie-Stack

### Backend

| Komponente | Technologie | Version | Verwendung |
|------------|-------------|---------|------------|
| **Framework** | FastAPI | Latest | REST API & Async-Support |
| **Server** | Uvicorn | Latest | ASGI Server |
| **Database** | SQLite3 | 3.x | Facts, Embeddings, Graph |
| **HTTP Client** | Requests | 2.31+ | Sync HTTP (⚠️ Problem!) |
| **Async HTTP** | httpx | 0.25+ | Teilweise verwendet |
| **YAML** | PyYAML | 6.0+ | Configs & Personas |
| **MCP** | FastMCP | Latest | MCP Protocol |

### AI/ML Models (Ollama)

| Layer | Model | Größe | Zweck |
|-------|-------|-------|-------|
| Thinking | DeepSeek-R1 | 8B | Reasoning & Planning |
| Control | Qwen3 | 4B | Fact-Checking |
| Output | Llama3.1 | 8B | Response Generation |
| Embeddings | mxbai-embed-large-v1 | f16 | Semantic Search |

### Container-Infrastruktur

- **Docker** - Containerisierung
- **Docker Compose** - Multi-Service-Orchestrierung
- **Networks**: Isolierte Bridge-Networks pro Service

---

## Datenfluss

### Request-Flow (Detailliert)

```
1. User-Input in Chat-UI
   └─> POST /api/chat/completions
       {
         "model": "gpt-4",
         "messages": [{"role": "user", "content": "..."}],
         "stream": true
       }

2. Adapter (z.B. LobeChat)
   └─> transform_request()
       • OpenAI-Format → CoreChatRequest
       • Conversation-ID-Extraktion
       • Persona-Lookup

3. Core Bridge - Layer 1: Thinking
   └─> ThinkingLayer.process()
       • DeepSeek-R1 Reasoning
       • Output: thinking_plan
         {
           "needs_memory": true,
           "hallucination_risk": "medium",
           "search_queries": ["user name", "preferences"]
         }

4. Memory Retrieval (wenn needs_memory=true)
   └─> MCPHub.get_memory_context()
       • Facts: query_facts(search_queries)
       • Embeddings: search_similar(query, top_k=5)
       • Graph: get_related_entities()
       • Combine → memory_context (String)

5. Core Bridge - Layer 2: Control (wenn risk != "low")
   └─> ControlLayer.process()
       • Input: user_query + memory_context
       • Qwen3 Fact-Checking
       • Output: corrections (falls nötig)

6. Core Bridge - Layer 3: Output
   └─> OutputLayer.process()
       • Input: user_query + memory_context + corrections + persona
       • Llama3.1 Generation (streaming)
       • Output: final_response (Generator)

7. Memory Save (wenn needs_memory=true)
   └─> MCPHub.save_to_memory()
       • Extract Facts (LLM-based)
       • Save to SQL
       • Generate Embeddings
       • Update Knowledge Graph

8. Adapter
   └─> transform_response()
       • CoreChatResponse → OpenAI-Format
       • Stream SSE Events

9. Chat-UI
   └─> Display Response (streaming)
```

### Memory-Context-Beispiel

**Input**: `"Was sind meine Lieblings-Programmiersprachen?"`

**Memory Retrieval**:

```yaml
Facts:
  - key: "favorite_languages"
    value: "Python, TypeScript, Rust"
    category: "preference"
    confidence: 0.95

Embeddings (Top-3):
  - "Der User bevorzugt statisch typisierte Sprachen" (similarity: 0.87)
  - "Python wird für AI/ML-Projekte verwendet" (similarity: 0.82)
  - "TypeScript für Frontend-Entwicklung" (similarity: 0.78)

Graph:
  - Entity: "Python" → Related: ["FastAPI", "pytest", "AI/ML"]
  - Entity: "TypeScript" → Related: ["React", "Node.js"]
```

**Combined Memory Context**:
```
Relevante Informationen:
- Lieblings-Programmiersprachen: Python, TypeScript, Rust
- Der User bevorzugt statisch typisierte Sprachen
- Python wird für AI/ML-Projekte verwendet
- TypeScript für Frontend-Entwicklung
```

---

## Verbesserungsvorschläge

### Priorität 1: Kritische Fixes

#### 1.1 Async/Await-Inkonsistenz beheben

**Problem**: Sync-Code (`requests`) blockiert Event-Loop in async-Funktionen

**Betroffene Dateien**:
- `assistant-proxy/core/layers/thinking.py:122`
- `assistant-proxy/core/layers/control.py:95`
- `assistant-proxy/core/layers/output.py:87`

**Impact**:
- Blockiert Concurrency
- Reduziert Throughput
- Schlechte Performance bei parallelen Requests

**Fix**: Migration zu `httpx.AsyncClient`

#### 1.2 Requirements pinnen

**Problem**: `requirements.txt` ohne Versions-Constraints

**Risiko**:
- Breaking Changes bei Updates
- Inkonsistente Deployments
- Schwer debugbare Fehler

**Fix**: Alle Dependencies pinnen

#### 1.3 Tests implementieren

**Problem**: Keine Test-Suite vorhanden

**Risiko**:
- Keine Regression-Detection
- Unsicheres Refactoring
- Produktions-Bugs

**Fix**: pytest-Setup mit 70%+ Coverage

#### 1.4 Bare except-Blöcke entfernen

**Problem**: `except:` schluckt alle Exceptions

**Risiko**:
- Schwer debugbare Fehler
- Verhindert graceful shutdown (KeyboardInterrupt)
- Versteckt echte Bugs

**Fix**: Spezifische Exception-Types

### Priorität 2: Sicherheit

#### 2.1 Authentifizierung implementieren

**Problem**: Alle Endpoints öffentlich zugänglich

**Risiko**:
- Unbefugter Zugriff
- API-Missbrauch
- Daten-Leaks

**Fix**: API-Key-basierte Authentifizierung

#### 2.2 CORS einschränken

**Problem**: `ALLOW_ORIGINS = ["*"]`

**Risiko**:
- Cross-Origin-Attacks
- CSRF-Anfälligkeit

**Fix**: Whitelist konfigurieren

#### 2.3 Rate-Limiting

**Problem**: Keine Request-Limitierung

**Risiko**:
- DoS-Anfälligkeit
- Ressourcen-Erschöpfung

**Fix**: FastAPI Rate-Limiter

#### 2.4 Docker Security

**Problem**: Container läuft als Root

**Risiko**:
- Privilege-Escalation
- Container-Breakout

**Fix**: Non-root User in Dockerfile

### Priorität 3: Performance

#### 3.1 Connection Pooling

**Problem**: Neue Connection pro Request

**Impact**: Unnötiger Overhead

**Fix**: httpx.AsyncClient mit Connection-Pool

#### 3.2 Memory-Caching

**Problem**: Keine Caching-Strategie

**Impact**: Langsame wiederholte Queries

**Fix**: Redis oder In-Memory-Cache

#### 3.3 N+1 Query-Problem

**Problem**: Separate DB-Queries in Loop

**Impact**: Langsame Memory-Retrieval

**Fix**: Batch-Queries

### Priorität 4: Code-Qualität

#### 4.1 CoreBridge.process() refactoring

**Problem**: 330 Zeilen, zu viele Responsibilities

**Impact**: Schwer wartbar, testbar

**Fix**: In kleinere Funktionen aufteilen

#### 4.2 Exception-Handler-Decorator

**Problem**: Duplikation von try-except-log-Patterns

**Impact**: Code-Duplikation

**Fix**: Gemeinsamer Decorator

#### 4.3 MCP-Transport-Basisklasse

**Problem**: Duplikation in http.py, sse.py, stdio.py

**Impact**: Code-Duplikation

**Fix**: Gemeinsame Abstraktion

### Priorität 5: Dokumentation

#### 5.1 OpenAPI-Dokumentation

**Problem**: Keine API-Docs

**Fix**: FastAPI Auto-Docs aktivieren

#### 5.2 Setup-Guide

**Problem**: Keine Installations-Anleitung

**Fix**: README mit Schritt-für-Schritt-Guide

#### 5.3 Architektur-Diagramme

**Problem**: Keine visuellen Darstellungen

**Fix**: Mermaid-Diagramme in Docs

---

## Code-Beispiele

### 1. Async/Await-Migration

#### Vorher (❌ Blockierend):

```python
# assistant-proxy/core/layers/thinking.py:122
import requests

class ThinkingLayer:
    async def process(self, request):
        # ❌ Blockiert Event-Loop!
        r = requests.post(
            f"{self.ollama_base}/api/generate",
            json={
                "model": "deepseek-r1:8b",
                "prompt": prompt,
                "stream": False
            },
            timeout=60
        )
        result = r.json()
        return result
```

#### Nachher (✅ Non-blocking):

```python
# assistant-proxy/core/layers/thinking.py
import httpx

class ThinkingLayer:
    def __init__(self, ollama_base: str):
        self.ollama_base = ollama_base
        # ✅ Connection-Pool mit Timeout
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=10)
        )

    async def process(self, request):
        # ✅ Non-blocking HTTP-Call
        response = await self.client.post(
            f"{self.ollama_base}/api/generate",
            json={
                "model": "deepseek-r1:8b",
                "prompt": prompt,
                "stream": False
            }
        )
        result = response.json()
        return result

    async def close(self):
        """Cleanup connection pool"""
        await self.client.aclose()
```

**Migration Checklist**:
- [ ] `thinking.py` migrieren
- [ ] `control.py` migrieren
- [ ] `output.py` migrieren
- [ ] `utils/ollama.py` migrieren
- [ ] Connection-Pool-Konfiguration
- [ ] Graceful Shutdown implementieren
- [ ] Tests für alle Layer

### 2. Requirements pinnen

#### Vorher (❌ Unpinned):

```txt
# requirements.txt
fastapi
uvicorn[standard]
requests
httpx
pyyaml
sqlite3
```

#### Nachher (✅ Pinned):

```txt
# requirements.txt
# Core Framework
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0

# HTTP Clients
httpx==0.25.1
requests==2.31.0  # Legacy - TODO: Remove after migration

# Configuration
pyyaml==6.0.1

# Database
# sqlite3 ist Teil von Python Standard Library

# MCP
fastmcp==0.2.0

# Utilities
python-dotenv==1.0.0
```

**Versions-Management**:
```bash
# Erstelle pinned requirements
pip freeze > requirements.lock

# Oder mit pip-tools
pip-compile requirements.in --output-file requirements.txt
```

### 3. Exception-Handling verbessern

#### Vorher (❌ Bare except):

```python
# assistant-proxy/mcp/client.py:214
def call_tool(self, tool_name: str, arguments: dict):
    try:
        result = self.transport.call(tool_name, arguments)
        return result
    except:  # ❌ Schluckt ALLES (auch KeyboardInterrupt!)
        pass
    return None
```

#### Nachher (✅ Spezifische Exceptions):

```python
# assistant-proxy/mcp/client.py
import logging
from typing import Optional
from httpx import TimeoutException, HTTPStatusError

logger = logging.getLogger(__name__)

class MCPCallError(Exception):
    """Custom exception for MCP call failures"""
    pass

def call_tool(self, tool_name: str, arguments: dict) -> Optional[dict]:
    try:
        result = self.transport.call(tool_name, arguments)
        return result

    except TimeoutException as e:
        logger.error(f"Tool '{tool_name}' timed out: {e}")
        raise MCPCallError(f"Tool call timed out: {tool_name}") from e

    except HTTPStatusError as e:
        logger.error(f"Tool '{tool_name}' returned HTTP {e.response.status_code}")
        if e.response.status_code >= 500:
            # Server-Fehler → Retry möglich
            raise MCPCallError(f"Server error calling {tool_name}") from e
        else:
            # Client-Fehler → Nicht retryable
            logger.warning(f"Invalid arguments for {tool_name}: {arguments}")
            return None

    except Exception as e:
        # Unerwartete Fehler loggen
        logger.exception(f"Unexpected error calling tool '{tool_name}': {e}")
        raise MCPCallError(f"Unexpected error: {tool_name}") from e
```

**Alle betroffenen Stellen**:
```bash
# Finde alle bare except
grep -rn "except:" assistant-proxy/

# Output:
# assistant-proxy/mcp/client.py:214
# assistant-proxy/mcp/transports/http.py:114
# assistant-proxy/mcp/transports/http.py:311
# assistant-proxy/mcp/transports/stdio.py:62
# assistant-proxy/mcp/transports/stdio.py:150
# assistant-proxy/mcp/transports/sse.py:162
```

### 4. API-Key-Authentifizierung

#### Implementierung:

```python
# assistant-proxy/auth.py (NEU)
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
import os

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def get_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Validiert API-Key aus Header.

    Raises:
        HTTPException: 403 wenn Key fehlt oder ungültig
    """
    expected_key = os.getenv("API_KEY")

    if not expected_key:
        # Entwicklungsmodus: Keine Auth erforderlich
        return "dev_mode"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API-Key fehlt im Header"
        )

    if api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ungültiger API-Key"
        )

    return api_key
```

#### Verwendung in Endpoints:

```python
# assistant-proxy/adapters/lobechat/main.py
from fastapi import Depends
from auth import get_api_key

@app.post("/api/chat/completions")
async def chat_completions(
    request: ChatRequest,
    api_key: str = Depends(get_api_key)  # ✅ Auth-Protection
):
    # Endpoint-Logik...
    pass
```

#### .env-Konfiguration:

```bash
# .env
API_KEY=your-secret-api-key-here

# docker-compose.yml
environment:
  - API_KEY=${API_KEY}
```

#### Client-Verwendung:

```bash
# cURL
curl -X POST http://localhost:8000/api/chat/completions \
  -H "X-API-Key: your-secret-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{"messages": [...]}'

# Python
import httpx

headers = {"X-API-Key": "your-secret-api-key-here"}
response = await client.post("/api/chat/completions", headers=headers)
```

### 5. Rate-Limiting

```python
# assistant-proxy/middleware/rate_limit.py (NEU)
from fastapi import Request, HTTPException
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio

class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
        self.lock = asyncio.Lock()

    async def check_rate_limit(self, client_id: str):
        """
        Prüft Rate-Limit für Client.

        Args:
            client_id: Eindeutige Client-ID (IP oder API-Key)

        Raises:
            HTTPException: 429 wenn Rate-Limit überschritten
        """
        async with self.lock:
            now = datetime.now()
            minute_ago = now - timedelta(minutes=1)

            # Entferne alte Requests
            self.requests[client_id] = [
                req_time for req_time in self.requests[client_id]
                if req_time > minute_ago
            ]

            # Prüfe Limit
            if len(self.requests[client_id]) >= self.requests_per_minute:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate-Limit überschritten: {self.requests_per_minute} Requests/Minute"
                )

            # Registriere neuen Request
            self.requests[client_id].append(now)

# Initialisierung
rate_limiter = RateLimiter(requests_per_minute=60)

# Middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host
    await rate_limiter.check_rate_limit(client_ip)
    response = await call_next(request)
    return response
```

### 6. CoreBridge Refactoring

#### Vorher (❌ God-Function - 330 Zeilen):

```python
# core/bridge.py
class CoreBridge:
    async def process(self, request: CoreChatRequest) -> CoreChatResponse:
        # 330 Zeilen Monster-Funktion
        # - Thinking Layer
        # - Memory Retrieval
        # - Control Layer
        # - Output Layer
        # - Memory Save
        # - Error Handling
        # ...
```

#### Nachher (✅ Modulare Funktionen):

```python
# core/bridge.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class ProcessingContext:
    """Shared context between processing stages"""
    request: CoreChatRequest
    thinking_plan: dict
    memory_context: str = ""
    control_feedback: Optional[dict] = None
    final_response: str = ""

class CoreBridge:
    async def process(self, request: CoreChatRequest) -> CoreChatResponse:
        """
        Orchestrates the 3-layer processing pipeline.

        Args:
            request: Incoming chat request

        Returns:
            CoreChatResponse with generated content
        """
        ctx = ProcessingContext(request=request, thinking_plan={})

        try:
            # Stage 1: Intent Analysis
            await self._execute_thinking_stage(ctx)

            # Stage 2: Memory Retrieval (optional)
            if ctx.thinking_plan.get("needs_memory"):
                await self._retrieve_memory(ctx)

            # Stage 3: Verification (optional)
            if self._should_verify(ctx):
                await self._execute_control_stage(ctx)

            # Stage 4: Response Generation
            await self._generate_output(ctx)

            # Stage 5: Memory Update (optional)
            if ctx.thinking_plan.get("needs_memory"):
                await self._save_to_memory(ctx)

            return CoreChatResponse(content=ctx.final_response)

        except Exception as e:
            logger.exception(f"Error in processing pipeline: {e}")
            return self._create_error_response(e)

    async def _execute_thinking_stage(self, ctx: ProcessingContext):
        """Execute Layer 1: Thinking"""
        logger.info("Starting Thinking Layer")
        ctx.thinking_plan = await self.thinking_layer.process(ctx.request)
        logger.debug(f"Thinking plan: {ctx.thinking_plan}")

    async def _retrieve_memory(self, ctx: ProcessingContext):
        """Retrieve relevant memory context"""
        logger.info("Retrieving memory context")
        queries = ctx.thinking_plan.get("search_queries", [])
        ctx.memory_context = await self.mcp_hub.get_memory_context(
            conversation_id=ctx.request.conversation_id,
            queries=queries
        )
        logger.debug(f"Memory context size: {len(ctx.memory_context)} chars")

    def _should_verify(self, ctx: ProcessingContext) -> bool:
        """Determine if Control Layer verification is needed"""
        if not self.config.enable_control_layer:
            return False

        risk = ctx.thinking_plan.get("hallucination_risk", "medium")
        return risk in ["medium", "high"]

    async def _execute_control_stage(self, ctx: ProcessingContext):
        """Execute Layer 2: Control"""
        logger.info("Starting Control Layer")
        ctx.control_feedback = await self.control_layer.process(
            request=ctx.request,
            memory_context=ctx.memory_context
        )
        logger.debug(f"Control feedback: {ctx.control_feedback}")

    async def _generate_output(self, ctx: ProcessingContext):
        """Execute Layer 3: Output"""
        logger.info("Starting Output Layer")
        ctx.final_response = await self.output_layer.process(
            request=ctx.request,
            memory_context=ctx.memory_context,
            control_feedback=ctx.control_feedback,
            persona=self.persona
        )
        logger.info(f"Generated response: {len(ctx.final_response)} chars")

    async def _save_to_memory(self, ctx: ProcessingContext):
        """Save new facts to memory"""
        logger.info("Saving to memory")
        await self.mcp_hub.save_to_memory(
            conversation_id=ctx.request.conversation_id,
            user_message=ctx.request.messages[-1].content,
            assistant_response=ctx.final_response
        )

    def _create_error_response(self, error: Exception) -> CoreChatResponse:
        """Create user-friendly error response"""
        return CoreChatResponse(
            content="Es tut mir leid, es ist ein Fehler aufgetreten. Bitte versuche es erneut."
        )
```

**Vorteile**:
- ✅ Jede Funktion hat eine klare Responsibility
- ✅ Testbar: Jede Stage einzeln testbar
- ✅ Lesbar: Überblick in `process()`, Details in Subfunktionen
- ✅ Wartbar: Änderungen isoliert
- ✅ Debuggbar: Granulares Logging

### 7. Connection-Pooling

```python
# assistant-proxy/utils/http_client.py (NEU)
import httpx
from typing import Optional

class HTTPClientManager:
    """Singleton für shared HTTP-Client mit Connection-Pooling"""

    _instance: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """
        Gibt shared AsyncClient zurück.

        Returns:
            Configured httpx.AsyncClient with connection pooling
        """
        if cls._instance is None:
            cls._instance = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=60.0,
                    write=10.0,
                    pool=5.0
                ),
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0
                ),
                http2=True  # HTTP/2 Support für Multiplexing
            )
        return cls._instance

    @classmethod
    async def close(cls):
        """Cleanup connection pool"""
        if cls._instance:
            await cls._instance.aclose()
            cls._instance = None

# Verwendung in Layers
class ThinkingLayer:
    def __init__(self, ollama_base: str):
        self.ollama_base = ollama_base
        self.client = HTTPClientManager.get_client()

    async def process(self, request):
        # ✅ Verwendet Connection-Pool
        response = await self.client.post(...)
        return response.json()

# Graceful Shutdown in FastAPI
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on shutdown"""
    await HTTPClientManager.close()
    logger.info("HTTP client closed")
```

### 8. Memory-Caching

```python
# assistant-proxy/cache/memory_cache.py (NEU)
from functools import lru_cache
from typing import Optional
import hashlib
import json

class MemoryCache:
    """Simple in-memory cache for frequently accessed memory contexts"""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        self.cache = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def _make_key(self, conversation_id: str, queries: list) -> str:
        """Generate cache key from conversation and queries"""
        content = f"{conversation_id}:{json.dumps(sorted(queries))}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, conversation_id: str, queries: list) -> Optional[str]:
        """Get cached memory context"""
        key = self._make_key(conversation_id, queries)
        entry = self.cache.get(key)

        if entry is None:
            return None

        # Check TTL
        import time
        if time.time() - entry["timestamp"] > self.ttl_seconds:
            del self.cache[key]
            return None

        return entry["value"]

    def set(self, conversation_id: str, queries: list, value: str):
        """Cache memory context"""
        import time

        # Evict oldest if cache full
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache, key=lambda k: self.cache[k]["timestamp"])
            del self.cache[oldest_key]

        key = self._make_key(conversation_id, queries)
        self.cache[key] = {
            "value": value,
            "timestamp": time.time()
        }

# Integration in MCPHub
class MCPHub:
    def __init__(self):
        self.memory_cache = MemoryCache(max_size=1000, ttl_seconds=300)

    async def get_memory_context(
        self,
        conversation_id: str,
        queries: list
    ) -> str:
        # Check cache first
        cached = self.memory_cache.get(conversation_id, queries)
        if cached:
            logger.debug("Memory cache hit")
            return cached

        # Cache miss → retrieve from DB
        logger.debug("Memory cache miss")
        context = await self._retrieve_from_db(conversation_id, queries)

        # Cache result
        self.memory_cache.set(conversation_id, queries, context)
        return context
```

### 9. Test-Setup (pytest)

```python
# tests/conftest.py (NEU)
import pytest
import asyncio
from httpx import AsyncClient
from assistant-proxy.core.bridge import CoreBridge
from assistant-proxy.core.models import CoreChatRequest, Message

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def http_client():
    """Shared HTTP client for tests"""
    async with AsyncClient() as client:
        yield client

@pytest.fixture
def sample_request():
    """Sample chat request for testing"""
    return CoreChatRequest(
        conversation_id="test-conv-123",
        messages=[
            Message(role="user", content="Was ist Python?")
        ],
        persona="default"
    )

@pytest.fixture
def mock_ollama(monkeypatch):
    """Mock Ollama API responses"""
    async def mock_post(*args, **kwargs):
        class MockResponse:
            def json(self):
                return {
                    "response": "Python ist eine Programmiersprache",
                    "done": True
                }
        return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

# tests/test_thinking_layer.py (NEU)
import pytest
from assistant-proxy.core.layers.thinking import ThinkingLayer

@pytest.mark.asyncio
async def test_thinking_layer_basic(sample_request, mock_ollama):
    """Test basic thinking layer processing"""
    layer = ThinkingLayer(ollama_base="http://localhost:11434")

    result = await layer.process(sample_request)

    assert "plan" in result
    assert "hallucination_risk" in result["plan"]
    assert result["plan"]["hallucination_risk"] in ["low", "medium", "high"]

@pytest.mark.asyncio
async def test_thinking_layer_needs_memory(sample_request, mock_ollama):
    """Test memory need detection"""
    layer = ThinkingLayer(ollama_base="http://localhost:11434")

    # Request requiring memory
    sample_request.messages[-1].content = "Was war mein letztes Projekt?"
    result = await layer.process(sample_request)

    assert result["plan"]["needs_memory"] is True
    assert len(result["plan"]["search_queries"]) > 0

# tests/test_core_bridge.py (NEU)
import pytest
from assistant-proxy.core.bridge import CoreBridge

@pytest.mark.asyncio
async def test_core_bridge_e2e(sample_request, mock_ollama):
    """End-to-end test of CoreBridge"""
    bridge = CoreBridge()

    response = await bridge.process(sample_request)

    assert response.content is not None
    assert len(response.content) > 0

@pytest.mark.asyncio
async def test_core_bridge_error_handling(sample_request):
    """Test error handling in CoreBridge"""
    bridge = CoreBridge()

    # Simulate error
    sample_request.messages = []  # Invalid request

    response = await bridge.process(sample_request)

    # Should return graceful error message
    assert "Fehler" in response.content or "error" in response.content.lower()

# Run tests
# pytest tests/ -v --cov=assistant-proxy --cov-report=html
```

### 10. Docker Security (Non-Root)

#### Vorher (❌ Root):

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
# ❌ Läuft als Root (UID 0)
```

#### Nachher (✅ Non-Root):

```dockerfile
FROM python:3.11-slim

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install dependencies as root
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### .dockerignore:

```
# .dockerignore (NEU)
.git
.gitignore
.DS_Store
__pycache__
*.pyc
*.pyo
*.pyd
.pytest_cache
.coverage
htmlcov/
*.log
.env
docker-compose*.yml
README.md
docs/
tests/
```

---

## Best Practices

### Python Best Practices

#### 1. Type-Hints überall

```python
# ✅ Gut
from typing import Optional, List, Dict

async def get_memory_context(
    conversation_id: str,
    queries: List[str],
    max_results: int = 5
) -> Dict[str, any]:
    ...

# ❌ Schlecht
async def get_memory_context(conversation_id, queries, max_results=5):
    ...
```

#### 2. Docstrings (Google-Style)

```python
def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate cosine similarity between two texts.

    Args:
        text1: First text for comparison
        text2: Second text for comparison

    Returns:
        Similarity score between 0.0 and 1.0

    Raises:
        ValueError: If either text is empty

    Example:
        >>> calculate_similarity("hello", "hello world")
        0.87
    """
    ...
```

#### 3. Logging statt print()

```python
import logging

logger = logging.getLogger(__name__)

# ✅ Gut
logger.info(f"Processing request {request_id}")
logger.error(f"Failed to connect: {error}", exc_info=True)

# ❌ Schlecht
print(f"Processing request {request_id}")
```

#### 4. Context Manager für Ressourcen

```python
# ✅ Gut
async with httpx.AsyncClient() as client:
    response = await client.get(url)

# ❌ Schlecht
client = httpx.AsyncClient()
response = await client.get(url)
# Vergisst await client.aclose()
```

### FastAPI Best Practices

#### 1. Pydantic für Validation

```python
from pydantic import BaseModel, Field, validator

class ChatRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=100)
    messages: List[Message] = Field(..., min_items=1)
    temperature: float = Field(0.7, ge=0.0, le=2.0)

    @validator("conversation_id")
    def validate_conversation_id(cls, v):
        if not v.startswith("conv-"):
            raise ValueError("conversation_id must start with 'conv-'")
        return v
```

#### 2. Dependency Injection

```python
from fastapi import Depends

def get_bridge() -> CoreBridge:
    """Dependency: CoreBridge instance"""
    return CoreBridge()

@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    bridge: CoreBridge = Depends(get_bridge)
):
    return await bridge.process(request)
```

#### 3. Response Models

```python
class ChatResponse(BaseModel):
    content: str
    conversation_id: str
    model: str
    usage: TokenUsage

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    ...
```

### Async Best Practices

#### 1. Keine Blocking-Calls in async

```python
# ❌ Schlecht
async def process():
    result = requests.get(url)  # Blockiert!

# ✅ Gut
async def process():
    async with httpx.AsyncClient() as client:
        result = await client.get(url)
```

#### 2. Concurrent Tasks mit asyncio.gather

```python
# ✅ Parallel execution
results = await asyncio.gather(
    fetch_facts(conversation_id),
    fetch_embeddings(query),
    fetch_graph_data(entity)
)
facts, embeddings, graph = results

# ❌ Sequential (langsam)
facts = await fetch_facts(conversation_id)
embeddings = await fetch_embeddings(query)
graph = await fetch_graph_data(entity)
```

#### 3. Timeouts setzen

```python
import asyncio

try:
    result = await asyncio.wait_for(
        slow_operation(),
        timeout=5.0
    )
except asyncio.TimeoutError:
    logger.error("Operation timed out")
```

### Database Best Practices

#### 1. Context Manager für Connections

```python
import sqlite3
from contextlib import contextmanager

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()

# Verwendung
with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM facts")
```

#### 2. Prepared Statements

```python
# ✅ Gut (parametrisiert)
cursor.execute(
    "SELECT * FROM facts WHERE conversation_id = ? AND key = ?",
    (conversation_id, key)
)

# ❌ Schlecht (SQL-Injection-Risiko!)
cursor.execute(
    f"SELECT * FROM facts WHERE conversation_id = '{conversation_id}'"
)
```

#### 3. Batch-Inserts

```python
# ✅ Gut (Batch)
data = [(conv_id, key, value) for ...]
cursor.executemany(
    "INSERT INTO facts (conversation_id, key, value) VALUES (?, ?, ?)",
    data
)

# ❌ Schlecht (Loop)
for item in data:
    cursor.execute("INSERT INTO facts ...", item)
```

---

## Roadmap

### Phase 1: Kritische Fixes (Priorität)

**Ziel**: Stabilität & Sicherheit

- [ ] Requirements pinnen (`requirements.txt`)
- [ ] Bare except-Blöcke fixen (6-8 Stellen)
- [ ] CORS konfigurierbar machen
- [ ] .dockerignore hinzufügen
- [ ] Docker non-root User
- [ ] Async/Await Migration (thinking.py, control.py, output.py)
- [ ] Connection-Pooling implementieren

**Erwarteter Impact**:
- ✅ Keine blocking I/O mehr
- ✅ Bessere Performance (3-5x Throughput)
- ✅ Reproduzierbare Deployments

### Phase 2: Testing & Qualität

**Ziel**: Vertrauen & Wartbarkeit

- [ ] pytest-Setup
- [ ] Unit-Tests für alle Layer (70%+ Coverage)
- [ ] Integration-Tests für Adapter
- [ ] E2E-Tests für komplette Pipeline
- [ ] CI/CD-Pipeline (GitHub Actions)
- [ ] Pre-commit Hooks (black, flake8, mypy)

**Erwarteter Impact**:
- ✅ Regression-Detection
- ✅ Sicheres Refactoring
- ✅ Dokumentierte Behavior

### Phase 3: Sicherheit & Auth

**Ziel**: Production-Ready

- [ ] API-Key-Authentifizierung
- [ ] Rate-Limiting (60 req/min)
- [ ] Request-Size-Limits
- [ ] CORS-Whitelist
- [ ] Secrets-Management (Vault/AWS Secrets)
- [ ] Audit-Logging

**Erwarteter Impact**:
- ✅ Schutz vor Missbrauch
- ✅ Compliance-Ready
- ✅ Nachvollziehbarkeit

### Phase 4: Performance-Optimierung

**Ziel**: Skalierbarkeit

- [ ] Memory-Caching (Redis)
- [ ] N+1-Query-Problem beheben
- [ ] Database-Indexierung optimieren
- [ ] Response-Streaming verbessern
- [ ] Load-Testing (Locust)
- [ ] Profiling & Optimierung

**Erwarteter Impact**:
- ✅ 10x schnellere Memory-Queries
- ✅ Höhere Concurrency
- ✅ Reduzierte Latency

### Phase 5: Refactoring & Architektur

**Ziel**: Wartbarkeit & Erweiterbarkeit

- [ ] CoreBridge.process() aufteilen
- [ ] MCPHub in kleinere Klassen
- [ ] Exception-Handler-Decorator
- [ ] MCP-Transport-Basisklasse
- [ ] Adapter-Code-Deduplizierung
- [ ] Config-Management verbessern

**Erwarteter Impact**:
- ✅ Einfacheres Onboarding
- ✅ Schnellere Feature-Entwicklung
- ✅ Weniger Bugs

### Phase 6: Dokumentation & Developer-Experience

**Ziel**: Adoption & Community

- [ ] Umfassende README
- [ ] OpenAPI-Dokumentation
- [ ] Architektur-Diagramme (Mermaid)
- [ ] Setup-Guide (lokales Development)
- [ ] Deployment-Guide (Docker, K8s)
- [ ] Contributing-Guide
- [ ] Beispiel-Personas & Use-Cases

**Erwarteter Impact**:
- ✅ Einfaches Setup für neue Entwickler
- ✅ Klarere API-Nutzung
- ✅ Community-Beiträge

### Phase 7: Advanced Features (Optional)

**Ziel**: Innovation & Differenzierung

- [ ] Multi-Model-Support (OpenAI, Anthropic)
- [ ] Fine-Tuning-Pipeline
- [ ] A/B-Testing-Framework
- [ ] Observability (Prometheus, Grafana)
- [ ] Distributed Tracing (OpenTelemetry)
- [ ] Multi-Tenancy-Support
- [ ] GraphQL-API

**Erwarteter Impact**:
- ✅ Flexibilität
- ✅ Enterprise-Ready
- ✅ Datengetriebene Verbesserungen

---

## Metriken & Monitoring

### Key Performance Indicators (KPIs)

```python
# Beispiel: Prometheus-Metriken
from prometheus_client import Counter, Histogram, Gauge

# Request-Metriken
requests_total = Counter(
    "assistant_requests_total",
    "Total number of requests",
    ["adapter", "status"]
)

request_duration = Histogram(
    "assistant_request_duration_seconds",
    "Request duration in seconds",
    ["layer"]
)

# Memory-Metriken
memory_cache_hits = Counter("memory_cache_hits_total", "Cache hits")
memory_cache_misses = Counter("memory_cache_misses_total", "Cache misses")

# LLM-Metriken
llm_tokens_used = Counter(
    "llm_tokens_used_total",
    "Total tokens used",
    ["model", "layer"]
)

# System-Metriken
active_connections = Gauge("active_connections", "Active HTTP connections")
```

### Logging-Struktur

```python
import logging
import json
from datetime import datetime

class StructuredLogger:
    """JSON-structured logging for log aggregation"""

    def log(self, level: str, message: str, **kwargs):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            **kwargs
        }
        print(json.dumps(log_entry))

logger = StructuredLogger()

# Verwendung
logger.log(
    "info",
    "Request processed",
    conversation_id="conv-123",
    duration_ms=450,
    model="deepseek-r1:8b",
    layer="thinking"
)
```

---

## Zusammenfassung

Dieses Dokument bietet eine umfassende Übersicht über:

1. **Architektur**: 3-Layer-System mit MCP-Hub und Memory
2. **Probleme**: Kritische Performance-, Sicherheits- und Code-Qualitätsprobleme
3. **Lösungen**: Konkrete Code-Beispiele für alle wichtigen Fixes
4. **Best Practices**: Python, FastAPI, Async, Database
5. **Roadmap**: Strukturierter Plan in 7 Phasen

### Nächste Schritte

**Empfehlung**: Starte mit **Phase 1 (Kritische Fixes)**

```bash
# 1. Requirements pinnen
pip freeze > requirements.txt

# 2. Tests aufsetzen
mkdir -p tests
touch tests/conftest.py tests/test_thinking_layer.py

# 3. Async-Migration starten
# - thinking.py
# - control.py
# - output.py

# 4. Docker Security
# - non-root user
# - .dockerignore
# - HEALTHCHECK
```

Bei Fragen oder für weitere Details zu spezifischen Themen, einfach nachfragen!
