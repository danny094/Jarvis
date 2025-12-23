# main.py
"""
Container Manager MCP Server v3.3

Verwaltet Sandbox-Container für sichere Code-Ausführung.
Nur Container aus der Registry sind erlaubt!

Features:
- Sichere Container-Isolation
- Persistente Sessions mit TTL
- Auto-Cleanup nach Inaktivität
- ttyd Integration für Live-Terminal

Modulare Architektur:
- config.py: Zentrale Konfiguration
- models.py: Pydantic Models
- containers/: Registry, Tracking, Lifecycle, Executor
- security/: Validation, Limits, Sandbox
- utils/: Docker Client, ttyd
"""

import os
import sys

# ============================================================
# PATH SETUP (WICHTIG für Docker!)
# ============================================================
_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# ============================================================
# ZENTRALE IMPORTS
# ============================================================

# Konfiguration
from config import (
    CLEANUP_INTERVAL,
    DEFAULT_SESSION_TTL,
    log_info,
    log_error,
)

# Pydantic Models
from models import (
    ContainerStartRequest,
    ContainerExecRequest,
    ContainerStopRequest,
    SessionExtendRequest,
    UserSandboxStartRequest,
    UserSandboxStopRequest,
)

# Container Management - DIREKTE SUBMODUL IMPORTS (umgeht __init__.py Problem!)
from containers.registry import (
    load_registry,
    is_container_allowed,
    list_containers,
)
from containers.tracking import (
    tracker,
    track_container,
    untrack_container,
    update_container_activity,
    is_container_tracked,
    get_user_sandbox,
    set_user_sandbox,
)
from containers.lifecycle import get_lifecycle
from containers.executor import CodeExecutor, ResourceLimits

# Utils
from utils.docker_client import get_docker_client, is_docker_available


# ============================================================
# LIFESPAN & BACKGROUND TASKS
# ============================================================

cleanup_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & Shutdown lifecycle."""
    global cleanup_task
    
    cleanup_task = asyncio.create_task(session_cleanup_loop())
    log_info("Session cleanup task started")
    
    yield
    
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
    
    log_info("Shutting down, cleaning up containers...")
    get_lifecycle().cleanup_all()


async def session_cleanup_loop():
    """Background task: Räumt abgelaufene Sessions auf."""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)
            count = get_lifecycle().cleanup_expired()
            if count > 0:
                log_info(f"Cleaned up {count} expired sessions")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log_error(f"Cleanup error: {e}")


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Container Manager",
    description="MCP Server für Sandbox-Container mit Session-Support",
    version="3.3.0",
    lifespan=lifespan,
)


# ============================================================
# HEALTH & INFO ENDPOINTS
# ============================================================

@app.get("/health")
async def health():
    """Health Check."""
    return {
        "status": "ok",
        "service": "container-manager",
        "version": "3.3.0",
        "docker": "connected" if is_docker_available() else "unavailable",
    }


@app.get("/mcp")
async def mcp_info():
    """MCP Server Info."""
    return {
        "name": "container-manager",
        "version": "3.3.0",
        "tools": [
            "container_list",
            "container_start",
            "container_exec",
            "container_stop",
            "container_status",
            "sandbox_execute",
            "user_sandbox_start",
            "user_sandbox_stop",
        ],
    }


# ============================================================
# CONTAINER ENDPOINTS
# ============================================================

@app.get("/containers")
async def container_list_endpoint():
    """Listet alle verfügbaren Container aus der Registry."""
    containers = list_containers()
    return {"containers": containers, "count": len(containers)}


@app.post("/containers/start")
def container_start(request: ContainerStartRequest):
    """Startet einen Container aus der Registry."""
    if not is_container_allowed(request.container_name):
        raise HTTPException(
            status_code=403,
            detail=f"Container '{request.container_name}' ist nicht in der Registry erlaubt!",
        )
    
    result = get_lifecycle().start(
        container_name=request.container_name,
        code=request.code,
        language=request.language or "python",
        keep_alive=request.keep_alive,
        enable_ttyd=request.enable_ttyd,
        ttl_seconds=request.ttl_seconds or DEFAULT_SESSION_TTL,
    )
    
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))
    
    return result


@app.post("/containers/exec")
def container_exec(request: ContainerExecRequest):
    """Führt Befehl in laufendem Container aus."""
    if not is_container_tracked(request.container_id):
        raise HTTPException(
            status_code=404,
            detail=f"Container '{request.container_id}' nicht gefunden",
        )
    
    update_container_activity(request.container_id)
    
    docker_client = get_docker_client()
    if not docker_client:
        raise HTTPException(status_code=503, detail="Docker nicht verfügbar")
    
    try:
        container = docker_client.containers.get(request.container_id)
        
        session = tracker.get(request.container_id)
        config = session.config if session else {}
        limits = ResourceLimits.from_config(config)
        
        executor = CodeExecutor(container, limits, validate=True)
        result = executor.run_command(request.command)
        
        return {
            "container_id": request.container_id,
            "command": request.command,
            **result.to_dict(),
        }
        
    except Exception as e:
        if "NotFound" in str(type(e)):
            untrack_container(request.container_id)
            raise HTTPException(status_code=404, detail="Container nicht mehr vorhanden")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/containers/stop")
def container_stop(request: ContainerStopRequest):
    """Stoppt und entfernt einen Container."""
    return get_lifecycle().stop(request.container_id)


@app.get("/containers/status")
def container_status():
    """Zeigt Status aller aktiven Container."""
    docker_client = get_docker_client()
    if not docker_client:
        return {"active_containers": [], "count": 0, "error": "Docker not available"}
    
    result = []
    tracked = tracker.get_all()
    
    for container_id, info in tracked.items():
        try:
            container = docker_client.containers.get(container_id)
            result.append({
                "container_id": container_id,
                "name": info.name,
                "status": container.status,
                "started_at": info.started_at,
                "persistent": info.persistent,
                "remaining_seconds": info.remaining_seconds,
            })
        except Exception:
            tracker.untrack(container_id)
    
    return {"active_containers": result, "count": len(result)}


@app.post("/containers/cleanup")
def container_cleanup():
    """Stoppt alle aktiven Container."""
    return get_lifecycle().cleanup_all()


# ============================================================
# SESSION ENDPOINTS
# ============================================================

@app.get("/sessions")
def list_sessions():
    """Listet alle aktiven Sessions."""
    sessions = []
    
    for container in tracker.get_persistent_sessions():
        sessions.append({
            "session_id": container.session_id,
            "container_id": container.container_id,
            "name": container.name,
            "started_at": container.started_at,
            "last_activity": container.last_activity,
            "ttl_seconds": container.ttl_seconds,
            "remaining_seconds": container.remaining_seconds,
            "ttyd_enabled": container.ttyd_enabled,
        })
    
    return {"sessions": sessions, "count": len(sessions)}


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    """Holt Session-Details."""
    container = tracker.get_by_session(session_id)
    
    if not container:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    return container.to_dict()


@app.post("/sessions/{session_id}/extend")
def extend_session(session_id: str, request: SessionExtendRequest):
    """Verlängert TTL einer Session."""
    new_ttl = tracker.extend_session(session_id, request.extend_seconds)
    
    if new_ttl is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    return {
        "session_id": session_id,
        "extended_by": request.extend_seconds,
        "new_ttl": new_ttl,
    }


@app.delete("/sessions/{session_id}")
def close_session(session_id: str):
    """Schließt eine Session manuell."""
    container = tracker.get_by_session(session_id)
    
    if not container:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    result = get_lifecycle().stop(container.container_id)
    return {"session_id": session_id, **result}


# ============================================================
# USER-SANDBOX ENDPOINTS
# ============================================================

@app.post("/sandbox/user/start")
def user_sandbox_start(request: UserSandboxStartRequest):
    """Startet die User-Sandbox."""
    existing = get_user_sandbox()
    if existing:
        return JSONResponse(
            status_code=409,
            content={
                "error": "User-Sandbox läuft bereits",
                "session_id": existing.get("session_id"),
                "ttyd_url": existing.get("ttyd_url"),
            },
        )
    
    if not is_container_allowed(request.container_name):
        raise HTTPException(status_code=403, detail="Container nicht erlaubt")
    
    result = get_lifecycle().start(
        container_name=request.container_name,
        keep_alive=True,
        enable_ttyd=True,
        ttl_seconds=None,
    )
    
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))
    
    sandbox_info = {
        "session_id": result.get("session_id"),
        "container_id": result.get("container_id"),
        "container_name": request.container_name,
        "ttyd_port": result.get("ttyd_url", "").split(":")[-1] if result.get("ttyd_url") else None,
        "ttyd_url": result.get("ttyd_url"),
        "started_at": datetime.now().isoformat(),
        "owner": "user",
        "preferred_model": request.preferred_model,
    }
    set_user_sandbox(sandbox_info)
    
    tracked = tracker.get(result.get("container_id"))
    if tracked:
        tracked.owner = "user"
        tracked.ttl_seconds = None
    
    return {
        "status": "started",
        **sandbox_info,
        "message": "User-Sandbox gestartet. Du hast volle Kontrolle!",
    }


@app.post("/sandbox/user/stop")
def user_sandbox_stop(request: UserSandboxStopRequest = UserSandboxStopRequest()):
    """Stoppt die User-Sandbox."""
    sandbox = get_user_sandbox()
    
    if not sandbox:
        return JSONResponse(
            status_code=404,
            content={"error": "Keine aktive User-Sandbox"},
        )
    
    container_id = sandbox.get("container_id")
    session_id = sandbox.get("session_id")
    
    result = get_lifecycle().stop(container_id, force=request.force)
    set_user_sandbox(None)
    
    return {"status": "stopped", "session_id": session_id, **result}


@app.get("/sandbox/user/status")
def user_sandbox_status():
    """Status der User-Sandbox."""
    sandbox = get_user_sandbox()
    
    if not sandbox:
        return {"active": False, "hint": "Starte mit POST /sandbox/user/start"}
    
    started_at = sandbox.get("started_at")
    uptime_seconds = 0
    if started_at:
        started_dt = datetime.fromisoformat(started_at)
        uptime_seconds = int((datetime.now() - started_dt).total_seconds())
    
    return {
        "active": True,
        **sandbox,
        "uptime_seconds": uptime_seconds,
        "uptime": f"{uptime_seconds // 60}m {uptime_seconds % 60}s",
    }


# ============================================================
# UNIFIED SANDBOX EXECUTE
# ============================================================

@app.post("/sandbox/execute")
def sandbox_execute(request: ContainerStartRequest):
    """Führt Code aus - nutzt User-Sandbox wenn aktiv, sonst ephemeral."""
    user_sandbox = get_user_sandbox()
    
    if user_sandbox:
        container_id = user_sandbox.get("container_id")
        session_id = user_sandbox.get("session_id")
        
        log_info(f"Using User-Sandbox: {container_id[:8]}")
        
        if not request.code:
            return {
                "status": "ready",
                "using_user_sandbox": True,
                "session_id": session_id,
            }
        
        docker_client = get_docker_client()
        if not docker_client:
            raise HTTPException(status_code=503, detail="Docker nicht verfügbar")
        
        try:
            container = docker_client.containers.get(container_id)
            
            executor = CodeExecutor(container)
            result = executor.execute(request.code, request.language or "python")
            
            return {
                "status": "executed",
                "using_user_sandbox": True,
                "session_id": session_id,
                "container_id": container_id,
                "execution_result": result.to_dict(),
            }
            
        except Exception as e:
            log_error(f"User-Sandbox execution failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    else:
        log_info("No User-Sandbox, using ephemeral")
        request.keep_alive = False
        request.enable_ttyd = False
        return container_start(request)


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup():
    """Startup: Registry laden und prüfen."""
    registry = load_registry()
    containers = registry.get("containers", {})
    
    log_info(f"Loaded {len(containers)} container definitions:")
    for name, config in containers.items():
        log_info(f"  - {name}: {config.get('description', 'No description')}")
    
    log_info("Container-Manager v3.3 with direct imports - Ready!")
