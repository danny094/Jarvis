# Ollama Client Module

An internal client library for interacting with the Ollama API, structured differently from the simple utils to support streaming and chat-specific features.

## Components

### `chat.py`
Handles interactions with the `/api/chat` endpoint.
- Supports streaming responses.
- Manages message history formatting.

### `generate.py`
Handles interactions with the `/api/generate` endpoint (raw text completion).

### `tags.py`
Utilities for listing and managing available Ollama models.
