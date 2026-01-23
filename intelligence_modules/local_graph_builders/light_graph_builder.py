
from .base_builder import BaseGraphBuilder
from code_tools.context_builder import CausalNode, CausalEdge, EdgeType, UncertaintyLevel
from typing import Dict
import json

class LightGraphBuilder(BaseGraphBuilder):
    """
    Lightweight Graph Builder.
    Focuses on speed and simplicity. 1 Prior + 1 Procedure = 1 Linear Plan.
    """
    
    def build_graph(self, query: str) -> Dict:
        # 1. Retrieval
        priors = self.retrieve_priors(query, limit=1)
        domain_graphs = self.retrieve_domain_graphs(query, limit=1)
        procs = self.retrieve_procedures(query, limit=1)
        
        # 2. Initialize Engine Context
        context = {
            'problem_statement': query,
            'variables': [],
            'relationships': []
        }
        
        # 3. Add Domain Variables if found
        if domain_graphs:
            dg = domain_graphs[0]
            try:
                # Cleanup the string representation of list in CSV
                nodes_raw = dg['nodes'].replace("'", '"')
                context['variables'] = json.loads(nodes_raw)
                
                edges_raw = dg['edges_json'].replace("'", '"')
                edges = json.loads(edges_raw)
                for e in edges:
                    context['relationships'].append({
                        'source': e['source'],
                        'target': e['target'],
                        'type': 'HYPOTHESIZED_CAUSE',
                        'weight': 0.7
                    })
            except Exception:
                pass

        # 4. Build the Causal DAG
        self.engine.build_dag_from_context(context)
        
        # 5. Inject Procedural Steps as Meta-Nodes
        if procs:
            proc = procs[0]
            steps = proc.get('step_sequence', '').split('|')
            prev_node = None
            for i, step in enumerate(steps):
                step_id = f"STEP_{i+1}"
                node = CausalNode(
                    node_id=step_id,
                    name=step.strip(),
                    node_type='procedural_step',
                    measurement_quality=1.0,
                    uncertainty=UncertaintyLevel.CERTAIN,
                    metadata={'procedure_id': proc['procedure_id']}
                )
                self.engine.add_node(node)
                
                # Link steps in sequence
                if prev_node:
                    edge = CausalEdge(
                        source=prev_node,
                        target=step_id,
                        edge_type=EdgeType.TEMPORAL_PRECEDENCE,
                        weight=1.0,
                        uncertainty=UncertaintyLevel.CERTAIN
                    )
                    self.engine.add_edge(edge)
                prev_node = step_id

        return self.engine.export_graph()

if __name__ == "__main__":
    import os
    # For local testing if run directly
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    builder = LightGraphBuilder(root)
    result = builder.build_graph("Why is inflation rising with money supply?")
    print(json.dumps(result, indent=2))
