# recorder.py - Network Data Collection (MVP)

import asyncio
from datetime import datetime
from typing import Dict
import docker

from .config import Config
from .database import insert_raw_stat


class NetworkRecorder:
    """
    Collects raw network statistics from /proc/net/dev and Docker
    MVP: Simple /proc/net/dev parsing + Docker container mapping
    """
    
    def __init__(self):
        self.docker_client = None
        self.last_stats = {}
        self.running = False
        
        try:
            self.docker_client = docker.from_env()
            print("✓ Docker client initialized")
        except Exception as e:
            print(f"⚠ Docker client failed: {e}")
    
    async def run(self):
        """Main recording loop"""
        self.running = True
        print(f"→ Recorder started (interval: {Config.COLLECTION_INTERVAL}s)")
        
        while self.running:
            try:
                await self.collect()
                await asyncio.sleep(Config.COLLECTION_INTERVAL)
            except Exception as e:
                print(f"[Recorder Error] {e}")
                await asyncio.sleep(5)
    
    async def collect(self):
        """Collect current network stats"""
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        # Read system-wide stats
        system_stats = self._read_proc_net_dev()
        
        # Map to containers (if Docker available)
        if self.docker_client:
            container_stats = await self._map_to_containers(system_stats)
        else:
            container_stats = {"system": system_stats.get("eth0", {})}
        
        # Calculate deltas and store
        for container, stats in container_stats.items():
            if container in self.last_stats:
                delta_rx = stats.get("rx_bytes", 0) - self.last_stats[container].get("rx_bytes", 0)
                delta_tx = stats.get("tx_bytes", 0) - self.last_stats[container].get("tx_bytes", 0)
                
                # Only store if there was traffic
                if delta_rx > 0 or delta_tx > 0:
                    insert_raw_stat(
                        timestamp=timestamp,
                        container_name=container,
                        interface=stats.get("interface", "unknown"),
                        rx_bytes=delta_rx,
                        tx_bytes=delta_tx
                    )
        
        self.last_stats = container_stats
    
    def _read_proc_net_dev(self) -> Dict[str, Dict]:
        """
        Parse /proc/net/dev
        Returns: {interface: {rx_bytes, tx_bytes, interface}}
        """
        stats = {}
        
        try:
            with open(Config.PROC_NET_DEV, 'r') as f:
                lines = f.readlines()[2:]  # Skip header lines
                
                for line in lines:
                    parts = line.split()
                    if len(parts) < 17:
                        continue
                    
                    interface = parts[0].rstrip(':')
                    
                    # Skip loopback
                    if interface == 'lo':
                        continue
                    
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])
                    
                    stats[interface] = {
                        'rx_bytes': rx_bytes,
                        'tx_bytes': tx_bytes,
                        'interface': interface
                    }
        
        except Exception as e:
            print(f"[read_proc_net_dev] Error: {e}")
        
        return stats
    
    async def _map_to_containers(self, system_stats: Dict) -> Dict[str, Dict]:
        """
        Map network interfaces to Docker containers
        MVP: Simple container name mapping
        """
        container_stats = {}
        
        if not self.docker_client:
            return {"system": system_stats.get("eth0", {})}
        
        try:
            containers = self.docker_client.containers.list()
            
            for container in containers:
                # Get container stats (simplified for MVP)
                container_name = container.name
                
                # For MVP, we'll aggregate all traffic
                # (proper veth mapping is Phase 2)
                container_stats[container_name] = system_stats.get("eth0", {
                    'rx_bytes': 0,
                    'tx_bytes': 0,
                    'interface': 'eth0'
                })
        
        except Exception as e:
            print(f"[map_to_containers] Error: {e}")
            # Fallback to system-wide stats
            container_stats["system"] = system_stats.get("eth0", {})
        
        return container_stats
    
    def stop(self):
        """Stop the recorder"""
        self.running = False
        print("→ Recorder stopped")
