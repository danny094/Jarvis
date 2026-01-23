# Causal Intelligence Module (CIM) by Agentarium

> **Intelligence, packaged.**

**Beyond Associative AI: An Executable Cognitive Architecture for Rigorous Causal Inference.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Founder: Frank Brsrk](https://img.shields.io/badge/Founder-Frank%20Brsrk-blue.svg)](https://x.com/frank_brsrk)
[![Company: Agentarium](https://img.shields.io/badge/Company-Agentarium-green.svg)](mailto:agentariumfrankbrsrk@gmail.com)

## overview

The **Causal Intelligence Module (CIM)** is a specialized RAG (Retrieval-Augmented Generation) framework designed to shift Large Language Models from **Ladder-1 (Association)** reasoning to **Ladder-2 (Intervention)** and **Ladder-3 (Counterfactual)** reasoning.

While standard LLMs are excellent at predicting patterns (Correlation), they fundamentally struggle with the "Why" and the "What if" (Causation). CIM addresses this by wrapping the LLM in a multi-layered architectural "Reasoning Jacket" that enforces structural causal models (SCMs) and deterministic mathematical validation.

## 核心 (Core) Features

*   **Snowball Retrieval Pipeline:** A 3-stage orchestrated retrieval flow:
    1.  **Knowledge RAG:** Identifies first principles and domain-specific Directed Acyclic Graphs (DAGs).
    2.  **Procedural RAG:** Injects validated reasoning templates and activates "Anti-Pattern" logic gates.
    3.  **Executable RAG:** Binds the LLM to a registry of deterministic Python tools for effect size, CI calculation, and graph traversal.
*   **Fallacy Mitigation:** Hard-coded anti-pattern checks (Berkson's Paradox, Collider Bias, Simpson's Paradox) to catch common inferential errors.
*   **Deterministic Bridge:** Uses a `causal_math_registry` to ensure that while the LLM *reasons*, the *calculations* are performed by verified code.

## Quick Start

1.  **Ingest:** Load the datasets in `knowledge_rag/`, `procedural_rag/`, and `executable_rag/` into your vector database.
2.  **Initialize:** Instantiate the `CausalReasoningModule`.
3.  **Query:**
    ```python
    cim.query("How does interest rate change affect our specific conversion funnel?")
    ```

## Documentation

*   [Philosophy & Intent](docs/PHILOSOPHY.md) - The "Why" behind Causal AI.
*   [Architecture Overview](docs/ARCHITECTURE_OVERVIEW.md) - The technical blueprint of the 3-stage pipeline.
*   [Technical Explanation](docs/TECHNICAL_EXPLANATION.md) - Deep dive into SCMs, do-calculus, and bias mitigation.
*   [Workflow Notes](docs/WORKFLOW_NOTES.md) - Operational guidelines for implementation.

## Maintainence & Vision

Built and Architected by **Frank Brsrk**, Founder of **Agentarium**.

*   **X (Twitter):** [@frank_brsrk](https://x.com/frank_brsrk)
*   **Email:** [agentariumfrankbrsrk@gmail.com](mailto:agentariumfrankbrsrk@gmail.com)
*   **Organization:** Agentarium — *Intelligence, packaged.*

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
