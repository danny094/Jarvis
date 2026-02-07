
import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import sys
import json
import jsonschema

# Add current directory to path to find local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mini_control_layer import get_mini_control, SkillRequest, ControlAction
from engine.skill_installer import SkillInstaller
from engine.skill_runner import get_skill_runner
from observability.events import EventLogger

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), "contracts")

def validate_contract(data: Dict, contract_name: str):
    schema_path = os.path.join(CONTRACTS_DIR, contract_name)
    if not os.path.exists(schema_path):
        print(f"Warning: Contract {contract_name} not found")
        return
        
    with open(schema_path, "r") as f:
        schema = json.load(f)
    
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Contract Violation: {e.message}")

app = FastAPI(
    title="TRION Tool Executor",
    description="Layer 4 Execution Runtime - Exclusive Side-Effects Provider",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === MODELS ===

class CreateSkillRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = ""
    triggers: List[str] = []
    auto_promote: bool = False

class RunSkillRequest(BaseModel):
    name: str
    action: str = "run"
    args: Dict[str, Any] = {}

class ValidateLineRequest(BaseModel):
    code: str

class UninstallSkillRequest(BaseModel):
    name: str

class InstallSkillRequest(BaseModel):
    name: str
    registry_url: str = None  # Optional override


class ContextRequest(BaseModel):
    context: str

# === ENDPOINTS ===

@app.get("/")
def health_check():
    return {"status": "active", "layer": 4, "role": "execution_runtime", "version": "1.1.0"}

@app.post("/v1/skills/create")
async def create_skill(request: CreateSkillRequest):
    """
    Handle skill creation via Mini-Control-Layer.
    This is the ONLY way to install a skill.
    """
    # 0. Validate Contract
    contract_payload = {
        "name": request.name,
        "script": request.code,
        "description": request.description,
        "triggers": request.triggers,
        "auto_promote": request.auto_promote
    }
    
    EventLogger.emit("create_skill_request", {"name": request.name}, status="received")
    
    try:
        validate_contract(contract_payload, "create_skill.json")
    except Exception as e:
        EventLogger.emit("contract_violation", {"error": str(e)}, status="error")
        raise e

    # 1. Prepare Request
    skill_req = SkillRequest(
        type="CREATE",
        name=request.name,
        code=request.code,
        description=request.description,
        triggers=request.triggers,
        auto_promote=request.auto_promote
    )
    
    # 2. Mini-Control Validation & Decision
    control = get_mini_control()
    decision = await control.process_request(skill_req)
    
    EventLogger.emit("validation_complete", {
        "name": request.name,
        "action": decision.action.value,
        "score": decision.validation_result.score if decision.validation_result else 0
    })
    
    # 3. IF APPROVE/WARN -> EXECUTE SIDE-EFFECTS
    if decision.action in [ControlAction.APPROVE, ControlAction.WARN]:
        is_draft = not request.auto_promote
        
        installer = SkillInstaller(skills_dir=os.getenv("SKILLS_DIR", "/skills"))
        
        manifest_data = {
            "description": request.description,
            "triggers": request.triggers,
            "validation_score": decision.validation_result.score if decision.validation_result else 0.0
        }
        
        install_result = installer.save_skill(
            name=request.name,
            code=request.code,
            manifest_data=manifest_data,
            is_draft=is_draft
        )
        
        return {
            **decision.to_dict(),
            "installation": install_result
        }
        
    return decision.to_dict()


@app.post("/v1/skills/run")
async def run_skill(request: RunSkillRequest):
    """
    Execute a skill in a sandboxed environment.
    
    Security Features:
    - Restricted builtins (no eval, exec, open, etc.)
    - Module whitelist
    - Execution timeout
    - Audit logging
    """
    EventLogger.emit("skill_run_request", {
        "name": request.name,
        "action": request.action
    }, status="received")
    
    runner = get_skill_runner()
    result = await runner.run(
        skill_name=request.name,
        action=request.action,
        args=request.args
    )
    
    if not result.success:
        EventLogger.emit("skill_run_failed", {
            "name": request.name,
            "error": result.error
        }, status="error")
    
    return result.to_dict()



@app.post("/v1/skills/install")
async def install_skill_from_registry(request: InstallSkillRequest):
    """
    Install a skill from the external TRION skill registry.
    Fetches skill definition from registry and installs it.
    """
    import httpx
    
    registry_url = request.registry_url or os.getenv("REGISTRY_URL", "http://localhost:8080")
    
    EventLogger.emit("skill_install_request", {
        "name": request.name,
        "registry": registry_url
    }, status="received")
    
    try:
        # 1. Fetch skill from registry
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{registry_url}/skills/{request.name}")
            if resp.status_code == 404:
                return {"success": False, "error": f"Skill '{request.name}' not found in registry"}
            if resp.status_code != 200:
                return {"success": False, "error": f"Registry error: {resp.status_code}"}
            
            skill_data = resp.json()
        
        # 2. Validate contract
        contract_payload = {
            "name": request.name,
            "script": skill_data.get("script", skill_data.get("code", "")),
            "description": skill_data.get("description", "Installed from registry"),
            "triggers": skill_data.get("triggers", [])
        }
        validate_contract(contract_payload, "create_skill.json")
        
        # 3. Install via SkillInstaller
        installer = SkillInstaller(skills_dir=os.getenv("SKILLS_DIR", "/skills"))
        install_result = installer.save_skill(
            name=request.name,
            code=contract_payload["script"],
            description=contract_payload["description"],
            triggers=contract_payload.get("triggers", []),
            metadata=skill_data.get("metadata", {})
        )
        
        EventLogger.emit("skill_installed_from_registry", {
            "name": request.name,
            "path": install_result.get("path")
        }, status="success")
        
        return {
            "success": True,
            "action": "installed",
            "installation": install_result
        }
        
    except ContractViolation as e:
        EventLogger.emit("skill_install_rejected", {"name": request.name, "reason": str(e)}, status="rejected")
        return {"success": False, "error": f"Contract violation: {str(e)}"}
    except Exception as e:
        EventLogger.emit("skill_install_failed", {"name": request.name, "error": str(e)}, status="error")
        return {"success": False, "error": str(e)}


@app.post("/v1/skills/uninstall")
async def uninstall_skill(request: UninstallSkillRequest):
    """
    Handle skill uninstallation.
    """
    installer = SkillInstaller(skills_dir=os.getenv("SKILLS_DIR", "/skills"))
    result = installer.uninstall_skill(request.name)
    return result

@app.post("/v1/validation/code")
async def validate_code(request: ValidateLineRequest):
    """
    Validate code without side effects.
    """
    control = get_mini_control()
    result = control.validate_code_quick(request.code)
    return result

@app.post("/v1/context/priors")
async def get_safety_priors(request: ContextRequest):
    """
    Get safety priors for a given context.
    """
    control = get_mini_control()
    priors = control.get_applicable_priors(request.context)
    return {"priors": priors}



@app.get("/v1/skills")
async def list_skills():
    """List all installed skills and drafts."""
    installer = SkillInstaller(skills_dir=os.getenv("SKILLS_DIR", "/skills"))
    return installer.list_skills()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
