# utils/docker_client.py
"""
Docker Client Management.

Lazy-Initialization und Connection Management für Docker.
"""

import threading
from typing import Optional

# ============================================================
# CONFIG (lokal)
# ============================================================

LOG_PREFIX = "[ContainerManager]"


def log_info(msg: str) -> None:
    print(f"{LOG_PREFIX} [INFO] {msg}")

def log_error(msg: str) -> None:
    print(f"{LOG_PREFIX} [ERROR] {msg}")


# ============================================================
# DOCKER CLIENT SINGLETON
# ============================================================

_docker_client = None
_docker_available: Optional[bool] = None
_docker_lock = threading.Lock()


def get_docker_client():
    """
    Lazy-Init für Docker Client.
    
    Thread-safe Singleton Pattern.
    
    Returns:
        Docker Client oder None wenn nicht verfügbar
    """
    global _docker_client, _docker_available
    
    # Quick check ohne Lock
    if _docker_available is False:
        return None
    
    if _docker_client is not None:
        return _docker_client
    
    # Thread-safe Initialization
    with _docker_lock:
        # Double-check nach Lock
        if _docker_client is not None:
            return _docker_client
        
        if _docker_available is False:
            return None
        
        try:
            import docker
            client = docker.from_env()
            client.ping()  # Test connection
            
            _docker_client = client
            _docker_available = True
            
            log_info("Docker client initialized successfully")
            return _docker_client
            
        except ImportError:
            log_error("Docker package not installed")
            _docker_available = False
            return None
            
        except Exception as e:
            log_error(f"Docker not available: {e}")
            _docker_available = False
            return None


def is_docker_available() -> bool:
    """
    Prüft ob Docker verfügbar ist.
    
    Returns:
        True wenn Docker funktioniert
    """
    return get_docker_client() is not None


def reset_docker_client() -> None:
    """
    Setzt Docker Client zurück.
    
    Nützlich nach Docker-Restart oder für Tests.
    """
    global _docker_client, _docker_available
    
    with _docker_lock:
        _docker_client = None
        _docker_available = None
        log_info("Docker client reset")


def get_docker_info() -> Optional[dict]:
    """
    Holt Docker System-Informationen.
    
    Returns:
        Docker info dict oder None
    """
    client = get_docker_client()
    if not client:
        return None
    
    try:
        return client.info()
    except Exception as e:
        log_error(f"Failed to get Docker info: {e}")
        return None


def get_docker_version() -> Optional[str]:
    """
    Holt Docker Version.
    
    Returns:
        Version string oder None
    """
    client = get_docker_client()
    if not client:
        return None
    
    try:
        return client.version().get("Version", "unknown")
    except:
        return None
