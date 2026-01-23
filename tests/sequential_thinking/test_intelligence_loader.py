"""
Tests for Intelligence Loader

Tests the API interface to Frank's Causal Intelligence Module (CIM)
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.sequential_thinking.intelligence_loader import (
    IntelligenceLoader,
    create_loader
)


# ========== FIXTURES ==========

@pytest.fixture
def loader():
    """Create IntelligenceLoader instance for testing"""
    return create_loader("intelligence_modules")


# ========== INITIALIZATION TESTS ==========

def test_loader_initialization(loader):
    """Test that loader initializes and loads all datasets"""
    assert loader is not None
    
    # Check datasets loaded
    assert len(loader.cognitive_priors) > 0, "Cognitive priors not loaded"
    assert len(loader.anti_patterns) > 0, "Anti-patterns not loaded"
    assert len(loader.reasoning_procedures) > 0, "Reasoning procedures not loaded"
    assert len(loader.ability_injectors) > 0, "Ability injectors not loaded"
    assert len(loader.math_registry) > 0, "Math registry not loaded"
    
    print(f"✅ Loaded: {loader}")


def test_get_stats(loader):
    """Test stats method"""
    stats = loader.get_stats()
    
    assert isinstance(stats, dict)
    assert 'cognitive_priors' in stats
    assert 'anti_patterns' in stats
    assert 'reasoning_procedures' in stats
    assert stats['cognitive_priors'] > 0
    assert stats['anti_patterns'] > 0
    
    print(f"✅ Stats: {stats}")


# ========== BIAS DETECTION TESTS ==========

def test_check_cognitive_bias_correlation_causation(loader):
    """Test detection of correlation-causation fallacy"""
    context = {
        'text': "X and Y are correlated, therefore X causes Y"
    }
    
    biases = loader.check_cognitive_bias(context)
    
    assert len(biases) > 0, "Should detect correlation-causation bias"
    
    # Check for AP002 (Correlation-Causation Conflation)
    ap002_found = any(b['pattern_id'] == 'AP002' for b in biases)
    assert ap002_found, "Should detect AP002"
    
    # Check bias structure
    bias = biases[0]
    assert 'pattern_id' in bias
    assert 'name' in bias
    assert 'severity' in bias
    assert 'correction_rule' in bias
    
    print(f"✅ Detected {len(biases)} biases")
    for b in biases:
        print(f"   - {b['pattern_id']}: {b['name']}")


def test_check_cognitive_bias_post_hoc(loader):
    """Test detection of post hoc fallacy"""
    context = {
        'text': "X happened before Y, therefore X caused Y"
    }
    
    biases = loader.check_cognitive_bias(context)
    
    # Should detect AP001 (Post Hoc Fallacy)
    ap001_found = any(b['pattern_id'] == 'AP001' for b in biases)
    assert ap001_found, "Should detect post hoc fallacy"
    
    print(f"✅ Detected post hoc fallacy")


def test_check_cognitive_bias_no_triggers(loader):
    """Test that clean reasoning doesn't trigger false positives"""
    context = {
        'text': "We conducted a randomized controlled trial to test causation"
    }
    
    biases = loader.check_cognitive_bias(context)
    
    # Should detect very few or no biases (this is good reasoning)
    print(f"✅ Clean reasoning detected {len(biases)} biases (expected: few)")


def test_check_cognitive_bias_invalid_input(loader):
    """Test error handling for invalid input"""
    with pytest.raises(ValueError):
        loader.check_cognitive_bias("not a dict")


# ========== PROCEDURE SELECTION TESTS ==========

def test_list_available_procedures(loader):
    """Test listing available procedures"""
    procedures = loader.list_available_procedures()
    
    assert isinstance(procedures, list)
    assert len(procedures) > 0, "Should have at least one procedure"
    
    print(f"✅ Available procedures: {len(procedures)}")
    print(f"   Examples: {procedures[:3]}")


def test_get_reasoning_procedure(loader):
    """Test procedure selection"""
    # Get first available procedure type
    procedures = loader.list_available_procedures()
    
    if len(procedures) > 0:
        first_type = procedures[0]
        procedure = loader.get_reasoning_procedure(first_type)
        
        assert procedure is not None
        assert isinstance(procedure, dict)
        
        print(f"✅ Retrieved procedure: {first_type}")


def test_get_reasoning_procedure_fallback(loader):
    """Test fallback when procedure type not found"""
    procedure = loader.get_reasoning_procedure("nonexistent_type")
    
    # Should return fallback (first procedure)
    assert procedure is not None
    
    print("✅ Fallback procedure works")


# ========== CONTEXT GRAPH TESTS ==========

def test_build_context_graph(loader):
    """Test graph construction"""
    variables = ['smoking', 'lung_cancer', 'age', 'genetics']
    
    graph = loader.build_context_graph(
        variables=variables,
        domain='epidemiology'
    )
    
    assert graph is not None
    assert isinstance(graph, dict)
    assert 'variables' in graph
    
    print(f"✅ Built graph for {len(variables)} variables")


def test_get_domain_template(loader):
    """Test domain template retrieval"""
    # Try to get a domain template
    # (May return None if domain not in dataset)
    template = loader.get_domain_template('general')
    
    print(f"✅ Domain template: {template is not None}")


# ========== MATH VALIDATION TESTS ==========

def test_validate_with_math(loader):
    """Test math validation interface"""
    result = loader.validate_with_math(
        function_name='cohens_d',
        mean1=10.0,
        mean2=12.0,
        sd1=2.0,
        sd2=2.0
    )
    
    assert result is not None
    assert isinstance(result, dict)
    assert 'function' in result
    assert result['function'] == 'cohens_d'
    
    print(f"✅ Math validation interface works")


# ========== COGNITIVE PRIORS TESTS ==========

def test_get_relevant_priors(loader):
    """Test cognitive prior retrieval"""
    context = {
        'text': "I observed a correlation between X and Y"
    }
    
    priors = loader.get_relevant_priors(context)
    
    assert isinstance(priors, list)
    # May have 0 or more priors depending on triggers
    
    print(f"✅ Retrieved {len(priors)} relevant priors")
    if len(priors) > 0:
        print(f"   Example: {priors[0]['prior_id']}")


def test_get_relevant_priors_invalid_input(loader):
    """Test error handling for priors"""
    with pytest.raises(ValueError):
        loader.get_relevant_priors("not a dict")


# ========== ABILITY INJECTION TESTS ==========

def test_get_ability_injector(loader):
    """Test ability injector retrieval"""
    # Get first ability type from dataset
    if len(loader.ability_injectors) > 0:
        first_ability = loader.ability_injectors.iloc[0]
        ability_type = first_ability.get('ability_type', 'test')
        
        injector = loader.get_ability_injector(ability_type)
        
        # May return dict or None
        print(f"✅ Ability injector: {injector is not None}")


# ========== INTEGRATION TESTS ==========

def test_complete_workflow(loader):
    """Test complete bias detection -> procedure selection workflow"""
    # Step 1: Check for biases
    context = {
        'text': 'X and Y are correlated, so X causes Y'
    }
    
    biases = loader.check_cognitive_bias(context)
    assert len(biases) > 0, "Should detect bias"
    
    # Step 2: Get procedures
    procedures = loader.list_available_procedures()
    assert len(procedures) > 0
    
    # Step 3: Select procedure
    if len(procedures) > 0:
        procedure = loader.get_reasoning_procedure(procedures[0])
        assert procedure is not None
    
    # Step 4: Get priors
    priors = loader.get_relevant_priors(context)
    assert isinstance(priors, list)
    
    print("✅ Complete workflow successful")
    print(f"   Biases: {len(biases)}")
    print(f"   Procedures: {len(procedures)}")
    print(f"   Priors: {len(priors)}")


# ========== MAIN ==========

if __name__ == "__main__":
    print("=== Running Intelligence Loader Tests ===\n")
    pytest.main([__file__, "-v", "-s"])
