
from .base_builder import BaseGraphBuilder
from code_tools.context_builder import CausalNode, CausalEdge, EdgeType, UncertaintyLevel
from typing import Dict
import json

class HeavyGraphBuilder(BaseGraphBuilder):
    """
    Heavy Graph Builder.
    Includes multi-prior retrieval and Anti-Pattern logic gates.
    """
    
    def build_graph(self, query: str) -> Dict:
        # 1. Deep Retrieval
        priors = self.retrieve_priors(query, limit=5)
        domain_graphs = self.retrieve_domain_graphs(query, limit=2)
        procs = self.retrieve_procedures(query, limit=3)
        anti_patterns = self.retrieve_anti_patterns(query)
        
        # 2. Build Base Context
        context = {
            'problem_statement': query,
            'variables': [],
            'relationships': [],
            'node_metadata': {}
        }
        
        # 3. Aggregate Variables and Edges from all retrieved Domain Graphs
        for dg in domain_graphs:
            try:
                nodes = json.loads(dg['nodes'].replace("'", '"'))
                context['variables'].extend(nodes)
                
                edges = json.loads(dg['edges_json'].replace("'", '"'))
                for e in edges:
                    context['relationships'].append({
                        'source': e['source'],
                        'target': e['target'],
                        'type': 'HYPOTHESIZED_CAUSE',
                        'weight': 0.8,
                        'metadata': {'domain': dg['domain']}
                    })
            except: continue
        
        context['variables'] = list(set(context['variables']))
        
        # 4. Initialize Engine
        self.engine.build_dag_from_context(context)
        
        # 5. Inject Anti-Pattern "Logic Gates"
        # If an anti-pattern is found, we add a "Validation Node" that MUST be cleared.
        for ap in anti_patterns:
            ap_id = ap['pattern_id']
            gate_node = CausalNode(
                node_id=f"GATE_{ap_id}",
                name=f"Mitigate: {ap['pattern_name']}",
                node_type='logic_gate',
                measurement_quality=1.0,
                uncertainty=UncertaintyLevel.CERTAIN,
                metadata={'mitigation': ap['correction_rule']}
            )
            self.engine.add_node(gate_node)
            
            # Connect gate to relevant outcome or primary relationship
            # For simplicity, we'll link it to the first variable in the query
            if context['variables']:
                target_var = context['variables'][0]
                edge = CausalEdge(
                    source=f"GATE_{ap_id}",
                    target=target_var,
                    edge_type=EdgeType.MECHANISM_STEP,
                    weight=1.0,
                    uncertainty=UncertaintyLevel.CERTAIN
                )
                self.engine.add_edge(edge)

        # 6. Map Procedural Steps
        for proc in procs:
            steps = proc.get('step_sequence', '').split('|')
            # Only use the most relevant procedure for the main path
            if proc == procs[0]:
                prev_node = None
                for i, step in enumerate(steps):
                    step_id = f"STEP_{proc['procedure_id']}_{i+1}"
                    node = CausalNode(
                        node_id=step_id,
                        name=step.strip(),
                        node_type='procedural_step',
                        measurement_quality=1.0,
                        uncertainty=UncertaintyLevel.CERTAIN,
                        metadata={'tool_ids': proc.get('suggested_tool_ids', '')}
                    )
                    self.engine.add_node(node)
                    if prev_node:
                        self.engine.add_edge(CausalEdge(
                            source=prev_node, target=step_id, 
                            edge_type=EdgeType.TEMPORAL_PRECEDENCE, weight=1.0, 
                            uncertainty=UncertaintyLevel.CERTAIN
                        ))
                    prev_node = step_id

        return self.engine.export_graph()
