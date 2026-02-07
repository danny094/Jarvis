# tests/pipeline/test_cases.py

"""
Central definitions for TRION Pipeline Test Cases.
This file is imported by specific test modules to ensure consistency.
"""

# -----------------------------------------------------------------------------
# 1. MCP DETECTION CASES
# Logic: Query -> ThinkingLayer -> Intent -> Expected Tools
# -----------------------------------------------------------------------------
MCP_DETECTION_CASES = [
    # Time & Date (Simple)
    {
        "id": "time_001",
        "query": "What time is it?",
        "expected_tools": ["get_current_time"],
        "category": "time-mcp"
    },
    {
        "id": "time_002",
        "query": "What timezone am I in?",
        "expected_tools": ["get_timezone"],
        "category": "time-mcp"
    },
    
    # Memory: Explicit Save
    {
        "id": "mem_save_001",
        "query": "Remember that my favorite color is blue",
        "expected_tools": ["memory_save"],
        "category": "memory"
    },
    {
        "id": "mem_save_002",
        "query": "Please note: I have a meeting at 5pm",
        "expected_tools": ["memory_save"],
        "category": "memory"
    },
    
    # Memory: Search/Recall
    {
        "id": "mem_search_001",
        "query": "What is my favorite color?",
        "expected_tools": ["memory_graph_search"],
        "category": "memory"
    },
    {
        "id": "mem_search_002",
        "query": "Do you know when my meeting is?",
        "expected_tools": ["memory_graph_search"],
        "category": "memory"
    },
    
    # No Tool (General Knowledge / Chitchat)
    {
        "id": "chat_001",
        "query": "Hello, how are you?",
        "expected_tools": [],
        "category": "chitchat"
    },
    {
        "id": "know_001",
        "query": "Explain the theory of relativity briefly",
        "expected_tools": [],
        "category": "knowledge"
    },
]

# -----------------------------------------------------------------------------
# 2. SEQUENTIAL THINKING ACTIVATION CASES
# Logic: Query -> Complexity Analysis -> needs_sequential_thinking (Bool)
# -----------------------------------------------------------------------------
SEQUENTIAL_THINKING_CASES = [
    # Should ACTIVATE (Complex/Multi-step)
    {
        "id": "seq_pos_001",
        "query": "Plan a 3-day trip to Paris including museums and food",
        "needs_sequential": True,
        "reason": "complex_planning"
    },
    {
        "id": "seq_pos_002",
        "query": "Compare Python and Rust for backend development",
        "needs_sequential": True,
        "reason": "comparison"
    },
    {
        "id": "seq_pos_003",
        "query": "Explain how a blockchain works step-by-step",
        "needs_sequential": True,
        "reason": "explicit_step_by_step"
    },
    
    # Should NOT ACTIVATE (Simple/Direct)
    {
        "id": "seq_neg_001",
        "query": "What time is it?",
        "needs_sequential": False,
        "reason": "simple_query"
    },
    {
        "id": "seq_neg_002",
        "query": "Who wrote Hamlet?",
        "needs_sequential": False,
        "reason": "fact_lookup"
    },
]

# -----------------------------------------------------------------------------
# 3. CIM (Cognitive Immune System) ACTIVATION CASES
# Logic: Query -> Bias Detection -> suggested_cim_modes (List)
# -----------------------------------------------------------------------------
CIM_ACTIVATION_CASES = [
    # Activation Expected
    {
        "id": "cim_pos_001",
        "query": "Is this argument logically valid: All men are mortal, Socrates is a man?",
        "expected_cim_modes": ["logical_validation"],
        "should_activate": True
    },
    {
        "id": "cim_pos_002",
        "query": "Everyone says Bitcoin is a scam, is that true?",
        "expected_cim_modes": ["bias_detection"], # or similar mode mapping
        "should_activate": True
    },
    
    # No Activation
    {
        "id": "cim_neg_001",
        "query": "Hello world",
        "expected_cim_modes": [],
        "should_activate": False
    },
]

# -----------------------------------------------------------------------------
# 4. CONTROL LAYER SORTING CASES
# Logic: Query -> Plan -> Execution Order
# -----------------------------------------------------------------------------
CONTROL_SORTING_CASES = [
    {
        "id": "sort_001",
        "query": "Save: I like pizza. What is my favorite food?",
        "expected_order": ["memory_save", "memory_graph_search"],
        "reason": "save_before_read"
    }
]
