"""
TRION Skill Manager (Dumb Proxy Version)

Delegates all write operations to the hardened ToolExecutionLayer via HTTP.
Maintains read-only access for listing/execution.
"""

import os
import json
import httpx
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

EXECUTOR_URL = os.getenv("EXECUTOR_URL", "http://tool-executor:8000")

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

    async def create_skill(self, name: str, skill_data: Dict[str, Any], draft: bool = True) -> Dict[str, Any]:
        """
        Proxy creation to Tool Executor.
        """
        payload = {
            "name": name,
            "code": skill_data.get("code"),
            "description": skill_data.get("description"),
            "triggers": skill_data.get("triggers", []),
            "auto_promote": not draft
        }
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{EXECUTOR_URL}/v1/skills/create", json=payload, timeout=30.0)
                return resp.json()
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
        # Read draft
        d = self.skills_dir / "_drafts" / name
        if not d.exists(): return {"error": "Not found"}
        code = ""
        if (d / "main.py").exists():
            with open(d / "main.py") as f: code = f.read()
        return {"name": name, "code": code}

    # Promote draft requires WRITE -> Proxy to executor? 
    # Or just create_skill with auto_promote=True using the draft code?
    # Executor doesn't have "promote" endpoint yet.
    # We can rely on create_skill overwriting.
    async def promote_draft(self, name: str):
         # Read draft
         draft = self.get_draft(name)
         if "error" in draft: return draft
         
         # Call create with auto_promote
         payload = {
             "name": name,
             "code": draft["code"],
             "auto_promote": True
         }
         async with httpx.AsyncClient() as client:
            resp = await client.post(f"{EXECUTOR_URL}/v1/skills/create", json=payload)
            return resp.json()
