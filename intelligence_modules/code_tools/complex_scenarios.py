"""
Example: Detective Investigation Scenario
Demonstrates the causal reasoning module on a complex real-world problem.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent))

from causal_cognitive_module import CausalReasoningModule


def detective_investigation_example():
    """
    Example: Investigating a suspicious death
    
    Scenario:
    - Victim: John Doe, found dead at 11:00 PM
    - Location: His apartment
    - Evidence: Empty glass with residue, open window, bruise on head
    
    Question: What caused John Doe's death?
    
    Variables:
    - death (outcome)
    - poison (potential cause)
    - fall (potential cause)
    - assault (potential cause)
    - time_of_death
    - glass_residue (evidence)
    - window_state (evidence)
    - head_bruise (evidence)
    """
    
    print("="*80)
    print("DETECTIVE INVESTIGATION: Suspicious Death")
    print("="*80)
    
    # Initialize module
    module_dir = Path(__file__).parent.parent
    module = CausalReasoningModule(module_dir)
    
    # Define the investigation query
    query = """
    John Doe was found dead in his apartment at 11:00 PM. 
    There is an empty glass with residue, an open window, and a bruise on his head.
    What caused his death? Was it poison, a fall, or assault?
    """
    
    # Define the causal context
    context_data = {
        'outcome': 'death',
        'variables': [
            'death',
            'poison',
            'fall',
            'assault',
            'glass_residue',
            'open_window',
            'head_bruise',
            'time_of_death'
        ],
        'node_types': {
            'death': 'outcome',
            'poison': 'exposure',
            'fall': 'exposure',
            'assault': 'exposure',
            'glass_residue': 'evidence',
            'open_window': 'evidence',
            'head_bruise': 'evidence'
        },
        'relationships': [
            # Poison hypothesis
            {
                'source': 'poison',
                'target': 'death',
                'type': 'HYPOTHESIZED_CAUSE',
                'weight': 0.7,
                'uncertainty': 'MODERATE',
                'evidence': ['glass_residue'],
                'temporal_lag': (0, 120)  # 0-120 minutes
            },
            {
                'source': 'glass_residue',
                'target': 'poison',
                'type': 'OBSERVED_CORRELATION',
                'weight': 0.8,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            
            # Fall hypothesis
            {
                'source': 'fall',
                'target': 'death',
                'type': 'HYPOTHESIZED_CAUSE',
                'weight': 0.6,
                'uncertainty': 'MODERATE',
                'evidence': ['open_window', 'head_bruise'],
                'temporal_lag': (0, 5)  # immediate
            },
            {
                'source': 'fall',
                'target': 'head_bruise',
                'type': 'MECHANISM_STEP',
                'weight': 0.9,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'open_window',
                'target': 'fall',
                'type': 'OBSERVED_CORRELATION',
                'weight': 0.5,
                'uncertainty': 'LOW_CONFIDENCE'
            },
            
            # Assault hypothesis
            {
                'source': 'assault',
                'target': 'death',
                'type': 'HYPOTHESIZED_CAUSE',
                'weight': 0.8,
                'uncertainty': 'MODERATE',
                'evidence': ['head_bruise'],
                'temporal_lag': (0, 30)
            },
            {
                'source': 'assault',
                'target': 'head_bruise',
                'type': 'MECHANISM_STEP',
                'weight': 0.95,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            
            # Confounding: assault could lead to fall
            {
                'source': 'assault',
                'target': 'fall',
                'type': 'POSSIBLE_CONFOUNDER',
                'weight': 0.7,
                'uncertainty': 'MODERATE'
            },
            
            # Confounding: poison could lead to fall (dizziness)
            {
                'source': 'poison',
                'target': 'fall',
                'type': 'POSSIBLE_CONFOUNDER',
                'weight': 0.6,
                'uncertainty': 'MODERATE'
            }
        ],
        'measurement_quality': {
            'glass_residue': 0.9,  # can be tested
            'open_window': 1.0,    # directly observed
            'head_bruise': 1.0,    # directly observed
            'time_of_death': 0.7   # estimated
        }
    }
    
    # Process through cognitive module
    context = module.process(query, context_data)
    
    # Display results
    print("\n" + context.final_response)
    
    # Additional analysis
    print("\n" + "="*80)
    print("ADDITIONAL DETECTIVE ANALYSIS")
    print("="*80)
    
    if context.calculation_results:
        print("\nGraph Analysis Results:")
        for key, value in context.calculation_results.items():
            print(f"  {key}: {value}")
    
    print("\n--- INVESTIGATIVE RECOMMENDATIONS ---")
    print("Based on the causal graph analysis:")
    print("1. Test glass residue for toxins (strongest evidence for poison)")
    print("2. Determine sequence: Did assault precede fall?")
    print("3. Examine head bruise pattern (assault vs. fall trauma differ)")
    print("4. Check window height and external landing (fall mechanics)")
    print("5. Consider combined causes (assault → poison → fall)")
    
    print("\n--- COGNITIVE PRIORS APPLIED ---")
    if context.retrieved_priors:
        for i, prior in enumerate(context.retrieved_priors[:3], 1):
            print(f"{i}. [{prior['category']}] {prior['statement']}")
    
    return context


def medical_diagnosis_example():
    """
    Example: Medical diagnosis with multiple symptoms
    
    Patient presents with:
    - Fever
    - Cough  
    - Fatigue
    - Difficulty breathing
    
    Possible diagnoses: COVID-19, Flu, Pneumonia, or combination?
    """
    
    print("\n" + "="*80)
    print("MEDICAL DIAGNOSIS: Respiratory Symptoms")
    print("="*80)
    
    module_dir = Path(__file__).parent.parent
    module = CausalReasoningModule(module_dir)
    
    query = """
    A patient presents with fever, cough, fatigue, and difficulty breathing.
    What is causing these symptoms? Is it COVID-19, influenza, pneumonia, or something else?
    """
    
    context_data = {
        'variables': [
            'fever', 'cough', 'fatigue', 'difficulty_breathing',
            'covid19', 'influenza', 'pneumonia', 'age', 'vaccination_status'
        ],
        'relationships': [
            # COVID-19 pathway
            {
                'source': 'covid19',
                'target': 'fever',
                'type': 'MECHANISM_STEP',
                'weight': 0.85,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'covid19',
                'target': 'cough',
                'type': 'MECHANISM_STEP',
                'weight': 0.80,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'covid19',
                'target': 'difficulty_breathing',
                'type': 'MECHANISM_STEP',
                'weight': 0.70,
                'uncertainty': 'MODERATE'
            },
            
            # Influenza pathway
            {
                'source': 'influenza',
                'target': 'fever',
                'type': 'MECHANISM_STEP',
                'weight': 0.90,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'influenza',
                'target': 'cough',
                'type': 'MECHANISM_STEP',
                'weight': 0.75,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'influenza',
                'target': 'fatigue',
                'type': 'MECHANISM_STEP',
                'weight': 0.85,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            
            # Pneumonia pathway
            {
                'source': 'pneumonia',
                'target': 'fever',
                'type': 'MECHANISM_STEP',
                'weight': 0.88,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'pneumonia',
                'target': 'cough',
                'type': 'MECHANISM_STEP',
                'weight': 0.90,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'pneumonia',
                'target': 'difficulty_breathing',
                'type': 'MECHANISM_STEP',
                'weight': 0.85,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            
            # Confounders
            {
                'source': 'age',
                'target': 'fever',
                'type': 'POSSIBLE_CONFOUNDER',
                'weight': 0.3,
                'uncertainty': 'LOW_CONFIDENCE'
            },
            {
                'source': 'vaccination_status',
                'target': 'covid19',
                'type': 'POSSIBLE_CONFOUNDER',
                'weight': 0.7,
                'uncertainty': 'HIGH_CONFIDENCE'
            },
            {
                'source': 'vaccination_status',
                'target': 'influenza',
                'type': 'POSSIBLE_CONFOUNDER',
                'weight': 0.6,
                'uncertainty': 'HIGH_CONFIDENCE'
            }
        ]
    }
    
    context = module.process(query, context_data)
    print("\n" + context.final_response)
    
    print("\n--- DIFFERENTIAL DIAGNOSIS RANKED BY GRAPH ANALYSIS ---")
    print("1. Pneumonia (strongest multi-symptom fit)")
    print("2. COVID-19 (high weight on breathing difficulty)")
    print("3. Influenza (high weight on fever + fatigue)")
    print("\nRecommendation: Order diagnostic tests in this priority")
    
    return context


if __name__ == "__main__":
    # Run detective investigation
    detective_context = detective_investigation_example()
    
    # Export for analysis
    output_path = Path(__file__).parent / 'detective_investigation_output.json'
    module_dir = Path(__file__).parent.parent
    module = CausalReasoningModule(module_dir)
    module.export_context(detective_context, output_path)
    
    # Run medical diagnosis
    medical_context = medical_diagnosis_example()
