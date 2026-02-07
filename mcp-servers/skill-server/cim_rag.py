import csv
import os
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# CSV files tracked for mtime-based cache invalidation
_TRACKED_FILES = [
    "intent_category_map.csv",
    "skill_templates.csv",
    "security_policies.csv",
    "meta_prompts.csv",
]


class CIMKnowledgeBase:
    """
    Handles loading and querying of CIM RAG datasets (CSVs).
    Provides access to intents, templates, policies, and personas.

    Uses mtime-based caching: reloads only when CSV files change.
    """

    def __init__(self, base_path: str = "/app/cim_data"):
        self.base_path = base_path
        self._intent_map: List[Dict] = []
        self._templates: Dict[str, Dict] = {}
        self._policies: List[Dict] = []
        self._personas: Dict[str, str] = {}
        self._initialized = False
        self._file_mtimes: Dict[str, float] = {}

    def load(self):
        """Loads CSV data into memory. Reloads only if files changed."""
        if self._initialized and not self._files_changed():
            return

        try:
            self._load_intents()
            self._load_templates()
            self._load_policies()
            self._load_personas()
            self._snapshot_mtimes()
            self._initialized = True
            logger.info("CIMKnowledgeBase loaded/reloaded successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize CIMKnowledgeBase: {e}")
            raise

    def _files_changed(self) -> bool:
        """Check if any tracked CSV file has been modified since last load."""
        for filename in _TRACKED_FILES:
            path = os.path.join(self.base_path, filename)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if self._file_mtimes.get(filename) != mtime:
                logger.info(f"CIM file changed: {filename}")
                return True
        return False

    def _snapshot_mtimes(self):
        """Record current mtimes for all tracked files."""
        self._file_mtimes.clear()
        for filename in _TRACKED_FILES:
            path = os.path.join(self.base_path, filename)
            try:
                self._file_mtimes[filename] = os.path.getmtime(path)
            except OSError:
                pass

    def _read_csv(self, filename: str) -> List[Dict]:
        path = os.path.join(self.base_path, filename)
        if not os.path.exists(path):
            logger.warning(f"CIM file not found: {path}")
            return []

        with open(path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return [row for row in reader]

    def _load_intents(self):
        self._intent_map = self._read_csv("intent_category_map.csv")

    def _load_templates(self):
        self._templates.clear()
        rows = self._read_csv("skill_templates.csv")
        for row in rows:
            template_id = row.get("template_id")
            if template_id:
                self._templates[template_id] = row

    def _load_policies(self):
        self._policies = self._read_csv("security_policies.csv")

    def _load_personas(self):
        self._personas.clear()
        rows = self._read_csv("meta_prompts.csv")
        for row in rows:
            role = row.get("agent_role")
            prompt = row.get("system_prompt")
            if role and prompt:
                self._personas[role] = prompt

    def get_policies(self) -> List[Dict]:
        return self._policies

    def get_template_by_intent(self, intent_text: str) -> Optional[Dict]:
        """
        Simple keyword matching for now.
        In a real RAG, this would differ to embedding search.
        """
        import re
        intent_text = intent_text.lower()

        # 1. Direct Regex Match from intent map
        for row in self._intent_map:
            pattern = row.get("intent_pattern", "")
            if pattern and re.search(pattern, intent_text, re.IGNORECASE):
                tmpl_ref = row.get("template_ref")
                return self._templates.get(tmpl_ref)

        # Fallback: Keyword search in templates
        for tmpl in self._templates.values():
            keywords = tmpl.get("intent_keywords", "").split("|")
            for kw in keywords:
                if kw and kw in intent_text:
                    return tmpl

        return None

    def get_persona(self, role: str) -> str:
        return self._personas.get(role, "You are a helpful AI assistant.")

# Global instance
cim_kb = CIMKnowledgeBase()
