import pandas as pd
import numpy as np
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import sys

# Ensure code_tools is in path
sys.path.append(str(Path(__file__).parent / "code_tools"))

try:
    from code_tools.causal_math_tools import CausalMathTools, GraphTraversalTools, ValidationTools, HypothesisRanking
except ImportError:
    # Fallback if running from a different root
    print("Warning: code_tools not found in path. Tool execution will be mocked.")

class CausalController:
    """
    The Orchestrator for the Causal Intelligence Module (CIM).
    Implements the 3-Stage 'Snowball' Retrieval Strategy.
    """
    
    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.logger = self._setup_logger()
        
        # Paths to RAG layers
        self.knowledge_path = self.root / "knowledge_rag"
        self.procedural_path = self.root / "procedural_rag"
        self.executable_path = self.root / "executable_rag"
        self.tool_path = self.root / "code_tools"

        # In-Memory Dataframes (The "Index")
        self.priors_df = None
        self.domain_graphs_df = None
        self.procedures_df = None
        self.anti_patterns_df = None
        self.injectors_df = None
        self.tool_registry_df = None

        self._load_datasets()
        self.logger.info("Causal Controller Initialized. All Knowledge Layers Loaded.")

    def _setup_logger(self):
        logger = logging.getLogger("CIM_Controller")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _load_datasets(self):
        """Loads all CSVs from the 3 layers into pandas DataFrames."""
        try:
            # Stage 1: Knowledge
            self.priors_df = pd.read_csv(self.knowledge_path / "cognitive_priors_v2.csv")
            self.domain_graphs_df = pd.read_csv(self.knowledge_path / "domain_graphs.csv", skipinitialspace=True)
            
            # Stage 2: Procedural
            self.procedures_df = pd.read_csv(self.procedural_path / "causal_reasoning_procedures_v2.csv")
            self.anti_patterns_df = pd.read_csv(self.procedural_path / "anti_patterns.csv")
            
            # Stage 3: Executable
            self.injectors_df = pd.read_csv(self.executable_path / "ability_injectors_v2.csv")
            self.tool_registry_df = pd.read_csv(self.executable_path / "causal_math_registry.csv")
            
        except FileNotFoundError as e:
            self.logger.error(f"Critical Dataset Missing: {e}")
            raise

    def process_query(self, user_query: str) -> Dict[str, Any]:
        """
        The Main Pipeline: Executes the Snowball Retrieval Strategy.
        """
        self.logger.info(f"Processing Query: '{user_query}'")
        
        # --- Stage 1: Knowledge Scaffold ---
        context = self._retrieve_knowledge(user_query)
        self.logger.info(f"Stage 1 Complete. Found {len(context['priors'])} priors, {len(context['graphs'])} graphs.")

        # --- Stage 2: Reasoning Plan ---
        plan = self._draft_procedure(user_query, context)
        self.logger.info(f"Stage 2 Complete. Selected Procedure: {plan['procedure']['procedure_name']}")
        
        # --- Stage 3: Execution Binding ---
        execution_packet = self._bind_tools(plan)
        self.logger.info(f"Stage 3 Complete. Active Injectors: {len(execution_packet['injectors'])}. Tools Ready: {len(execution_packet['tools'])}")

        return {
            "query": user_query,
            "context": context,
            "plan": plan,
            "execution": execution_packet
        }

    def _retrieve_knowledge(self, query: str) -> Dict:
        """
        Stage 1: Retrieve Cognitive Priors and Domain Graphs.
        In production, this uses Vector Search. Here, we use keyword matching.
        """
        # Simple Keyword Match Simulation
        query_terms = set(query.lower().split())
        
        # Find Priors
        matching_priors = []
        for _, row in self.priors_df.iterrows():
            emb_text = str(row['embedding_text']).lower()
            if any(term in emb_text for term in query_terms):
                matching_priors.append(row.to_dict())
        
        # Find Graphs
        matching_graphs = []
        for _, row in self.domain_graphs_df.iterrows():
            emb_text = str(row['embedding_text']).lower()
            if any(term in emb_text for term in query_terms):
                matching_graphs.append(row.to_dict())

        return {"priors": matching_priors[:3], "graphs": matching_graphs[:1]}

    def _draft_procedure(self, query: str, context: Dict) -> Dict:
        """
        Stage 2: Select Procedure and Filter Anti-Patterns.
        """
        # 1. Select Procedure (Simple Heuristic for demo)
        selected_procedure = None
        best_score = 0
        
        for _, row in self.procedures_df.iterrows():
            score = 0
            emb_text = str(row['embedding_text']).lower()
            for term in query.lower().split():
                if term in emb_text:
                    score += 1
            if score > best_score:
                best_score = score
                selected_procedure = row.to_dict()
        
        if not selected_procedure:
            # Default to Basic Causal Analysis if no match
            selected_procedure = self.procedures_df[self.procedures_df['procedure_id'] == 'PROC001'].iloc[0].to_dict()

        # 2. Check Anti-Patterns (Logic Gate)
        active_anti_patterns = []
        for _, row in self.anti_patterns_df.iterrows():
            triggers = str(row['trigger_keywords']).split('|')
            if any(t.strip() in query.lower() for t in triggers):
                active_anti_patterns.append(row.to_dict())

        return {
            "procedure": selected_procedure,
            "anti_patterns": active_anti_patterns
        }

    def _bind_tools(self, plan: Dict) -> Dict:
        """
        Stage 3: Retrieve Injectors and Map Tools.
        """
        # 1. Get Injectors based on procedure context
        proc_context = plan['procedure'].get('trigger_context', '')
        active_injectors = []
        
        # Basic logic: If procedure is 'strict', load Strict Discipline injector
        if plan['procedure'].get('enforcement_level') == 'strict':
             strict_inj = self.injectors_df[self.injectors_df['ability_id'] == 'AB001']
             if not strict_inj.empty:
                 active_injectors.append(strict_inj.iloc[0].to_dict())

        # 2. Map Suggested Tools
        tool_ids = str(plan['procedure'].get('suggested_tool_ids', '')).split(',')
        ready_tools = []
        
        for tid in tool_ids:
            tid = tid.strip()
            tool_meta = self.tool_registry_df[self.tool_registry_df['tool_id'] == tid]
            if not tool_meta.empty:
                ready_tools.append(tool_meta.iloc[0].to_dict())

        return {
            "injectors": active_injectors,
            "tools": ready_tools
        }

    def execute_math_tool(self, tool_id: str, **kwargs):
        """
        Executes a deterministic tool from the registry.
        """
        tool_row = self.tool_registry_df[self.tool_registry_df['tool_id'] == tool_id]
        if tool_row.empty:
            raise ValueError(f"Tool ID {tool_id} not found in registry.")
            
        tool_info = tool_row.iloc[0]
        class_name = tool_info['class_name']
        method_name = tool_info['method_name']
        
        # Dynamic Dispatch
        if class_name == 'CausalMathTools':
            method = getattr(CausalMathTools, method_name)
        elif class_name == 'GraphTraversalTools':
            method = getattr(GraphTraversalTools, method_name)
        elif class_name == 'ValidationTools':
            method = getattr(ValidationTools, method_name)
        elif class_name == 'HypothesisRanking':
            method = getattr(HypothesisRanking, method_name)
        else:
            raise NotImplementedError(f"Class {class_name} not linked in controller.")
            
        return method(**kwargs)

# --- CLI Entry Point for Testing ---
if __name__ == "__main__":
    import argparse
    
    # Simple CLI to test the controller
    controller = CausalController(root_dir=str(Path(__file__).parent))
    
    test_query = "analyze the correlation between ad spend and revenue considering seasonality"
    print(f"\n--- TEST QUERY: '{test_query}' ---\n")
    
    result = controller.process_query(test_query)
    
    print(f"[KNOWLEDGE] Priors Found: {[p['prior_id'] for p in result['context']['priors']]}")
    print(f"[KNOWLEDGE] Graphs Found: {[g['graph_id'] for g in result['context']['graphs']]}")
    print(f"[PROCEDURE] Selected: {result['plan']['procedure']['procedure_name']} (ID: {result['plan']['procedure']['procedure_id']})")
    print(f"[LOGIC GATE] Anti-Patterns Triggered: {[ap['pattern_name'] for ap in result['plan']['anti_patterns']]}")
    print(f"[EXECUTION] Tools Bound: {[t['tool_name'] for t in result['execution']['tools']]}")

    # Example: Execute a bound tool (Simulated)
    if result['execution']['tools']:
        t = result['execution']['tools'][0]
        print(f"\n[DEMO] Ready to execute {t['method_name']} via {t['class_name']}.")
