# Core Module

The central brain of the assistant proxy. It orchestrates the processing of requests through a multi-layer pipeline designed to mimic complex reasoning capabilities ("System 2 thinking").

## Purpose

To act as the bridge between the external interface (Adapters) and the internal logic (LLMs, Memory). It transforms raw requests into a standardized format, simulates a thinking process, retrieves relevant memories, and generates a controlled response.

## Architecture

The `CoreBridge` executes a pipeline for each request:

1.  **Thinking Layer** (`layers/thinking.py`):
    - Uses a reasoning model (e.g., DeepSeek R1 or Qwen) to analyze the user's request.
    - Generates a "chain of thought" or an implementation plan.
2.  **Memory Retrieval** (`bridge.py`):
    - Searches for relevant facts in the `sql-memory` system based on the Thinking Layer's analysis.
    - Checks both user-specific memory and system-wide knowledge (tools context).
3.  **Control Layer** (`layers/control.py`):
    - Acts as a critic. It reviews the plan and the available memory.
    - Ensures safety, relevance, and adherence to system instructions.
4.  **Output Layer** (`layers/output.py`):
    - Generates the final natural language response for the user.
    - Synthesizes the initial thought, the retrieved memory, and the critic's feedback.

## Key Components

### `bridge.py`
Contains the `CoreBridge` class. It manages the lifecycle of a request, handles the "Thinking vs. Speaking" logic, and allows for streaming responses that show the thought process (similar to "Extended Thinking").

### `models.py`
Defines the standard data structures:
- `CoreChatRequest`: Normalized input format.
- `CoreChatResponse`: Normalized output format.
- `Message`: Standard message object.

### Layers (`layers/`)
- **`thinking.py`**: Interacts with reasoning models to produce a "Note to self".
- **`control.py`**: Validates the reasoning and ensures constraints.
- **`output.py`**: Formats the final answer.

## Usage

The Core module is primarily used by Adapters.

```python
from core.bridge import get_bridge
from core.models import CoreChatRequest, Message, MessageRole

bridge = get_bridge()

req = CoreChatRequest(
    model="default",
    messages=[Message(role=MessageRole.USER, content="Hello")]
)

# Synchronous
response = bridge.process(req)
print(response.content)

# Streaming
for chunk, done, metadata in bridge.process_stream(req):
    print(chunk, end="")
```
