**FIX:***
___



Root Cause:
LobeChat ALWAYS expects a `message` *field in every chunk!*
But the adapter **NOT** sends a `message` field for these chunk types:

# ❌ PROBLEM 1: thinking_stream
elif chunk_type == "thinking_stream":
    response_data = {
        "model": model,
        "created_at": created_at,
        "thinking_stream": ...,     # Custom field
        "done": False,
        # ❌ MISSING: "message"
    }

# ❌ PROBLEM 2: thinking_done  
elif chunk_type == "thinking_done":
    response_data = {
        "model": model,
        "created_at": created_at,
        "thinking": ...,            # Custom field
        "done": False,
        # ❌ FEHLTMISSING: "message"
    }

# ❌ PROBLEM 3: container_start
elif chunk_type == "container_start":
    response_data = {
        "model": model,
        "created_at": created_at,
        "container_start": {...},   # Custom field
        "done": False,
        # ❌ MISSING: "message"
    }

# ❌ PROBLEM 4: container_done
elif chunk_type == "container_done":
    response_data = {
        "model": model,
        "created_at": created_at,
        "container_done": {...},    # Custom field
        "done": False,
        # ❌ MISSING: "message"
    }
```

---

### 🧠 Why does the error occur?
```
┌─────────────────────────────────────────────────────────────────┐
│  LobeChat Frontend (React/Next.js)                              │
│                                                                 │
│  Receives: { "thinking": {...}, "done": false }                │
│                                                                 │
│  try:  e.message.thinking                                  │
│             └─ e.message is UNDEFINED!                        │
│                └─ TypeError!                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

// LobeChat excepts:
const content = chunk.message?.content;
const thinking = chunk.message?.thinking;  // ← Here it crash !
___
***Solution***

# ✅ Empty message for all custom chunks
elif chunk_type == "thinking_done":
    response_data = {
        "model": model,
        "created_at": created_at,
        "message": {"role": "assistant", "content": ""},  # ← FIX
        "thinking": metadata.get("thinking", {}),
        "done": False,
    }

s