
import json
from typing import Dict, List

class MermaidGenerator:
    """
    Generates Mermaid.js syntax from causal graph JSON.
    Used for visual auditing of the reasoning path.
    """
    
    @staticmethod
    def generate(graph_json: Dict) -> str:
        lines = ["graph TD"]
        
        # Define styles for node types
        lines.append("    %% Node Styles")
        lines.append("    classDef exposure fill:#f9f,stroke:#333,stroke-width:4px;")
        lines.append("    classDef outcome fill:#00ff00,stroke:#333,stroke-width:4px;")
        lines.append("    classDef logic_gate fill:#ff4444,stroke:#fff,stroke-width:2px,color:#fff;")
        lines.append("    classDef procedure fill:#44aaff,stroke:#333,stroke-dasharray: 5 5;")
        lines.append("    classDef utility fill:#f90,stroke:#333,stroke-width:2px;")
        lines.append("    classDef decision fill:#666,stroke:#fff,stroke-width:2px,color:#fff;")
        lines.append("    classDef scenario fill:#eee,stroke:#999,stroke-dasharray: 5 5;")
        lines.append("    classDef confounder fill:#9cf,stroke:#333,stroke-width:1px;")
        lines.append("    classDef variable fill:#fff,stroke:#333,stroke-width:1px;")

        # 1. Add Nodes with types
        for node in graph_json.get('nodes', []):
            node_id = node['node_id']
            name = node['name']
            ntype = node.get('node_type', 'variable')
            
            # Apply styling and naming
            # Special markers for logic gates
            if ntype == 'logic_gate':
                node_str = f"    {node_id}{{ {name} }}"
            else:
                node_str = f"    {node_id}[{name}]"
                
            lines.append(node_str)
            
            # Sub-type classes
            if ntype == 'exposure':
                lines.append(f"    class {node_id} exposure")
            elif ntype == 'outcome':
                lines.append(f"    class {node_id} outcome")
            elif ntype == 'logic_gate':
                lines.append(f"    class {node_id} logic_gate")
            elif ntype == 'procedural_step':
                lines.append(f"    class {node_id} procedure")
            elif ntype == 'utility':
                lines.append(f"    class {node_id} utility")
            elif ntype == 'decision':
                lines.append(f"    class {node_id} decision")
            elif ntype == 'scenario':
                lines.append(f"    class {node_id} scenario")
            elif ntype == 'confounder':
                lines.append(f"    class {node_id} confounder")
            else:
                lines.append(f"    class {node_id} variable")

        # 2. Add Edges with relationship types
        for edge in graph_json.get('edges', []):
            source = edge['source']
            target = edge['target']
            etype = edge.get('edge_type', 'causal_link')
            
            # Define arrow style based on type
            if etype == 'possible_confounder':
                arrow = "---"
            elif etype == 'observed_correlation':
                arrow = "-.-"
            elif etype == 'logic_gate':
                arrow = "==>"
            elif etype == 'intervention':
                arrow = "==>"
            else:
                arrow = "-->"
                
            label = etype.replace('_', ' ')
            lines.append(f"    {source} {arrow}|{label}| {target}")

        return "\n".join(lines)

if __name__ == "__main__":
    # Test with mockup
    mock_graph = {
        "nodes": [
            {"node_id": "X", "name": "Advertising", "node_type": "exposure"},
            {"node_id": "Y", "name": "Revenue", "node_type": "outcome"},
            {"node_id": "GATE_1", "name": "Check Seasonality", "node_type": "logic_gate"},
            {"node_id": "STEP_1", "name": "Calculate Impact", "node_type": "procedural_step"}
        ],
        "edges": [
            {"source": "X", "target": "Y", "edge_type": "hypothesized_cause"},
            {"source": "GATE_1", "target": "X", "edge_type": "logic_gate"},
            {"source": "STEP_1", "target": "Y", "edge_type": "causal_link"}
        ]
    }
    print(MermaidGenerator.generate(mock_graph))
