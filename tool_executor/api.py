
import os
import subprocess
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

class ContractViolation(Exception):
    """Raised when an incoming payload violates a JSON-Schema contract."""


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
        raise ContractViolation(e.message)

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
    gap_patterns: List[str] = []
    gap_question: Optional[str] = None
    preferred_model: Optional[str] = None
    default_params: Dict[str, Any] = {}
    # C4.5 Single Control Authority: pre-validated decision from skill-server.
    # Required when SKILL_CONTROL_AUTHORITY=skill_server; ignored in legacy_dual mode.
    # Fields: action (approve|warn|block), passed, reason, warnings,
    #         validation_score, source ("skill_server"), policy_version.
    control_decision: Optional[Dict[str, Any]] = None

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

class InstallPackageRequest(BaseModel):
    package: str

# Packages that are safe for skill use and can be installed via UI
PACKAGE_ALLOWLIST = {
    # Data & science
    "numpy", "pandas", "scipy", "matplotlib",
    # HTTP & APIs
    "httpx", "aiohttp", "beautifulsoup4", "lxml",
    # Utilities
    "python-dateutil", "pytz", "arrow",
    "pillow", "qrcode",
    # Monitoring
    "psutil", "gputil",
    # Text & NLP
    "nltk", "fuzzywuzzy", "python-levenshtein",
    # Data formats
    "toml", "xmltodict", "python-dotenv",
}


# PEP668-safe package installation target for runtime-extensible skills.
# We install into a dedicated venv and expose it to the skill runner.
EXECUTOR_PYTHON_VENV = os.getenv("EXECUTOR_PYTHON_VENV", "/tmp/trion-tool-executor-venv")


def _venv_python_path() -> str:
    return os.path.join(EXECUTOR_PYTHON_VENV, "bin", "python")


def _pip_list_with_python(python_bin: str) -> List[Dict[str, str]]:
    """Return pip list output for a specific interpreter; fail-closed to []."""
    if not python_bin or not os.path.exists(python_bin):
        return []
    result = subprocess.run(
        [python_bin, "-m", "pip", "list", "--format=json"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return []
    try:
        raw = json.loads(result.stdout)
    except Exception:
        return []
    out: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        version = str(item.get("version", "")).strip()
        if not name:
            continue
        out.append({"name": name, "version": version})
    return out


def _merge_packages(*package_lists: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Merge package records by case-insensitive name.
    First-seen casing/version wins for stable UI output.
    """
    merged: Dict[str, Dict[str, str]] = {}
    for package_list in package_lists:
        for pkg in package_list:
            name = str(pkg.get("name", "")).strip()
            version = str(pkg.get("version", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key not in merged:
                merged[key] = {"name": name, "version": version}
    return sorted(merged.values(), key=lambda p: p["name"].lower())


def _list_effective_packages() -> List[Dict[str, str]]:
    """
    List packages available to executor skills:
    - system interpreter (base image)
    - dedicated executor venv (if already created)
    """
    system_packages = _pip_list_with_python(sys.executable)
    venv_packages = _pip_list_with_python(_venv_python_path())
    return _merge_packages(system_packages, venv_packages)


def _ensure_executor_venv() -> tuple[bool, str]:
    """Create executor package venv on demand (PEP668-safe)."""
    python_bin = _venv_python_path()
    if os.path.exists(python_bin):
        return True, ""

    os.makedirs(EXECUTOR_PYTHON_VENV, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "venv", EXECUTOR_PYTHON_VENV],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return False, result.stderr or result.stdout or "Failed to create executor venv"
    return True, ""


def _install_package_in_executor_venv(package_name: str) -> tuple[bool, str]:
    """Install package into dedicated venv using interpreter-bound pip."""
    python_bin = _venv_python_path()
    if not os.path.exists(python_bin):
        return False, "Executor venv missing"

    result = subprocess.run(
        [python_bin, "-m", "pip", "install", package_name, "--quiet", "--disable-pip-version-check"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        return False, result.stderr or result.stdout or "Installation failed"
    return True, result.stdout or "Installed successfully"


# === ENDPOINTS ===

@app.get("/")
def health_check():
    return {"status": "active", "layer": 4, "role": "execution_runtime", "version": "1.1.0"}

@app.post("/v1/skills/create")
async def create_skill(request: CreateSkillRequest):
    """
    Handle skill creation.

    C4.5 Single Control Authority:
    - SKILL_CONTROL_AUTHORITY=skill_server (default): skill-server is the sole
      decision authority. A valid control_decision must be forwarded with the
      request. Executor never calls its local Mini-Control for CREATE decisions.
    - SKILL_CONTROL_AUTHORITY=legacy_dual: executor also runs its own
      Mini-Control validation (old behaviour — rollback only).
    """
    authority = os.getenv("SKILL_CONTROL_AUTHORITY", "skill_server").lower()

    # 0. Validate Contract
    contract_payload = {
        "name": request.name,
        "script": request.code,
        "description": request.description,
        "triggers": request.triggers,
        "auto_promote": request.auto_promote,
    }

    EventLogger.emit(
        "create_skill_request",
        {"name": request.name, "authority": authority},
        status="received",
    )

    try:
        validate_contract(contract_payload, "create_skill.json")
    except ContractViolation as e:
        EventLogger.emit("contract_violation", {"error": str(e)}, status="error")
        raise HTTPException(status_code=400, detail=f"Contract Violation: {str(e)}")

    # ── skill_server authority mode (default) ─────────────────────────────
    if authority == "skill_server":
        cd = request.control_decision

        # Fail-closed: decision must be present
        if not cd:
            EventLogger.emit(
                "missing_authority_decision",
                {"name": request.name},
                status="error",
            )
            return {
                "success": False,
                "error": "Missing authority decision from skill-server",
                "error_type": "missing_authority_decision",
            }

        action = cd.get("action", "")
        if action not in ("approve", "warn"):
            EventLogger.emit(
                "rejected_by_authority",
                {"name": request.name, "action": action},
                status="rejected",
            )
            return {
                "success": False,
                "error": f"Request rejected by skill-server authority: {cd.get('reason', action)}",
                "error_type": "rejected_by_authority",
                "control_decision": cd,
            }

        # Strict: passed must be True — guards against forwarded BLOCK decisions
        if cd.get("passed") is not True:
            EventLogger.emit(
                "rejected_by_authority",
                {"name": request.name, "reason": "passed_not_true"},
                status="rejected",
            )
            return {
                "success": False,
                "error": "control_decision.passed must be True",
                "error_type": "rejected_by_authority",
                "control_decision": cd,
            }

        # Strict: source must be "skill_server" — rejects decisions from unknown origins
        if cd.get("source") != "skill_server":
            EventLogger.emit(
                "rejected_by_authority",
                {"name": request.name, "source": cd.get("source")},
                status="rejected",
            )
            return {
                "success": False,
                "error": f"control_decision.source must be 'skill_server', got '{cd.get('source')}'",
                "error_type": "rejected_by_authority",
                "control_decision": cd,
            }

        # Install — pure side-effect, no local CIM call
        is_draft = not request.auto_promote
        installer = SkillInstaller(skills_dir=os.getenv("SKILLS_DIR", "/skills"))
        manifest_data = {
            "description": request.description,
            "triggers": request.triggers,
            "validation_score": cd.get("validation_score", 0.0),
            "gap_patterns": request.gap_patterns,
            "gap_question": request.gap_question,
            "preferred_model": request.preferred_model,
            "default_params": request.default_params,
        }
        install_result = installer.save_skill(
            name=request.name,
            code=request.code,
            manifest_data=manifest_data,
            is_draft=is_draft,
        )
        EventLogger.emit(
            "validation_complete",
            {"name": request.name, "action": action, "score": cd.get("validation_score", 0.0)},
        )
        return {
            "action": action,
            "passed": True,
            "reason": cd.get("reason", ""),
            "warnings": cd.get("warnings", []),
            "installation": install_result,
        }

    # ── legacy_dual mode (rollback) ───────────────────────────────────────
    # 1. Prepare Request
    skill_req = SkillRequest(
        type="CREATE",
        name=request.name,
        code=request.code,
        description=request.description,
        triggers=request.triggers,
        auto_promote=request.auto_promote,
    )

    # 2. Mini-Control Validation & Decision (executor-local, legacy only)
    control = get_mini_control()
    decision = await control.process_request(skill_req)

    EventLogger.emit(
        "validation_complete",
        {
            "name": request.name,
            "action": decision.action.value,
            "score": decision.validation_result.score if decision.validation_result else 0,
        },
    )

    # 3. IF APPROVE/WARN -> EXECUTE SIDE-EFFECTS
    if decision.action in [ControlAction.APPROVE, ControlAction.WARN]:
        is_draft = not request.auto_promote
        installer = SkillInstaller(skills_dir=os.getenv("SKILLS_DIR", "/skills"))
        manifest_data = {
            "description": request.description,
            "triggers": request.triggers,
            "validation_score": decision.validation_result.score if decision.validation_result else 0.0,
            "gap_patterns": request.gap_patterns,
            "gap_question": request.gap_question,
            "preferred_model": request.preferred_model,
            "default_params": request.default_params,
        }
        install_result = installer.save_skill(
            name=request.name,
            code=request.code,
            manifest_data=manifest_data,
            is_draft=is_draft,
        )
        return {
            **decision.to_dict(),
            "installation": install_result,
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

    Rollback: set ENABLE_SKILL_REGISTRY_INSTALL=false to disable.
    """
    import httpx

    # C – Rollback flag
    if os.getenv("ENABLE_SKILL_REGISTRY_INSTALL", "true").lower() != "true":
        return {
            "success": False,
            "error": "Registry install disabled by flag",
            "error_type": "disabled_by_flag",
        }

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
        code = skill_data.get("script", skill_data.get("code", ""))
        contract_payload = {
            "name": request.name,
            "script": code,
            "description": skill_data.get("description", "Installed from registry"),
            "triggers": skill_data.get("triggers", []),
        }
        validate_contract(contract_payload, "create_skill.json")

        # 3. Install via SkillInstaller — correct signature (A)
        installer = SkillInstaller(skills_dir=os.getenv("SKILLS_DIR", "/skills"))
        manifest_data = {
            "description": contract_payload["description"],
            "triggers": contract_payload["triggers"],
            "gap_patterns": skill_data.get("gap_patterns", []),
            "gap_question": skill_data.get("gap_question"),
            "preferred_model": skill_data.get("preferred_model"),
            "default_params": skill_data.get("default_params", {}),
        }
        install_result = installer.save_skill(
            name=request.name,
            code=code,
            manifest_data=manifest_data,
            is_draft=False,
        )

        EventLogger.emit("skill_installed_from_registry", {
            "name": request.name,
            "path": install_result.get("path")
        }, status="success")

        return {
            "success": True,
            "action": "installed",
            "installation": install_result,
        }

    except ContractViolation as e:
        # B – structured, no 500
        EventLogger.emit("skill_install_rejected", {"name": request.name, "reason": str(e)}, status="rejected")
        return {
            "success": False,
            "error": f"Contract violation: {str(e)}",
            "error_type": "contract_violation",
        }
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


@app.get("/v1/packages")
async def list_packages():
    """List all installed Python packages in the executor environment."""
    packages = _list_effective_packages()
    return {
        "packages": packages,
        "allowlist": sorted(PACKAGE_ALLOWLIST),
    }


@app.get("/v1/packages/installed")
async def list_installed_packages_compat():
    """
    Compat endpoint for Mini-Control package availability check.

    Returns package names as a flat string list so Mini-Control can parse
    them without knowing the richer UI shape of /v1/packages.
    Shape: {"packages": ["pkg1", "pkg2", ...]}

    /v1/packages (UI endpoint) is NOT changed — it still returns the full
    {packages: [{name, version}, ...], allowlist: [...]} shape.
    """
    packages = _list_effective_packages()
    return {"packages": [p["name"].lower() for p in packages if isinstance(p, dict) and p.get("name")]}


@app.post("/v1/packages/install")
async def install_package(request: InstallPackageRequest):
    """
    Install a Python package into the executor environment.
    Only packages from PACKAGE_ALLOWLIST are permitted.
    This endpoint must only be triggered by explicit human UI action.
    """
    pkg = request.package.strip().lower()

    if pkg not in PACKAGE_ALLOWLIST:
        EventLogger.emit("package_install_rejected", {"package": pkg}, status="rejected")
        return {
            "success": False,
            "error": f"Package '{pkg}' is not in the allowed list. Contact admin to add it.",
            "allowlist": sorted(PACKAGE_ALLOWLIST),
        }

    EventLogger.emit("package_install_start", {"package": pkg}, status="received")

    venv_ready, venv_error = _ensure_executor_venv()
    if not venv_ready:
        EventLogger.emit("package_install_failed", {"package": pkg, "error": venv_error}, status="error")
        return {"success": False, "error": venv_error}

    install_ok, output = _install_package_in_executor_venv(pkg)
    if not install_ok:
        EventLogger.emit("package_install_failed", {"package": pkg, "error": output}, status="error")
        return {"success": False, "error": output}

    EventLogger.emit("package_installed", {"package": pkg}, status="success")
    return {"success": True, "package": pkg, "output": output}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
