
from .base_builder import BaseGraphBuilder
from code_tools.context_builder import CausalNode, CausalEdge, EdgeType, UncertaintyLevel
from typing import Dict
import json

class SimulationGraphBuilder(BaseGraphBuilder):
    """
    Simulation Graph Builder.
    Designed for counterfactual branching and 'What-if' path tracing.
    """
    
    def build_graph(self, query: str) -> Dict:
        # 1. Retrieval (Force Counterfactual/Sensitivity procedures)
        domain_graphs = self.retrieve_domain_graphs(query, limit=1)
        # Specifically retrieve Counterfactual Reasoning (PROC005) or Sensitivity (PROC019)
        sim_procs = self.retrieve_procedures("counterfactual simulation sensitivity what-if")
        
        context = {
            'problem_statement': query,
            'variables': [],
            'relationships': []
        }
        
        # 2. Add Domain DAG as the 'Factual' Model
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
        
        self.engine.build_dag_from_context(context)
        
        # 3. Create 'World State' Branches
        # For a simulation, we often create a fork in the graph.
        if context['variables']:
            pivot_var = context['variables'][0]
            
            # Scenario A: Baseline
            self.engine.add_node(CausalNode(
                node_id="WORLD_BASELINE", name="Factual Scenario (Status Quo)", 
                node_type='scenario', measurement_quality=1.0, uncertainty=UncertaintyLevel.CERTAIN
            ))
            self.engine.add_edge(CausalEdge(
                source="WORLD_BASELINE", target=pivot_var, 
                edge_type=EdgeType.OBSERVED_CORRELATION, weight=1.0, 
                uncertainty=UncertaintyLevel.CERTAIN
            ))
            
            # Scenario B: Counterfactual Intervention
            self.engine.add_node(CausalNode(
                node_id="WORLD_COUNTERFACTUAL", name="Alternative Scenario (Intervention)", 
                node_type='scenario', measurement_quality=1.0, uncertainty=UncertaintyLevel.MODERATE
            ))
            self.engine.add_edge(CausalEdge(
                source="WORLD_COUNTERFACTUAL", target=pivot_var, 
                edge_type=EdgeType.INTERVENTION, weight=1.0, 
                uncertainty=UncertaintyLevel.CERTAIN
            ))

        # 4. Link Simulation Procedures
        if sim_procs:
            main_proc = sim_procs[0]
            steps = main_proc['step_sequence'].split('|')
            for i, step in enumerate(steps):
                step_id = f"SIM_STEP_{i+1}"
                self.engine.add_node(CausalNode(
                    node_id=step_id, name=step.strip(), node_type='procedural_step',
                    measurement_quality=1.0, uncertainty=UncertaintyLevel.CERTAIN
                ))

        return self.engine.export_graph()
