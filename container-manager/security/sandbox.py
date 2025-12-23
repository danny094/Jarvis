# security/sandbox.py
"""
Sandbox Security Configuration.

Definiert Sicherheitseinstellungen für Container-Sandboxes:
- Netzwerk-Isolation
- Capability Dropping
- Security Options
- Read-Only Filesystem
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

# Defaults hier definieren
DEFAULT_NETWORK_MODE = "none"
DEFAULT_READ_ONLY = False
DEFAULT_CAP_DROP = ["ALL"]
DEFAULT_CAP_ADD = []
DEFAULT_SECURITY_OPT = ["no-new-privileges:true"]


@dataclass
class SandboxSecurity:
    """
    Sicherheitseinstellungen für eine Sandbox.
    
    Attributes:
        network_mode: Docker Netzwerk-Modus ("none", "bridge", etc.)
        read_only: Filesystem read-only machen
        needs_confirm: User-Bestätigung vor Start erforderlich
        cap_drop: Liste der zu entfernenden Capabilities
        cap_add: Liste der hinzuzufügenden Capabilities
        security_opt: Docker Security Options
    """
    network_mode: str = DEFAULT_NETWORK_MODE
    read_only: bool = DEFAULT_READ_ONLY
    needs_confirm: bool = False
    cap_drop: List[str] = field(default_factory=lambda: DEFAULT_CAP_DROP.copy())
    cap_add: List[str] = field(default_factory=lambda: DEFAULT_CAP_ADD.copy())
    security_opt: List[str] = field(default_factory=lambda: DEFAULT_SECURITY_OPT.copy())
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "SandboxSecurity":
        """
        Erstellt SandboxSecurity aus Container-Config.
        
        Args:
            config: Container-Konfiguration aus der Registry
            
        Returns:
            SandboxSecurity Instanz
        """
        security = config.get("security", {})
        
        return cls(
            network_mode=security.get("network_mode", DEFAULT_NETWORK_MODE),
            read_only=security.get("read_only", DEFAULT_READ_ONLY),
            needs_confirm=security.get("needs_confirm", False),
            cap_drop=security.get("cap_drop", DEFAULT_CAP_DROP.copy()),
            cap_add=security.get("cap_add", DEFAULT_CAP_ADD.copy()),
            security_opt=security.get("security_opt", DEFAULT_SECURITY_OPT.copy()),
        )
    
    def to_docker_options(self, enable_ttyd: bool = False) -> Dict[str, Any]:
        """
        Konvertiert zu Docker container.run() Optionen.
        
        Args:
            enable_ttyd: Wenn True, wird Netzwerk für ttyd aktiviert
            
        Returns:
            Dict mit Docker-kompatiblen Optionen
        """
        options = {
            "cap_drop": self.cap_drop,
            "cap_add": self.cap_add,
            "security_opt": self.security_opt,
        }
        
        # Netzwerk-Modus
        if self.network_mode == "none" and not enable_ttyd:
            options["network_mode"] = "none"
        # Wenn ttyd aktiviert, brauchen wir Netzwerk für Port-Binding
        
        # Read-only Filesystem
        if self.read_only:
            options["read_only"] = True
        
        return options
    
    @property
    def is_isolated(self) -> bool:
        """Prüft ob Container netzwerk-isoliert ist."""
        return self.network_mode == "none"
    
    @property
    def is_hardened(self) -> bool:
        """Prüft ob Container gehärtet ist (alle Caps gedroppt)."""
        return "ALL" in self.cap_drop and len(self.cap_add) == 0
    
    def get_risk_level(self) -> str:
        """
        Berechnet Risiko-Level basierend auf Einstellungen.
        
        Returns:
            "low", "medium", "high"
        """
        score = 0
        
        # Netzwerk-Zugang erhöht Risiko
        if not self.is_isolated:
            score += 3
        
        # Nicht-hardened erhöht Risiko
        if not self.is_hardened:
            score += 2
        
        # Read-write Filesystem erhöht Risiko
        if not self.read_only:
            score += 1
        
        if score <= 1:
            return "low"
        elif score <= 3:
            return "medium"
        else:
            return "high"
    
    def __str__(self) -> str:
        return f"SandboxSecurity(network={self.network_mode}, hardened={self.is_hardened}, risk={self.get_risk_level()})"


def create_user_sandbox_security() -> SandboxSecurity:
    """
    Erstellt Security-Config für User-Sandbox.
    
    User-Sandbox braucht Netzwerk für ttyd, ist aber
    ansonsten gehärtet.
    
    Returns:
        SandboxSecurity für User-Sandbox
    """
    return SandboxSecurity(
        network_mode="bridge",  # Braucht Netzwerk für ttyd Port
        read_only=False,  # User kann Dateien erstellen
        needs_confirm=False,  # User hat explizit gestartet
        cap_drop=["ALL"],
        cap_add=[],
        security_opt=["no-new-privileges:true"],
    )
