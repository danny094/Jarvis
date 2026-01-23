# Assistant Proxy Adapters

This module handles the translation between external chat interfaces and the internal `assistant-proxy` Core. It uses an Adapter Pattern to allow different UIs to be plugged in easily.

## Purpose

To support multiple chat interfaces (e.g., LobeChat, OpenWebUI) without changing the core logic of the assistant. Each adapter transforms incoming requests into a standardized `CoreChatRequest` and transforms the response back to the specific format expected by the UI.

## Structure

### `base.py`
Defines the `BaseAdapter` abstract class. All new adapters must inherit from this and implement:
- `transform_request(raw_request)`: Converts UI-specific JSON to `CoreChatRequest`.
- `transform_response(core_response)`: Converts `CoreChatResponse` back to UI-specific JSON.

### Supported Adapters

#### LobeChat
- **Path**: `lobechat/`
- **Description**: Adapter for the LobeChat interface. Includes specialized logic for handling LobeChat's specific plugin and message formats.
- **Components**:
    - `adapter.py`: The adapter implementation.
    - `main.py`: Entry point for a standalone LobeChat integration service.

#### OpenWebUI
- **Path**: `openwebui/`
- **Description**: Adapter for Open WebUI (formerly Ollama WebUI).
- **Components**:
    - `adapter.py`: The adapter implementation.
    - `main.py`: Entry point for OpenWebUI integration.

#### Jarvis
- **Path**: `Jarvis/`
- **Description**: A custom dashboard/UI named "Jarvis".
- **Components**:
    - `adapter.py`: Adapter logic.
    - `index.html`: The frontend for the Jarvis dashboard.

## Usage

To add a new adapter:
1. Create a new directory under `adapters/`.
2. Create an `adapter.py` that inherits from `BaseAdapter`.
3. Implement the transformation methods.
4. Register the adapter in the main application logic.
