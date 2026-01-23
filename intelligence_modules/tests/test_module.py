"""
Unit tests for the Causal Reasoning Cognitive Module
Run with: pytest test_module.py
"""

import sys
from pathlib import Path
import json

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

import pytest
import pandas as pd
from context_builder import (
    ContextGraphBuilder, CausalNode, CausalEdge, 
    EdgeType, UncertaintyLevel
)
from code_tools.causal_math_tools import (
    CausalMathTools, GraphTraversalTools, HypothesisRanking,
    ValidationTools, EvidenceScore
)


class TestCausalMathTools:
    """Test deterministic mathematical operations"""
    
    def test_effect_size_calculation(self):
        effect = CausalMathTools.calculate_effect_size(10.0, 8.0, 2.0)
        assert effect == 1.0, "Effect size should be (10-8)/2 = 1.0"
    
    def test_effect_size_zero_std(self):
        effect = CausalMathTools.calculate_effect_size(10.0, 8.0, 0.0)
        assert effect == 0.0, "Effect size should be 0 when std is 0"
    
    def test_confidence_interval(self):
        ci = CausalMathTools.calculate_confidence_interval(10.0, 1.0, 0.95)
        lower, upper = ci
        assert lower < 10.0 < upper, "Mean should be within CI"
        assert abs(upper - lower - 3.92) < 0.1, "95% CI for std_error=1 should be ~1.96*2"
    
    def test_bayes_update(self):
        # Strong evidence for H1
        posterior = CausalMathTools.bayes_update(
            prior=0.5, 
            likelihood_h1=0.9, 
            likelihood_h0=0.1
        )
        assert posterior > 0.5, "Posterior should increase with strong evidence"
        assert 0 <= posterior <= 1, "Posterior must be valid probability"
    
    def test_bayes_update_zero_denominator(self):
        posterior = CausalMathTools.bayes_update(
            prior=0.5,
            likelihood_h1=0.0,
            likelihood_h0=0.0
        )
        assert posterior == 0.5, "Should return prior when denominator is 0"


class TestGraphTraversal:
    """Test graph traversal and analysis tools"""
    
    def test_find_top_k_paths(self):
        import networkx as nx
        
        # Create simple graph
        G = nx.DiGraph()
        G.add_edge('A', 'B', weight=0.8)
        G.add_edge('B', 'C', weight=0.7)
        G.add_edge('A', 'C', weight=0.5)
        
        paths = GraphTraversalTools.find_top_k_paths(G, 'A', 'C', k=2)
        
        assert len(paths) == 2, "Should find 2 paths"
        assert paths[0][1] >= paths[1][1], "Paths should be sorted by weight"
    
    def test_find_top_k_paths_no_path(self):
        import networkx as nx
        
        G = nx.DiGraph()
        G.add_edge('A', 'B', weight=0.8)
        
        paths = GraphTraversalTools.find_top_k_paths(G, 'A', 'C', k=5)
        assert len(paths) == 0, "Should return empty list when no path exists"
    
    def test_detect_contradictions(self):
        import networkx as nx
        
        G = nx.DiGraph()
        G.add_edge('A', 'B', edge_type='positive')
        G.add_edge('A', 'B', edge_type='negative')
        
        contradictions = GraphTraversalTools.detect_contradictions(G)
        assert len(contradictions) > 0, "Should detect contradictory edges"


class TestHypothesisRanking:
    """Test hypothesis scoring and ranking"""
    
    def test_score_hypothesis_no_evidence(self):
        score = HypothesisRanking.score_hypothesis(
            hypothesis={'id': 'H1'},
            evidence_list=[],
            penalties=None
        )
        assert score == 0.0, "No evidence should give score of 0"
    
    def test_score_hypothesis_with_evidence(self):
        evidence = [
            EvidenceScore('E1', 'RCT', 0.9, 1.0, {}),
            EvidenceScore('E2', 'cohort', 0.7, 0.5, {})
        ]
        
        score = HypothesisRanking.score_hypothesis(
            hypothesis={'id': 'H1'},
            evidence_list=evidence,
            penalties=None
        )
        
        assert 0 < score <= 1, "Score should be valid probability"
        assert score > 0.7, "High quality evidence should give high score"
    
    def test_score_hypothesis_with_penalties(self):
        evidence = [EvidenceScore('E1', 'RCT', 0.9, 1.0, {})]
        
        score_no_penalty = HypothesisRanking.score_hypothesis(
            hypothesis={'id': 'H1'},
            evidence_list=evidence,
            penalties=None
        )
        
        score_with_penalty = HypothesisRanking.score_hypothesis(
            hypothesis={'id': 'H1'},
            evidence_list=evidence,
            penalties={'bias': 0.3}
        )
        
        assert score_with_penalty < score_no_penalty, "Penalties should reduce score"
    
    def test_bradford_hill_criteria(self):
        # Strong causal evidence
        score = HypothesisRanking.apply_bradford_hill_criteria(
            strength=0.9,
            consistency=0.9,
            specificity=0.8,
            temporality=1.0,
            gradient=0.8,
            plausibility=0.9,
            coherence=0.9,
            experiment=0.9,
            analogy=0.7
        )
        
        assert score > 0.8, "Strong evidence should give high score"
    
    def test_bradford_hill_no_temporality(self):
        # Missing temporal precedence (necessary condition)
        score = HypothesisRanking.apply_bradford_hill_criteria(
            strength=0.9,
            consistency=0.9,
            specificity=0.8,
            temporality=0.3,  # Below threshold
            gradient=0.8,
            plausibility=0.9,
            coherence=0.9,
            experiment=0.9,
            analogy=0.7
        )
        
        assert score == 0.0, "Missing temporal precedence should give score of 0"


class TestValidationTools:
    """Test validation and completeness checks"""
    
    def test_validate_plan_completeness_valid(self):
        plan = {
            'field1': 'value1',
            'field2': 'value2',
            'field3': 'value3'
        }
        
        is_complete, missing = ValidationTools.validate_plan_completeness(
            plan,
            ['field1', 'field2', 'field3']
        )
        
        assert is_complete, "Plan should be complete"
        assert len(missing) == 0, "No fields should be missing"
    
    def test_validate_plan_completeness_missing(self):
        plan = {
            'field1': 'value1'
        }
        
        is_complete, missing = ValidationTools.validate_plan_completeness(
            plan,
            ['field1', 'field2', 'field3']
        )
        
        assert not is_complete, "Plan should be incomplete"
        assert 'field2' in missing, "field2 should be missing"
        assert 'field3' in missing, "field3 should be missing"
    
    def test_enforce_token_budget_no_truncation(self):
        text = "Short text"
        result = ValidationTools.enforce_token_budget(text, max_tokens=100)
        assert result == text, "Short text should not be truncated"
    
    def test_enforce_token_budget_truncation(self):
        text = "A" * 1000
        result = ValidationTools.enforce_token_budget(text, max_tokens=10)
        assert len(result) < len(text), "Long text should be truncated"
        assert "[truncated]" in result, "Should indicate truncation"
    
    def test_check_dag_validity_valid(self):
        import networkx as nx
        
        G = nx.DiGraph()
        G.add_edge('A', 'B')
        G.add_edge('B', 'C')
        
        is_valid, cycles = ValidationTools.check_dag_validity(G)
        assert is_valid, "Acyclic graph should be valid"
        assert cycles is None, "No cycles should be found"
    
    def test_check_dag_validity_cycle(self):
        import networkx as nx
        
        G = nx.DiGraph()
        G.add_edge('A', 'B')
        G.add_edge('B', 'C')
        G.add_edge('C', 'A')  # Creates cycle
        
        is_valid, cycles = ValidationTools.check_dag_validity(G)
        assert not is_valid, "Cyclic graph should be invalid"
        assert len(cycles) > 0, "Cycle should be detected"


class TestContextGraphBuilder:
    """Test context graph construction"""
    
    def test_add_node(self):
        builder = ContextGraphBuilder()
        
        node = CausalNode(
            node_id='X',
            name='Variable X',
            node_type='exposure',
            measurement_quality=0.9,
            uncertainty=UncertaintyLevel.HIGH_CONFIDENCE
        )
        
        builder.add_node(node)
        
        assert 'X' in builder.nodes, "Node should be added"
        assert 'X' in builder.graph.nodes, "Node should be in networkx graph"
    
    def test_add_edge(self):
        builder = ContextGraphBuilder()
        
        # Add nodes first
        node1 = CausalNode('A', 'A', 'exposure', 0.9, UncertaintyLevel.HIGH_CONFIDENCE)
        node2 = CausalNode('B', 'B', 'outcome', 0.9, UncertaintyLevel.HIGH_CONFIDENCE)
        builder.add_node(node1)
        builder.add_node(node2)
        
        # Add edge
        edge = CausalEdge(
            source='A',
            target='B',
            edge_type=EdgeType.HYPOTHESIZED_CAUSE,
            weight=0.8,
            uncertainty=UncertaintyLevel.MODERATE
        )
        
        builder.add_edge(edge)
        
        assert len(builder.edges) == 1, "Edge should be added"
        assert builder.graph.has_edge('A', 'B'), "Edge should be in networkx graph"
    
    def test_identify_confounders(self):
        builder = ContextGraphBuilder()
        
        # Create DAG: Z -> X, Z -> Y (Z is confounder)
        for node_id in ['X', 'Y', 'Z']:
            builder.add_node(CausalNode(node_id, node_id, 'variable', 0.9, UncertaintyLevel.HIGH_CONFIDENCE))
        
        builder.add_edge(CausalEdge('Z', 'X', EdgeType.HYPOTHESIZED_CAUSE, 0.7, UncertaintyLevel.MODERATE))
        builder.add_edge(CausalEdge('Z', 'Y', EdgeType.HYPOTHESIZED_CAUSE, 0.7, UncertaintyLevel.MODERATE))
        
        confounders = builder.identify_confounders('X', 'Y')
        
        assert 'Z' in confounders, "Z should be identified as confounder"
    
    def test_identify_mediators(self):
        builder = ContextGraphBuilder()
        
        # Create chain: X -> M -> Y (M is mediator)
        for node_id in ['X', 'M', 'Y']:
            builder.add_node(CausalNode(node_id, node_id, 'variable', 0.9, UncertaintyLevel.HIGH_CONFIDENCE))
        
        builder.add_edge(CausalEdge('X', 'M', EdgeType.MECHANISM_STEP, 0.8, UncertaintyLevel.HIGH_CONFIDENCE))
        builder.add_edge(CausalEdge('M', 'Y', EdgeType.MECHANISM_STEP, 0.8, UncertaintyLevel.HIGH_CONFIDENCE))
        
        mediators = builder.identify_mediators('X', 'Y')
        
        assert 'M' in mediators, "M should be identified as mediator"
    
    def test_identify_colliders(self):
        builder = ContextGraphBuilder()
        
        # Create collider: X -> C <- Y
        for node_id in ['X', 'Y', 'C']:
            builder.add_node(CausalNode(node_id, node_id, 'variable', 0.9, UncertaintyLevel.HIGH_CONFIDENCE))
        
        builder.add_edge(CausalEdge('X', 'C', EdgeType.HYPOTHESIZED_CAUSE, 0.7, UncertaintyLevel.MODERATE))
        builder.add_edge(CausalEdge('Y', 'C', EdgeType.HYPOTHESIZED_CAUSE, 0.7, UncertaintyLevel.MODERATE))
        
        colliders = builder.identify_colliders()
        
        assert 'C' in colliders, "C should be identified as collider"


class TestDatasetLoading:
    """Test that CSV datasets are properly formatted"""
    
    def test_cognitive_priors_schema(self):
        path = Path(__file__).parent.parent / 'knowledge_rag' / 'cognitive_priors.csv'
        df = pd.read_csv(path)
        
        required_columns = [
            'prior_id', 'prior_type', 'category', 'statement',
            'metadata', 'active_trigger', 'retrieval_weight', 'source_domain'
        ]
        
        for col in required_columns:
            assert col in df.columns, f"Missing required column: {col}"
        
        assert len(df) > 0, "Should have at least one prior"
        assert df['retrieval_weight'].between(0, 1).all(), "Weights should be 0-1"
    
    def test_procedures_schema(self):
        path = Path(__file__).parent.parent / 'procedural_rag' / 'causal_reasoning_procedures.csv'
        df = pd.read_csv(path)
        
        required_columns = [
            'procedure_id', 'procedure_name', 'step_sequence',
            'constraint_type', 'trigger_context', 'required_outputs', 'enforcement_level'
        ]
        
        for col in required_columns:
            assert col in df.columns, f"Missing required column: {col}"
        
        assert len(df) > 0, "Should have at least one procedure"
    
    def test_abilities_schema(self):
        path = Path(__file__).parent.parent / 'ability_rag' / 'ability_injectors.csv'
        df = pd.read_csv(path)
        
        required_columns = [
            'ability_id', 'ability_name', 'injection_type',
            'prompt_override', 'trigger_condition', 'scope', 'priority', 'reversible'
        ]
        
        for col in required_columns:
            assert col in df.columns, f"Missing required column: {col}"
        
        assert len(df) > 0, "Should have at least one ability"


if __name__ == "__main__":
    # Run tests manually
    print("Running manual tests (use pytest for full test suite)...")
    
    # Test math tools
    print("\n=== Testing Causal Math Tools ===")
    test_math = TestCausalMathTools()
    test_math.test_effect_size_calculation()
    test_math.test_bayes_update()
    print("✓ Math tools tests passed")
    
    # Test graph builder
    print("\n=== Testing Graph Builder ===")
    test_graph = TestContextGraphBuilder()
    test_graph.test_add_node()
    test_graph.test_identify_confounders()
    print("✓ Graph builder tests passed")
    
    # Test validation tools
    print("\n=== Testing Validation Tools ===")
    test_val = TestValidationTools()
    test_val.test_validate_plan_completeness_valid()
    test_val.test_check_dag_validity_valid()
    print("✓ Validation tools tests passed")
    
    # Test datasets
    print("\n=== Testing Dataset Schemas ===")
    test_data = TestDatasetLoading()
    test_data.test_cognitive_priors_schema()
    test_data.test_procedures_schema()
    test_data.test_abilities_schema()
    print("✓ Dataset schema tests passed")
    
    print("\n" + "="*50)
    print("ALL TESTS PASSED ✓")
    print("="*50)
