# utils/ttyd.py
"""
ttyd Integration für Live-Terminal.

Startet und verwaltet ttyd Web-Terminal in Containern.
"""

from typing import Optional, Any, Tuple


TTYD_PORT = 7681
TTYD_COMMAND = "ttyd -W -p 7681 bash"

LOG_PREFIX = "[ttyd]"

def log_info(msg: str):
    print(f"{LOG_PREFIX} {msg}")

def log_warning(msg: str):
    print(f"{LOG_PREFIX} WARN: {msg}")


def start_ttyd(
    container: Any,
    port: int = TTYD_PORT,
    command: str = TTYD_COMMAND,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Startet ttyd im Container.
    
    Args:
        container: Docker Container Objekt
        port: ttyd Port im Container
        command: ttyd Befehl
        
    Returns:
        Tuple (success, host_port, ttyd_url)
    """
    try:
        container.exec_run(command, detach=True, user="root")
        container.reload()
        
        port_key = f'{port}/tcp'
        port_info = container.ports.get(port_key)
        
        if port_info and len(port_info) > 0:
            host_port = port_info[0]['HostPort']
            ttyd_url = f"http://localhost:{host_port}"
            
            log_info(f"ttyd gestartet auf Port {host_port}")
            return True, host_port, ttyd_url
        
        log_warning("ttyd gestartet, aber kein Port-Mapping gefunden")
        return False, None, None
        
    except Exception as e:
        log_warning(f"ttyd Start fehlgeschlagen: {e}")
        return False, None, None


def get_ttyd_url(container: Any, port: int = TTYD_PORT) -> Optional[str]:
    """Holt ttyd URL für einen Container."""
    try:
        container.reload()
        
        port_key = f'{port}/tcp'
        port_info = container.ports.get(port_key)
        
        if port_info and len(port_info) > 0:
            host_port = port_info[0]['HostPort']
            return f"http://localhost:{host_port}"
        
        return None
    except Exception:
        return None
