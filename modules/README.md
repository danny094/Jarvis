# Helper Modules

Standalone modules that provide specific capabilities to the assistant, separating concerns from the core logic.

## Meta Decision (`meta_decision/`)
A module aimed at high-level decision making.
- **Purpose**: To determine the next course of action based on the user's input and retrieved memory.
- **Mechanism**: Uses `deepseek-r1:8b` with a specialized system prompt (`decision_prompt.txt`).
- **Usage**:
    ```python
    from modules.meta_decision.decision import run_decision_layer
    decision = await run_decision_layer({"user": "...", "memory": "..."})
    ```

## Validator Client (`validator/`)
A client library for connecting to the external `validator-service`.
- **Purpose**: To offload the validation of generated answers to a dedicated microservice.
- **Functions**:
    - `validate_embedding`: Semantic similarity check.
    - `validate_instruction`: LLM-based quality check (instruction following, hallucination detection).
- **Configuration**: Uses `VALIDATOR_URL` (e.g., `http://validator-service:8000`).
