# Jarvis Adapter & WebUI

A specialized adapter and web interface for the assistant. Jarvis is designed to be the primary, "native" interface for the `assistant-proxy`, offering deep integration with the system's 3-layer architecture.

## Overview

Jarvis consists of two main parts:
1.  **Backend Adapter**: A FastAPI-based service that translates the custom Jarvis API format to the Core Bridge.
2.  **Web Frontend**: A single-page HTML/JS application acting as a dashboard for interacting with the assistant and configuring the system.

## Backend Adapter (`adapter.py`, `main.py`)

### Purpose
To provide a low-overhead, optimized API endpoint for the Jarvis frontend. Unlike the LobeChat adapter (which mimics OpenAI), Jarvis uses a custom JSON format that exposes more system internals (like Layer metadata).

### API Endpoints
- **POST `/chat`**: Accepts a simple JSON query and returns a response with metadata.
    - **Request**:
        ```json
        {
          "query": "Hello",
          "conversation_id": "user_1",
          "stream": true
        }
        ```
    - **Response**:
        ```json
        {
          "response": "Hi there!",
          "done": true,
          "metadata": { "model": "llama3.1:8b", "memory_used": true }
        }
        ```
- **GET `/health`**: Simple status check.

## Frontend (`index.html`, `static/`)

A sophisticated dashboard providing real-time visibility into the assistant's thought process.

### Key Features
- **Layer Visualization**: Real-time status indicators ("traffic lights") for Thinking, Control, and Output layers.
- **Quick Modes**: Switch between "Fast" (skip layers), "Balanced", and "Accurate".
- **Deep Configuration**: A tabbed settings modal allowing granular control over:
    - **Layers**: Toggle individual layers, select models, adjust temperature.
    - **Memory**: Configure retrieval thresholds (Top-K) and graph walk parameters.
    - **Advanced**: Network settings, validation rules.
- **Quick Actions**: Toolbar for common tasks like clearing memory or regenerating responses.

### Upgrade Notes (v2.0.0)
The frontend recently underwent a major overhaul (Phase 1 Implemented). Key improvements include:
- Tabbed settings instead of a long list.
- Responsive design updates.
- Visual feedback for system status.

## Usage

### Running the Adapter
The Jarvis backend typically runs as part of the `assistant-proxy` docker-compose stack.
```bash
python -m adapters.jarvis.main
```

### Accessing the UI
Serve the `index.html` file using any static file server (e.g., Nginx, Python http.server) or open it directly if configured to talk to the backend.
