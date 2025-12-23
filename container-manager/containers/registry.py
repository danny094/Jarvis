# containers/registry.py
"""
Container Registry Management.

Lädt und verwaltet die Container-Registry (registry.yaml).
Nur Container aus der Registry sind erlaubt!
"""

import os
import yaml
from typing import Dict, Any, Optional, List

# ============================================================
# CONFIG (lokal definiert um zirkuläre Imports zu vermeiden)
# ============================================================

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "/app/container_defs/registry.yaml")
CONTAINERS_PATH = os.environ.get("CONTAINERS_PATH", "/app/container_defs")
LOG_PREFIX = "[ContainerManager]"


def log_info(msg: str) -> None:
    print(f"{LOG_PREFIX} [INFO] {msg}")

def log_error(msg: str) -> None:
    print(f"{LOG_PREFIX} [ERROR] {msg}")


# ============================================================
# REGISTRY CACHE
# ============================================================

_registry_cache: Optional[Dict] = None
_registry_mtime: float = 0


def _invalidate_cache():
    """Invalidiert den Registry-Cache."""
    global _registry_cache, _registry_mtime
    _registry_cache = None
    _registry_mtime = 0


# ============================================================
# REGISTRY FUNCTIONS
# ============================================================

def load_registry(force_reload: bool = False) -> Dict[str, Any]:
    """
    Lädt die Container-Registry.
    
    Args:
        force_reload: Cache ignorieren und neu laden
        
    Returns:
        Registry Dict mit "containers" und "settings"
    """
    global _registry_cache, _registry_mtime
    
    # Cache Check
    if not force_reload and _registry_cache is not None:
        try:
            current_mtime = os.path.getmtime(REGISTRY_PATH)
            if current_mtime == _registry_mtime:
                return _registry_cache
        except:
            pass
    
    # Laden
    try:
        with open(REGISTRY_PATH, "r") as f:
            registry = yaml.safe_load(f)
        
        # Cache updaten
        _registry_cache = registry
        try:
            _registry_mtime = os.path.getmtime(REGISTRY_PATH)
        except:
            pass
        
        log_info(f"Registry loaded: {len(registry.get('containers', {}))} containers")
        return registry
        
    except FileNotFoundError:
        log_error(f"Registry not found: {REGISTRY_PATH}")
        return {"containers": {}, "settings": {}}
    except yaml.YAMLError as e:
        log_error(f"Registry YAML error: {e}")
        return {"containers": {}, "settings": {}}
    except Exception as e:
        log_error(f"Registry load error: {e}")
        return {"containers": {}, "settings": {}}


def get_container_config(name: str) -> Optional[Dict[str, Any]]:
    """
    Holt Config für einen Container aus der Registry.
    
    Args:
        name: Container-Name
        
    Returns:
        Container-Config Dict oder None
    """
    registry = load_registry()
    return registry.get("containers", {}).get(name)


def is_container_allowed(name: str) -> bool:
    """
    Prüft ob Container in Registry ist (Whitelist).
    
    Args:
        name: Container-Name
        
    Returns:
        True wenn erlaubt
    """
    return get_container_config(name) is not None


def list_containers() -> List[Dict[str, Any]]:
    """
    Listet alle verfügbaren Container.
    
    Returns:
        Liste mit Container-Infos
    """
    registry = load_registry()
    containers = registry.get("containers", {})
    
    result = []
    for name, config in containers.items():
        result.append({
            "name": name,
            "description": config.get("description", ""),
            "triggers": config.get("triggers", []),
            "needs_confirm": config.get("security", {}).get("needs_confirm", False),
            "network_mode": config.get("security", {}).get("network_mode", "none"),
        })
    
    return result


def get_registry_settings() -> Dict[str, Any]:
    """
    Holt globale Registry-Einstellungen.
    
    Returns:
        Settings Dict
    """
    registry = load_registry()
    return registry.get("settings", {})


def get_image_name(container_name: str) -> str:
    """
    Gibt Image-Namen für einen Container zurück.
    
    Args:
        container_name: Container-Name
        
    Returns:
        Docker Image Name
    """
    config = get_container_config(container_name)
    if not config:
        return f"jarvis-{container_name}:latest"
    
    return config.get("image", f"jarvis-{container_name}:latest")


def get_build_context(container_name: str) -> Optional[str]:
    """
    Gibt Build-Context Pfad für einen Container zurück.
    
    Args:
        container_name: Container-Name
        
    Returns:
        Voller Pfad zum Build-Context oder None
    """
    config = get_container_config(container_name)
    if not config:
        return None
    
    build_context = config.get("build_context")
    if not build_context:
        return None
    
    # Relativer Pfad → Absolut
    if build_context.startswith("./"):
        return f"{CONTAINERS_PATH}/{container_name}"
    
    return build_context
