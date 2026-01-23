# TRION Architecture

## Decision, Control & Reasoning Pipeline

> **Goal**
> Build a transparent, explainable, and safe AI orchestration architecture that decides **when structured reasoning is necessary**, **how it should be executed**, and **when it must be limited or stopped**.

---

## Why TRION Exists

Most AI systems either:

* overthink trivial tasks, or
* underthink critical ones.

**TRION is built to do neither.**
It enforces *intentional reasoning*: structured thinking is used **only when it adds correctness, safety, or clarity**.

> **Safety forces explainability. Explainability forces architecture.**

---

## Core Philosophy

TRION strictly separates responsibilities:

* **Thinking** → proposes intent and complexity
* **Control** → validates risk and necessity
* **Sequential Thinking (ST)** → plans execution
* **CIM** → validates reasoning quality
* **Output** → executes and responds

> Not every intelligent-sounding question deserves structured reasoning.

CIM is **not** an end-user feature.
It is a **governance layer between reasoning and execution**.

---

## High-Level Pipeline

```
USER QUERY
   ↓
THINKING LAYER (DeepSeek)
   ↓
MEMORY RETRIEVAL
   ↓
CONTROL LAYER (Qwen + Light CIM)
   ↓
SEQUENTIAL THINKING (Planner)
   ↓
CIM MODES (Temporal / Strategic / Validation)
   ↓
OUTPUT LAYER
```

---

## Layer Responsibilities

> ⚠️ **Implementation Note**
> Some components are intentionally **v0 / placeholder**. This document describes the **target architecture**, not just the current code state.

---

### 1. Thinking Layer (DeepSeek)

**Role**: Intent & complexity *proposal*

**Strengths**

* Full conversation context
* Strong pattern and intent detection
* Early hallucination risk estimation

**Limitations**

* May overestimate complexity
* No access to CIM datasets
* Cannot enforce safety rules

**Output (Proposal Only)**

```json
{
  "needs_sequential_thinking": true,
  "sequential_complexity": 7,
  "suggested_cim_modes": ["temporal", "strategic"],
  "hallucination_risk": "high",
  "reasoning_type": "causal"
}
```

> Thinking can **suggest**, but never decide.

---

### 2. Control Layer (Qwen + Light CIM)

**Role**: Validation, correction, and gating

**Golden Rule**
Control never reasons about *content*.
It reasons about **risk, structure, and necessity**.

**Responsibilities**

* Approve or reject structured reasoning
* Enforce Sequential Thinking when required
* Add or remove CIM modes
* Prevent over-engineering

**Example Output**

```json
{
  "approved": true,
  "final_instruction": "Proceed with structured reasoning",
  "warnings": ["Financial decision detected"],
  "corrected_cim_modes": ["temporal", "strategic", "heavy"]
}
```

---

### 3. Sequential Thinking (ST) – Planner

**Role**: Planning and decomposition (not validation)

#### Current Status

⚠️ **v0 – Placeholder**

The current ST implementation generates ordered steps **without real planning**:

* no dependency analysis
* no reordering
* no task boundary detection

```python
def think(message: str, steps: int = 3):
    for i in range(steps):
        chain.append({
            "step": i + 1,
            "thought": f"Analyse Schritt {i+1}: {message}"
        })
```

#### Target Design

ST will evolve into a **true planner**:

* dependency-aware execution plans
* task boundary detection
* reordering and optimization

```
[Step 1: Collect data]
[Step 2: Analyze factors]
[Step 3: Compare outcomes]
[Step 4: Synthesize result]
```

The abstraction is intentional to allow future planner strategies.

---

## CIM – Cognitive Integrity Modules

CIM validates *how* reasoning is performed, not *what* the answer is.

Modes are **activated contextually** and may differ per phase.

---

### TEMPORAL — Context Holder

* **Always active when ST runs**
* Preserves long context
* Tracks inter-step dependencies

> Control never stores long context. TEMPORAL does.

---

### STRATEGIC — Plan Optimizer

* Activated for multi-step tasks
* Reorders steps
* Detects parallelization opportunities

---

### LIGHT — Fast Sanity Check

* Always-on during execution
* <100 ms overhead
* Detects obvious logical errors

**Dataset**

* Top 10 common cognitive biases (embedded)

---

### HEAVY — Deep Validation

**Triggered when:**

* High complexity (≥7)
* Financial / medical / legal domains
* High hallucination risk

**Capabilities**

* Full causal validation
* Bias & assumption detection
* Explicit causal graphs

**Cost**: High latency, high confidence

> HEAVY is exclusive and blocking.

---

### SIMULATION — Scenario Explorer

* What-if reasoning
* Multiple outcome generation
* Feeds results back into ST

---

## CIM Timing Strategy

**Hybrid Model (Recommended)**

| Phase            | Active Modes                        |
| ---------------- | ----------------------------------- |
| Before Execution | TEMPORAL, STRATEGIC, SIMULATION     |
| During Execution | LIGHT (always), HEAVY (if required) |

---

## Performance Philosophy

* Not all queries deserve worst-case latency
* Confidence-based short-circuiting
* Hard execution budgets

**Targets**

* No ST: `< 2s`
* ST + LIGHT: `< 8s`
* ST + HEAVY: `< 20s`

---

## Memory in the Pipeline

Memory retrieval is **mandatory** between Thinking and Control.

```
THINKING → MEMORY → CONTROL
```

Control decisions are made **with memory context**, never raw input alone.

---

## Error Handling & Fallbacks

* **Control Block** → safe default + explanation
* **CIM Failure** → reduced validation + warning
* **ST Timeout** → partial plan + retry option
* **Memory Failure** → uncertainty explicitly stated

---

## Logging & Tracing

* **Decision Logs** (`/logs/decisions`) – human-readable
* **Trace Logs** (`/logs/traces`) – machine-readable
* **Debug Logs** (`/logs/debug`) – errors & metrics

Retention: 30 days or last 1000 traces

---

## Phase 1 – Implementation Scope

**Included**

* Thinking → Control → ST → TEMPORAL → LIGHT

**Deferred**

* HEAVY
* SIMULATION
* Feedback learning

---

## Roadmap Principle

TRION is not designed to always think harder.

It is designed to **know when structured thinking is necessary** — and when it is not.
