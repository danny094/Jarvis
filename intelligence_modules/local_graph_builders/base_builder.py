
import sys
import os
import csv
import json
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod

# Add the parent directory to sys.path to import from code_tools
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from code_tools.context_builder import ContextGraphBuilder, CausalNode, CausalEdge, EdgeType, UncertaintyLevel

class BaseGraphBuilder(ABC):
    """
    Abstract Base Class for Context Graph Builders.
    Handles common RAG retrieval and graph orchestration.
    """
    
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.knowledge_path = os.path.join(workspace_root, "knowledge_rag")
        self.procedural_path = os.path.join(workspace_root, "procedural_rag")
        self.engine = ContextGraphBuilder()

    def _read_csv(self, file_path: str) -> List[Dict]:
        """Utility to read CSV files manually to avoid pandas dependency."""
        data = []
        if not os.path.exists(file_path):
            return data
        with open(file_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return data

    def retrieve_priors(self, query: str, limit: int = 3) -> List[Dict]:
        """Simple keyword-based retrieval for cognitive priors."""
        priors = self._read_csv(os.path.join(self.knowledge_path, "cognitive_priors_v2.csv"))
        # Simplified scoring based on embedding_text keywords
        scored_priors = []
        query_words = set(query.lower().split())
        for p in priors:
            text = p.get('embedding_text', '').lower()
            score = sum(1 for word in query_words if word in text)
            if score > 0:
                scored_priors.append((score, p))
        
        scored_priors.sort(key=lambda x: x[0], reverse=True)
        return [p for score, p in scored_priors[:limit]]

    def retrieve_domain_graphs(self, query: str, limit: int = 1) -> List[Dict]:
        """Retrieve relevant pre-defined domain DAGs."""
        graphs = self._read_csv(os.path.join(self.knowledge_path, "domain_graphs.csv"))
        scored_graphs = []
        query_words = set(query.lower().split())
        for g in graphs:
            text = (g.get('domain', '') + " " + g.get('embedding_text', '')).lower()
            score = sum(1 for word in query_words if word in text)
            if score > 0:
                scored_graphs.append((score, g))
        
        scored_graphs.sort(key=lambda x: x[0], reverse=True)
        return [g for score, g in scored_graphs[:limit]]

    def retrieve_procedures(self, query: str, limit: int = 3) -> List[Dict]:
        """Retrieve relevant reasoning procedures."""
        procedures = self._read_csv(os.path.join(self.procedural_path, "causal_reasoning_procedures_v2.csv"))
        scored_procs = []
        query_words = set(query.lower().split())
        for p in procedures:
            text = (p.get('procedure_name', '') + " " + p.get('embedding_text', '')).lower()
            score = sum(1 for word in query_words if word in text)
            if score > 0:
                scored_procs.append((score, p))
        
        scored_procs.sort(key=lambda x: x[0], reverse=True)
        return [p for score, p in scored_procs[:limit]]

    def retrieve_anti_patterns(self, query: str) -> List[Dict]:
        """Retrieve relevant anti-patterns (logic gates)."""
        anti_patterns = self._read_csv(os.path.join(self.procedural_path, "anti_patterns.csv"))
        # Broad lookup - check if query context triggers any anti-pattern
        triggered = []
        query_words = set(query.lower().split())
        for ap in anti_patterns:
            # Check keywords or fallback text
            trigger_text = ap.get('trigger_keywords', '').lower()
            if any(word in trigger_text for word in query_words):
                triggered.append(ap)
        return triggered

    @abstractmethod
    def build_graph(self, query: str) -> Dict:
        """Main entry point to be implemented by specialized builders."""
        pass
