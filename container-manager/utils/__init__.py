# utils/__init__.py
"""
Utility Module für Container-Manager.

Enthält:
- docker_client.py: Docker Client Management
- ttyd.py: ttyd Integration (zukünftig)
"""

from .docker_client import get_docker_client, is_docker_available

__all__ = [
    "get_docker_client",
    "is_docker_available",
]
