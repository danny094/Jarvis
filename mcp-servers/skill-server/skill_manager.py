"""
TRION Skill Manager (Dumb Proxy Version)

Delegates all write operations to the hardened ToolExecutionLayer via HTTP.
Maintains read-only access for listing/execution.
"""

import os
import json
import shutil
import httpx
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

EXECUTOR_URL = os.getenv("EXECUTOR_URL", "http://tool-executor:8000")
MEMORY_URL = os.getenv("MEMORY_URL", "http://mcp-sql-memory:8081")

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class SkillManager:
    """
    Proxy Manager.
    - READs: Directly from mounted volume (ReadOnly)
    - WRITEs: Forwarded to ToolExecutionLayer
    """

    def __init__(self, skills_dir: str, registry_url: str):
        self.skills_dir = Path(skills_dir)
        self.registry_url = registry_url
        self.installed_file = self.skills_dir / "_registry" / "installed.json"

    def _load_installed(self) -> Dict[str, Dict]:
        """Load installed skills from registry file (Read Only)"""
        if self.installed_file.exists():
            try:
                with open(self.installed_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def list_installed(self) -> List[Dict[str, Any]]:
        """List all installed skills"""
        installed = self._load_installed()
        skills = []
        for name, info in installed.items():
            skill_path = self.skills_dir / name
            skills.append({
                "name": name,
                "version": info.get("version", "unknown"),
                "installed_at": info.get("installed_at"),
                "description": info.get("description", ""),
                "status": "installed" if skill_path.exists() else "broken"
            })
        return skills

    async def validate_code(self, code: str) -> Dict[str, Any]:
        """Proxy validation"""
        payload = {"code": code}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/validation/code", json=payload, timeout=10.0)
                return resp.json()
            except Exception as e:
                return {"error": str(e)}

    async def get_priors(self, context: str) -> Dict[str, Any]:
        """Proxy priors"""
        payload = {"context": context}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/context/priors", json=payload, timeout=10.0)
                return resp.json()
            except Exception as e:
                return {"error": str(e)}

    @staticmethod
    def _extract_skill_keywords(name: str, description: str = "", triggers: list = None) -> list:
        """
        Extrahiert Keywords aus Name + Description + Triggers.
        Kein LLM — rein regelbasiert (snake_case split + Stop-Word-Filter).
        Diese Keywords reichern das Embedding an → bessere semantische Suche.
        """
        import re
        _STOP = frozenset({
            "der", "die", "das", "ein", "eine", "und", "oder", "ist", "sind",
            "wird", "werden", "für", "von", "mit", "auf", "bei", "nach",
            "the", "a", "an", "is", "are", "for", "of", "with", "on", "in",
            "to", "and", "or", "it", "skill", "erstellt", "zeigt", "gibt",
            "macht", "holt", "liefert", "shows", "gets", "returns",
        })
        keywords = set()
        # snake_case + camelCase Split
        for part in re.split(r"[_\-\s]+", name.lower()):
            sub = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).lower()
            for w in sub.split():
                if len(w) >= 3 and w not in _STOP:
                    keywords.add(w)
        # Description
        if description:
            for w in re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", description.lower()):
                if w not in _STOP:
                    keywords.add(w)
        # Triggers
        for t in (triggers or []):
            for w in re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", t.lower()):
                if w not in _STOP:
                    keywords.add(w)
        return sorted(keywords)[:20]

    async def _register_skill_in_graph(
        self, name: str, description: str, triggers: list
    ) -> None:
        """
        Registriert einen neu erstellten Skill als Graph-Node in sql-memory.
        Ermöglicht semantische Skill-Discovery ohne hardcoded Keywords.
        conversation_id="_skills" — konsistent mit "_container_events".

        NEU: Keywords werden extrahiert und in Embedding-Content eingebettet,
        damit der SkillSemanticRouter (in core/) den Skill via cosine similarity findet.
        Non-blocking: Fehler werden nur geloggt, nie propagiert.
        """
        import time as _time
        import json as _json
        triggers_text = ", ".join(triggers) if triggers else ""

        # Keywords extrahieren (kein LLM!)
        keywords = self._extract_skill_keywords(name, description, triggers)
        keywords_text = " ".join(keywords) if keywords else ""

        # Angereicherter Content für besseres Embedding
        content = f"{name}: {description}"
        if triggers_text:
            content += f". Triggers: {triggers_text}"
        if keywords_text:
            content += f". Keywords: {keywords_text}"

        # Metadata enthält skill_name explizit → SkillRouter kann direkt lesen
        metadata = _json.dumps({
            "skill_name": name,
            "keywords": keywords,
        })

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{MEMORY_URL}/mcp",
                    headers=_MCP_HEADERS,
                    json={
                        "jsonrpc": "2.0",
                        "id": int(_time.time() * 1000),
                        "method": "tools/call",
                        "params": {
                            "name": "graph_add_node",
                            "arguments": {
                                "source_type": "skill",
                                "content": content,
                                "conversation_id": "_skills",
                                "confidence": 0.9,
                                "metadata": metadata,
                            },
                        },
                    },
                )
            print(f"[SkillManager] Graph-Node erstellt für Skill '{name}' (keywords: {keywords[:5]})")
        except Exception as e:
            print(f"[SkillManager] Graph-Registrierung fehlgeschlagen (non-critical): {e}")

    async def create_skill(self, name: str, skill_data: Dict[str, Any], draft: bool = True) -> Dict[str, Any]:
        """
        Proxy creation to Tool Executor.
        Nach Erfolg: Skill wird als Graph-Node registriert (semantische Discovery).
        """
        payload = {
            "name": name,
            "code": skill_data.get("code"),
            "description": skill_data.get("description"),
            "triggers": skill_data.get("triggers", []),
            "auto_promote": not draft,
            "gap_patterns": skill_data.get("gap_patterns", []),
            "gap_question": skill_data.get("gap_question"),
            "preferred_model": skill_data.get("preferred_model"),
            "default_params": skill_data.get("default_params", {}),
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/skills/create", json=payload, timeout=30.0)
                result = resp.json()

                # ── GRAPH HOOK: Bei Erfolg im Skill-Graph registrieren ──
                # Executor gibt {installation: {success: true}} zurück, kein Top-Level "success"
                _install_ok = (
                    result.get("success")
                    or result.get("installation", {}).get("success")
                )
                if _install_ok:
                    await self._register_skill_in_graph(
                        name=name,
                        description=skill_data.get("description", ""),
                        triggers=skill_data.get("triggers", []),
                    )

                return result
            except Exception as e:
                return {"success": False, "error": f"Executor unreachable: {e}"}


    async def install_skill(self, name: str) -> Dict[str, Any]:
        """
        Proxy installation to Tool Executor.
        
        Installs a skill from the external TRION registry.
        All write operations happen in the hardened tool-executor service.
        """
        payload = {
            "name": name,
            "registry_url": self.registry_url
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/skills/install", json=payload)
                return resp.json()
            except httpx.TimeoutException:
                return {"success": False, "error": "Installation timeout - skill may be large"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def uninstall_skill(self, name: str) -> Dict[str, Any]:
        """
        Proxy uninstall to Tool Executor.
        """
        payload = {"name": name}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/skills/uninstall", json=payload, timeout=10.0)
                return resp.json()
            except Exception as e:
                return {"success": False, "error": f"Executor unreachable: {e}"}

    # ... (Other read methods like list_available, run_skill remain similar but read-only)
    
    async def list_available(self) -> List[Dict[str, Any]]:
        """Fetch available skills (Read Only)"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.registry_url}/index.json")
                if response.status_code == 200:
                    return response.json().get("skills", [])
        except Exception:
            pass
        return [] # Fallback omitted for brevity, logic remains same

    async def run_skill(self, name: str, action: str = "run", args: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Proxy skill execution to Tool Executor (Sandboxed).
        
        All skill execution now happens in the hardened tool-executor service
        which provides:
        - Restricted builtins (no eval, exec, open, etc.)
        - Module whitelist
        - Execution timeout
        - Audit logging
        """
        args = args or {}
        
        payload = {
            "name": name,
            "action": action,
            "args": args
        }
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{EXECUTOR_URL}/v1/skills/run",
                    json=payload,
                    timeout=60.0  # Skills can take longer
                )
                return resp.json()
            except httpx.TimeoutException:
                return {"success": False, "error": "Skill execution timed out"}
            except Exception as e:
                return {"success": False, "error": f"Executor unreachable: {e}"}


    def get_skill_info(self, name: str) -> Dict[str, Any]:
        """Read skill info."""
        installed = self._load_installed()
        if name in installed:
            return installed[name]
        return {"error": "Not installed"}
    
    def list_drafts(self):
        # Read from _drafts
        drafts_dir = self.skills_dir / "_drafts"
        if not drafts_dir.exists(): return []
        results = []
        for d in drafts_dir.iterdir():
            if (d / "manifest.yaml").exists():
                 results.append({"name": d.name})
        return results

    def get_draft(self, name: str):
        """Read draft code + manifest (description, triggers)."""
        d = self.skills_dir / "_drafts" / name
        if not d.exists():
            return {"error": "Not found"}
        code = ""
        if (d / "main.py").exists():
            with open(d / "main.py") as f:
                code = f.read()
        # Lese description + triggers + neue Felder aus manifest.yaml
        description = ""
        triggers = []
        gap_patterns: list = []
        gap_question = None
        preferred_model = None
        default_params: dict = {}
        manifest_path = d / "manifest.yaml"
        if manifest_path.exists():
            try:
                import yaml
                with open(manifest_path) as f:
                    manifest = yaml.safe_load(f) or {}
                description = manifest.get("description", "")
                triggers = manifest.get("triggers", [])
                gap_patterns = manifest.get("gap_patterns", [])
                gap_question = manifest.get("gap_question")
                preferred_model = manifest.get("preferred_model")
                default_params = manifest.get("default_params", {})
            except Exception:
                pass
        return {
            "name": name,
            "code": code,
            "description": description,
            "triggers": triggers,
            "gap_patterns": gap_patterns,
            "gap_question": gap_question,
            "preferred_model": preferred_model,
            "default_params": default_params,
        }

    # Promote draft requires WRITE -> Proxy to executor? 
    # Or just create_skill with auto_promote=True using the draft code?
    # Executor doesn't have "promote" endpoint yet.
    # We can rely on create_skill overwriting.
    async def promote_draft(self, name: str):
        """Promote draft to active — liest description aus manifest.yaml."""
        draft = self.get_draft(name)
        if "error" in draft:
            return draft

        description = draft.get("description", "")
        # Contract erfordert minLength: 10
        if not description or len(description.strip()) < 10:
            description = f"Skill {name}: Automatisch erstellter Skill."

        payload = {
            "name": name,
            "code": draft["code"],
            "description": description,
            "triggers": draft.get("triggers", []),
            "auto_promote": True,
            "gap_patterns": draft.get("gap_patterns", []),
            "gap_question": draft.get("gap_question"),
            "preferred_model": draft.get("preferred_model"),
            "default_params": draft.get("default_params", {}),
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{EXECUTOR_URL}/v1/skills/create", json=payload, timeout=30.0
            )
            result = resp.json()

        # Graph-Hook: auch beim Promoten registrieren
        _install_ok = (
            result.get("success")
            or result.get("installation", {}).get("success")
        )
        if _install_ok:
            await self._register_skill_in_graph(
                name=name,
                description=description,
                triggers=draft.get("triggers", []),
            )
            # Draft-Ordner nach erfolgreichem Deploy löschen
            draft_path = self.skills_dir / "_drafts" / name
            if draft_path.exists():
                shutil.rmtree(draft_path)

        return result
