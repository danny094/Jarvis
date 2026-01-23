"""
Context Graph Construction Module
Builds causal context graphs with weighted edges and relationship mappings.
"""

import networkx as nx
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass, field
from enum import Enum
import json


class EdgeType(Enum):
    """Types of edges in the causal context graph"""
    HYPOTHESIZED_CAUSE = "hypothesized_cause"
    OBSERVED_CORRELATION = "observed_correlation"
    TEMPORAL_PRECEDENCE = "temporal_precedence"
    POSSIBLE_CONFOUNDER = "possible_confounder"
    MEDIATOR = "mediator"
    COLLIDER = "collider"
    FEEDBACK_LOOP = "feedback_loop"
    INTERVENTION = "intervention"
    MECHANISM_STEP = "mechanism_step"


class UncertaintyLevel(Enum):
    """Uncertainty levels for nodes and edges"""
    CERTAIN = 1.0
    HIGH_CONFIDENCE = 0.8
    MODERATE = 0.6
    LOW_CONFIDENCE = 0.4
    SPECULATIVE = 0.2
    UNKNOWN = 0.0


@dataclass
class CausalNode:
    """Represents a variable/entity in the causal graph"""
    node_id: str
    name: str
    node_type: str  # 'exposure', 'outcome', 'confounder', 'mediator', 'collider'
    measurement_quality: float  # 0-1 scale
    uncertainty: UncertaintyLevel
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'node_id': self.node_id,
            'name': self.name,
            'node_type': self.node_type,
            'measurement_quality': self.measurement_quality,
            'uncertainty': self.uncertainty.value,
            'metadata': self.metadata
        }


@dataclass
class CausalEdge:
    """Represents a relationship between nodes"""
    source: str
    target: str
    edge_type: EdgeType
    weight: float  # strength of relationship, 0-1
    uncertainty: UncertaintyLevel
    evidence: List[str] = field(default_factory=list)
    temporal_lag: Optional[Tuple[float, float]] = None  # (min_lag, max_lag)
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'source': self.source,
            'target': self.target,
            'edge_type': self.edge_type.value,
            'weight': self.weight,
            'uncertainty': self.uncertainty.value,
            'evidence': self.evidence,
            'temporal_lag': self.temporal_lag,
            'metadata': self.metadata
        }


class ContextGraphBuilder:
    """
    Builds and manages causal context graphs.
    Implements graph construction logic for causal reasoning.
    """
    
    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, CausalNode] = {}
        self.edges: List[CausalEdge] = []
        
    def add_node(self, node: CausalNode) -> None:
        """Add a node to the context graph"""
        self.nodes[node.node_id] = node
        self.graph.add_node(
            node.node_id,
            **node.to_dict()
        )
    
    def add_edge(self, edge: CausalEdge) -> None:
        """Add an edge to the context graph"""
        self.edges.append(edge)
        self.graph.add_edge(
            edge.source,
            edge.target,
            **edge.to_dict()
        )
    
    def identify_candidate_variables(self, query_context: Dict) -> List[str]:
        """
        Extract candidate variables from query context.
        Returns list of variable identifiers.
        """
        candidates = []
        
        # Extract from explicit mentions
        if 'variables' in query_context:
            candidates.extend(query_context['variables'])
        
        # Extract from relationships
        if 'relationships' in query_context:
            for rel in query_context['relationships']:
                candidates.extend([rel.get('source'), rel.get('target')])
        
        # Extract from problem statement via NLP (simplified)
        if 'problem_statement' in query_context:
            # In production, use NER or custom extraction
            candidates.extend(self._extract_entities(query_context['problem_statement']))
        
        return list(set(filter(None, candidates)))
    
    def _extract_entities(self, text: str) -> List[str]:
        """Simplified entity extraction - replace with NER in production"""
        # Placeholder - in production use spaCy or similar
        return []
    
    def classify_node_type(self, node_id: str, context: Dict) -> str:
        """Classify node as exposure, outcome, confounder, mediator, or collider"""
        
        # Check if explicitly marked
        if 'node_types' in context and node_id in context['node_types']:
            return context['node_types'][node_id]
        
        # Check if it's the outcome of interest
        if 'outcome' in context and node_id == context['outcome']:
            return 'outcome'
        
        # Check if it's the primary exposure
        if 'exposure' in context and node_id == context['exposure']:
            return 'exposure'
        
        # Analyze graph structure to infer type
        if node_id in self.graph:
            predecessors = list(self.graph.predecessors(node_id))
            successors = list(self.graph.successors(node_id))
            
            # Collider: multiple causes, no effects in analysis
            if len(predecessors) >= 2 and len(successors) == 0:
                return 'collider'
            
            # Mediator: on path from exposure to outcome
            if self._is_on_causal_path(node_id, context):
                return 'mediator'
        
        # Default to confounder if influences both exposure and outcome
        return 'confounder'
    
    def _is_on_causal_path(self, node_id: str, context: Dict) -> bool:
        """Check if node is on the path from exposure to outcome"""
        if 'exposure' not in context or 'outcome' not in context:
            return False
        
        exposure = context['exposure']
        outcome = context['outcome']
        
        if exposure not in self.graph or outcome not in self.graph:
            return False
        
        # Check all paths from exposure to outcome
        try:
            paths = nx.all_simple_paths(self.graph, exposure, outcome)
            for path in paths:
                if node_id in path:
                    return True
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass
        
        return False
    
    def identify_confounders(self, exposure: str, outcome: str) -> List[str]:
        """
        Identify confounders: variables that influence both exposure and outcome.
        Returns list of confounder node IDs.
        """
        confounders = []
        
        for node_id in self.graph.nodes():
            if node_id == exposure or node_id == outcome:
                continue
            
            # Check if node has paths to both exposure and outcome
            has_path_to_exposure = nx.has_path(self.graph, node_id, exposure)
            has_path_to_outcome = nx.has_path(self.graph, node_id, outcome)
            
            if has_path_to_exposure and has_path_to_outcome:
                confounders.append(node_id)
        
        return confounders
    
    def identify_mediators(self, exposure: str, outcome: str) -> List[str]:
        """
        Identify mediators: variables on the causal path from exposure to outcome.
        """
        mediators = []
        
        try:
            paths = list(nx.all_simple_paths(self.graph, exposure, outcome))
            for path in paths:
                # Exclude exposure and outcome themselves
                mediators.extend(path[1:-1])
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass
        
        return list(set(mediators))
    
    def identify_colliders(self) -> List[str]:
        """
        Identify colliders: nodes with multiple incoming edges.
        Conditioning on colliders creates spurious associations.
        """
        colliders = []
        
        for node_id in self.graph.nodes():
            if self.graph.in_degree(node_id) >= 2:
                colliders.append(node_id)
        
        return colliders
    
    def build_dag_from_context(self, context: Dict) -> None:
        """
        Build a Directed Acyclic Graph from query context.
        Main entry point for graph construction.
        """
        # Step 1: Identify candidate variables
        variables = self.identify_candidate_variables(context)
        
        # Step 2: Create nodes
        for var in variables:
            node = CausalNode(
                node_id=var,
                name=var,
                node_type=self.classify_node_type(var, context),
                measurement_quality=context.get('measurement_quality', {}).get(var, 0.8),
                uncertainty=UncertaintyLevel.MODERATE,
                metadata=context.get('node_metadata', {}).get(var, {})
            )
            self.add_node(node)
        
        # Step 3: Create edges from relationships
        if 'relationships' in context:
            for rel in context['relationships']:
                edge_type = EdgeType[rel.get('type', 'OBSERVED_CORRELATION')]
                edge = CausalEdge(
                    source=rel['source'],
                    target=rel['target'],
                    edge_type=edge_type,
                    weight=rel.get('weight', 0.5),
                    uncertainty=UncertaintyLevel[rel.get('uncertainty', 'MODERATE')],
                    evidence=rel.get('evidence', []),
                    temporal_lag=rel.get('temporal_lag'),
                    metadata=rel.get('metadata', {})
                )
                self.add_edge(edge)
        
        # Step 4: Validate DAG (detect cycles)
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            print(f"Warning: Graph contains cycles: {cycles}")
            print("Feedback loops detected - switching to dynamic systems mode")
    
    def get_adjustment_set(self, exposure: str, outcome: str) -> Set[str]:
        """
        Identify minimum sufficient adjustment set for causal effect estimation.
        Uses backdoor criterion.
        """
        # Simplified implementation - production should use causal-learn or dowhy
        confounders = set(self.identify_confounders(exposure, outcome))
        colliders = set(self.identify_colliders())
        
        # Remove colliders from adjustment set
        adjustment_set = confounders - colliders
        
        return adjustment_set
    
    def compute_relevance_scores(self, query: str) -> Dict[str, float]:
        """
        Compute relevance scores for each node based on query.
        Returns dict mapping node_id to relevance score (0-1).
        """
        scores = {}
        
        for node_id, node in self.nodes.items():
            # Simple scoring based on name match (replace with embeddings in production)
            score = 0.5  # default
            
            if node.name.lower() in query.lower():
                score = 0.9
            
            # Adjust by uncertainty
            score *= node.uncertainty.value
            
            scores[node_id] = score
        
        return scores
    
    def get_causal_paths(self, source: str, target: str, max_length: int = 5) -> List[List[str]]:
        """Get all causal paths from source to target up to max_length"""
        try:
            paths = nx.all_simple_paths(self.graph, source, target, cutoff=max_length)
            return list(paths)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
    
    def export_graph(self) -> Dict:
        """Export graph structure as dictionary"""
        return {
            'nodes': [node.to_dict() for node in self.nodes.values()],
            'edges': [edge.to_dict() for edge in self.edges],
            'metrics': {
                'node_count': len(self.nodes),
                'edge_count': len(self.edges),
                'is_dag': nx.is_directed_acyclic_graph(self.graph),
                'density': nx.density(self.graph)
            }
        }
    
    def visualize_ascii(self) -> str:
        """Generate ASCII representation of the graph"""
        lines = ["=== Causal Context Graph ===\n"]
        
        lines.append("Nodes:")
        for node_id, node in self.nodes.items():
            lines.append(f"  [{node.node_type}] {node.name} (uncertainty: {node.uncertainty.value})")
        
        lines.append("\nEdges:")
        for edge in self.edges:
            arrow = "→" if edge.edge_type == EdgeType.HYPOTHESIZED_CAUSE else "↔"
            lines.append(f"  {edge.source} {arrow} {edge.target} [{edge.edge_type.value}] (weight: {edge.weight})")
        
        return "\n".join(lines)


# Example usage and testing
if __name__ == "__main__":
    # Test the graph builder
    builder = ContextGraphBuilder()
    
    # Example context: Smoking and lung cancer
    context = {
        'exposure': 'smoking',
        'outcome': 'lung_cancer',
        'variables': ['smoking', 'lung_cancer', 'age', 'genetics', 'air_pollution'],
        'relationships': [
            {
                'source': 'smoking',
                'target': 'lung_cancer',
                'type': 'HYPOTHESIZED_CAUSE',
                'weight': 0.85,
                'uncertainty': 'HIGH_CONFIDENCE',
                'evidence': ['cohort_studies', 'rct_cessation']
            },
            {
                'source': 'age',
                'target': 'smoking',
                'type': 'OBSERVED_CORRELATION',
                'weight': 0.4,
                'uncertainty': 'MODERATE'
            },
            {
                'source': 'age',
                'target': 'lung_cancer',
                'type': 'OBSERVED_CORRELATION',
                'weight': 0.6,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'genetics',
                'target': 'lung_cancer',
                'type': 'POSSIBLE_CONFOUNDER',
                'weight': 0.5,
                'uncertainty': 'MODERATE'
            },
            {
                'source': 'air_pollution',
                'target': 'lung_cancer',
                'type': 'HYPOTHESIZED_CAUSE',
                'weight': 0.6,
                'uncertainty': 'MODERATE'
            }
        ]
    }
    
    builder.build_dag_from_context(context)
    
    print(builder.visualize_ascii())
    print("\n" + "="*50)
    print(f"Confounders: {builder.identify_confounders('smoking', 'lung_cancer')}")
    print(f"Adjustment set: {builder.get_adjustment_set('smoking', 'lung_cancer')}")
    print(f"Colliders: {builder.identify_colliders()}")
    
    # Export
    print("\n" + "="*50)
    print("Graph export:")
    print(json.dumps(builder.export_graph(), indent=2))
