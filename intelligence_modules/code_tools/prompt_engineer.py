
from typing import Dict, List

class CausalPromptEngineer:
    """
    Translates a causal graph JSON into a structured prompt 
    that enforces causal discipline on an LLM.
    """
    
    @staticmethod
    def engineer_prompt(graph_json: Dict) -> str:
        prompt = [
            "### CAUSAL REASONING DIRECTIVE",
            "You are acting as a Causal Intelligence Module. Follow these structural constraints strictly:",
            ""
        ]
        
        # 1. Variables and their roles
        prompt.append("#### 1. KNOWN VARIABLES & ROLES")
        for node in graph_json.get('nodes', []):
            role = node.get('node_type', 'variable').upper()
            prompt.append(f"- **{node['name']}** ({node['node_id']}): Role: {role}. Confidence: {node.get('uncertainty', 0.5)}.")
        
        # 2. Relationship Constraints
        prompt.append("\n#### 2. CAUSAL CONSTRAINTS (Edges)")
        for edge in graph_json.get('edges', []):
            etype = edge.get('edge_type', 'link').replace('_', ' ').upper()
            prompt.append(f"- Relationship: {edge['source']} -> {edge['target']} is marked as {etype}.")
        
        # 3. Dedicated Mitigations (Logic Gates)
        gates = [n for n in graph_json.get('nodes', []) if n.get('node_type') == 'logic_gate']
        if gates:
            prompt.append("\n#### 3. CRITICAL LOGIC GATES (Mitigation Required)")
            prompt.append("The following biases or fallacies have been proactively identified. You MUST address these in your response:")
            for gate in gates:
                mitigation = gate.get('metadata', {}).get('mitigation', 'General caution required.')
                prompt.append(f"- **{gate['name']}**: Instruction: {mitigation}")
        
        # 4. Procedural Roadmap (Plan)
        steps = [n for n in graph_json.get('nodes', []) if n.get('node_type') == 'procedural_step']
        if steps:
            prompt.append("\n#### 4. REASONING ROADMAP")
            prompt.append("Follow these steps in sequence to derive your conclusion:")
            for i, step in enumerate(steps, 1):
                tools = step.get('metadata', {}).get('tool_ids', 'No specific tools bound.')
                prompt.append(f"{i}. {step['name']} (Reference Tools: {tools})")
        
        prompt.append("\n#### 5. SYNTHESIS INSTRUCTION")
        prompt.append("When synthesizing your final answer, explain the mechanims by which X causes Y, and explicitly state what would happen under the counterfactual scenario if the primary exposure was removed.")
        
        return "\n".join(prompt)

if __name__ == "__main__":
    # Test
    mock_graph = {
        "nodes": [
            {"node_id": "X", "name": "Ad Spend", "node_type": "exposure"},
            {"node_id": "GATE_1", "name": "Simpson's Paradox", "node_type": "logic_gate", "metadata": {"mitigation": "Check subgroup consistency before aggregating results."}},
            {"node_id": "STEP_1", "name": "Analyze subgroups", "node_type": "procedural_step"}
        ],
        "edges": []
    }
    print(CausalPromptEngineer.engineer_prompt(mock_graph))
