[README.md](https://github.com/user-attachments/files/23788527/README.md)

# 📘 Ollama-Pipeline-Bridge
*A universal bridge for multi-agent pipelines, chat interfaces, and memory systems.*

Ollama-Pipeline-Bridge is a modular, extensible proxy server that connects Ollama models to any chat interface, multi-agent workflow, or custom AI pipeline.  
It acts as a central integration layer between:

- chat UIs and frontends  
- specialized agents  
- a persistent memory system  
- validation/classification modules  
- the Ollama LLM backend  

With this bridge, you can build your own multi-agent architecture including tool routing, memory recall, and standardized request/response handling.

---

# 🚀 Features

- **⚡ Universal integration**  
  Connects Ollama to any chat UI or external system.

- **🧩 Multi-agent pipeline**  
  Build your own agents (planner, classifier, validator, persona, tool agents, etc.).

- **🧠 Integrated persistent memory**  
  SQL-backed memory storage for user history, agent states, and long-term context.

- **🔌 Modular adapter architecture**  
  Easily plug in new interfaces, tools, or external services.

- **🐳 Docker-ready**  
  Full Docker setup for local or server deployments.

- **🛠 Highly extensible**  
  Add new modules, agents, validators, memory types, or adapter layers.

---

# 🏗 Project Structure

```
Ollama-Pipeline-Bridge/
│
├─ adapters/         → Connectors for chat UIs and external systems
├─ classifier/       → Text classification logic and routing helpers
├─ core/             → Main pipeline + routing system
├─ memory/           → Memory interfaces and retrieval logic
├─ modules/          → Agents, tools, role modules
├─ ollama/           → Ollama API integration
├─ sql-memory/       → SQL-backed persistent memory engine
├─ utils/            → Helpers, logging, formatting, etc.
├─ validator-service/→ Optional output validation service
│
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
└─ main.py
```

---

# 🧠 Architecture Overview

```
                +------------------------------+
                |       Chat Interface         |
                |   (Web, App, CLI, Discord)   |
                +---------------+--------------+
                                |
                                v
                    +-------------------------+
                    |        adapters/        |
                    | (Translate UI ↔ Bridge) |
                    +-----------+-------------+
                                |
                                v
                  +-------------------------------+
                  |              core/            |
                  |    Routing & Pipeline Logic  |
                  +---------------+---------------+
                                  |
      ---------------------------------------------------------
      |                    |                  |                |
      v                    v                  v                v
+-------------+     +-------------+     +-----------+     +-----------+
|  modules/   |     | classifier/ |     | validator |     |   tools   |
|   Agents    |     |  Router     |     | (optional)|     | (optional)|
+------+-------+     +------+-----+     +-----+------+     +-----+-----+
       |                     |                 |                 |
       -----------------------                 |                 |
                     |                         |                 |
                     v                         v                 v
             +--------------------------------------------------------+
             |           memory/ + sql-memory/ (persistent)           |
             | Stores: history, state, profile, context, metadata     |
             +---------------------------+-----------------------------+
                                         |
                                         v
                                +----------------+
                                |     Ollama     |
                                +----------------+
```

---

# 📦 Installation

## 🔧 Local Installation

```bash
git clone https://github.com/danny094/Ollama-Pipeline-Bridge.git
cd Ollama-Pipeline-Bridge

pip install -r requirements.txt

python main.py
```

---

## 🐳 Docker Deployment (Recommended)

```bash
docker compose up --build
```

The server will be available at:

```
http://localhost:8080
```

---

# ⚙️ Configuration

Configuration is located in:

```
config.py
```

Configurable options include:

- Ollama endpoint  
- default models  
- memory backend  
- logging  
- agent pipeline  
- adapter settings  

---

# 🧪 Basic Processing Flow

1. The user sends a message to a chat frontend.  
2. An adapter converts it to the internal pipeline format.  
3. The core router selects the appropriate agent.  
4. Memory is queried for relevant context.  
5. The agent processes the request or calls Ollama.  
6. The formatted response is returned to the UI.

---

# 🧱 Agents / Modules

Inside `modules/` you can define unlimited custom agents:

- planner agents  
- persona agents  
- validators  
- classifier and router agents  
- tool-specific agents  

Agents can be chained or routed dynamically.

---

# 🧠 Memory System

The SQL-backed memory system stores:

- conversation history  
- long-term user data  
- agent state  
- metadata  
- global variables  

Memory loads and updates automatically during routing.

---

# 🌐 API Endpoints

```
POST /api/chat
POST /api/generate
GET  /api/memory
```

You can use the bridge as a standalone AI backend.

---

# 🧩 Creating Custom Adapters

Adapters consist of:

- input parsers  
- output formatters  

You can connect:

- web interfaces  
- Discord bots  
- custom dashboards  
- CLI tools  
- AnythingLLM  
- LobeChat  

---

# 🚧 Roadmap

- [ ] Automatic agent routing  
- [ ] Optional vector memory  
- [ ] Web dashboard  
- [ ] Plugin system  
- [ ] Unit tests  
- [ ] API authentication  
- [ ] Live JSON log viewer  

---

# 📄 License

Licensed under **CC BY-NC 4.0**.  
Commercial use is not permitted.

---

# ❤️ Maintainer

Developed by **Danny**.  
Issues and contributions are welcome.
