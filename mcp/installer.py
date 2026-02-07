"""
MCP Installation & Management Module
Handles Tier 1 (Simple Python) MCPs only
"""
from fastapi import APIRouter, UploadFile, HTTPException
from pathlib import Path
import shutil
import zipfile
import json
import subprocess
from typing import Dict, List
from .hub import get_hub

router = APIRouter()

CUSTOM_MCPS_DIR = Path("/app/custom_mcps")
MAX_SIZE = 50 * 1024 * 1024  # 50MB

class InstallationError(Exception):
    """Custom exception with rollback capability"""
    def __init__(self, message: str, target_dir: Path = None):
        self.message = message
        self.target_dir = target_dir
    
    def rollback(self):
        if self.target_dir and self.target_dir.exists():
            shutil.rmtree(self.target_dir)

@router.post("/install")
async def install_mcp(file: UploadFile):
    """
    Install a Tier 1 (Simple) MCP from ZIP upload.
    
    Phases:
    1. Upload & Extract
    2. Validate config.json
    3. Install requirements
    4. Hot Reload Registry
    5. Health Check
    """
    target_dir = None
    
    try:
        # PHASE 1: Upload & Size Check
        content = await file.read()
        if len(content) > MAX_SIZE:
            raise HTTPException(400, "File too large (max 50MB)")
        
        # PHASE 2: Extract
        temp_zip = Path("/tmp") / (file.filename or "mcp_upload.zip")
        temp_zip.write_bytes(content)
        
        # Extract to temp first
        temp_extract = Path("/tmp/mcp_extract")
        if temp_extract.exists():
            shutil.rmtree(temp_extract)
        
        with zipfile.ZipFile(temp_zip, 'r') as z:
            z.extractall(temp_extract)
        
        # PHASE 3: Validate
        config_file = temp_extract / "config.json"
        
        # Handle case where zip contains a single folder
        if not config_file.exists():
            # Check if there is exactly one subfolder
            subdirs = [d for d in temp_extract.iterdir() if d.is_dir()]
            if len(subdirs) == 1:
                temp_extract = subdirs[0]
                config_file = temp_extract / "config.json"
        
        if not config_file.exists():
            raise InstallationError("config.json not found in root or first subfolder")
        
        try:
            config = json.loads(config_file.read_text())
        except Exception:
             raise InstallationError("Invalid JSON in config.json")
        
        # Check tier
        if config.get("tier") != "simple":
            raise InstallationError("Only Tier 1 (simple) MCPs supported")
        
        # Validate required fields
        required = ["name", "url", "description"]
        if not all(k in config for k in required):
            raise InstallationError(f"Missing required fields: {required}")
        
        mcp_name = config["name"]
        target_dir = CUSTOM_MCPS_DIR / mcp_name
        
        # Check conflicts
        if target_dir.exists():
            # For now: fail. Later: option to override.
            raise HTTPException(409, f"MCP '{mcp_name}' already exists")
        
        # Create parent dir if not exists (should be handled by docker volume, but failsafe)
        CUSTOM_MCPS_DIR.mkdir(parents=True, exist_ok=True)
            
        # Move to final location
        shutil.move(str(temp_extract), str(target_dir))
        
        # PHASE 4: Install Dependencies
        requirements = target_dir / "requirements.txt"
        if requirements.exists():
            result = subprocess.run(
                ["uv", "pip", "install", "--system", "-r", str(requirements)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise InstallationError(
                    f"Dependency installation failed: {result.stderr}",
                    target_dir
                )
        
        # PHASE 5: Hot Reload
        hub = get_hub()
        hub.reload_registry()
        
        # PHASE 6: Health Check
        # TODO: Implement health check
        
        return {
            "success": True,
            "mcp": {
                "name": mcp_name,
                "description": config.get("description", ""),
                "url": config.get("url")
            }
        }
    
    except InstallationError as e:
        e.rollback()
        raise HTTPException(500, e.message)
    
    except HTTPException:
        # Re-raise HTTP exceptions (like 409)
        if target_dir and target_dir.exists() and "mcp_name" in locals():
             # Only cleanup if we just created it. 
             # But how do we know? Hard to say. 
             # Safe strategy: If HTTPException was raised after move, we might leave junk.
             # Ideally we check if we moved it.
             pass
        raise
        
    except Exception as e:
        if target_dir:
            shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(500, f"Installation failed: {str(e)}")

@router.get("/list")
async def list_mcps():
    """List all installed MCPs (Core + Custom) with online status"""
    hub = get_hub()
    return {"mcps": hub.list_mcps()}

@router.delete("/{name}")
async def delete_mcp(name: str):
    """Delete a custom MCP"""
    target = CUSTOM_MCPS_DIR / name
    
    if not target.exists():
        raise HTTPException(404, f"MCP '{name}' not found")
    
    # Don't allow deleting core MCPs
    from mcp_registry import CORE_MCPS
    if name in CORE_MCPS:
        raise HTTPException(403, "Cannot delete core MCPs")
    
    # Safely remove directory
    try:
        shutil.rmtree(target)
    except Exception as e:
         raise HTTPException(500, f"Deletion failed: {e}")
    
    # Hot Reload
    hub = get_hub()
    hub.reload_registry()
    
    return {"success": True, "deleted": name}

@router.post("/{name}/toggle")
async def toggle_mcp(name: str):
    """Enable/Disable an MCP"""
    from mcp_registry import get_mcps
    mcps = get_mcps()
    
    if name not in mcps:
        raise HTTPException(404, f"MCP '{name}' not found")
    
    # Toggle enabled state
    config_path = CUSTOM_MCPS_DIR / name / "config.json"
    
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            current_state = config.get("enabled", True)
            config["enabled"] = not current_state
            
            config_path.write_text(json.dumps(config, indent=2))
            
            # Hot Reload
            hub = get_hub()
            hub.reload_registry()
            
            return {"success": True, "enabled": config["enabled"]}
        except Exception as e:
            raise HTTPException(500, f"Toggle failed: {e}")
    
    raise HTTPException(500, "Cannot toggle core MCPs (config.json not found)")

@router.get("/{name}/details")
async def get_mcp_details(name: str):
    """Get detailed info about a specific MCP including its tools"""
    hub = get_hub()
    
    # Get all MCPs to find this one
    all_mcps = hub.list_mcps()
    mcp_info = None
    for mcp in all_mcps:
        if mcp["name"] == name:
            mcp_info = mcp
            break
    
    if not mcp_info:
        raise HTTPException(404, f"MCP {name} not found")
    
    # Get tools for this MCP
    tools = []
    for tool_name, mcp_name in hub._tools_cache.items():
        if mcp_name == name:
            tool_def = hub._tool_definitions.get(tool_name, {})
            tools.append({
                "name": tool_name,
                "description": tool_def.get("description", "No description"),
                "inputSchema": tool_def.get("inputSchema", {})
            })
    
    return {
        "mcp": mcp_info,
        "tools": tools
    }
