"""
Container Commander — MCP Tools for KI Integration
═══════════════════════════════════════════════════════
Registers Container Commander functions as MCP tools
so the KI can request containers, execute code, manage snapshots.

KI System Prompt Injection:
  Every container-related response includes the reminder:
  "Sei ressourcenschonend. Beende Container sofort nach Erledigung."

Tool List:
  - request_container    → Deploy a blueprint as container
  - stop_container       → Stop a running container
  - exec_in_container    → Run a command inside container
  - container_logs       → Get logs from container
  - container_stats      → Get CPU/RAM/efficiency score
  - blueprint_list       → List available blueprints
  - blueprint_get        → Get blueprint details
  - blueprint_create     → Create a new blueprint (trusted images only)
  - snapshot_list        → List volume snapshots
  - snapshot_restore     → Restore a snapshot
  - optimize_container   → Adjust resource limits on running container
  - home_write           → Write file to TRION home container
  - home_read            → Read file from TRION home container
  - home_list            → List directory in TRION home container
"""

import logging
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ── KI System Prompt ──────────────────────────────────────

CONTAINER_SYSTEM_PROMPT = """Du hast Zugriff auf Container-Management Tools.
WICHTIG: Sei ressourcenschonend!
- Starte nur Container die du wirklich brauchst
- Beende Container SOFORT nach Erledigung
- Nutze die kleinsten Resource-Limits die ausreichen
- Prüfe container_stats regelmäßig auf Efficiency Score
- Bei efficiency_level "red" → optimize oder stoppen"""


# ── Tool Definitions (MCP Schema) ─────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "request_container",
        "description": "Deploy a container from a blueprint. Returns container_id for use with exec/logs/stats. IMPORTANT: Stop the container when done!",
        "inputSchema": {
            "type": "object",
            "properties": {
                "blueprint_id": {"type": "string", "description": "ID of the blueprint to deploy (use blueprint_list to see available)"},
                "resume_volume": {"type": "string", "description": "Optional: volume name to resume previous workspace"},
            },
            "required": ["blueprint_id"]
        }
    },
    {
        "name": "stop_container",
        "description": "Stop and remove a running container. Always call this when done with a container!",
        "inputSchema": {
            "type": "object",
            "properties": {
                "container_id": {"type": "string", "description": "Container ID to stop"}
            },
            "required": ["container_id"]
        }
    },
    {
        "name": "exec_in_container",
        "description": "Execute a shell command inside a running container. Returns stdout/stderr and exit code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "container_id": {"type": "string", "description": "Container ID"},
                "command": {"type": "string", "description": "Shell command to execute (e.g. 'python3 script.py')"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)", "default": 30}
            },
            "required": ["container_id", "command"]
        }
    },
    {
        "name": "container_logs",
        "description": "Get recent logs from a container.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "container_id": {"type": "string", "description": "Container ID"},
                "tail": {"type": "integer", "description": "Number of lines (default: 100)", "default": 100}
            },
            "required": ["container_id"]
        }
    },
    {
        "name": "container_stats",
        "description": "Get live resource stats (CPU, RAM, network) and efficiency score. Check this regularly! Red efficiency = stop or optimize.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "container_id": {"type": "string", "description": "Container ID"}
            },
            "required": ["container_id"]
        }
    },
    {
        "name": "blueprint_list",
        "description": "List all available container blueprints. Use this to find the right blueprint before requesting a container.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Optional tag filter (e.g. 'python', 'data')"}
            }
        }
    },
    {
        "name": "blueprint_get",
        "description": "Get detailed information about a specific blueprint including Dockerfile, resources, and required secrets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "blueprint_id": {"type": "string", "description": "Blueprint ID to look up"}
            },
            "required": ["blueprint_id"]
        }
    },
    {
        "name": "snapshot_list",
        "description": "List available snapshots for workspace recovery.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "volume_name": {"type": "string", "description": "Optional: filter by volume name"}
            }
        }
    },
    {
        "name": "snapshot_restore",
        "description": "Restore a snapshot into a volume. Use with request_container(resume_volume=...) to continue previous work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Snapshot filename (from snapshot_list)"},
                "target_volume": {"type": "string", "description": "Optional: target volume name (auto-generated if empty)"}
            },
            "required": ["filename"]
        }
    },
    {
        "name": "optimize_container",
        "description": "Adjust resource limits on a running container. Use when efficiency is yellow/red to right-size resources.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "container_id": {"type": "string", "description": "Container ID"},
                "cpu_limit": {"type": "string", "description": "New CPU limit (e.g. '0.5')"},
                "memory_limit": {"type": "string", "description": "New memory limit (e.g. '256m')"}
            },
            "required": ["container_id"]
        }
    },
    {
        "name": "blueprint_create",
        "description": "Create a new container blueprint from a trusted Docker image. Only official and verified images are allowed (ubuntu, python, node, postgres, mongo, redis, nginx, alpine).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Unique blueprint ID (e.g. 'my-python-sandbox')"},
                "image": {"type": "string", "description": "Docker image (e.g. 'python:3.12-slim')"},
                "name": {"type": "string", "description": "Human-readable name"},
                "description": {"type": "string", "description": "What this blueprint is for"},
                "memory_limit": {"type": "string", "description": "Memory limit (e.g. '512m')", "default": "512m"},
                "cpu_limit": {"type": "string", "description": "CPU limit (e.g. '0.5')", "default": "0.5"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for filtering"}
            },
            "required": ["id", "image", "name"]
        }
    },
    {
        "name": "home_write",
        "description": "Write a file to TRION's home container. Creates the home container if not running.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to /home/trion (e.g. 'notes/todo.md')"},
                "content": {"type": "string", "description": "File content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "home_read",
        "description": "Read a file from TRION's home container.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to /home/trion (e.g. 'notes/todo.md')"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "home_list",
        "description": "List contents of a directory in TRION's home container.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to /home/trion (default: root)", "default": "."}
            }
        }
    },
]


# ── Tool Execution ────────────────────────────────────────

def call_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Execute a container commander tool and return the result."""
    
    try:
        if tool_name == "request_container":
            return _tool_request_container(arguments)
        elif tool_name == "stop_container":
            return _tool_stop_container(arguments)
        elif tool_name == "exec_in_container":
            return _tool_exec(arguments)
        elif tool_name == "container_logs":
            return _tool_logs(arguments)
        elif tool_name == "container_stats":
            return _tool_stats(arguments)
        elif tool_name == "blueprint_list":
            return _tool_blueprint_list(arguments)
        elif tool_name == "blueprint_get":
            return _tool_blueprint_get(arguments)
        elif tool_name == "snapshot_list":
            return _tool_snapshot_list(arguments)
        elif tool_name == "snapshot_restore":
            return _tool_snapshot_restore(arguments)
        elif tool_name == "optimize_container":
            return _tool_optimize(arguments)
        elif tool_name == "blueprint_create":
            return _tool_blueprint_create(arguments)
        elif tool_name == "home_write":
            return _tool_home_write(arguments)
        elif tool_name == "home_read":
            return _tool_home_read(arguments)
        elif tool_name == "home_list":
            return _tool_home_list(arguments)
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        logger.error(f"[MCP-Commander] Tool '{tool_name}' failed: {e}")
        return {"error": str(e)}


# ── Tool Implementations ──────────────────────────────────

def _tool_request_container(args: dict) -> dict:
    from .engine import start_container, PendingApprovalError
    try:
        instance = start_container(
            blueprint_id=args["blueprint_id"],
            resume_volume=args.get("resume_volume"),
        )
        return {
            "status": "running",
            "container_id": instance.container_id,
            "name": instance.name,
            "blueprint_id": instance.blueprint_id,
            "volume": instance.volume_name,
            "ttl_seconds": instance.ttl_remaining,
            "hint": "Beende den Container mit stop_container wenn du fertig bist!",
        }
    except PendingApprovalError as e:
        return {
            "status": "pending_approval",
            "approval_id": e.approval_id,
            "reason": e.reason,
            "hint": "Der User muss die Netzwerk-Freigabe erst genehmigen.",
        }
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}


def _tool_stop_container(args: dict) -> dict:
    from .engine import stop_container
    stopped = stop_container(args["container_id"])
    return {
        "stopped": stopped,
        "container_id": args["container_id"],
    }


def _tool_exec(args: dict) -> dict:
    from .engine import exec_in_container
    exit_code, output = exec_in_container(
        args["container_id"],
        args["command"],
        args.get("timeout", 30),
    )
    return {
        "exit_code": exit_code,
        "output": output,
        "container_id": args["container_id"],
    }


def _tool_logs(args: dict) -> dict:
    from .engine import get_container_logs
    logs = get_container_logs(args["container_id"], args.get("tail", 100))
    return {
        "logs": logs,
        "container_id": args["container_id"],
    }


def _tool_stats(args: dict) -> dict:
    from .engine import get_container_stats
    stats = get_container_stats(args["container_id"])
    # Add optimization hint
    eff = stats.get("efficiency", {})
    if eff.get("level") == "red":
        stats["hint"] = "⚠️ Efficiency ist ROT — Container idle? Stoppe ihn oder nutze optimize_container."
    elif eff.get("level") == "yellow":
        stats["hint"] = "Container underutilized. Prüfe ob du kleinere Resources nutzen kannst."
    return stats


def _tool_blueprint_list(args: dict) -> dict:
    from .blueprint_store import list_blueprints
    bps = list_blueprints(tag=args.get("tag"))
    return {
        "blueprints": [
            {
                "id": bp.id,
                "name": bp.name,
                "description": bp.description,
                "icon": bp.icon,
                "network": bp.network.value,
                "tags": bp.tags,
                "resources": {
                    "cpu": bp.resources.cpu_limit,
                    "memory": bp.resources.memory_limit,
                    "timeout": bp.resources.timeout_seconds,
                },
            }
            for bp in bps
        ],
        "count": len(bps),
    }


def _tool_blueprint_get(args: dict) -> dict:
    from .blueprint_store import resolve_blueprint
    bp = resolve_blueprint(args["blueprint_id"])
    if not bp:
        return {"error": f"Blueprint '{args['blueprint_id']}' not found"}
    return bp.model_dump()


def _tool_snapshot_list(args: dict) -> dict:
    from .volumes import list_snapshots
    snaps = list_snapshots(volume_name=args.get("volume_name"))
    return {"snapshots": snaps, "count": len(snaps)}


def _tool_snapshot_restore(args: dict) -> dict:
    from .volumes import restore_snapshot
    vol = restore_snapshot(args["filename"], args.get("target_volume"))
    if not vol:
        return {"error": "Restore failed"}
    return {
        "restored": True,
        "volume": vol,
        "hint": "Nutze request_container(blueprint_id=..., resume_volume='" + vol + "') um den Workspace fortzusetzen.",
    }


def _tool_optimize(args: dict) -> dict:
    """Adjust resource limits on a running container via Docker update."""
    from .engine import get_client, _parse_memory
    client = get_client()
    container_id = args["container_id"]

    try:
        container = client.containers.get(container_id)
        update_kwargs = {}

        if args.get("cpu_limit"):
            cpu = float(args["cpu_limit"])
            update_kwargs["cpu_quota"] = int(cpu * 100000)
            update_kwargs["cpu_period"] = 100000

        if args.get("memory_limit"):
            mem = _parse_memory(args["memory_limit"])
            update_kwargs["mem_limit"] = mem
            update_kwargs["memswap_limit"] = mem * 2

        if not update_kwargs:
            return {"error": "No changes specified. Provide cpu_limit and/or memory_limit."}

        container.update(**update_kwargs)

        return {
            "optimized": True,
            "container_id": container_id,
            "new_limits": {
                "cpu": args.get("cpu_limit", "unchanged"),
                "memory": args.get("memory_limit", "unchanged"),
            },
        }
    except Exception as e:
        return {"error": f"Optimize failed: {str(e)}"}


# ── Trusted Image Validation ──────────────────────────────

TRUSTED_IMAGE_PATTERNS = [
    r"^(library/)?(ubuntu|debian|alpine|busybox):",
    r"^(library/)?(python|node|ruby|golang|rust|openjdk):",
    r"^(library/)?(postgres|mysql|mariadb|mongo|redis|memcached):",
    r"^(library/)?(nginx|httpd|traefik|caddy):",
    r"^(library/)?(elasticsearch|kibana|logstash):",
    r"^(library/)?(grafana|prometheus):",
]


def is_trusted_image(image: str) -> bool:
    """Check if an image is from a trusted source (official Docker images)."""
    for pattern in TRUSTED_IMAGE_PATTERNS:
        if re.match(pattern, image.lower()):
            return True
    return False


# ── TRION Home Container ──────────────────────────────────

TRION_HOME_BLUEPRINT_ID = "trion-home"
TRION_HOME_VOLUME = "trion_home_data"
TRION_HOME_PATH = "/home/trion"

_trion_home_container_id = None  # Cached container ID


def _ensure_trion_home() -> str:
    """Ensure TRION home container is running. Returns container_id."""
    global _trion_home_container_id
    from .engine import start_container, list_containers
    from .blueprint_store import get_blueprint, create_blueprint
    from .models import Blueprint, ResourceLimits, MountDef, NetworkMode
    
    # Check if already running
    running = list_containers()
    for c in running:
        if c.blueprint_id == TRION_HOME_BLUEPRINT_ID:
            _trion_home_container_id = c.container_id
            return c.container_id
    
    # Ensure blueprint exists
    bp = get_blueprint(TRION_HOME_BLUEPRINT_ID)
    if not bp:
        logger.info("[TRION Home] Creating trion-home blueprint...")
        bp = Blueprint(
            id=TRION_HOME_BLUEPRINT_ID,
            name="TRION Home Workspace",
            description="TRIONs persistenter Arbeitsbereich für Notizen, Projekte und Experimente",
            image="python:3.12-slim",
            resources=ResourceLimits(memory_limit="512m", cpu_limit="0.5", timeout_seconds=0),  # No timeout
            mounts=[MountDef(host=TRION_HOME_VOLUME, container=TRION_HOME_PATH, type="volume")],
            network=NetworkMode.INTERNAL,
            tags=["system", "persistent", "home"],
            icon="🏠",
        )
        create_blueprint(bp)
    
    # Start container
    instance = start_container(
        blueprint_id=TRION_HOME_BLUEPRINT_ID,
        resume_volume=TRION_HOME_VOLUME,
    )
    _trion_home_container_id = instance.container_id
    
    # Create home directory structure
    from .engine import exec_in_container
    exec_in_container(_trion_home_container_id, f"mkdir -p {TRION_HOME_PATH}/notes {TRION_HOME_PATH}/projects {TRION_HOME_PATH}/scripts {TRION_HOME_PATH}/.config", timeout=10)
    
    return _trion_home_container_id


# ── New Tool Implementations ──────────────────────────────

def _tool_blueprint_create(args: dict) -> dict:
    """Create a new blueprint from a trusted Docker image."""
    from .blueprint_store import create_blueprint, get_blueprint
    from .models import Blueprint, ResourceLimits, NetworkMode
    
    image = args["image"]
    blueprint_id = args["id"]
    
    # Security: Validate trusted image
    if not is_trusted_image(image):
        return {
            "error": f"Image '{image}' is not trusted. Only official Docker images are allowed.",
            "allowed_prefixes": ["ubuntu:", "python:", "node:", "postgres:", "mongo:", "redis:", "nginx:", "alpine:"],
        }
    
    # Check if blueprint already exists
    existing = get_blueprint(blueprint_id)
    if existing:
        return {"error": f"Blueprint '{blueprint_id}' already exists. Use a different ID."}
    
    # Build blueprint
    bp = Blueprint(
        id=blueprint_id,
        name=args["name"],
        description=args.get("description", ""),
        image=image,
        resources=ResourceLimits(
            memory_limit=args.get("memory_limit", "512m"),
            cpu_limit=args.get("cpu_limit", "0.5"),
        ),
        network=NetworkMode.INTERNAL,
        tags=args.get("tags", []),
        icon="📦",
    )
    
    created = create_blueprint(bp)
    logger.info(f"[Blueprint] Created: {created.id} (image={image})")
    
    return {
        "created": True,
        "blueprint_id": created.id,
        "name": created.name,
        "image": created.image,
        "hint": f"Starte den Container mit: request_container(blueprint_id='{created.id}')",
    }


def _tool_home_write(args: dict) -> dict:
    """Write a file to TRION's home container."""
    from .engine import exec_in_container
    import base64
    
    # Validate required parameters
    if "path" not in args:
        return {"error": "Missing required parameter 'path'. Example: 'notes/todo.md'"}
    if "content" not in args:
        return {"error": "Missing required parameter 'content'. Provide the text to write."}
    
    container_id = _ensure_trion_home()
    path = args["path"].lstrip("/")  # Relative to home
    content = args["content"]
    
    # Encode content to base64 to handle special characters
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    
    # Create parent directories and write file
    full_path = f"{TRION_HOME_PATH}/{path}"
    # Get parent directory
    if "/" in path:
        parent_dir = f"{TRION_HOME_PATH}/{'/'.join(path.split('/')[:-1])}"
    else:
        parent_dir = TRION_HOME_PATH
    
    exit_code, output = exec_in_container(
        container_id,
        f"sh -c \"mkdir -p '{parent_dir}' && echo '{encoded}' | base64 -d > '{full_path}'\"",
        timeout=10
    )
    
    if exit_code != 0:
        return {"error": f"Write failed: {output}"}
    
    return {
        "written": True,
        "path": path,
        "size": len(content),
        "container_id": container_id,
    }


def _tool_home_read(args: dict) -> dict:
    """Read a file from TRION's home container."""
    from .engine import exec_in_container
    
    # Validate required parameters
    if "path" not in args:
        return {"error": "Missing required parameter 'path'. Example: 'notes/todo.md'"}
    
    container_id = _ensure_trion_home()
    path = args["path"].lstrip("/")
    full_path = f"{TRION_HOME_PATH}/{path}"
    
    exit_code, output = exec_in_container(
        container_id,
        f"sh -c \"cat '{full_path}'\"",
        timeout=10
    )
    
    if exit_code != 0:
        return {"error": f"Read failed: {output}", "path": path}
    
    return {
        "content": output,
        "path": path,
        "container_id": container_id,
    }


def _tool_home_list(args: dict) -> dict:
    """List contents of a directory in TRION's home container."""
    from .engine import exec_in_container
    
    container_id = _ensure_trion_home()
    path = args.get("path", ".").lstrip("/")
    full_path = f"{TRION_HOME_PATH}/{path}" if path and path != "." else TRION_HOME_PATH
    
    exit_code, output = exec_in_container(
        container_id,
        f"sh -c \"ls -la '{full_path}'\"",
        timeout=10
    )
    
    if exit_code != 0:
        return {"error": f"List failed: {output}", "path": path}
    
    return {
        "listing": output,
        "path": path,
        "container_id": container_id,
    }


# ── Registration Helper ───────────────────────────────────

def get_tool_definitions() -> List[Dict]:
    """Return all tool definitions for MCP registration."""
    return TOOL_DEFINITIONS


def get_system_prompt() -> str:
    """Return the system prompt that should be injected when containers are active."""
    return CONTAINER_SYSTEM_PROMPT
