# CIM Skill Builder RAG

This directory contains the complete knowledge base for the **Automated Skill Builder Agent**. It is designed to allow an LLM to autonomously generate, validate, and execute python/js tools.

## File Manifest

### 1. Blueprints (The "What")
- **`skill_templates.csv`**: Code skeletons for different domains (Math, ML, API, etc.) with input/output schemas.
- **`intent_category_map.csv`**: Maps user natural language requests to specific templates.
- **`output_standards.csv`**: JSON schemas for standardized return values.

### 2. Guardrails (The "Constraint")
- **`security_policies.csv`**: Strict rules for the environment (e.g., No Sockets, Max RAM).
- **`dependency_whitelist.csv`**: Safe libraries allowed for import (e.g., Pandas, Scikit-learn).
- **`error_handling_patterns.csv`**: Pre-baked try/except logic and recovery strategies.

### 3. Lifecycle (The "How")
- **`execution_environment.csv`**: Definitions of runtime environments (Docker/Sandbox) where skills run.
- **`validation_tests.csv`**: Templates for unit tests to verify generated code.
- **`../data/code_good_patterns.csv`**: Best-practice patterns (moved to data/ alongside anti-patterns).
- Skill metrics now tracked in mcp-sql-memory SQLite database (replaced skill_memory.csv).
- **`skill_dependency_graph.csv`**: Defines how complex skills are composed of smaller atomic skills.

### 4. Agent Personas (The "Who")
- **`meta_prompts.csv`**: System prompts for the Coder, Reviewer, Tester, and Optimizer agents.

## Workflow

1.  **Intent Analysis**: User query matched against `intent_category_map.csv` -> Select Template.
2.  **Generation**: **Coder Agent** uses `skill_templates.csv` + `data/code_good_patterns.csv` to write code.
3.  **Audit**: **Reviewer Agent** checks code against `security_policies.csv` and `dependency_whitelist.csv`.
4.  **Testing**: **Tester Agent** generates tests from `validation_tests.csv` and runs them in `test_harness_config.csv`.
5.  **Execution**: Code is deployed to environment defined in `execution_environment.csv`.
6.  **Feedback**: Result logged to mcp-sql-memory (skill_metrics table).

## Integration
This RAG source is consumed by the **Skill Builder Node** in the CIM pipeline.
