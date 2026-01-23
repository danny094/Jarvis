# Workflow Notes: Operational Guidelines

This document outlines the operational life-cycle of a query within the Causal Intelligence Module.

## The "Snowball" Retrieval Strategy

CIM does not perform a single search. It follows a sequential **Accumulation Pattern**:

### Stage 1: Framework Assembly (Knowledge RAG)
*   **Action:** Query vector database for keywords in `cognitive_priors_v2.csv` and `domain_graphs.csv`.
*   **Requirement:** The agent MUST locate at least one theoretical prior (e.g., "Temporal Precedence") before proceeding.
*   **Result:** A "Theoretical Scaffold" for the response.

### Stage 2: Strategy Drafting (Procedural RAG)
*   **Action:** Match the assembly from Stage 1 to a specific procedure (e.g., `PROC008 - Effect Size Evaluation`).
*   **Critical Step:** Run the **Anti-Pattern Filter**. The agent compares the current reasoning plan against `anti_patterns.csv`. If a match is found (e.g., potential for *Survivorship Bias*), the plan is updated with a mandatory mitigation step.
*   **Result:** A validated logic-gate that the agent must pass through.

### Stage 3: Execution & Synthesis (Executable RAG)
*   **Action:** Activate `ability_injectors` to set the tone (e.g., "Strict Causal Discipline").
*   **Tool Mapping:** For every step in the procedure assigned in Stage 2, the agent checks `causal_math_registry` for a `tool_id`.
*   **Result:** The agent makes a sub-call to the Python code tools, receives deterministic results, and synthesizes the final report.

## Implementation Checklist for Developers

1.  **Strict Mode:** Ensure `AB001` (Strict Causal Discipline) is ALWAYS active for any query containing the words "cause," "because," or "why."
2.  **Tool Priority:** If a calculation can be done via `CausalMathTools`, the LLM is prohibited from performing it manually.
3.  **Audit Trail:** Every final response must cite:
    *   The **Prior ID** used.
    *   The **Procedure ID** followed.
    *   The **Math Tool ID** invoked.

## Handling Uncertainty

If the RAG retrieval fails to find a pre-validated DAG in `domain_graphs.csv`, the workflow must transition to **Discovery Mode**:
1.  Invoke `DISC001` (PC Algorithm).
2.  Propose a tentative DAG.
3.  Flag the conclusion as "Low Confidence: Discovery-based."

## Performance Tuning
*   **Embedding text matters:** When adding new domains, ensure the `embedding_text` column contains both domain-specific nouns and causal verbs (e.g., "inhibits," "triggers," "controls").
