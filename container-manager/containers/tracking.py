# containers/tracking.py
"""
Container & Session Tracking.

Thread-safe Tracking aller aktiven Container und Sessions.
"""

import uuid
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

# ============================================================
# CONFIG (lokal)
# ============================================================

DEFAULT_SESSION_TTL = 300  # 5 Minuten
MAX_SESSION_TTL = 3600     # 1 Stunde
LOG_PREFIX = "[ContainerManager]"


def log_info(msg: str) -> None:
    print(f"{LOG_PREFIX} [INFO] {msg}")

def log_warning(msg: str) -> None:
    print(f"{LOG_PREFIX} [WARN] {msg}")


# ============================================================
# TRACKED CONTAINER DATACLASS
# ============================================================

@dataclass
class TrackedContainer:
    """Informationen zu einem getrackten Container."""
    container_id: str
    session_id: str
    name: str
    started_at: str
    last_activity: str
    persistent: bool = False
    ttl_seconds: Optional[int] = None
    ttyd_enabled: bool = False
    ttyd_port: Optional[str] = None
    ttyd_url: Optional[str] = None
    owner: str = "system"
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "container_id": self.container_id,
            "session_id": self.session_id,
            "name": self.name,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "persistent": self.persistent,
            "ttl_seconds": self.ttl_seconds,
            "ttyd_enabled": self.ttyd_enabled,
            "ttyd_port": self.ttyd_port,
            "ttyd_url": self.ttyd_url,
            "owner": self.owner,
        }
    
    @property
    def is_expired(self) -> bool:
        """Prüft ob Session abgelaufen ist."""
        if not self.persistent or self.ttl_seconds is None:
            return False
        
        last = datetime.fromisoformat(self.last_activity)
        expires = last + timedelta(seconds=self.ttl_seconds)
        return datetime.now() > expires
    
    @property
    def remaining_seconds(self) -> Optional[int]:
        """Verbleibende Sekunden bis Ablauf."""
        if not self.persistent or self.ttl_seconds is None:
            return None
        
        last = datetime.fromisoformat(self.last_activity)
        remaining = self.ttl_seconds - (datetime.now() - last).seconds
        return max(0, remaining)


# ============================================================
# CONTAINER TRACKER CLASS
# ============================================================

class ContainerTracker:
    """
    Thread-safe Container Tracker.
    
    Verwaltet alle aktiven Container und deren Sessions.
    """
    
    def __init__(self):
        self._containers: Dict[str, TrackedContainer] = {}
        self._lock = threading.Lock()
        self._user_sandbox: Optional[Dict[str, Any]] = None
        self._user_sandbox_lock = threading.Lock()
    
    # ============================================================
    # CONTAINER TRACKING
    # ============================================================
    
    def track(self, container_id: str, info: Dict[str, Any]) -> str:
        """
        Fügt Container zum Tracking hinzu.
        
        Args:
            container_id: Docker Container ID
            info: Container-Informationen
            
        Returns:
            Session-ID
        """
        with self._lock:
            session_id = info.get("session_id") or str(uuid.uuid4())
            now = datetime.now().isoformat()
            
            tracked = TrackedContainer(
                container_id=container_id,
                session_id=session_id,
                name=info.get("name", "unknown"),
                started_at=info.get("started_at", now),
                last_activity=info.get("last_activity", now),
                persistent=info.get("persistent", False),
                ttl_seconds=info.get("ttl_seconds"),
                ttyd_enabled=info.get("ttyd_enabled", False),
                ttyd_port=info.get("ttyd_port"),
                ttyd_url=info.get("ttyd_url"),
                owner=info.get("owner", "system"),
                config=info.get("config", {}),
            )
            
            self._containers[container_id] = tracked
            log_info(f"Tracking container {container_id[:8]} (session: {session_id[:8]})")
            
            return session_id
    
    def untrack(self, container_id: str) -> bool:
        """
        Entfernt Container aus Tracking.
        
        Args:
            container_id: Docker Container ID
            
        Returns:
            True wenn entfernt
        """
        with self._lock:
            if container_id in self._containers:
                del self._containers[container_id]
                log_info(f"Untracked container {container_id[:8]}")
                return True
            return False
    
    def update_activity(self, container_id: str) -> bool:
        """
        Aktualisiert last_activity Timestamp.
        
        Args:
            container_id: Docker Container ID
            
        Returns:
            True wenn aktualisiert
        """
        with self._lock:
            if container_id in self._containers:
                self._containers[container_id].last_activity = datetime.now().isoformat()
                return True
            return False
    
    def get(self, container_id: str) -> Optional[TrackedContainer]:
        """
        Holt Container-Info.
        
        Args:
            container_id: Docker Container ID
            
        Returns:
            TrackedContainer oder None
        """
        with self._lock:
            return self._containers.get(container_id)
    
    def get_by_session(self, session_id: str) -> Optional[TrackedContainer]:
        """
        Findet Container by Session-ID.
        
        Args:
            session_id: Session ID
            
        Returns:
            TrackedContainer oder None
        """
        with self._lock:
            for container in self._containers.values():
                if container.session_id == session_id:
                    return container
            return None
    
    def is_tracked(self, container_id: str) -> bool:
        """Prüft ob Container getrackt wird."""
        with self._lock:
            return container_id in self._containers
    
    def get_all(self) -> Dict[str, TrackedContainer]:
        """Gibt Kopie aller getrackten Container zurück."""
        with self._lock:
            return dict(self._containers)
    
    def get_expired(self) -> List[TrackedContainer]:
        """Gibt Liste abgelaufener Container zurück."""
        with self._lock:
            return [c for c in self._containers.values() if c.is_expired]
    
    def get_persistent_sessions(self) -> List[TrackedContainer]:
        """Gibt alle persistenten Sessions zurück."""
        with self._lock:
            return [c for c in self._containers.values() if c.persistent]
    
    def extend_session(self, session_id: str, extend_seconds: int) -> Optional[int]:
        """
        Verlängert Session TTL.
        
        Args:
            session_id: Session ID
            extend_seconds: Sekunden zum Verlängern
            
        Returns:
            Neue TTL oder None
        """
        with self._lock:
            for container in self._containers.values():
                if container.session_id == session_id:
                    container.last_activity = datetime.now().isoformat()
                    if container.ttl_seconds:
                        container.ttl_seconds = min(
                            container.ttl_seconds + extend_seconds,
                            MAX_SESSION_TTL
                        )
                    return container.ttl_seconds
            return None
    
    def clear(self) -> int:
        """
        Löscht alle Container aus Tracking.
        
        Returns:
            Anzahl gelöschter Einträge
        """
        with self._lock:
            count = len(self._containers)
            self._containers.clear()
            log_info(f"Cleared {count} containers from tracking")
            return count
    
    @property
    def count(self) -> int:
        """Anzahl getrackter Container."""
        with self._lock:
            return len(self._containers)
    
    # ============================================================
    # USER SANDBOX
    # ============================================================
    
    def get_user_sandbox(self) -> Optional[Dict[str, Any]]:
        """Holt aktive User-Sandbox."""
        with self._user_sandbox_lock:
            return self._user_sandbox.copy() if self._user_sandbox else None
    
    def set_user_sandbox(self, sandbox: Optional[Dict[str, Any]]) -> None:
        """Setzt User-Sandbox."""
        with self._user_sandbox_lock:
            self._user_sandbox = sandbox
            if sandbox:
                log_info(f"User-Sandbox set: {sandbox.get('container_id', 'unknown')[:8]}")
            else:
                log_info("User-Sandbox cleared")
    
    def is_user_sandbox_active(self) -> bool:
        """Prüft ob User-Sandbox aktiv ist."""
        return self.get_user_sandbox() is not None


# ============================================================
# GLOBAL TRACKER INSTANCE
# ============================================================

tracker = ContainerTracker()


# ============================================================
# LEGACY COMPATIBILITY FUNCTIONS
# ============================================================

def track_container(container_id: str, info: Dict[str, Any]) -> None:
    """Legacy: Container tracken."""
    tracker.track(container_id, info)

def untrack_container(container_id: str) -> bool:
    """Legacy: Container aus Tracking entfernen."""
    return tracker.untrack(container_id)

def update_container_activity(container_id: str) -> bool:
    """Legacy: Activity updaten."""
    return tracker.update_activity(container_id)

def get_container_session(container_id: str) -> Optional[Dict[str, Any]]:
    """Legacy: Session-Info holen."""
    container = tracker.get(container_id)
    return container.to_dict() if container else None

def is_container_tracked(container_id: str) -> bool:
    """Legacy: Prüfen ob getrackt."""
    return tracker.is_tracked(container_id)

def get_tracked_containers() -> Dict[str, Dict[str, Any]]:
    """Legacy: Alle getrackten Container."""
    return {cid: c.to_dict() for cid, c in tracker.get_all().items()}

def get_user_sandbox() -> Optional[Dict[str, Any]]:
    """Legacy: User-Sandbox holen."""
    return tracker.get_user_sandbox()

def set_user_sandbox(sandbox: Optional[Dict[str, Any]]) -> None:
    """Legacy: User-Sandbox setzen."""
    tracker.set_user_sandbox(sandbox)

def is_user_sandbox_active() -> bool:
    """Legacy: User-Sandbox aktiv?"""
    return tracker.is_user_sandbox_active()
