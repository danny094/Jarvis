
import sys
import argparse
import json
import os
import datetime
from pathlib import Path

# Define the root of the project
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Import the local graph builders
from local_graph_builders.graph_selector import GraphSelector
from code_tools.visualizer import MermaidGenerator
from code_tools.prompt_engineer import CausalPromptEngineer

def audit_log(payload: dict):
    """Saves the execution trace to the audit directory."""
    log_dir = Path(ROOT_DIR) / "logs" / "causal_traces"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"trace_{timestamp}.json"
    
    with open(log_dir / filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    
    # Pruning: Keep last 100 traces
    try:
        all_traces = sorted(log_dir.glob("trace_*.json"), key=os.path.getmtime)
        if len(all_traces) > 100:
            for old_trace in all_traces[:-100]:
                old_trace.unlink()
    except Exception: pass

    return filename

def main():
    parser = argparse.ArgumentParser(description="Causal Intelligence Module (CIM) Gatekeeper CLI")
    
    # The Query
    parser.add_argument("query", type=str, help="The user query to process")
    
    # Activation Switches
    parser.add_argument("-c", "--causal", action="store_true", help="Explicitly activate Causal Intelligence Module (CIM)")
    
    # Mode Selection
    parser.add_argument("-m", "--mode", type=str, default=None, 
                        choices=["light", "heavy", "strategic", "temporal", "simulation"],
                        help="Force a specific CIM builder mode (overrides auto-detection)")

    # Output Format
    parser.add_argument("-j", "--json", action="store_true", help="Output full graph as JSON")
    parser.add_argument("-v", "--visual", action="store_true", help="Output Mermaid diagram syntax")
    parser.add_argument("-p", "--prompt", action="store_true", help="Output engineered causal prompt for LLM")

    args = parser.parse_args()

    # Activation Logic
    is_triggered = args.causal or args.query.startswith(("/c ", "/causal "))
    clean_query = args.query.replace("/causal ", "").replace("/c ", "").strip()

    if is_triggered:
        selector = GraphSelector(ROOT_DIR)
        
        # Determine Builder: Forced Mode vs Auto-Selected
        if args.mode:
            builder = selector.get_builder_by_name(args.mode)
            selection_source = "manual_override"
        else:
            builder = selector.select_builder(clean_query)
            selection_source = "auto_selector"

        # Execute Construction
        graph_result = builder.build_graph(clean_query)
        
        # 1. Audit Logging
        trace_file = audit_log({
            "query": clean_query,
            "mode": builder.__class__.__name__,
            "source": selection_source,
            "graph": graph_result
        })

        # Metadata
        final_output = {
            "cim_active": True,
            "mode_selected": builder.__class__.__name__,
            "selection_source": selection_source,
            "query": clean_query,
            "trace_file": trace_file,
            "graph": graph_result
        }
        
        # 2. Add Visuals if requested
        if args.visual:
            final_output["mermaid"] = MermaidGenerator.generate(graph_result)
            
        # 3. Add Prompt if requested
        if args.prompt:
            final_output["causal_prompt"] = CausalPromptEngineer.engineer_prompt(graph_result)

    else:
        # Bypass Path
        final_output = {
            "cim_active": False,
            "mode_selected": "NONE",
            "query": args.query,
            "status": "ASSOCIATIVE_MODE_ONLY (Pass-through to standard LLM)"
        }

    # Final Emission
    if args.json or args.visual or args.prompt:
        # If any specialized output is requested, print the JSON containing them
        print(json.dumps(final_output, indent=2))
    else:
        # Clean terminal output for human reading
        status = "ACTUALIZING CAUSAL GRAPH" if final_output["cim_active"] else "BYPASSING CIM"
        print(f"[{status}] Mode: {final_output['mode_selected']} | Selection: {final_output.get('selection_source', 'none')}")
        if final_output["cim_active"]:
            print(f"Nodes Created: {len(graph_result['nodes'])}")
            print(f"Edges Created: {len(graph_result['edges'])}")
            print(f"Audit Trace saved to: {final_output['trace_file']}")

if __name__ == "__main__":
    main()
