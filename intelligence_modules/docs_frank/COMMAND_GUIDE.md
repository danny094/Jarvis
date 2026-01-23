# CIM Command Guide & CLI Reference

This guide explains how to interact with the **Causal Intelligence Module (CIM)** via the command line. The `cim.py` script acts as the primary gatekeeper and orchestration layer.

---

## 1. Basic Activation

By default, the system remains in **Associative Mode** (Fast pathway) to save compute. You must explicitly trigger the Causal Workflow.

### Using Flags
```bash
python cim.py "My query here" --causal
```

### Using Slash Commands (Auto-Prefix)
The system automatically detects these prefixes in the query string:
```bash
python cim.py "/c Why is interest rate affecting sales?"
python cim.py "/causal How does X impact Y?"
```

---

## 2. Global Flags & Options

| Flag | Full Name | Description |
| :--- | :--- | :--- |
| `-c` | `--causal` | Activates the Causal Intelligence workflow. |
| `-m` | `--mode` | **Manual Override**: Force a specific logic builder (`light`, `heavy`, `strategic`, `temporal`, `simulation`). |
| `-v` | `--visual` | Generates **Mermaid.js** syntax for graph visualization. |
| `-p` | `--prompt` | Generates a **Causal Prompt Directive** for LLM orchestration. |
| `-j` | `--json` | Outputs the raw results as a structured JSON object (Best for n8n/API). |

---

## 3. Advanced Usage Examples

### Force a Specific Logic (Manual Override)
If the auto-selector picks `light` but you want deep validation:
```bash
python cim.py "Sales drop" -m heavy
```

### Generate Visual + Prompt for LLM
To get the Mermaid graph and the system instructions in one output:
```bash
python cim.py "/c Analyze churn" -v -p
```

### Full System Dump (For n8n/Automation)
```bash
python cim.py "/c Scenario test" -j
```

---

## 4. Understanding Output Types

### **Causal Prompt Directive (`-p`)**
This is a structured narrative that tells an LLM exactly how to think. It translates the mathematical graph into high-level instructions:
*   **Variable Roles:** Identifies what is an Exposure vs. Outcome.
*   **Constraint Enforcement:** "You MUST address Simpson's Paradox."
*   **Procedural Roadmap:** Lists the specific reasoning steps to follow.

### **Mermaid Visualization (`-v`)**
Produces code that can be rendered in Mermaid-ready editors (GitHub, Notion, Obsidian).
*   **Pink Nodes:** Primary exposure (cause).
*   **Green Nodes:** Primary outcome (effect).
*   **Red Hexagons:** Logic Gates (fallacy mitigations).
*   **Blue Dashed:** Procedural reasoning steps.

---

## 5. Auditing & Traces

Every successful causal execution generates a **Trace File**.
*   **Location:** `/logs/causal_traces/trace_[timestamp].json`
*   **Contents:** The raw query, the selected builder, the logic source (auto vs manual), and the full generated graph.
*   **Purpose:** Use these for debugging, fine-tuning the `GraphSelector`, or compliance auditing.

---

## 6. Pro-Tips
*   **Shortcuts:** Use `/c` instead of `--causal` to quickly toggle the module.
*   **Keywords:** The `auto_selector` looks for words like *"What if" (Simulation)*, *"Trend" (Temporal)*, or *"Strategy" (Strategic)*.
*   **Bypass:** To run a standard query without ANY causal overhead, simply omit the flags and prefixes.
