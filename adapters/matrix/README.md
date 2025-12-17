# Matrix Bot Adapter (Synapse Integration)

This module integrates a **Matrix / Synapse chat server** into the **Assistant-Proxy pipeline**.
It acts as a **thin adapter** that connects Matrix rooms to the Core Bridge without modifying any internal AI logic.

The bot is intentionally **logic-free**:
- no models
- no memory
- no heuristics
- no container handling

All intelligence remains inside the existing Assistant-Proxy architecture.

---

## Architecture Overview

```
Matrix Client (FluffyChat / Element)
        |
        |  @ki do something
        v
Synapse (Matrix Server)
        |
        |  Client API Events
        v
Matrix Bot Adapter
        |
        |  CoreChatRequest
        v
Assistant Proxy Core Bridge
        |
        |  Thinking → Control → Output → MCP → Containers
        v
Matrix Bot Adapter
        |
        v
Matrix Room (response)
```

The Matrix bot is conceptually **just another adapter**, equivalent to:
- LobeChat adapter
- OpenWebUI adapter

---

## Design Principles

- **No core modification required**
- **Client-agnostic** (FluffyChat, Element, mobile, web)
- **Persona-aware**
- **Room-scoped conversations**
- **Future-proof** (Matrix client changes do not affect the core)

---

## Folder Structure

```
assistant-proxy/
├── adapters/
│   ├── matrix/
│   │   ├── __init__.py
│   │   ├── client.py        # Matrix transport (matrix-nio)
│   │   ├── adapter.py       # Matrix → CoreChatRequest
│   │   ├── config.py        # Homeserver & credentials
│   │   └── persona_map.py   # Optional room → persona mapping
```

---

## Requirements

- Python 3.10+
- A running Synapse server
- A registered Matrix user for the bot
- Existing Assistant-Proxy Core Bridge

### Python dependencies

```bash
pip install matrix-nio httpx pyyaml
```

---

## Matrix Bot User Setup

Create a normal Matrix user on your Synapse server, for example:

```
@ki:your-server.local
```

Notes:
- No admin privileges required
- No Synapse plugin needed
- The bot is just a normal Matrix client without UI

---

## Authentication (Recommended)

Use an **access token** instead of a password.

1. Log in once using a Matrix client (Element / FluffyChat)
2. Copy the access token
3. Store it in `config.py`

```python
# adapters/matrix/config.py

MATRIX_HOMESERVER = "http://synapse:8008"
BOT_USER_ID = "@ki:your-server.local"
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
BOT_MENTION = "@ki"
```

---

## Adapter Logic

The adapter translates Matrix messages into the internal request format used by the Core Bridge.

- Listens for messages
- Ignores messages without `@ki`
- Converts Matrix room IDs into conversation IDs
- Forwards messages to the Core Bridge
- Returns the final response

**Important:**  
The adapter does not decide anything.  
All decisions happen in the Core Bridge layers.

---

## Conversation Mapping

Each Matrix room becomes a **stable conversation context**:

```
conversation_id = "matrix:<room_id>"
```

This guarantees:
- isolated memory per room
- deterministic behavior
- compatibility with SQL / Vector / Graph memory

---

## Persona Support

Persona selection is optional and fully decoupled.

### Static Mapping Example

```python
# adapters/matrix/persona_map.py

ROOM_PERSONAS = {
    "!devroom:server": "default",
    "!chatroom:server": "matrix-friendly",
}
```

Applied during request creation:

```python
persona = ROOM_PERSONAS.get(room_id, "default")
```

Persona logic is applied **only in the Output Layer**, never in Thinking or Control layers.

---

## Running the Bot

Start the Matrix adapter as a standalone process:

```bash
python -m adapters.matrix.client
```

The bot will:
- connect to Synapse
- sync room events
- react only to `@ki`
- post responses back into the same room

---

## Security Considerations

- The bot reacts **only to explicit mentions**
- No message interception
- No silent background analysis
- All container execution remains sandboxed
- Rate limiting and auth remain core-level concerns

---

## What This Adapter Does NOT Do

- ❌ No AI logic
- ❌ No memory management
- ❌ No tool execution
- ❌ No container control
- ❌ No Synapse modification
- ❌ No client-side hooks

This is intentional.

---

## Why This Works Well With Assistant-Proxy

- The Core Bridge remains **stable**
- New chat platforms can be added without refactoring
- Matrix becomes a first-class input channel
- Persona, memory and validation remain consistent across all UIs

---

## Summary

The Matrix bot is not an AI agent.  
It is a **transport adapter** that connects Synapse to a multi-layer AI system.

> Chat UI is presentation.  
> Synapse is distribution.  
> Intelligence lives in the Core Bridge.
