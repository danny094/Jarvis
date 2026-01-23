# Implementation Plan: Context Graph Builders

This plan outlines the design and development of 5 specialized Context Graph Builders for the Causal Intelligence Module (CIM). These builders transform user queries into structured reasoning DAGs (Directed Acyclic Graphs) that orchestrate the transition from Knowledge to Execution.

## 1. Directory Structure
```text
local_graph_builders/          # Local/Full builders
cloud_n8n_code_tools/        # Unified and flattened n8n blocks
cim.py                   # The Gatekeeper CLI Switch
```

## 2. The Gatekeeper (On-Demand Switch)
*   **Purpose:** Prevent latency and compute waste on non-causal queries.
*   **Trigger Mechanism:** 
    *   **Flag:** `-c` or `--causal` in CLI call.
    *   **Prefix:** Start query with `/c` or `/causal`.
*   **Manual Override:** Use `-m [mode]` (e.g., `-m temporal`) to force a specific reasoning engine regardless of query text.
*   **Function:** Acts as a Binary Switch. If False, the system bypasses the Causal Intelligence Module and uses standard LLM associative reasoning.

## 3. Shared Foundation: `BaseBuilder`
*   **Role:** Abstract class providing core RAG retrieval logic.
*   **Features:**
    *   Vector search wrappers for `knowledge_rag` and `procedural_rag`.
    *   JSON serialization for graph structures.
    *   Standardized `GraphNode` and `GraphEdge` objects.

## 4. Specialized Builders

### A. LightGraphBuilder (The Fast-Path)
*   **Goal:** Minimal latency for simple causal inquiries.
*   **Logic:**
    1.  Retrieve top 1 Knowledge Prior.
    2.  Retrieve top 1 Procedural Template.
    3.  Generate a linear sequence of steps.
*   **Output:** A simple 1D graph (Path) of reasoning.

### B. HeavyGraphBuilder (The Analytical-Path)
*   **Goal:** Deep validation and fallacy prevention.
*   **Logic:**
    1.  Full variable extraction from `domain_graphs.csv`.
    2.  Multi-prior retrieval (3+ priors).
    3.  **Logic Gate Injection:** Cross-reference context with `anti_patterns.csv`. If a match exists (e.g., "Simpson's Paradox"), inject a mandatory validation node.
*   **Output:** A multi-layered DAG with hard-linked tools.

### C. StrategicGraphBuilder (In-Depth: Causal + Decision)
*   **Goal:** Solve "What should I do?" rather than "Why did it happen?".
*   **Logic:**
    1.  Merge Causal DAGs with **Influence Diagrams**.
    2.  **Node Types:** Observation nodes, Action (Decision) nodes, and Utility (Value) nodes.
    3.  Heuristic retrieval for optimization strategies.
*   **Output:** A graph that identifies the "Best Intervention" based on causal constraints.

### D. TemporalGraphBuilder (The Chronological-Path)
*   **Goal:** Solve time-series and feedback-loop problems.
*   **Logic:**
    1.  Retrieve `PROC009` (Temporal Analysis) and `PROC010` (Replication).
    2.  Node attributes include `lag_time` and `timestamp_relative`.
    3.  Identifies cyclical edges (feedback loops) and handles recursion limits.
*   **Output:** A sequence-aware graph where edges are weighted by temporal precedence.

### E. SimulationGraphBuilder (The Counterfactual-Path)
*   **Goal:** "What if" scenario branching.
*   **Logic:**
    1.  Retrieve `PROC005` (Counterfactual Reasoning) and `PROC019` (Sensitivity Analysis).
    2.  **Branching Logic:** For a given intervention, generate multiple "World States."
    3.  Connects directly to `causal_math_tools` for Monte Carlo simulations.
*   **Output:** A tree-like graph showing outcomes of different hypothetical paths.

## 5. Implementation Phasing
1.  **Phase 0:** Unified Gatekeeper Switch (`cim.py`).
2.  **Phase 1:** Core Library (`local_graph_builders/`).
3.  **Phase 2:** Fallacy Detection (Anti-Pattern Logic Gates).
4.  **Phase 3:** Advanced Reasoning (Temporal & Simulation).
6.  **Phase 5: Perception & Synthesis** (Completed)
    *   **Mermaid Visualizer:** Dynamic graph rendering via `--visual`.
    *   **Causal Prompt Engineer:** Translating graphs into direct LLM constraints via `--prompt`.
    *   **Causal Audit Log:** Trace saving for every execution in `/logs/causal_traces/`.
