"""
Deterministic Code Tools for Causal Reasoning
Mathematical and logical computations that must be exact and repeatable.
Keeps the LLM out of decisions it's bad at.
"""

import argparse
import sys
import json
import ast
from typing import List, Dict, Tuple, Set, Optional, Any
from dataclasses import dataclass
# Lazy imports for heavy libs (scipy, networkx, numpy) to allow partial usage


@dataclass
class EvidenceScore:
    """Scored evidence item"""
    evidence_id: str
    evidence_type: str
    quality_score: float
    weight: float
    metadata: Dict


class CausalMathTools:
    """Deterministic mathematical operations for causal inference"""
    
    @staticmethod
    def calculate_effect_size(
        treatment_mean: float,
        control_mean: float,
        pooled_std: float
    ) -> float:
        """
        Calculate Cohen's d effect size.
        Deterministic - no LLM interpretation.
        """
        if pooled_std == 0:
            return 0.0
        return (treatment_mean - control_mean) / pooled_std
    
    @staticmethod
    def calculate_confidence_interval(
        mean: float,
        std_error: float,
        confidence_level: float = 0.95
    ) -> Tuple[float, float]:
        """
        Calculate confidence interval.
        Returns (lower_bound, upper_bound).
        """
        from scipy import stats
        z_score = stats.norm.ppf((1 + confidence_level) / 2)
        margin = z_score * std_error
        return (mean - margin, mean + margin)
    
    @staticmethod
    def bayes_update(
        prior: float,
        likelihood_h1: float,
        likelihood_h0: float
    ) -> float:
        """
        Bayesian update of probability.
        P(H1|E) = P(E|H1) * P(H1) / [P(E|H1)*P(H1) + P(E|H0)*P(H0)]
        """
        prior_h0 = 1 - prior
        denominator = (likelihood_h1 * prior) + (likelihood_h0 * prior_h0)
        
        if denominator == 0:
            return prior
        
        posterior = (likelihood_h1 * prior) / denominator
        return posterior

    @staticmethod
    def calculate_tipping_point(
        observed_effect: float,
        standard_error: float,
        alpha: float = 0.05
    ) -> Dict[str, float]:
        """
        Calculate the 'Tipping Point' (Sensitivity Analysis).
        Determines how much an unmeasured confounder would have to 
        alter the data to invalidate the causal conclusion.
        """
        critical_value = 1.96 if alpha == 0.05 else 2.58
        margin_of_error = critical_value * standard_error
        
        # How far is the effect from the zero-line of significance?
        robustness_gap = abs(observed_effect) - margin_of_error
        
        return {
            "robustness_value": robustness_gap / abs(observed_effect) if observed_effect != 0 else 0,
            "tipping_point_magnitude": robustness_gap,
            "is_stable": robustness_gap > 0
        }
    
    @staticmethod
    def calculate_correlation(x: List[float], y: List[float]) -> Tuple[float, float]:
        """
        Calculate Pearson correlation coefficient and p-value.
        Returns (correlation, p_value).
        """
        if len(x) != len(y) or len(x) < 2:
            return (0.0, 1.0)
        
        from scipy import stats
        corr, p_value = stats.pearsonr(x, y)
        return (corr, p_value)
    
    @staticmethod
    def partial_correlation(
        x: np.ndarray,
        y: np.ndarray,
        z: np.ndarray
    ) -> float:
        """
        Calculate partial correlation between x and y controlling for z.
        This is critical for confounder adjustment.
        """
        import numpy as np
        # Residualize x and y with respect to z
        residual_x = x - np.dot(z, np.linalg.lstsq(z, x, rcond=None)[0])
        residual_y = y - np.dot(z, np.linalg.lstsq(z, y, rcond=None)[0])
        
        # Calculate correlation of residuals
        corr = np.corrcoef(residual_x, residual_y)[0, 1]
        return corr
    
    @staticmethod
    def power_analysis(
        effect_size: float,
        alpha: float = 0.05,
        n: int = 100
    ) -> float:
        """
        Calculate statistical power for given parameters.
        Returns power (0-1).
        """
        # Simplified power calculation for t-test
        from scipy.stats import nct
        from scipy import stats
        import numpy as np
        
        df = 2 * n - 2
        nc = effect_size * np.sqrt(n / 2)
        t_crit = stats.t.ppf(1 - alpha/2, df)
        
        power = 1 - nct.cdf(t_crit, df, nc) + nct.cdf(-t_crit, df, nc)
        return power


class GraphTraversalTools:
    """Deterministic graph traversal and analysis"""
    
    @staticmethod
    def find_top_k_paths(
        graph: nx.DiGraph,
        source: str,
        target: str,
        k: int = 5,
        weight_attr: str = 'weight'
    ) -> List[Tuple[List[str], float]]:
        """
        Find top-k weighted paths from source to target.
        Returns list of (path, total_weight) tuples.
        """
        all_paths = []
        
        import networkx as nx
        try:
            for path in nx.all_simple_paths(graph, source, target):
                # Calculate path weight
                total_weight = 0
                for i in range(len(path) - 1):
                    edge_data = graph.get_edge_data(path[i], path[i+1])
                    total_weight += edge_data.get(weight_attr, 0)
                
                all_paths.append((path, total_weight))
        except nx.NetworkXNoPath:
            return []
        
        # Sort by weight and return top k
        all_paths.sort(key=lambda x: x[1], reverse=True)
        return all_paths[:k]
    
    @staticmethod
    def find_strongest_path(
        graph: nx.DiGraph,
        source: str,
        target: str,
        weight_attr: str = 'weight'
    ) -> Optional[Tuple[List[str], float]]:
        """Find the single strongest path between two nodes"""
        paths = GraphTraversalTools.find_top_k_paths(graph, source, target, k=1, weight_attr=weight_attr)
        return paths[0] if paths else None
    
    @staticmethod
    def detect_contradictions(
        graph: nx.DiGraph,
        edge_type_attr: str = 'edge_type'
    ) -> List[Dict]:
        """
        Detect contradictory edges in the graph.
        Detect contradictory edges (e.g., X->Y (positive) and X->Y (negative) simultaneously.
        """
        contradictions = []
        
        # Group edges by (source, target) pair
        edge_groups = {}
        for u, v, data in graph.edges(data=True):
            key = (u, v)
            if key not in edge_groups:
                edge_groups[key] = []
            edge_groups[key].append(data)
        
        # Check for contradictions within each group
        for (u, v), edges in edge_groups.items():
            if len(edges) > 1:
                # Check for contradictory evidence
                edge_types = [e.get(edge_type_attr, '') for e in edges]
                if len(set(edge_types)) > 1:
                    contradictions.append({
                        'source': u,
                        'target': v,
                        'conflicting_types': edge_types,
                        'edges': edges
                    })
        
        return contradictions
    
    @staticmethod
    def calculate_node_centrality(graph: nx.DiGraph) -> Dict[str, float]:
        """
        Calculate betweenness centrality for all nodes.
        Identifies critical nodes in causal pathways.
        """
        import networkx as nx
        return nx.betweenness_centrality(graph)
    
    @staticmethod
    def identify_bottlenecks(
        graph: nx.DiGraph,
        source: str,
        target: str
    ) -> List[str]:
        """
        Identify bottleneck nodes: nodes that appear in all paths from source to target.
        These are critical mediators.
        """
        import networkx as nx
        try:
            all_paths = list(nx.all_simple_paths(graph, source, target))
        except nx.NetworkXNoPath:
            return []
        
        if not all_paths:
            return []
        
        # Find intersection of all paths (excluding source and target)
        path_sets = [set(path[1:-1]) for path in all_paths]
        bottlenecks = set.intersection(*path_sets) if path_sets else set()
        
        return list(bottlenecks)


class HypothesisRanking:
    """Deterministic hypothesis scoring and ranking"""
    
    @staticmethod
    def score_hypothesis(
        hypothesis: Dict,
        evidence_list: List[EvidenceScore],
        penalties: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Score a hypothesis based on evidence with penalty adjustments.
        
        Args:
            hypothesis: Hypothesis details
            evidence_list: List of evidence scores
            penalties: Dict of penalty types and amounts
        
        Returns:
            Final score (0-1)
        """
        if not evidence_list:
            return 0.0
        
        # Base score: weighted average of evidence
        total_weight = sum(e.weight for e in evidence_list)
        if total_weight == 0:
            base_score = 0.0
        else:
            base_score = sum(e.quality_score * e.weight for e in evidence_list) / total_weight
        
        # Apply penalties
        if penalties:
            for penalty_type, penalty_value in penalties.items():
                base_score *= (1 - penalty_value)
        
        return max(0.0, min(1.0, base_score))
    
    @staticmethod
    def rank_hypotheses(
        hypotheses: List[Dict],
        evidence_map: Dict[str, List[EvidenceScore]],
        penalties: Optional[Dict[str, Dict[str, float]]] = None
    ) -> List[Tuple[Dict, float]]:
        """
        Rank multiple hypotheses deterministically.
        
        Returns:
            List of (hypothesis, score) tuples sorted by score descending
        """
        ranked = []
        
        for hyp in hypotheses:
            hyp_id = hyp.get('hypothesis_id', '')
            evidence = evidence_map.get(hyp_id, [])
            hyp_penalties = penalties.get(hyp_id, {}) if penalties else None
            
            score = HypothesisRanking.score_hypothesis(hyp, evidence, hyp_penalties)
            ranked.append((hyp, score))
        
        # Sort by score descending
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked
    
    @staticmethod
    def apply_bradford_hill_criteria(
        strength: float,
        consistency: float,
        specificity: float,
        temporality: float,
        gradient: float,
        plausibility: float,
        coherence: float,
        experiment: float,
        analogy: float
    ) -> float:
        """
        Apply Bradford Hill criteria for causation.
        All inputs on 0-1 scale.
        Returns overall causal strength score.
        """
        # Weighted average - temporality is mandatory
        if temporality < 0.5:
            return 0.0  # Temporal precedence is necessary
        
        weights = {
            'strength': 0.15,
            'consistency': 0.15,
            'specificity': 0.10,
            'temporality': 0.20,  # highest weight - necessary condition
            'gradient': 0.10,
            'plausibility': 0.10,
            'coherence': 0.10,
            'experiment': 0.15,  # high weight for experimental evidence
            'analogy': 0.05
        }
        
        score = (
            weights['strength'] * strength +
            weights['consistency'] * consistency +
            weights['specificity'] * specificity +
            weights['temporality'] * temporality +
            weights['gradient'] * gradient +
            weights['plausibility'] * plausibility +
            weights['coherence'] * coherence +
            weights['experiment'] * experiment +
            weights['analogy'] * analogy
        )
        
        return score


class ValidationTools:
    """Deterministic validation and completeness checks"""
    
    @staticmethod
    def validate_plan_completeness(
        plan: Dict,
        required_fields: List[str]
    ) -> Tuple[bool, List[str]]:
        """
        Validate that a reasoning plan contains all required fields.
        
        Returns:
            (is_complete, missing_fields)
        """
        missing = []
        for field in required_fields:
            if field not in plan or plan[field] is None:
                missing.append(field)
        
        return (len(missing) == 0, missing)
    
    @staticmethod
    def enforce_token_budget(
        text: str,
        max_tokens: int,
        tokenizer_avg_chars_per_token: float = 4.0
    ) -> str:
        """
        Enforce token budget by truncating text.
        Uses approximate tokenization.
        """
        estimated_tokens = len(text) / tokenizer_avg_chars_per_token
        
        if estimated_tokens <= max_tokens:
            return text
        
        # Truncate
        target_chars = int(max_tokens * tokenizer_avg_chars_per_token)
        return text[:target_chars] + "... [truncated]"
    
    @staticmethod
    def check_dag_validity(graph: nx.DiGraph) -> Tuple[bool, Optional[List]]:
        """
        Check if graph is a valid DAG.
        
        Returns:
            (is_valid, cycles) where cycles is None if valid, else list of cycles
        """
        import networkx as nx
        if nx.is_directed_acyclic_graph(graph):
            return (True, None)
        else:
            cycles = list(nx.simple_cycles(graph))
            return (False, cycles)
    
    @staticmethod
    def verify_temporal_consistency(
        events: List[Dict[str, Any]],
        time_key: str = 'timestamp'
    ) -> Tuple[bool, List[str]]:
        """
        Verify temporal consistency of events.
        Checks that causes precede effects.
        
        Returns:
            (is_consistent, violations)
        """
        violations = []
        
        for i, event in enumerate(events):
            if 'causes' in event:
                event_time = event.get(time_key, 0)
                
                for caused_event_id in event['causes']:
                    # Find the caused event
                    caused_event = next((e for e in events if e.get('id') == caused_event_id), None)
                    
                    if caused_event:
                        caused_time = caused_event.get(time_key, 0)
                        
                        if event_time >= caused_time:
                            violations.append(
                                f"Event '{event.get('id')}' at time {event_time} "
                                f"cannot cause '{caused_event_id}' at earlier time {caused_time}"
                            )
        
        return (len(violations) == 0, violations)


class MemoryScoring:
    """Deterministic memory retrieval scoring"""
    
    @staticmethod
    def score_memory_relevance(
        memory_embedding: np.ndarray,
        query_embedding: np.ndarray,
        recency_weight: float = 0.3,
        importance_weight: float = 0.2,
        similarity_weight: float = 0.5,
        timestamp: Optional[float] = None,
        importance: float = 0.5,
        current_time: Optional[float] = None
    ) -> float:
        """
        Score memory relevance using multiple factors.
        Completely deterministic.
        
        Args:
            memory_embedding: Vector embedding of memory
            query_embedding: Vector embedding of query
            recency_weight: Weight for recency component
            importance_weight: Weight for importance component
            similarity_weight: Weight for semantic similarity
            timestamp: When memory was created
            importance: Importance score (0-1)
            current_time: Current timestamp
        
        Returns:
            Composite score (0-1)
        """
        # Semantic similarity (cosine)
        import numpy as np
        similarity = np.dot(memory_embedding, query_embedding) / (
            np.linalg.norm(memory_embedding) * np.linalg.norm(query_embedding)
        )
        similarity = (similarity + 1) / 2  # Normalize to 0-1
        
        # Recency score
        recency = 0.5  # default
        if timestamp is not None and current_time is not None:
            age = current_time - timestamp
            # Exponential decay: score = e^(-age/half_life)
            half_life = 86400  # 1 day in seconds
            recency = np.exp(-age / half_life)
        
        # Composite score
        score = (
            similarity_weight * similarity +
            recency_weight * recency +
            importance_weight * importance
        )
        
        return score
    
    @staticmethod
    def rank_memories(
        memories: List[Dict],
        query_embedding: np.ndarray,
        top_k: int = 10,
        current_time: Optional[float] = None
    ) -> List[Tuple[Dict, float]]:
        """
        Rank memories by relevance and return top-k.
        
        Returns:
            List of (memory, score) tuples
        """
        scored = []
        
        import numpy as np
        for memory in memories:
            score = MemoryScoring.score_memory_relevance(
                memory_embedding=np.array(memory['embedding']),
                query_embedding=query_embedding,
                timestamp=memory.get('timestamp'),
                importance=memory.get('importance', 0.5),
                current_time=current_time
            )
            scored.append((memory, score))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return scored[:top_k]


# Example usage
# --- CLI Wrapper ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deterministic Causal Math Tools CLI")
    parser.add_argument("--op", required=True, help="Name of the operation/method to execute")
    parser.add_argument("--args", nargs='*', help="Arguments in key=value format (e.g. x=10 y=[1,2])")
    
    args = parser.parse_args()
    
    # 1. Parse Arguments
    kwargs = {}
    if args.args:
        for arg in args.args:
            if '=' in arg:
                k, v = arg.split('=', 1)
                try:
                    # Try interpreting as Python literal (number, list, boolean, dict)
                    val = ast.literal_eval(v)
                except (ValueError, SyntaxError):
                    # Fallback to string
                    val = v
                    
                # Special handling for Graph files (auto-load)
                if k == 'graph' and isinstance(val, str) and val.endswith('.json'):
                    import os
                    if os.path.exists(val):
                        try:
                            with open(val, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            # Convert to NetworkX
                            import networkx as nx
                            if 'nodes' in data and 'edges' in data: # Custom context_builder format
                                G = nx.DiGraph()
                                for n in data['nodes']:
                                    G.add_node(n['node_id'], **n)
                                for e in data['edges']:
                                    G.add_edge(e['source'], e['target'], **e)
                                val = G
                            elif 'nodes' in data and 'links' in data: # Standard node-link
                                val = nx.node_link_graph(data)
                        except Exception as e:
                            print(f"Warning: Could not auto-load graph from {val}: {e}", file=sys.stderr)
                
                kwargs[k] = val

    # 2. Find Method
    tool_classes = [CausalMathTools, GraphTraversalTools, HypothesisRanking, ValidationTools, MemoryScoring]
    target_method = None
    
    for cls in tool_classes:
        if hasattr(cls, args.op):
            target_method = getattr(cls, args.op)
            break
            
    if not target_method:
        print(json.dumps({"error": f"Operation '{args.op}' not found"}), file=sys.stderr)
        sys.exit(1)
        
    # 3. Execute & Print
    try:
        result = target_method(**kwargs)
        
        # Helper to serialize sets/tuples
        def default_serializer(obj):
            if isinstance(obj, (set, tuple)):
                return list(obj)
            if hasattr(obj, 'to_dict'):
                return obj.to_dict()
            return str(obj)

        print(json.dumps(result, indent=2, default=default_serializer))
        
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        sys.exit(1)
