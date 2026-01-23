"""
CIM MCP Server - Frank's Causal Intelligence Module as MCP Service

Exposes CIM functionality via MCP protocol for use by Sequential Thinking
and other services.

Port: 8086
Tools:
  - analyze: Build causal graph for a query
  - validate_before: Check step before execution (anti-patterns, biases)
  - validate_after: Validate step result (fallacies, logic gates)
  - correct_course: Get corrected reasoning plan
  - get_modes: List available CIM modes
"""

import os
import sys
import json
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastmcp import FastMCP

# Setup paths
ROOT_DIR = os.environ.get("CIM_ROOT", "/app/intelligence_modules")
sys.path.insert(0, ROOT_DIR)

# Import Frank's CIM components
from local_graph_builders.graph_selector import GraphSelector
from local_graph_builders.light_graph_builder import LightGraphBuilder
from local_graph_builders.heavy_graph_builder import HeavyGraphBuilder
from code_tools.visualizer import MermaidGenerator
from code_tools.prompt_engineer import CausalPromptEngineer

# Initialize MCP Server
mcp = FastMCP("cim-server")

# Initialize GraphSelector
selector = GraphSelector(ROOT_DIR)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def audit_log(payload: dict) -> str:
    """Saves execution trace to audit directory."""
    log_dir = Path(ROOT_DIR) / "logs" / "causal_traces"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"trace_{timestamp}.json"
    
    try:
        with open(log_dir / filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        
        # Pruning: Keep last 100 traces
        all_traces = sorted(log_dir.glob("trace_*.json"), key=os.path.getmtime)
        if len(all_traces) > 100:
            for old_trace in all_traces[:-100]:
                old_trace.unlink()
    except Exception as e:
        return f"audit_error_{timestamp}"
    
    return filename


def load_anti_patterns() -> List[Dict]:
    """Load anti-patterns from procedural RAG."""
    patterns_file = Path(ROOT_DIR) / "procedural_rag" / "anti_patterns.csv"
    patterns = []
    
    if patterns_file.exists():
        try:
            import csv
            with open(patterns_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                patterns = list(reader)
        except Exception:
            pass
    
    return patterns


def check_anti_patterns(text: str, patterns: List[Dict]) -> List[Dict]:
    """Check text against anti-patterns."""
    violations = []
    text_lower = text.lower()
    
    for pattern in patterns:
        # Simple keyword matching (could be enhanced with embeddings)
        pattern_name = pattern.get("name", "").lower()
        pattern_keywords = pattern.get("keywords", "").lower().split(",")
        
        for keyword in pattern_keywords:
            keyword = keyword.strip()
            if keyword and keyword in text_lower:
                violations.append({
                    "pattern": pattern.get("name", "Unknown"),
                    "description": pattern.get("description", ""),
                    "mitigation": pattern.get("mitigation", ""),
                    "severity": pattern.get("severity", "medium"),
                    "matched_keyword": keyword
                })
                break  # One match per pattern is enough
    
    return violations


# ============================================================
# MCP TOOLS
# ============================================================

@mcp.tool()
def analyze(
    query: str,
    mode: Optional[str] = None,
    include_visual: bool = False,
    include_prompt: bool = False
) -> Dict[str, Any]:
    """
    Build a causal graph for a query using Frank's CIM.
    
    Args:
        query: The query to analyze
        mode: Force specific mode (light, heavy, strategic, temporal, simulation)
              If None, auto-selects based on query
        include_visual: Include Mermaid diagram syntax
        include_prompt: Include engineered causal prompt for LLM
    
    Returns:
        Causal graph with nodes, edges, and metadata
    """
    try:
        # Select builder
        if mode:
            builder = selector.get_builder_by_name(mode)
            selection_source = "manual_override"
        else:
            builder = selector.select_builder(query)
            selection_source = "auto_selector"
        
        # Build graph
        graph_result = builder.build_graph(query)
        
        # Audit log
        trace_file = audit_log({
            "query": query,
            "mode": builder.__class__.__name__,
            "source": selection_source,
            "graph": graph_result
        })
        
        # Build response
        result = {
            "success": True,
            "cim_active": True,
            "mode_selected": builder.__class__.__name__,
            "selection_source": selection_source,
            "query": query,
            "trace_file": trace_file,
            "graph": graph_result,
            "node_count": len(graph_result.get("nodes", [])),
            "edge_count": len(graph_result.get("edges", []))
        }
        
        # Add visuals if requested
        if include_visual:
            result["mermaid"] = MermaidGenerator.generate(graph_result)
        
        # Add prompt if requested
        if include_prompt:
            result["causal_prompt"] = CausalPromptEngineer.engineer_prompt(graph_result)
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "query": query
        }


@mcp.tool()
def validate_before(
    step_description: str,
    step_id: str = "step_0",
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate a step BEFORE execution.
    
    Checks for:
    - Anti-patterns in reasoning
    - Cognitive biases
    - Logical fallacies in the plan
    
    Args:
        step_description: What the step intends to do
        step_id: Identifier for the step
        context: Optional context from previous steps
    
    Returns:
        Validation result with safe/derailed status and warnings
    """
    try:
        # Load anti-patterns
        patterns = load_anti_patterns()
        
        # Check for violations
        full_text = f"{step_description} {context or ''}"
        violations = check_anti_patterns(full_text, patterns)
        
        # Use LightGraphBuilder for quick validation
        builder = LightGraphBuilder(ROOT_DIR)
        graph = builder.build_graph(step_description)
        
        # Determine safety
        is_safe = len(violations) == 0
        severity_scores = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        max_severity = max(
            [severity_scores.get(v.get("severity", "medium"), 2) for v in violations],
            default=0
        )
        
        result = {
            "success": True,
            "step_id": step_id,
            "safe": is_safe,
            "derailed": max_severity >= 3,  # High or critical = derailed
            "violations": violations,
            "violation_count": len(violations),
            "max_severity": max_severity,
            "warnings": [v["pattern"] for v in violations],
            "mitigations": [v["mitigation"] for v in violations if v.get("mitigation")],
            "quick_graph": {
                "node_count": len(graph.get("nodes", [])),
                "edge_count": len(graph.get("edges", []))
            }
        }
        
        # Log validation
        audit_log({
            "action": "validate_before",
            "step_id": step_id,
            "result": result
        })
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "step_id": step_id,
            "safe": True,  # Fail open for availability
            "derailed": False,
            "error": str(e)
        }


@mcp.tool()
def validate_after(
    step_id: str,
    step_result: str,
    expected_outcome: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate step result AFTER execution.
    
    Checks for:
    - Fallacies in the result
    - Consistency with expected outcome
    - Logic gate violations
    
    Args:
        step_id: Identifier for the step
        step_result: The actual result/output of the step
        expected_outcome: What was expected (optional)
    
    Returns:
        Validation result with valid/needs_correction status
    """
    try:
        # Build graph of the result
        builder = selector.select_builder(step_result)
        graph = builder.build_graph(step_result)
        
        # Check for anti-patterns in result
        patterns = load_anti_patterns()
        violations = check_anti_patterns(step_result, patterns)
        
        # Check consistency if expected outcome provided
        consistency_score = 1.0
        consistency_issues = []
        
        if expected_outcome:
            # Simple keyword overlap check (could use embeddings)
            expected_words = set(expected_outcome.lower().split())
            result_words = set(step_result.lower().split())
            overlap = len(expected_words & result_words)
            consistency_score = overlap / max(len(expected_words), 1)
            
            if consistency_score < 0.3:
                consistency_issues.append("Result significantly differs from expected outcome")
        
        # Determine validity
        is_valid = len(violations) == 0 and consistency_score >= 0.3
        
        result = {
            "success": True,
            "step_id": step_id,
            "valid": is_valid,
            "needs_correction": not is_valid,
            "violations": violations,
            "consistency_score": consistency_score,
            "consistency_issues": consistency_issues,
            "graph": {
                "mode": builder.__class__.__name__,
                "node_count": len(graph.get("nodes", [])),
                "edge_count": len(graph.get("edges", []))
            }
        }
        
        # Log validation
        audit_log({
            "action": "validate_after",
            "step_id": step_id,
            "result": result
        })
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "step_id": step_id,
            "valid": True,  # Fail open
            "needs_correction": False,
            "error": str(e)
        }


@mcp.tool()
def correct_course(
    step_id: str,
    current_plan: str,
    violations: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generate a corrected reasoning plan using HeavyGraphBuilder.
    
    Called when validate_before or validate_after indicates problems.
    
    Args:
        step_id: Identifier for the step
        current_plan: The current (problematic) plan
        violations: List of detected violations/issues
    
    Returns:
        Corrected reasoning plan with injected validation nodes
    """
    try:
        # Use HeavyGraphBuilder for deep correction
        builder = HeavyGraphBuilder(ROOT_DIR)
        
        # Build comprehensive graph
        enhanced_query = f"[CORRECTION NEEDED] {current_plan}"
        if violations:
            enhanced_query += f" [VIOLATIONS: {', '.join(violations)}]"
        
        graph = builder.build_graph(enhanced_query)
        
        # Generate corrected prompt
        corrected_prompt = CausalPromptEngineer.engineer_prompt(graph)
        
        # Generate visualization
        mermaid = MermaidGenerator.generate(graph)
        
        result = {
            "success": True,
            "step_id": step_id,
            "corrected": True,
            "original_plan": current_plan,
            "addressed_violations": violations or [],
            "corrected_graph": graph,
            "corrected_prompt": corrected_prompt,
            "mermaid_diagram": mermaid,
            "injected_nodes": [
                n for n in graph.get("nodes", [])
                if n.get("type") in ["validation", "gate", "mitigation"]
            ]
        }
        
        # Log correction
        audit_log({
            "action": "correct_course",
            "step_id": step_id,
            "result": result
        })
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "step_id": step_id,
            "corrected": False,
            "error": str(e)
        }


@mcp.tool()
def get_modes() -> Dict[str, Any]:
    """
    List available CIM modes and their descriptions.
    
    Returns:
        Dictionary of available modes with descriptions
    """
    return {
        "success": True,
        "modes": {
            "light": {
                "name": "LightGraphBuilder",
                "description": "Fast-path for simple queries, minimal latency",
                "use_case": "Quick causal checks, simple questions"
            },
            "heavy": {
                "name": "HeavyGraphBuilder", 
                "description": "Deep validation with logic gate injection",
                "use_case": "Complex reasoning, bias detection, safety-critical"
            },
            "strategic": {
                "name": "StrategicGraphBuilder",
                "description": "Decision nodes with utility optimization",
                "use_case": "Strategy questions, optimization, decision-making"
            },
            "temporal": {
                "name": "TemporalGraphBuilder",
                "description": "Time-series analysis with feedback loops",
                "use_case": "Historical analysis, trends, forecasting"
            },
            "simulation": {
                "name": "SimulationGraphBuilder",
                "description": "Counterfactual branching for 'what if' scenarios",
                "use_case": "Hypotheticals, counterfactuals, scenario planning"
            }
        },
        "auto_selection": "Based on query keywords and complexity"
    }


@mcp.tool()
def health() -> Dict[str, Any]:
    """Health check for the CIM server."""
    return {
        "status": "healthy",
        "service": "cim-server",
        "version": "1.0.0",
        "root_dir": ROOT_DIR,
        "builders_available": list(selector.builders.keys())
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("🧠 Starting CIM MCP Server on port 8086...")
    print(f"   ROOT_DIR: {ROOT_DIR}")
    print("   Tools available:")
    print("   - analyze: Build causal graph")
    print("   - validate_before: Pre-execution validation")
    print("   - validate_after: Post-execution validation")
    print("   - correct_course: Get corrected plan")
    print("   - get_modes: List available modes")
    print("   - health: Health check")
    
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8086
    )
