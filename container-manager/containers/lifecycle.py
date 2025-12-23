# containers/lifecycle.py
"""
Container Lifecycle Management.

Verwaltet den Lebenszyklus von Containern:
- Start / Stop / Cleanup
- Image Building
- ttyd Integration
"""

import os
import sys
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

# ============================================================
# PATH SETUP (MUSS VOR ALLEN LOKALEN IMPORTS KOMMEN!)
# ============================================================

_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)

for _path in [_parent_dir, _current_dir]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ============================================================
# IMPORTS MIT FALLBACK
# ============================================================

try:
    # Relative Imports (Standard für Packages)
    from .registry import get_container_config, get_image_name, get_build_context
    from .tracking import tracker
    from .executor import CodeExecutor, ResourceLimits
except ImportError:
    # Absolute Imports (Fallback für Docker)
    from containers.registry import get_container_config, get_image_name, get_build_context
    from containers.tracking import tracker
    from containers.executor import CodeExecutor, ResourceLimits

# ResourceLimits aus security/ wenn verfügbar
try:
    from security.limits import ResourceLimits as SecurityResourceLimits
    ResourceLimits = SecurityResourceLimits
except ImportError:
    pass  # Behalte ResourceLimits von executor

# ============================================================
# CONFIG (lokal)
# ============================================================

CONTAINER_STOP_TIMEOUT = 10
TTYD_PORT = 7681
TTYD_COMMAND = "ttyd -W -p 7681 bash"
LOG_PREFIX = "[ContainerManager]"


def log_info(msg: str) -> None:
    print(f"{LOG_PREFIX} [INFO] {msg}")

def log_error(msg: str) -> None:
    print(f"{LOG_PREFIX} [ERROR] {msg}")

def log_warning(msg: str) -> None:
    print(f"{LOG_PREFIX} [WARN] {msg}")


# ============================================================
# DOCKER CLIENT (inline)
# ============================================================

_docker_client = None
_docker_available = None


def get_docker_client():
    """Lazy-Init für Docker Client."""
    global _docker_client, _docker_available
    
    if _docker_available is False:
        return None
    
    if _docker_client is not None:
        return _docker_client
    
    try:
        import docker
        client = docker.from_env()
        client.ping()
        
        _docker_client = client
        _docker_available = True
        log_info("Docker client initialized")
        return _docker_client
        
    except Exception as e:
        log_error(f"Docker not available: {e}")
        _docker_available = False
        return None


def is_docker_available() -> bool:
    """Prüft ob Docker verfügbar ist."""
    return get_docker_client() is not None


# ============================================================
# SANDBOX SECURITY (inline)
# ============================================================

def get_security_options(config: Dict[str, Any], enable_ttyd: bool = False) -> Dict[str, Any]:
    """Erstellt Docker Security Options aus Config."""
    security = config.get("security", {})
    
    options = {
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
    }
    
    # Netzwerk
    network_mode = security.get("network_mode", "none")
    if enable_ttyd:
        # User-Sandbox braucht Netzwerk für ttyd UND Internet-Zugang
        options["network_mode"] = "bridge"
    elif network_mode == "none":
        options["network_mode"] = "none"
    # Sonst: Docker-Default (bridge)
    
    # Read-only
    if security.get("read_only", False):
        options["read_only"] = True
    
    return options


# ============================================================
# CONTAINER LIFECYCLE CLASS
# ============================================================

class ContainerLifecycle:
    """
    Verwaltet Container-Lebenszyklus.
    """
    
    def __init__(self, docker_client=None):
        self._client = docker_client
    
    @property
    def client(self):
        """Lazy-Loading Docker Client."""
        if self._client is None:
            self._client = get_docker_client()
        return self._client
    
    def build_image_if_needed(self, container_name: str) -> str:
        """Baut Docker-Image wenn nötig."""
        image_name = get_image_name(container_name)
        build_context = get_build_context(container_name)
        
        if not self.client:
            log_warning(f"Docker not available, cannot build {image_name}")
            return image_name
        
        if not build_context:
            return image_name
        
        try:
            log_info(f"Building {image_name} from {build_context}...")
            self.client.images.build(
                path=build_context,
                tag=image_name,
                rm=True,
            )
            log_info(f"Built {image_name}")
        except Exception as e:
            log_error(f"Build failed: {e}")
        
        return image_name
    
    def start(
        self,
        container_name: str,
        code: Optional[str] = None,
        language: str = "python",
        keep_alive: bool = False,
        enable_ttyd: bool = False,
        ttl_seconds: int = 300,
    ) -> Dict[str, Any]:
        """Startet einen Container."""
        if not self.client:
            return {"error": "Docker nicht verfügbar", "status": "error"}
        
        # Config laden
        config = get_container_config(container_name)
        if not config:
            return {"error": f"Container '{container_name}' nicht in Registry", "status": "error"}
        
        # Limits
        limits = ResourceLimits.from_config(config)
        
        # Image
        image_name = self.build_image_if_needed(container_name)
        
        # Docker-Optionen
        container_options = {
            "image": image_name,
            "detach": True,
            "remove": False,
            "tty": True,
            "stdin_open": True,
            "mem_limit": limits.memory,
            "pids_limit": limits.pids,
        }
        
        # CPU Limits
        if limits.cpus:
            container_options["cpu_period"] = 100000
            container_options["cpu_quota"] = int(limits.cpus * 100000)
        
        # Security
        security_opts = get_security_options(config, enable_ttyd)
        container_options.update(security_opts)
        
        # ttyd Port
        if enable_ttyd:
            container_options["ports"] = {f'{TTYD_PORT}/tcp': None}
        
        try:
            # Container starten
            container = self.client.containers.run(**container_options)
            container_id = container.id[:12]
            session_id = str(uuid.uuid4())
            
            log_info(f"Started {container_name} as {container_id}")
            
            # ttyd starten
            ttyd_url = None
            ttyd_port = None
            
            if enable_ttyd:
                ttyd_result = self._start_ttyd(container)
                ttyd_port = ttyd_result.get("port")
                ttyd_url = ttyd_result.get("url")
            
            # Tracking
            tracker.track(container_id, {
                "session_id": session_id,
                "name": container_name,
                "config": config,
                "persistent": keep_alive,
                "ttl_seconds": ttl_seconds if keep_alive else None,
                "ttyd_enabled": enable_ttyd,
                "ttyd_port": ttyd_port,
                "ttyd_url": ttyd_url,
            })
            
            # Code ausführen
            execution_result = None
            if code:
                executor = CodeExecutor(container, limits)
                result = executor.execute(code, language)
                execution_result = result.to_dict()
            
            # Cleanup bei nicht-persistent
            if not keep_alive and execution_result:
                self._cleanup_container(container)
                tracker.untrack(container_id)
            
            return {
                "status": "started",
                "container_id": container_id,
                "container_name": container_name,
                "session_id": session_id,
                "execution_result": execution_result,
                "ttyd_url": ttyd_url,
                "persistent": keep_alive,
            }
            
        except Exception as e:
            log_error(f"Start failed: {e}")
            return {"error": str(e), "status": "error"}
    
    def stop(self, container_id: str, force: bool = False) -> Dict[str, Any]:
        """Stoppt einen Container."""
        if not self.client:
            tracker.untrack(container_id)
            return {"status": "no_docker", "container_id": container_id}
        
        try:
            container = self.client.containers.get(container_id)
            
            if container.status in ["exited", "dead"]:
                try:
                    container.remove()
                except Exception:
                    pass
            else:
                if force:
                    container.kill()
                else:
                    container.stop(timeout=CONTAINER_STOP_TIMEOUT)
                container.remove()
            
            tracker.untrack(container_id)
            log_info(f"Stopped {container_id}")
            
            return {"status": "stopped", "container_id": container_id}
            
        except Exception as e:
            if "NotFound" in str(type(e)) or "404" in str(e):
                tracker.untrack(container_id)
                return {"status": "already_stopped", "container_id": container_id}
            
            log_error(f"Stop failed: {e}")
            tracker.untrack(container_id)
            return {"status": "error", "error": str(e), "container_id": container_id}
    
    def cleanup_all(self) -> Dict[str, Any]:
        """Stoppt alle getrackten Container."""
        if not self.client:
            count = tracker.clear()
            return {"stopped": [], "count": 0, "cleared_tracking": count}
        
        stopped = []
        tracked = tracker.get_all()
        
        for container_id in tracked.keys():
            result = self.stop(container_id)
            if result.get("status") in ["stopped", "already_stopped"]:
                stopped.append(container_id)
        
        return {"stopped": stopped, "count": len(stopped)}
    
    def cleanup_expired(self) -> int:
        """Räumt abgelaufene Sessions auf."""
        expired = tracker.get_expired()
        count = 0
        
        for container in expired:
            result = self.stop(container.container_id)
            if result.get("status") != "error":
                count += 1
                log_info(f"Cleaned up expired: {container.container_id}")
        
        return count
    
    def _start_ttyd(self, container) -> Dict[str, Any]:
        """Startet ttyd im Container."""
        try:
            container.exec_run(
                TTYD_COMMAND,
                detach=True,
                user="root",
            )
            
            container.reload()
            
            port_info = container.ports.get(f'{TTYD_PORT}/tcp')
            if port_info and len(port_info) > 0:
                host_port = port_info[0]['HostPort']
                log_info(f"ttyd started on port {host_port}")
                return {
                    "port": host_port,
                    "url": f"http://localhost:{host_port}",
                }
        except Exception as e:
            log_error(f"ttyd start failed: {e}")
        
        return {"port": None, "url": None}
    
    def _cleanup_container(self, container) -> None:
        """Räumt Container auf."""
        try:
            container.stop(timeout=5)
            container.remove()
        except Exception:
            pass


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

_lifecycle: Optional[ContainerLifecycle] = None


def get_lifecycle() -> ContainerLifecycle:
    """Singleton ContainerLifecycle."""
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = ContainerLifecycle()
    return _lifecycle


def start_container(container_name: str, **kwargs) -> Dict[str, Any]:
    """Convenience: Container starten."""
    return get_lifecycle().start(container_name, **kwargs)


def stop_container(container_id: str, force: bool = False) -> Dict[str, Any]:
    """Convenience: Container stoppen."""
    return get_lifecycle().stop(container_id, force)


def cleanup_all_containers() -> Dict[str, Any]:
    """Convenience: Alle Container aufräumen."""
    return get_lifecycle().cleanup_all()
