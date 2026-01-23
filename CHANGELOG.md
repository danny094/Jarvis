# Changelog

All notable changes to TRION are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-01-23

### 🚀 Added

#### Sequential Thinking v5.0

- Live streaming of thinking process (`seq_thinking_stream` events)
- Two-phase thinking: internal reasoning → structured steps
- Step-by-step display in TRION Panel
- Support for DeepSeek-R1 thinking format

#### CIM Integration

- Causal Inference Module for hallucination prevention
- LightCIM for fast validation
- CIM MCP Server for external integration

#### TRION Panel

- Observability UI for Sequential Thinking
- Live thinking stream display
- Step progress visualization
- Collapsible thinking sections

#### Memory System

- SQL-based memory storage
- Graph relationships
- Semantic search with embeddings
- Auto-save conversations

#### MCP Architecture

- Model Context Protocol server support
- Sequential Thinking MCP
- CIM Server MCP
- SQL-Memory MCP
- Extensible tool integration

#### Adapters

- Jarvis WebUI (main interface)
- LobeChat compatibility adapter
- OpenAI-compatible API
- Admin API for management

### 🔧 Fixed

#### Event System

- Fixed event passthrough in admin-api
- Fixed `task_id` consistency in Sequential Thinking
- Fixed streaming event handling in frontend
- Fixed flat event types for proper routing

#### Streaming

- Fixed empty `thinking` field handling
- Fixed content buffer accumulation
- Fixed step parsing from DeepSeek responses

#### Frontend

- Fixed Sequential Plugin event listeners
- Fixed TRION Panel updates
- Fixed thinking stream display

### 📝 Changed

- Renamed `thinking_stream` → `seq_thinking_stream`
- Renamed `thinking_done` → `seq_thinking_done`
- Simplified registry task management
- Improved system prompts for better formatting

---

## [0.9.0] - 2026-01-15

### Added

- Initial 3-Layer Pipeline (Thinking → Control → Output)
- Basic Ollama integration
- Jarvis WebUI prototype
- Docker containerization

### Changed

- Refactored from monolith to microservices
- Moved to async/await patterns

---

## [0.8.0] - 2025-12-20

### Added

- Initial project structure
- Basic proxy functionality
- LobeChat adapter

---

## Legend

- 🚀 **Added** - New features
- 🔧 **Fixed** - Bug fixes
- 📝 **Changed** - Changes in existing functionality
- ⚠️ **Deprecated** - Soon-to-be removed features
- 🗑️ **Removed** - Removed features
- 🔒 **Security** - Security fixes
