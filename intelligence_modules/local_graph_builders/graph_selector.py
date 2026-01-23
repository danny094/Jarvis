
from typing import Type, Dict
from .base_builder import BaseGraphBuilder
from .light_graph_builder import LightGraphBuilder
from .heavy_graph_builder import HeavyGraphBuilder
from .strategic_graph_builder import StrategicGraphBuilder
from .temporal_graph_builder import TemporalGraphBuilder
from .simulation_graph_builder import SimulationGraphBuilder

class GraphSelector:
    """
    Orchestrator that selects the most appropriate Graph Builder 
    based on query intent and complexity.
    """
    
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        # Registry of builders
        self.builders: Dict[str, Type[BaseGraphBuilder]] = {
            "light": LightGraphBuilder,
            "heavy": HeavyGraphBuilder,
            "strategic": StrategicGraphBuilder,
            "temporal": TemporalGraphBuilder,
            "simulation": SimulationGraphBuilder
        }

    def select_builder(self, query: str) -> BaseGraphBuilder:
        """
        Analyze query keywords and structure to route to the correct builder.
        """
        q = query.lower()
        
        # 1. Simulation/Counterfactual ("What if", "Hypothetically", "If I had")
        if any(word in q for word in ["what if", "hypothetically", "counterfactual", "imagine", "had not"]):
            return self.builders["simulation"](self.workspace_root)
        
        # 2. Temporal/Time-series ("Time", "Lag", "Forecast", "History", "Sequence")
        if any(word in q for word in ["time", "lag", "historical", "sequence", "trend", "forecast", "years", "months"]):
            return self.builders["temporal"](self.workspace_root)
        
        # 3. Strategic/Decision ("Should", "Best way", "Optimize", "Strategy", "Action")
        if any(word in q for word in ["should", "strategy", "optimize", "maximize", "best way", "decision", "action"]):
            return self.builders["strategic"](self.workspace_root)
        
        # 4. Heavy (Complexity/Safety)
        # Trigger heavy if query is long or contains complex causality terms
        if len(q.split()) > 15 or any(word in q for word in ["bias", "paradox", "confounding", "complex", "mechanism"]):
            return self.builders["heavy"](self.workspace_root)
            
        # 5. Default to Light for quick, simple causal checks
        return self.builders["light"](self.workspace_root)

    def get_builder_by_name(self, name: str) -> BaseGraphBuilder:
        """Manually override and get a specific builder."""
        return self.builders.get(name, LightGraphBuilder)(self.workspace_root)

if __name__ == "__main__":
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    selector = GraphSelector(root)
    
    test_queries = [
        "Why is inflation rising?", # Expected: Light
        "What if we had raised interest rates 6 months ago?", # Expected: Simulation
        "What is the best strategy to reduce churn?", # Expected: Strategic
        "Analyze the complex interaction of bias and confounding in drug trials" # Expected: Heavy
    ]
    
    for tq in test_queries:
        builder = selector.select_builder(tq)
        print(f"Query: '{tq}' -> Selected: {builder.__class__.__name__}")
