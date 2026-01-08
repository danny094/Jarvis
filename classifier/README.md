# Classifier Module

This module analyzes incoming user messages to determine their intent and how they should be handled by the memory system. It uses a specialized LLM prompt to extract structured metadata from natural language.

---

## ⚠️ IMPORTANT NOTE (Updated 2026-01-05)

**System prompt files have been archived:**
- Location: `/classifier/system-prompts/` (NOT IN USE)
- Reason: Classifier must be STATIC for security
- See: `system-prompts/README.md` for detailed explanation

**Current implementation:**
- Hardcoded prompts in `classifier.py` (STATIC)
- No dynamic loading (BY DESIGN)
- No persona influence (INTENTIONAL)

---

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

## Architecture Decision: Static vs. Dynamic

**Why classifier prompts are hardcoded:**

The classifier makes **critical infrastructure decisions**:
```
User Input → [CLASSIFIER] → Memory Layer (STM/MTM/LTM)
                   ↓
            System integrity depends on this
```

**Security concerns with dynamic prompts:**
- ❌ Could manipulate memory storage
- ❌ Could corrupt long-term memory
- ❌ Hard to debug memory issues
- ❌ Unpredictable system behavior

**Contrast with Persona System:**
- ✅ Personas affect OUTPUT (user-facing)
- ✅ Classifier affects INFRASTRUCTURE (system-critical)
- ✅ Personas can be dynamic safely
- ❌ Classifier must remain static

See `system-prompts/README.md` for full explanation.

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

## Modifying Classifier Behavior

**To change classification logic:**

1. Edit `classifier.py` directly (SYSTEM_PROMPT)
2. Test thoroughly with `pytest tests/test_classifier.py`
3. Verify memory behavior over several days
4. Document changes in git commit

**Do NOT:**
- Load prompts from external files
- Make classifier persona-dependent
- Implement hot-reload

## Files

```
classifier/
├── README.md                 ← You are here
├── classifier.py             ← Main classification logic (STATIC)
├── prompts.py               ← Prompt definitions
├── 02_CLASSIFER.md          ← Technical documentation
└── system-prompts/          ← ARCHIVED (not in use)
    ├── README.md            ← Why these are archived
    └── *.txt                ← Old prompt files (reference only)
```

## Related Systems

- **Persona System:** `/personas/` (Dynamic, user-facing)
- **Memory System:** `/sql-memory/` (Receives classifier output)
- **Output Layer:** `/core/layers/output.py` (Uses persona, not classifier)

---

**Last Updated:** 2026-01-05  
**Status:** Production, Static by Design
