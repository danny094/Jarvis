
***Jarvis becomes TR|ON. A completely new web user interface. An operating system in the browser.***

<img width="1866" height="913" alt="Bildschirmfoto 2026-01-27 um 02 50 07" src="https://github.com/user-attachments/assets/49e890a1-d0c0-4f86-8d0a-c72ddfc3d7b5" />


[README.md](https://github.com/user-attachments/files/24833535/README.md)
<div align="center">

# 🚀 TRION - AI Pipeline Framework

**A modular, self-hosted AI assistant architecture with intelligent reasoning capabilities**

[![Discord](https://img.shields.io/discord/<SERVER_ID>?label=Discord&logo=discord)](https://discord.gg/KaAUUQGX)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg?style=flat-square)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](docker-compose.yml)

***Easy MCP Drag and Drop install***
<div align="center">
</div>

[![Video Vorschaubild](https://img.youtube.com/vi/k627-Eu-i5U/0.jpg)](https://www.youtube.com/watch?v=ryk627-Eu-i5U)
<div align="center">

</div>

***Expandable plugin system***
<div align="center">
         
[![Video Vorschaubild](https://img.youtube.com/vi/TzkBheaJAcE/0.jpg)](https://www.youtube.com/watch?v=TzkBheaJAcE)
<div align="center">

</div>

***Upload and edit your own persona***
<img width="1866" height="913" alt="Bildschirmfoto 2026-01-27 um 03 24 39" src="https://github.com/user-attachments/assets/64bd0cf0-3d86-4960-8989-ca5ed32d3096" />

</div>

***Ready for the future***
<img width="1866" height="958" alt="Bildschirmfoto 2026-01-27 um 03 27 52" src="https://github.com/user-attachments/assets/f22b7851-09a6-48d0-bfca-49d51526c330" />


</div>
---
## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧠 **3-Layer Pipeline** | Thinking → Control → Output architecture for intelligent responses |
| 🔄 **Sequential Thinking** | Step-by-step reasoning with live streaming |
| 🎯 **CIM Integration** | Causal Inference Module for hallucination prevention |
| 💾 **Memory System** | SQL + Graph + Semantic search for context-aware responses |
| 🔌 **MCP Servers** | Model Context Protocol for extensible tool integration |
| 🌐 **Multiple Adapters** | Jarvis WebUI, LobeChat, OpenAI-compatible API |
| 🐳 **Docker Ready** | One-command deployment with docker-compose |
| 🔒 **Self-Hosted** | 100% local, GDPR-compliant, no cloud dependencies |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ADAPTERS                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │   Jarvis   │  │  LobeChat  │  │  OpenAI    │                │
│  │   WebUI    │  │  Adapter   │  │  Compat    │                │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘                │
└────────┼───────────────┼───────────────┼────────────────────────┘
         │               │               │
         └───────────────┼───────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     CORE BRIDGE                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   THINKING   │→ │   CONTROL    │→ │    OUTPUT    │          │
│  │    Layer     │  │    Layer     │  │    Layer     │          │
│  │              │  │              │  │              │          │
│  │ • Intent     │  │ • LightCIM   │  │ • Response   │          │
│  │ • Complexity │  │ • Sequential │  │ • Streaming  │          │
│  │ • Planning   │  │ • Validation │  │ • Memory     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MCP SERVERS                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ Sequential  │  │    CIM      │  │ SQL-Memory  │             │
│  │  Thinking   │  │   Server    │  │   Server    │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                       OLLAMA                                    │
│   DeepSeek-R1 | Llama 3.1 | Qwen | Any local model             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Ollama with models installed (e.g., `ollama pull deepseek-r1:8b`)

### Installation

```bash
# Clone the repository
git clone https://github.com/danny094/Jarvis.git
cd Jarvis

# Start all services
docker-compose up -d

# Access the WebUI
open http://localhost:8400
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| Jarvis WebUI | 8400 | Main user interface |
| Admin API | 8200 | Backend API |
| Ollama | 11434 | LLM inference |
| SQL-Memory | 8010 | Memory MCP server |

---

## 📁 Project Structure

```
trion/
├── adapters/              # Frontend adapters
│   ├── Jarvis/            # Main WebUI
│   ├── admin-api/         # Backend API
│   └── lobechat/          # LobeChat compatibility
├── core/                  # Core pipeline
│   ├── bridge.py          # Main orchestrator
│   └── layers/            # Thinking, Control, Output
├── mcp-servers/           # MCP tool servers
│   ├── sequential-thinking/
│   └── cim-server/
├── sql-memory/            # Memory system
├── documentation/         # Detailed docs
└── docker-compose.yml     # Deployment config
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Architecture v5](documentation/ARCHITECTURE_v5.md) | Detailed architecture docs |
| [API Reference](documentation/API_REFERENCE.md) | API endpoints & usage |
| [TRION Panel](documentation/TRION_PANEL_README.md) | Observability UI |
| [Contributing](CONTRIBUTING.md) | Contribution guidelines |
| [FAQ](FAQ.md) | Frequently asked questions |

---

## 🔧 Configuration

Key environment variables in `docker-compose.yml`:

```yaml
OLLAMA_BASE: http://ollama:11434
THINKING_MODEL: deepseek-r1:8b
CONTROL_MODEL: deepseek-r1:8b
OUTPUT_MODEL: llama3.1:8b
```

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
A big thank you goes to [Frank Brsrk / Agentarium] for providing CIM
---

## 📜 License

This project is licensed  - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Built with ❤️ and AI assistance**

[Discord](https://discord.gg/t8jAxMtk) · [Issues](https://github.com/yourusername/trion/issues) · [Docs](documentation/)

</div>
