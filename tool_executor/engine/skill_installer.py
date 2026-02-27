
import importlib.util
import os
import yaml
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from observability.events import EventLogger


def _load_registry_store():
    """
    Load skill_registry_store by absolute path so the import is robust
    even when sys.modules["engine"] has been mocked in tests.
    Result is cached under a private module name.
    """
    _name = "_skill_registry_store_impl"
    import sys
    if _name in sys.modules:
        return sys.modules[_name]
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_registry_store.py")
    spec = importlib.util.spec_from_file_location(_name, _path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[_name] = mod
    return mod

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
        (self.skills_dir / "_history").mkdir(exist_ok=True)

    def _resolve_overwrite_policy(self) -> str:
        """
        Returns overwrite policy for existing targets.
        Supported:
        - overwrite (default): delete existing target before write
        - archive: move existing target to _history/<skill>/<timestamp>
        - error: refuse overwrite with FileExistsError
        """
        policy = os.getenv("SKILL_OVERWRITE_POLICY", "overwrite").strip().lower()
        if policy in {"overwrite", "archive", "error"}:
            return policy
        return "overwrite"

    def _archive_existing_target(self, safe_name: str, source_dir: Path) -> Path:
        """Archive existing skill directory before replacing it."""
        ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        archive_root = self.skills_dir / "_history" / safe_name
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_dir = archive_root / ts
        shutil.move(str(source_dir), str(archive_dir))
        return archive_dir

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

        overwrite_policy = self._resolve_overwrite_policy()
        archived_to = None
        if target_dir.exists():
            if overwrite_policy == "error":
                raise FileExistsError(
                    f"Skill '{safe_name}' already exists at '{target_dir}' and SKILL_OVERWRITE_POLICY=error"
                )
            if overwrite_policy == "archive":
                archived_to = self._archive_existing_target(safe_name, target_dir)
                EventLogger.emit(
                    "skill_overwrite_archived",
                    {"name": safe_name, "archived_to": str(archived_to)},
                    status="success",
                )
            else:
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
            "validation_score": manifest_data.get("validation_score", 0.0),
            "gap_patterns": manifest_data.get("gap_patterns", []),
            "gap_question": manifest_data.get("gap_question") or None,
            "preferred_model": manifest_data.get("preferred_model") or None,
            "default_params": manifest_data.get("default_params", {}),
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
                # Remove draft after successful promotion
                draft_path = self.skills_dir / "_drafts" / safe_name
                if draft_path.exists():
                    shutil.rmtree(draft_path)
            except Exception as e:
                # ROLLBACK: Failed to update registry
                EventLogger.emit("rollback_triggered", {"name": safe_name, "reason": str(e)}, status="warning")
                shutil.rmtree(target_dir)
                raise e
            
        return {
            "success": True,
            "path": str(target_dir),
            "status": "draft" if is_draft else "active",
            "overwrite_policy": overwrite_policy,
            "archived_to": str(archived_to) if archived_to else None,
        }

    def _update_registry_file(self, name: str, manifest: Dict):
        """
        Update installed.json — atomic V2 write via skill_registry_store.
        Increments revision on each update, preserves installed_at across updates.
        Sets updated_at, channel, skill_key on every write.
        """
        store = _load_registry_store()
        import os as _os

        registry_path = self.skills_dir / "_registry" / "installed.json"
        skills = store.load_registry(registry_path)

        # Preserve installed_at and increment revision
        existing = skills.get(name, {})
        installed_at = existing.get("installed_at") or datetime.now().isoformat()
        old_revision = int(existing.get("revision") or 0)
        new_revision = old_revision + 1
        now = datetime.now().isoformat()

        mode = _os.getenv("SKILL_KEY_MODE", "name").lower()
        skill_key = store.make_skill_key(name, channel="active", mode=mode)

        skills[name] = {
            "skill_key": skill_key,
            "name": name,
            "channel": "active",
            "version": manifest["version"],
            "installed_at": installed_at,
            "updated_at": now,
            "revision": new_revision,
            "description": manifest["description"],
            "triggers": manifest.get("triggers", []),
            "gap_patterns": manifest.get("gap_patterns", []),
            "gap_question": manifest.get("gap_question"),
            "preferred_model": manifest.get("preferred_model"),
            "default_params": manifest.get("default_params", {}),
        }

        # Atomic V2 write — never leaves a partial file on disk
        store.save_registry_atomic(registry_path, skills, mode=mode)

    def uninstall_skill(self, name: str) -> Dict[str, Any]:
        """Remove a skill."""
        target_dir = self.skills_dir / name
        
        if not target_dir.exists():
             return {"success": False, "message": "Skill not found"}
            
        shutil.rmtree(target_dir)
        self._remove_from_registry(name)
        
        return {"success": True, "message": f"Skill {name} uninstalled"}

    def _remove_from_registry(self, name: str):
        """Remove skill from installed.json — atomic V2 write via skill_registry_store."""
        store = _load_registry_store()
        load_registry = store.load_registry
        save_registry_atomic = store.save_registry_atomic

        registry_path = self.skills_dir / "_registry" / "installed.json"
        if not registry_path.exists():
            return

        skills = load_registry(registry_path)
        if name not in skills:
            return

        del skills[name]
        save_registry_atomic(registry_path, skills)


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
