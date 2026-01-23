
from .base_builder import BaseGraphBuilder
from code_tools.context_builder import CausalNode, CausalEdge, EdgeType, UncertaintyLevel
from typing import Dict
import json

class StrategicGraphBuilder(BaseGraphBuilder):
    """
    Strategic (In-Depth) Graph Builder.
    Merges Causal Graphs with Decision Graphs (Influence Diagrams).
    Adds 'Decision' nodes (Interventions) and 'Utility' nodes (Goals).
    """
    
    def build_graph(self, query: str) -> Dict:
        # 1. Retrieval
        domain_graphs = self.retrieve_domain_graphs(query, limit=1)
        procs = self.retrieve_procedures(query, limit=2)
        
        # 2. Base Context
        context = {
            'problem_statement': query,
            'variables': [],
            'relationships': []
        }
        
        # 3. Add Domain Variables
        if domain_graphs:
            dg = domain_graphs[0]
            try:
                context['variables'] = json.loads(dg['nodes'].replace("'", '"'))
                edges = json.loads(dg['edges_json'].replace("'", '"'))
                for e in edges:
                    context['relationships'].append({
                        'source': e['source'], 'target': e['target'], 'type': 'HYPOTHESIZED_CAUSE'
                    })
            except: pass

        # 4. Build Engine
        self.engine.build_dag_from_context(context)
        
        # 5. Inject Strategic Nodes (Influence Diagram conversion)
        # Identify the likely 'Outcome' and add a Utility node connected to it
        if context['variables']:
            outcome_var = context['variables'][-1] # Heuristic: usually the last mentioned
            
            # Add Utility Node
            utility_node = CausalNode(
                node_id="UTILITY_GOAL",
                name=f"Maximize/Optimize: {outcome_var}",
                node_type='utility',
                measurement_quality=1.0,
                uncertainty=UncertaintyLevel.CERTAIN
            )
            self.engine.add_node(utility_node)
            self.engine.add_edge(CausalEdge(
                source=outcome_var, target="UTILITY_GOAL", 
                edge_type=EdgeType.MECHANISM_STEP, weight=1.0, 
                uncertainty=UncertaintyLevel.CERTAIN
            ))
            
            # Add Decision Node
            decision_node = CausalNode(
                node_id="DECISION_ACTION",
                name="Intervention/Action Choice",
                node_type='decision',
                measurement_quality=1.0,
                uncertainty=UncertaintyLevel.CERTAIN
            )
            self.engine.add_node(decision_node)
            
            # Connect Decision to the first/exposure variable
            exposure_var = context['variables'][0]
            self.engine.add_edge(CausalEdge(
                source="DECISION_ACTION", target=exposure_var, 
                edge_type=EdgeType.INTERVENTION, weight=1.0, 
                uncertainty=UncertaintyLevel.CERTAIN
            ))

        return self.engine.export_graph()
