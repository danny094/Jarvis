# security/limits.py
"""
Resource Limits & Timeout Management.

Definiert Ressourcen-Limits für Container und
stellt sicher, dass sie eingehalten werden.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional

# Defaults hier definieren (keine zirkulären Imports)
DEFAULT_MEMORY_LIMIT = "512m"
DEFAULT_CPU_LIMIT = 1.0
DEFAULT_PIDS_LIMIT = 100
DEFAULT_DISK_LIMIT = "100m"
DEFAULT_EXECUTION_TIMEOUT = 60
MAX_EXECUTION_TIMEOUT = 300


@dataclass
class ResourceLimits:
    """
    Resource-Limits für einen Container.
    
    Attributes:
        memory: RAM-Limit (z.B. "512m", "1g")
        cpus: CPU-Limit (z.B. 1.0, 0.5)
        pids: Maximale Prozesse (Fork-Bomb Schutz)
        disk: Disk-Limit für tmpfs (z.B. "100m")
        timeout: Maximale Ausführungszeit in Sekunden
    """
    memory: str = DEFAULT_MEMORY_LIMIT
    cpus: float = DEFAULT_CPU_LIMIT
    pids: int = DEFAULT_PIDS_LIMIT
    disk: str = DEFAULT_DISK_LIMIT
    timeout: int = DEFAULT_EXECUTION_TIMEOUT
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "ResourceLimits":
        """
        Erstellt ResourceLimits aus Container-Config.
        
        Args:
            config: Container-Konfiguration aus der Registry
            
        Returns:
            ResourceLimits Instanz
        """
        resources = config.get("resources", {})
        security = config.get("security", {})
        
        return cls(
            memory=resources.get("memory", DEFAULT_MEMORY_LIMIT),
            cpus=float(resources.get("cpus", DEFAULT_CPU_LIMIT)),
            pids=int(resources.get("pids_limit", DEFAULT_PIDS_LIMIT)),
            disk=resources.get("disk_limit", DEFAULT_DISK_LIMIT),
            timeout=min(
                int(security.get("max_runtime_seconds", DEFAULT_EXECUTION_TIMEOUT)),
                MAX_EXECUTION_TIMEOUT
            ),
        )
    
    def to_docker_options(self) -> Dict[str, Any]:
        """
        Konvertiert zu Docker container.run() Optionen.
        
        Returns:
            Dict mit Docker-kompatiblen Optionen
        """
        options = {
            "mem_limit": self.memory,
            "pids_limit": self.pids,
        }
        
        # CPU Limits (Docker verwendet period/quota)
        if self.cpus:
            options["cpu_period"] = 100000
            options["cpu_quota"] = int(self.cpus * 100000)
        
        return options
    
    def get_tmpfs_config(self) -> Dict[str, str]:
        """
        Erstellt tmpfs Konfiguration für /workspace.
        
        Returns:
            Dict für Docker tmpfs Option
        """
        return {"/workspace": f"size={self.disk}"}
    
    def get_timeout_command(self, cmd: list) -> list:
        """
        Wrappet einen Command mit timeout.
        
        Args:
            cmd: Original Command als Liste
            
        Returns:
            Command mit timeout Prefix
        """
        return ["timeout", str(self.timeout)] + cmd
    
    def validate(self) -> bool:
        """
        Validiert die Limits.
        
        Returns:
            True wenn alle Limits gültig
        """
        if self.timeout > MAX_EXECUTION_TIMEOUT:
            return False
        if self.cpus <= 0 or self.cpus > 16:
            return False
        if self.pids <= 0 or self.pids > 1000:
            return False
        return True
    
    def __str__(self) -> str:
        return f"ResourceLimits(mem={self.memory}, cpu={self.cpus}, pids={self.pids}, timeout={self.timeout}s)"
