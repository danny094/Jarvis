# containers/__init__.py
"""
Container Management Module.

Zentrale Imports für Container-Verwaltung.
"""

import os
import sys

# ============================================================
# PATH SETUP für Docker & lokale Entwicklung
# ============================================================

# Aktuelles Verzeichnis = containers/
_current_dir = os.path.dirname(os.path.abspath(__file__))
# Parent = container-manager/
_parent_dir = os.path.dirname(_current_dir)

# Beide zum Pfad hinzufügen für zuverlässige Imports
for _path in [_parent_dir, _current_dir]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ============================================================
# IMPORTS mit Fallback
# ============================================================

try:
    # Versuche relative imports (Standard für Packages)
    from .registry import (
        load_registry,
        get_container_config,
        is_container_allowed,
        list_containers,
        get_image_name,
        get_build_context,
    )
    from .tracking import (
        ContainerTracker,
        TrackedContainer,
        tracker,
        track_container,
        untrack_container,
        update_container_activity,
        get_container_session,
        is_container_tracked,
        get_tracked_containers,
        get_user_sandbox,
        set_user_sandbox,
        is_user_sandbox_active,
    )
    from .executor import (
        CodeExecutor,
        ExecutionResult,
        ResourceLimits,
        execute_code_in_container,
    )
    from .lifecycle import (
        ContainerLifecycle,
        get_lifecycle,
        start_container,
        stop_container,
        cleanup_all_containers,
    )
except ImportError as e:
    # Fallback: Absolute imports (für Docker oder wenn als Script ausgeführt)
    print(f"[containers/__init__.py] Relative import failed: {e}, trying absolute...")
    
    from containers.registry import (
        load_registry,
        get_container_config,
        is_container_allowed,
        list_containers,
        get_image_name,
        get_build_context,
    )
    from containers.tracking import (
        ContainerTracker,
        TrackedContainer,
        tracker,
        track_container,
        untrack_container,
        update_container_activity,
        get_container_session,
        is_container_tracked,
        get_tracked_containers,
        get_user_sandbox,
        set_user_sandbox,
        is_user_sandbox_active,
    )
    from containers.executor import (
        CodeExecutor,
        ExecutionResult,
        ResourceLimits,
        execute_code_in_container,
    )
    from containers.lifecycle import (
        ContainerLifecycle,
        get_lifecycle,
        start_container,
        stop_container,
        cleanup_all_containers,
    )

__all__ = [
    # Registry
    "load_registry",
    "get_container_config",
    "is_container_allowed",
    "list_containers",
    "get_image_name",
    "get_build_context",
    # Tracking
    "ContainerTracker",
    "TrackedContainer",
    "tracker",
    "track_container",
    "untrack_container",
    "update_container_activity",
    "get_container_session",
    "is_container_tracked",
    "get_tracked_containers",
    "get_user_sandbox",
    "set_user_sandbox",
    "is_user_sandbox_active",
    # Executor
    "CodeExecutor",
    "ExecutionResult",
    "ResourceLimits",
    "execute_code_in_container",
    # Lifecycle
    "ContainerLifecycle",
    "get_lifecycle",
    "start_container",
    "stop_container",
    "cleanup_all_containers",
]
