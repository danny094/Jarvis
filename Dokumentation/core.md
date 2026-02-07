# TRION Core Module Documentation

**Path:** `/DATA/AppData/MCP/Jarvis/Jarvis/core/`
**Version:** 4.0 (Adaptive Architecture)
**Last Updated:** 2026-02-07

## 1. Overview

The `core` module is the **Brain of TRION**. It implements the **Cognitive Architecture** that drives the AI's reasoning, decision-making, and execution capabilities. Unlike simple LLM wrappers, TRION uses a multi-layered approach to separate planning, verification, and action.

---

## 2. Architecture: The 4-Layer Model

TRION follows a "System 2 Thinking" approach, broken down into 4 distinct layers:

| Layer | Name | Model (Typ.) | Responsibility |
|-------|------|--------------|----------------|
| **0** | **Tool Selector** | Qwen 1.5B | **Pre-Filtering:** Selects relevant tools from the massive inventory (65+) *before* reasoning begins. Prevents context pollution. |
| **1** | **Thinking** | DeepSeek-R1 | **Planning:** Analyzes intent, checks memory needs, and creates a structured execution plan. Does NOT execute tools. |
| **2** | **Control** | Qwen 2.5 | **Verification:** acts as the "Critic". Checks the plan for safety, logic errors, and policy violations. Streams "Sequential Thinking" steps. |
| **3** | **Output** | Llama 3 | **Action:** Generates the final response and executes the specific tools requested. Uses Native Tool Calling. |

---

## 3. Key Components

### 3.1 Orchestrator (`orchestrator.py`)

The **PipelineOrchestrator** is the central nervous system. It manages the flow between layers and handles streaming data to the frontend.

* **Responsibilities:**
  * Initializing the ContextManager and Layers.
  * Routing the request through Layer 0 $\to$ 1 $\to$ 2 $\to$ 3.
  * **Heuristic Tool Argument Construction:** (Currently) fills in missing tool parameters (e.g., for `home_write`).
  * **Streaming:** Manages SSE (Server-Sent Events) for real-time feedback.
  * **Chunking:** Splits large inputs for processing via MCP.

### 3.2 layer 0: Tool Selector (`tool_selector.py`)

* **Purpose:** Solves "Attention Dilution" by filtering tools.
* **Mechanism:**
    1. **Semantic Search:** Finds top 15 relevant tools via vector search.
    2. **LLM Selection:** Uses a small, fast model to pick the best 3-5 tools.
* **Input:** User Query + Context.
* **Output:** List of Tool Names.

### 3.3 Layer 1: Thinking (`layers/thinking.py`)

* **Purpose:** Deep Reasoning & Planning.
* **Prompt:** `THINKING_PROMPT` enforces a structured JSON output containing:
  * `intent`: What does the user want?
  * `suggested_tools`: Which tools are needed?
  * `complexity`: 1-10 scale.
  * `needs_memory`: Should we search the database?
* **Streaming:** Shows the user "TRION is thinking..." with live chunks.

### 3.4 Layer 2: Control (`layers/control.py`)

* **Purpose:** Safety & Logic Check.
* **Features:**
  * **Sequential Thinking v5:** For complex tasks, it streams a step-by-step logic chain (`## Step 1...`) to the UI.
  * **LightCIM:** Fast keyword-based safety checks.
  * **Policy Engine:** Can block actions or request user confirmation (e.g., "Create Skill").

### 3.5 Layer 3: Output (`layers/output.py`)

* **Purpose:** Final Execution & Response.
* **Mechanism:**
  * Converts MCP Tools to **Native Ollama Format**.
  * Executes the "Tool Loop": Call Tool $\to$ Get Result $\to$ Feed to LLM $\to$ Token Stream.
  * Injects the **Persona** (Tone, Style).

### 3.6 Context Manager (`context_manager.py`)

* **Purpose:** Data Retrieval Hub.
* **Sources:**
  * **Memory:** User facts, graph data.
  * **System Knowledge:** Documentation about tools (RAG).
  * **Conversation History:** Recent chat logs.

### 3.7 Safety (`safety/light_cim.py`)

* **Purpose:** Low-latency safety guardrails.
* **Checks:** Regex/Keyword matching for dangerous topics (PII, violence, system attacks) before the LLM even sees the request.

### 3.8 Persona (`persona.py`)

* **Purpose:** Dynamic System Prompt generation.
* **Features:**
  * Adapts to User Profile (Name, context).
  * Injects "Home Awareness" (TRION Home instructions).
  * Defines Capabilities and Guidelines.

---

## 4. Data Flow

1. **Request:** User sends message.
2. **Safety:** `LightCIM` checks for immediate red flags.
3. **Layer 0:** `ToolSelector` reduces 65 tools to 5 relevant ones.
4. **Layer 1:** `ThinkingLayer` analyzes intent and requests specific tools/memory.
5. **Context:** `Orchestrator` fetches Memory and Tool Context.
6. **Layer 2:** `ControlLayer` verifies the plan. If complex, runs `Sequential Thinking`.
7. **Layer 3:** `OutputLayer` executes valid tools (via `mcp.hub`) and streams the final answer.
8. **Memory:** New facts are saved back to the Learning Loop.

---

## 5. Recent Changes (v4.0)

* **Tool Selector (Layer 0):** Added to improve tool selection accuracy.
* **TRION Home Awareness:** `persona.py` now instructs TRION to use persistent storage.
* **Heuristic Argument Fix:** `orchestrator.py` now specifically handles `home_` tools to fix missing parameters.
