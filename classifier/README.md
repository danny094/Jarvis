# Classifier Module

This module analyzes incoming user messages to determine their intent and how they should be handled by the memory system. It uses a specialized LLM prompt to extract structured metadata from natural language.

## Purpose

To automatically categorize user inputs into different memory layers and types. This allows the system to:
- Identify long-term facts (e.g., "I am 30 years old") vs. short-term noise ("Hello").
- Detect specific queries for stored information ("How old am I?").
- Capture emotional states or preferences.

## Mechanism

The `classify_message` function sends the user's text to an Ollama model (default: `qwen3:4b`) with a strict system prompt that enforces JSON output.

### Classification Fields

The model returns a JSON object with:

- **`save`** (bool): Whether this information is worth saving.
- **`layer`** (str): Target memory layer.
    - `stm`: Short-term (context, conversational).
    - `mtm`: Mid-term (moods, temporary states).
    - `ltm`: Long-term (permanent facts).
- **`type`** (str): Category of the content.
    - `fact`: Permanent information.
    - `identity`: Self-identification.
    - `preference`: Likes/dislikes.
    - `task`: To-dos.
    - `emotion`: Emotional expression.
    - `fact_query`: A question about stored facts.
    - `irrelevant`: Chitchat.
- **`key`** / **`value`**: Extracted structured key-value pair (if applicable).
- **`confidence`**: Estimated certainty (0.0 - 1.0).

## Configuration

- `CLASSIFIER_MODEL`: The Ollama model to use (default: `qwen3:4b`).
- `OLLAMA_BASE`: URL of the Ollama API (imported from global config).

## System Prompts

The module contains several text files defining system prompts for different aspects of the assistant:
- `prompt_system.txt`: The main system prompt.
- `system_core.txt`, `system_memory.txt`, etc.: Modular prompt components for safety, style, and persona.

## Usage

```python
from classifier.classifier import classify_message

result = classify_message("My name is Danny.", conversation_id="123")
print(result)
# Output:
# {
#   "save": True,
#   "layer": "ltm",
#   "type": "fact",
#   "key": "name",
#   "value": "Danny",
#   ...
# }
```
