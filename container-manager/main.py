# container-manager/main.py
"""
Container Manager MCP Server

Verwaltet Sandbox-Container für sichere Code-Ausführung.
Nur Container aus der Registry sind erlaubt!
"""

import os
import yaml
import asyncio
import base64
import docker
import docker.errors
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ============================================================
# CONFIG
# ============================================================

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "/app/containers/registry.yaml")
MAX_OUTPUT_LENGTH = 10000  # Max chars für Container-Output

# ============================================================
# MODELS
# ============================================================

class ContainerStartRequest(BaseModel):
    container_name: str
    code: Optional[str] = None
    command: Optional[str] = None
    timeout: Optional[int] = 60

class ContainerExecRequest(BaseModel):
    container_id: str
    command: str
    timeout: Optional[int] = 30

class ContainerStopRequest(BaseModel):
    container_id: str

# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Container Manager",
    description="MCP Server für Sandbox-Container",
    version="1.0.0"
)

# Docker Client - LAZY INIT (nicht beim Import!)
_docker_client = None
_docker_available = None

def get_docker_client():
    """Lazy-Init für Docker Client."""
    global _docker_client, _docker_available
    
    if _docker_available is False:
        return None
    
    if _docker_client is None:
        try:
            import docker
            _docker_client = docker.from_env()
            _docker_client.ping()  # Test connection
            _docker_available = True
            print("[ContainerManager] Docker client initialized successfully")
        except Exception as e:
            print(f"[ContainerManager] Docker not available: {e}")
            _docker_available = False
            return None
    
    return _docker_client

# Aktive Container tracken (mit Lock für Thread-Safety)
import threading
active_containers: Dict[str, Dict[str, Any]] = {}
active_containers_lock = threading.Lock()

def track_container(container_id: str, info: Dict[str, Any]) -> None:
    """Thread-safe: Container zum Tracking hinzufügen."""
    with active_containers_lock:
        active_containers[container_id] = info

def untrack_container(container_id: str) -> bool:
    """Thread-safe: Container aus Tracking entfernen. Returns True wenn entfernt."""
    with active_containers_lock:
        if container_id in active_containers:
            del active_containers[container_id]
            return True
        return False

def is_container_tracked(container_id: str) -> bool:
    """Thread-safe: Prüft ob Container getrackt wird."""
    with active_containers_lock:
        return container_id in active_containers

def get_tracked_containers() -> Dict[str, Dict[str, Any]]:
    """Thread-safe: Kopie aller getrackten Container."""
    with active_containers_lock:
        return dict(active_containers)

# ============================================================
# HELPERS
# ============================================================

def load_registry() -> Dict:
    """Lädt die Container-Registry."""
    try:
        with open(REGISTRY_PATH, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[ContainerManager] Registry load error: {e}")
        return {"containers": {}, "settings": {}}

def get_container_config(name: str) -> Optional[Dict]:
    """Holt Config für einen Container aus der Registry."""
    registry = load_registry()
    return registry.get("containers", {}).get(name)

def is_container_allowed(name: str) -> bool:
    """Prüft ob Container in Registry ist."""
    return get_container_config(name) is not None

def build_image_if_needed(container_name: str, config: Dict) -> str:
    """Baut das Docker-Image wenn nötig."""
    image_name = config.get("image", f"jarvis-{container_name}:latest")
    build_context = config.get("build_context")
    
    # Docker Client holen
    client = get_docker_client()
    if not client:
        print(f"[ContainerManager] Docker not available, cannot build {image_name}")
        return image_name
    
    if build_context:
        full_path = f"/app/containers/{container_name}"
        try:
            print(f"[ContainerManager] Building {image_name} from {full_path}...")
            client.images.build(
                path=full_path,
                tag=image_name,
                rm=True
            )
            print(f"[ContainerManager] Built {image_name}")
        except Exception as e:
            print(f"[ContainerManager] Build failed: {e}")
            # Versuche existierendes Image zu nutzen
            pass
    
    return image_name

# ============================================================
# MCP ENDPOINTS
# ============================================================

@app.get("/health")
async def health():
    """Health Check."""
    docker_client = get_docker_client()
    docker_status = "connected" if docker_client else "unavailable"
    
    return {
        "status": "ok", 
        "service": "container-manager",
        "docker": docker_status
    }

@app.get("/mcp")
async def mcp_info():
    """MCP Server Info."""
    return {
        "name": "container-manager",
        "version": "1.0.0",
        "tools": [
            "container_list",
            "container_start",
            "container_exec",
            "container_stop",
            "container_status"
        ]
    }

# ============================================================
# TOOL: container_list
# ============================================================

@app.get("/containers")
async def container_list():
    """Listet alle verfügbaren Container aus der Registry."""
    registry = load_registry()
    containers = registry.get("containers", {})
    
    result = []
    for name, config in containers.items():
        result.append({
            "name": name,
            "description": config.get("description", ""),
            "triggers": config.get("triggers", []),
            "needs_confirm": config.get("security", {}).get("needs_confirm", False)
        })
    
    return {"containers": result, "count": len(result)}

# ============================================================
# TOOL: container_start
# ============================================================

@app.post("/containers/start")
def container_start(request: ContainerStartRequest):
    """
    Startet einen Container aus der Registry.
    
    SICHERHEIT: Nur registrierte Container sind erlaubt!
    
    NOTE: Sync endpoint - FastAPI führt das automatisch im Threadpool aus,
    damit Docker's blocking calls den Event Loop nicht blockieren.
    """
    container_name = request.container_name
    
    # SICHERHEITSCHECK 1: Ist Container in Registry?
    if not is_container_allowed(container_name):
        raise HTTPException(
            status_code=403,
            detail=f"Container '{container_name}' ist nicht in der Registry erlaubt!"
        )
    
    config = get_container_config(container_name)
    security = config.get("security", {})
    resources = config.get("resources", {})
    
    # Image bauen/laden
    image_name = build_image_if_needed(container_name, config)
    
    # Container-Optionen
    container_options = {
        "image": image_name,
        "detach": True,
        "remove": False,  # Wir räumen selbst auf
        "tty": True,
        "stdin_open": True,
    }
    
    # Netzwerk-Isolation
    network_mode = security.get("network_mode", "none")
    if network_mode == "none":
        container_options["network_mode"] = "none"
    
    # Ressourcen-Limits
    if resources.get("memory"):
        container_options["mem_limit"] = resources["memory"]
    if resources.get("cpus"):
        container_options["cpu_period"] = 100000
        container_options["cpu_quota"] = int(float(resources["cpus"]) * 100000)
    
    # Read-only Filesystem
    if security.get("read_only"):
        container_options["read_only"] = True
    
    try:
        # Docker Client holen
        docker_client = get_docker_client()
        if not docker_client:
            raise HTTPException(
                status_code=503,
                detail="Docker ist nicht verfügbar"
            )
        
        # Container starten
        container = docker_client.containers.run(**container_options)
        container_id = container.id[:12]
        
        # Tracken (thread-safe)
        track_container(container_id, {
            "name": container_name,
            "started_at": datetime.now().isoformat(),
            "config": config
        })
        
        print(f"[ContainerManager] Started {container_name} as {container_id}")
        
        # Wenn Code mitgegeben wurde, direkt ausführen
        result = None
        if request.code:
            # Methode 1: Code als Datei schreiben via tar/put_archive (zuverlässigste Methode)
            import io
            import tarfile
            
            # Tar-Archiv im Memory erstellen
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                # Code als Datei hinzufügen
                code_bytes = request.code.encode('utf-8')
                tarinfo = tarfile.TarInfo(name='code.py')
                tarinfo.size = len(code_bytes)
                tar.addfile(tarinfo, io.BytesIO(code_bytes))
            
            tar_stream.seek(0)
            
            # Archiv in Container entpacken
            container.put_archive('/workspace', tar_stream)
            print(f"[ContainerManager] Code written via put_archive ({len(request.code)} chars)")
            
            # Code ausführen
            exec_result = container.exec_run(
                ["python", "/workspace/code.py"],
                workdir="/workspace",
                demux=True
            )
            
            stdout = exec_result.output[0].decode() if exec_result.output[0] else ""
            stderr = exec_result.output[1].decode() if exec_result.output[1] else ""
            
            result = {
                "exit_code": exec_result.exit_code,
                "stdout": stdout[:MAX_OUTPUT_LENGTH],
                "stderr": stderr[:MAX_OUTPUT_LENGTH]
            }
            
            print(f"[ContainerManager] Code executed, exit_code={exec_result.exit_code}")
        
        return {
            "status": "started",
            "container_id": container_id,
            "container_name": container_name,
            "execution_result": result
        }
        
    except docker.errors.ImageNotFound:
        raise HTTPException(
            status_code=404,
            detail=f"Image '{image_name}' nicht gefunden. Bitte erst bauen."
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Container-Start fehlgeschlagen: {str(e)}"
        )

# ============================================================
# TOOL: container_exec
# ============================================================

@app.post("/containers/exec")
def container_exec(request: ContainerExecRequest):
    """Führt Befehl in laufendem Container aus (sync - Threadpool)."""
    container_id = request.container_id
    
    # Prüfe ob Container bekannt (thread-safe)
    if not is_container_tracked(container_id):
        raise HTTPException(
            status_code=404,
            detail=f"Container '{container_id}' nicht gefunden oder nicht aktiv"
        )
    
    try:
        docker_client = get_docker_client()
        if not docker_client:
            raise HTTPException(status_code=503, detail="Docker nicht verfügbar")
        
        container = docker_client.containers.get(container_id)
        
        # Befehl ausführen mit Timeout
        exec_result = container.exec_run(
            request.command,
            workdir="/workspace",
            demux=True
        )
        
        stdout = exec_result.output[0].decode() if exec_result.output[0] else ""
        stderr = exec_result.output[1].decode() if exec_result.output[1] else ""
        
        return {
            "container_id": container_id,
            "command": request.command,
            "exit_code": exec_result.exit_code,
            "stdout": stdout[:MAX_OUTPUT_LENGTH],
            "stderr": stderr[:MAX_OUTPUT_LENGTH]
        }
        
    except Exception as e:
        if "NotFound" in str(type(e)):
            # Container existiert nicht mehr
            untrack_container(container_id)
            raise HTTPException(
                status_code=404,
                detail=f"Container '{container_id}' existiert nicht mehr"
            )
        raise HTTPException(
            status_code=500,
            detail=f"Exec fehlgeschlagen: {str(e)}"
        )

# ============================================================
# TOOL: container_stop
# ============================================================

@app.post("/containers/stop")
def container_stop(request: ContainerStopRequest):
    """Stoppt und entfernt einen Container (sync - Threadpool)."""
    container_id = request.container_id
    
    # Docker Client holen
    docker_client = get_docker_client()
    if not docker_client:
        # Kein Docker verfügbar - Container ist eh weg, cleanup tracking
        untrack_container(container_id)
        return {
            "status": "no_docker",
            "container_id": container_id,
            "message": "Docker not available, container assumed stopped"
        }
    
    try:
        container = docker_client.containers.get(container_id)
        
        # Prüfe Status - wenn schon exited, nur remove
        if container.status in ["exited", "dead"]:
            print(f"[ContainerManager] Container {container_id} already {container.status}, just removing...")
            try:
                container.remove()
            except:
                pass  # Removal kann fehlschlagen wenn schon weg
        else:
            # Noch running - normal stoppen
            container.stop(timeout=5)
            container.remove()
        
        # Aus Tracking entfernen (thread-safe)
        untrack_container(container_id)
        
        print(f"[ContainerManager] Stopped and removed {container_id}")
        
        return {
            "status": "stopped",
            "container_id": container_id
        }
        
    except docker.errors.NotFound:
        # Container existiert nicht (mehr) - Das ist OK!
        print(f"[ContainerManager] Container {container_id} not found (already gone)")
        untrack_container(container_id)
        return {
            "status": "already_stopped",
            "container_id": container_id,
            "message": "Container not found, assumed already stopped"
        }
    except docker.errors.APIError as e:
        # Docker API Fehler - aber Container ist vermutlich weg
        print(f"[ContainerManager] API Error stopping {container_id}: {e}")
        untrack_container(container_id)
        # Kein 500 werfen - graceful handling!
        return {
            "status": "error_but_cleaned",
            "container_id": container_id,
            "message": f"Error: {str(e)}, but tracking cleaned up"
        }
    except Exception as e:
        # Unerwarteter Fehler - aber trotzdem cleanup tracking
        print(f"[ContainerManager] Unexpected error stopping {container_id}: {e}")
        untrack_container(container_id)
        # Auch hier kein 500 - graceful!
        return {
            "status": "error_but_cleaned",
            "container_id": container_id,
            "message": f"Unexpected error: {str(e)}, but tracking cleaned up"
        }

# ============================================================
# TOOL: container_status
# ============================================================

@app.get("/containers/status")
def container_status():
    """Zeigt Status aller aktiven Container (sync - Threadpool)."""
    docker_client = get_docker_client()
    if not docker_client:
        return {
            "active_containers": [],
            "count": 0,
            "error": "Docker not available"
        }
    
    result = []
    
    # Thread-safe Kopie der Container
    tracked = get_tracked_containers()
    for container_id, info in tracked.items():
        try:
            container = docker_client.containers.get(container_id)
            result.append({
                "container_id": container_id,
                "name": info["name"],
                "status": container.status,
                "started_at": info["started_at"]
            })
        except docker.errors.NotFound:
            # Container ist weg - aus Tracking entfernen
            untrack_container(container_id)
    
    return {
        "active_containers": result,
        "count": len(result)
    }

# ============================================================
# CLEANUP: Alte Container aufräumen
# ============================================================

@app.post("/containers/cleanup")
def container_cleanup():
    """Stoppt alle aktiven Container (sync - Threadpool)."""
    docker_client = get_docker_client()
    if not docker_client:
        # Kein Docker - nur Tracking leeren (thread-safe)
        with active_containers_lock:
            count = len(active_containers)
            active_containers.clear()
        return {"stopped": [], "count": 0, "cleared_tracking": count}
    
    stopped = []
    
    # Thread-safe Kopie der Container-IDs
    tracked = get_tracked_containers()
    for container_id in tracked.keys():
        try:
            container = docker_client.containers.get(container_id)
            container.stop(timeout=5)
            container.remove()
            stopped.append(container_id)
        except Exception as e:
            print(f"[ContainerManager] Cleanup error for {container_id}: {e}")
        
        untrack_container(container_id)
    
    return {"stopped": stopped, "count": len(stopped)}

# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup():
    """Startup: Registry laden und prüfen."""
    registry = load_registry()
    containers = registry.get("containers", {})
    
    print(f"[ContainerManager] Loaded {len(containers)} container definitions:")
    for name, config in containers.items():
        print(f"  - {name}: {config.get('description', 'No description')}")
    
    print("[ContainerManager] Ready!")

@app.on_event("shutdown")
async def shutdown():
    """Shutdown: Alle Container aufräumen."""
    print("[ContainerManager] Shutting down, cleaning up containers...")
    # container_cleanup ist jetzt sync - direkt aufrufen
    container_cleanup()
