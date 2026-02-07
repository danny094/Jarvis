
import os
import yaml
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from observability.events import EventLogger

class SkillInstaller:
    """
    Handles the physical installation of skills on the filesystem.
    This is the ONLY class allowed to write to SKILLS_DIR.
    """
    
    def __init__(self, skills_dir: str = "/skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        (self.skills_dir / "_drafts").mkdir(exist_ok=True)
        (self.skills_dir / "_registry").mkdir(exist_ok=True)

    def save_skill(self, name: str, code: str, manifest_data: Dict[str, Any], is_draft: bool) -> Dict[str, Any]:
        """
        Write skill files to disk.
        """
        # Security: sanitize name again just in case
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        if not safe_name.replace("_", "").isalnum():
             raise ValueError(f"Invalid skill name: {name}")

        target_dir = self.skills_dir / ("_drafts" if is_draft else safe_name) / safe_name
        
        # If active, it lives in root/name. If draft, lives in _drafts/name
        # Wait, the structure in SkillManager was:
        # Draft: _drafts/name
        # Active: name
        if is_draft:
            target_dir = self.skills_dir / "_drafts" / safe_name
        else:
            target_dir = self.skills_dir / safe_name

        if target_dir.exists():
            # TODO: Add versioning or overwrite policy?
            # For now, overwrite is allowed for development
            shutil.rmtree(target_dir)
        
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Write Manifest
        manifest = {
            "name": safe_name,
            "version": manifest_data.get("version", "1.0.0"),
            "description": manifest_data.get("description", ""),
            "triggers": manifest_data.get("triggers", []),
            "author": "ai", # Explicitly marked
            "created_at": datetime.now().isoformat(),
            "validation_score": manifest_data.get("validation_score", 0.0)
        }
        
        with open(target_dir / "manifest.yaml", "w") as f:
            yaml.dump(manifest, f, default_flow_style=False)
            
        # 2. Write Code
        with open(target_dir / "main.py", "w") as f:
            f.write(code)
            
            
        # 3. Update Registry (if active)
        if not is_draft:
            try:
                self._update_registry_file(safe_name, manifest)
                EventLogger.emit("skill_installed", {"name": safe_name}, status="success")
            except Exception as e:
                # ROLLBACK: Failed to update registry
                EventLogger.emit("rollback_triggered", {"name": safe_name, "reason": str(e)}, status="warning")
                shutil.rmtree(target_dir)
                raise e
            
        return {
            "success": True,
            "path": str(target_dir),
            "status": "draft" if is_draft else "active"
        }

    def _update_registry_file(self, name: str, manifest: Dict):
        """Update the installed.json registry file."""
        registry_path = self.skills_dir / "_registry" / "installed.json"
        
        registry = {}
        if registry_path.exists():
            try:
                with open(registry_path, "r") as f:
                    registry = yaml.safe_load(f) or {} # Using yaml loader for json is fine usually, but let's stick to json
                    # Wait, checking SkillManager... it used json.load
            except:
                pass
                
        # Re-read properly
        if registry_path.exists():
             import json
             with open(registry_path, "r") as f:
                 try:
                     registry = json.load(f)
                 except:
                     registry = {}

        registry[name] = {
            "version": manifest["version"],
            "installed_at": datetime.now().isoformat(),
            "description": manifest["description"],
            "triggers": manifest.get("triggers", [])
        }
        
        import json
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

    def uninstall_skill(self, name: str) -> Dict[str, Any]:
        """Remove a skill."""
        target_dir = self.skills_dir / name
        
        if not target_dir.exists():
             return {"success": False, "message": "Skill not found"}
            
        shutil.rmtree(target_dir)
        self._remove_from_registry(name)
        
        return {"success": True, "message": f"Skill {name} uninstalled"}

    def _remove_from_registry(self, name: str):
        registry_path = self.skills_dir / "_registry" / "installed.json"
        if not registry_path.exists():
            return
            
        import json
        with open(registry_path, 'r') as f:
            try:
                registry = json.load(f)
            except:
                return
        
        if name in registry:
            del registry[name]
            with open(registry_path, 'w') as f:
                json.dump(registry, f, indent=2)


    def list_skills(self) -> Dict[str, Any]:
        """List all skills (active and draft)."""
        skills = {
            "active": [],
            "drafts": []
        }
        
        # 1. List Active Skills
        if self.skills_dir.exists():
            for item in self.skills_dir.iterdir():
                if item.is_dir() and not item.name.startswith("_"):
                    skills["active"].append(item.name)
                    
        # 2. List Drafts
        drafts_dir = self.skills_dir / "_drafts"
        if drafts_dir.exists():
            for item in drafts_dir.iterdir():
                if item.is_dir():
                    skills["drafts"].append(item.name)
                    
        return skills
