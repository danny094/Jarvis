# Tool Intelligence Module

**Namespace:** `core.tool_intelligence`
**Manager:** `ToolIntelligenceManager`

## Purpose
This module handles the "Self-Correction" and "Resilience" capabilities of the Jarvis architecture. It sits between the Orchestrator and the Tool Execution, monitoring results for errors and attempting autonomous recovery.

## Components

### 1. `manager.py`
- **Role:** Central Facade / Entry Point.
- **Responsibility:** Coordinates the flow between detection, search, and retry.
- **Usage:** Injected into `PipelineOrchestrator`.

### 2. `error_detector.py`
- **Role:** Analysis.
- **Responsibility:** Inspects tool results (dicts, objects, strings) to determine if a failure occurred.
- **Key Function:** `detect_tool_error(result)`

### 3. `auto_search.py`
- **Role:** Knowledge Retrieval.
- **Responsibility:** Searches both the `archive` (long-term) and `workspace_events` (short-term/FastLane) for past solutions to similar errors.
- **Key Function:** `search_past_solutions(tool_name, error_msg)`

### 4. `auto_retry.py` (Phase 3.5)
- **Role:** Active Recovery.
- **Responsibility:** Determines if an error is retryable and modifies parameters for a second attempt.
- **Status:** *Pending Implementation*

## Integration
Used in `core/orchestrator.py`:
```python
self.tool_intelligence = ToolIntelligenceManager(self.archive_manager)
# ...
ti_result = self.tool_intelligence.handle_tool_result(tool_name, result, tool_args)
```
