
from .base_builder import BaseGraphBuilder
from code_tools.context_builder import CausalNode, CausalEdge, EdgeType, UncertaintyLevel
from typing import Dict
import json

class TemporalGraphBuilder(BaseGraphBuilder):
    """
    Temporal Graph Builder.
    Focused on time-series, lags, and event sequencing.
    """
    
    def build_graph(self, query: str) -> Dict:
        # 1. Retrieval (Force temporal procedures)
        domain_graphs = self.retrieve_domain_graphs(query, limit=1)
        # Specifically retrieve Temporal Analysis (PROC009)
        temporal_proc = next((p for p in self.retrieve_procedures("temporal timeline lag") if p['procedure_id'] == 'PROC009'), None)
        
        context = {
            'problem_statement': query,
            'variables': [],
            'relationships': []
        }
        
        # 2. Build DAG with Lag Awareness
        if domain_graphs:
            dg = domain_graphs[0]
            try:
                nodes = json.loads(dg['nodes'].replace("'", '"'))
                edges = json.loads(dg['edges_json'].replace("'", '"'))
                
                # In Temporal Graph, nodes are often represented as T, T-1, etc.
                # Here we just apply the 'lag' attribute to edges
                for var in nodes:
                    self.engine.add_node(CausalNode(
                        node_id=var, name=var, node_type='variable', 
                        measurement_quality=0.8, uncertainty=UncertaintyLevel.MODERATE
                    ))
                
                for e in edges:
                    lag_info = e.get('lag', 'none')
                    edge = CausalEdge(
                        source=e['source'],
                        target=e['target'],
                        edge_type=EdgeType.TEMPORAL_PRECEDENCE if lag_info != 'none' else EdgeType.HYPOTHESIZED_CAUSE,
                        weight=0.7,
                        uncertainty=UncertaintyLevel.MODERATE,
                        metadata={'lag': lag_info}
                    )
                    self.engine.add_edge(edge)
            except: pass

        # 3. Inject Temporal Analysis Steps
        if temporal_proc:
            steps = temporal_proc['step_sequence'].split('|')
            for i, step in enumerate(steps):
                step_id = f"TEMP_PROC_{i+1}"
                self.engine.add_node(CausalNode(
                    node_id=step_id, name=step.strip(), node_type='procedural_step',
                    measurement_quality=1.0, uncertainty=UncertaintyLevel.CERTAIN
                ))

        return self.engine.export_graph()
