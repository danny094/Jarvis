# Assistant-Proxy: Plugin-basierte Adapter-Architektur

## Übersicht

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    LobeChat     │     │   Open WebUI    │     │   Andere UI     │
│  (denkt es ist  │     │  (denkt es ist  │     │                 │
│    Ollama)      │     │    Ollama)      │     │                 │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ LobeChat-Adapter│     │OpenWebUI-Adapter│     │  Neuer Adapter  │
│   Port: 8100    │     │   Port: 8200    │     │   Port: 8xxx    │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │      Core-Bridge       │
                    │  (Zentrale Logik)      │
                    │  - Meta-Decision       │
                    │  - Classifier          │
                    │  - Memory (MCP)        │
                    │  - Validator           │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │        Ollama          │
                    │   (LLM Backend)        │
                    └────────────────────────┘
```

## Verzeichnisstruktur

```
assistant-proxy/
├── adapters/                    # Plugin-Verzeichnis
│   ├── __init__.py
│   ├── base.py                  # Abstract Base Adapter
│   │
│   ├── lobechat/                # LobeChat Plugin
│   │   ├── __init__.py
│   │   ├── adapter.py           # Request/Response Transformation
│   │   ├── main.py              # Standalone FastAPI Server
│   │   └── Dockerfile
│   │
│   └── openwebui/               # Open WebUI Plugin (Template)
│       ├── __init__.py
│       ├── adapter.py
│       └── main.py
│
├── core/                        # Zentrale Logik
│   ├── __init__.py
│   ├── models.py                # Interne Datenmodelle
│   └── bridge.py                # Core-Bridge (Hauptlogik)
│
├── classifier/                  # Message-Klassifizierung
├── mcp/                         # Memory-Client
├── modules/                     # Meta-Decision, Validator
├── utils/                       # Logger, Prompt-Builder
│
└── docker-compose.new.yml       # Neue Docker-Konfiguration
```

## Neuen Adapter erstellen

### 1. Adapter-Klasse erstellen

```python
# adapters/meinechatui/adapter.py

from adapters.base import BaseAdapter
from core.models import CoreChatRequest, CoreChatResponse, Message, MessageRole

class MeineChatUIAdapter(BaseAdapter):
    
    @property
    def name(self) -> str:
        return "meinechatui"
    
    def transform_request(self, raw_request: dict) -> CoreChatRequest:
        # Raw-Request der Chat-UI → CoreChatRequest
        messages = [
            Message(role=MessageRole.USER, content=raw_request["text"])
        ]
        return CoreChatRequest(
            model=raw_request.get("model", "default"),
            messages=messages,
            source_adapter=self.name,
        )
    
    def transform_response(self, response: CoreChatResponse) -> dict:
        # CoreChatResponse → Format der Chat-UI
        return {
            "reply": response.content,
            "model": response.model,
        }
```

### 2. FastAPI-Server erstellen

```python
# adapters/meinechatui/main.py

from fastapi import FastAPI, Request
from adapters.meinechatui.adapter import MeineChatUIAdapter
from core.bridge import get_bridge

app = FastAPI()
adapter = MeineChatUIAdapter()
bridge = get_bridge()

@app.post("/chat")
async def chat(request: Request):
    raw_data = await request.json()
    core_request = adapter.transform_request(raw_data)
    core_response = await bridge.process(core_request)
    return adapter.transform_response(core_response)
```

### 3. Zu docker-compose.yml hinzufügen

```yaml
meinechatui-adapter:
  build:
    context: .
    dockerfile: adapters/meinechatui/Dockerfile
  ports:
    - "8300:8300"
  environment:
    - OLLAMA_BASE=http://ollama:11434
    - MCP_BASE=http://mcp-sql-memory:8081/mcp
```

## Verwendung

### Mit Docker Compose

```bash
# Alte docker-compose.yml sichern
mv docker-compose.yml docker-compose.old.yml
mv docker-compose.new.yml docker-compose.yml

# Services starten
docker-compose up -d --build
```

### In LobeChat eintragen

```
Ollama-URL: http://<server-ip>:8100
```

LobeChat denkt, es redet mit Ollama – tatsächlich geht alles durch die Bridge.

## Datenfluss

1. **LobeChat** sendet Ollama-kompatiblen Request an `http://server:8100/api/chat`
2. **LobeChat-Adapter** transformiert zu `CoreChatRequest`
3. **Core-Bridge** führt Pipeline aus:
   - Meta-Decision Layer
   - Classifier
   - Memory Retrieval (MCP)
   - Ollama Call
   - Validator
   - Memory Save
4. **Core-Bridge** gibt `CoreChatResponse` zurück
5. **LobeChat-Adapter** transformiert zu Ollama-Format
6. **LobeChat** zeigt Antwort an

## Interne Modelle

```python
@dataclass
class CoreChatRequest:
    model: str
    messages: List[Message]
    conversation_id: str = "global"
    temperature: Optional[float] = None
    source_adapter: str = "unknown"

@dataclass
class CoreChatResponse:
    model: str
    content: str
    done: bool = True
    classifier_result: Optional[dict] = None
    memory_used: bool = False
```
