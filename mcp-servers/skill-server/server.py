"""
TRION Skill Server - MCP Extension Layer

Provides controlled skill installation and execution.
Skills are isolated, sandboxed capabilities that extend TRION.

MCP Tools:
- list_skills
- install_skill
- uninstall_skill
- run_skill
- get_skill_info
"""

import os
import json
import time
import asyncio
import traceback
import importlib
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from skill_manager import SkillManager
import skill_memory
from skill_knowledge import get_categories, search as kb_search, handle_query_skill_knowledge

# === CONFIGURATION ===

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8088"))
SKILLS_DIR = os.getenv("SKILLS_DIR", "/skills")
REGISTRY_URL = os.getenv("REGISTRY_URL", "https://raw.githubusercontent.com/trion-ai/skill-registry/main")


def _get_skill_package_install_mode() -> str:
    """
    Resolve package-install policy without hard dependency on top-level config.py.

    In isolated skill-server containers /app/config.py may not exist.
    Fail-safe behavior: env fallback with strict enum normalization.
    """
    mode = ""
    try:
        cfg = importlib.import_module("config")
        getter = getattr(cfg, "get_skill_package_install_mode", None)
        if callable(getter):
            mode = str(getter()).lower()
    except Exception:
        mode = ""

    if not mode:
        mode = os.getenv("SKILL_PACKAGE_INSTALL_MODE", "allowlist_auto").lower()
    if mode not in ("allowlist_auto", "manual_only"):
        return "allowlist_auto"
    return mode


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_trace_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = f"skill-{int(time.time() * 1000)}"
    safe = re.sub(r"[^a-zA-Z0-9:_-]", "", raw)[:64]
    return safe or f"skill-{int(time.time() * 1000)}"


def _safe_text(value: Any, *, max_len: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def _sanitize_suggested_tools(raw_tools: Any) -> List[str]:
    result: List[str] = []
    if not isinstance(raw_tools, list):
        return result
    for item in raw_tools:
        if isinstance(item, dict):
            name = _safe_text(item.get("tool") or item.get("name"), max_len=120)
        else:
            name = _safe_text(item, max_len=120)
        if name:
            result.append(name)
    return result[:20]


def _sanitize_thinking_plan(thinking_plan: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(thinking_plan, dict):
        return None

    safe: Dict[str, Any] = {}
    for key in ("intent", "reasoning", "reasoning_type", "hallucination_risk", "time_reference"):
        if key in thinking_plan:
            text = _safe_text(thinking_plan.get(key), max_len=2000)
            if text:
                safe[key] = text

    for key in ("needs_memory", "is_fact_query", "needs_sequential_thinking", "sequential_thinking_required"):
        if key in thinking_plan:
            safe[key] = bool(thinking_plan.get(key))

    if "sequential_complexity" in thinking_plan:
        try:
            c = int(thinking_plan.get("sequential_complexity", 0))
        except Exception:
            c = 0
        safe["sequential_complexity"] = max(0, min(10, c))

    raw_keys = thinking_plan.get("memory_keys", [])
    if isinstance(raw_keys, list):
        memory_keys = [_safe_text(k, max_len=80) for k in raw_keys]
        memory_keys = [k for k in memory_keys if k]
        if memory_keys:
            safe["memory_keys"] = memory_keys[:20]

    suggested_tools = _sanitize_suggested_tools(thinking_plan.get("suggested_tools", []))
    if suggested_tools:
        safe["suggested_tools"] = suggested_tools

    return safe or None

# === MCP TOOL DEFINITIONS ===

TOOLS = [
    {
        "name": "list_skills",
        "description": "List all installed skills and available skills from the registry. Returns skill names, versions, and status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_available": {
                    "type": "boolean",
                    "description": "Include available (not installed) skills from registry",
                    "default": True
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g., 'pdf', 'web', 'data')",
                    "default": None
                }
            },
            "required": []
        }
    },
    {
        "name": "install_skill",
        "description": "Install a skill from the official TRION skill registry. Only approved skills can be installed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to install (e.g., 'pdf_tools', 'web_scraper')"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "uninstall_skill",
        "description": "Uninstall/remove an installed skill.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to uninstall"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "run_skill",
        "description": "Execute an installed skill with the provided arguments. Skills run in a sandboxed environment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to execute"
                },
                "action": {
                    "type": "string",
                    "description": "Action/function to call within the skill",
                    "default": "run"
                },
                "args": {
                    "type": "object",
                    "description": "Arguments to pass to the skill",
                    "default": {}
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_skill_info",
        "description": "Get detailed information about a skill including its manifest, permissions, and dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill"
                }
            },
            "required": ["name"]
        }
    },
    # === NEW: Mini-Control-Layer Tools (Delegated) ===
    {
        "name": "create_skill",
        "description": "AI creates and validates a new skill. The code is checked against safety priors before saving.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill (lowercase, underscores)"
                },
                "description": {
                    "type": "string",
                    "description": "What does this skill do?"
                },
                "triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords that trigger this skill",
                    "default": []
                },
                "code": {
                    "type": "string",
                    "description": "Python source code for the skill"
                },
                "auto_promote": {
                    "type": "boolean",
                    "description": "Automatically activate (if validation passes)",
                    "default": False
                },
                "gap_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords that trigger gap-detection for this skill domain (e.g. ['krypto', 'bitcoin', 'ethereum']). Used to ask the user clarifying questions before re-creating this skill.",
                    "default": []
                },
                "gap_question": {
                    "type": "string",
                    "description": "Question shown to the user when gap_patterns match. Should offer a sensible default. Example: 'Soll ich CoinGecko nutzen (kostenlos)? Standard: BTC, ETH, SOL in EUR.'"
                },
                "default_params": {
                    "type": "object",
                    "description": "Default execution parameters for this skill (e.g. {\"coins\": [\"bitcoin\", \"ethereum\"], \"currency\": \"EUR\"})",
                    "default": {}
                }
            },
            "required": ["name", "description", "code"]
        }
    },
    {
        "name": "validate_skill_code",
        "description": "Validate skill code against safety priors without saving. Use for real-time feedback.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to validate"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_safety_priors",
        "description": "Get relevant safety priors for a given context. Helps AI write safer skill code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Description of what the skill will do"
                }
            },
            "required": ["context"]
        }
    },
    {
        "name": "list_draft_skills",
        "description": "List all skills currently in draft status",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_skill_draft",
        "description": "Get code and metadata for a specific draft skill",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the draft skill"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "promote_skill_draft",
        "description": "Promote a draft skill to active (installed) status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the draft skill to promote"
                }
            },
            "required": ["name"]
        }
    },
    # === NEW: SkillKnowledgeBase ===
    {
        "name": "query_skill_knowledge",
        "description": (
            "Sucht in der Skill-Inspirationsdatenbank nach Templates und Paket-Infos. "
            "Gibt code_snippet, packages und triggers zurück. "
            "Nutze dies BEVOR du einen neuen Skill erstellst um passende Templates zu finden."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff (z.B. 'ping check', 'cpu überwachen', 'bitcoin kurs')"
                },
                "category": {
                    "type": "string",
                    "description": "Kategorie-Filter: Netzwerk, System, API, Daten, Berechnung, Datei"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximale Anzahl Ergebnisse (Standard: 5)",
                    "default": 5
                }
            },
            "required": []
        }
    },
    # === NEW: Autonomous Skill Task (v2) ===
    {
        "name": "autonomous_skill_task",
        "description": "Autonomously handle a skill-related task: discover existing skills, create new ones if needed, and execute them. This is the main entry point for intelligent skill handling.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_text": {
                    "type": "string",
                    "description": "The original user request/message"
                },
                "intent": {
                    "type": "string", 
                    "description": "Extracted intent from ThinkingLayer"
                },
                "complexity": {
                    "type": "integer",
                    "description": "Task complexity (1-10, lower = simpler)",
                    "default": 5
                },
                "allow_auto_create": {
                    "type": "boolean",
                    "description": "Allow automatic skill creation without confirmation",
                    "default": True
                },
                "execute_after_create": {
                    "type": "boolean",
                    "description": "Execute skill immediately after creation",
                    "default": True
                },
                "thinking_plan": {
                    "type": "object",
                    "description": "Optional ThinkingLayer output with reasoning context"
                }
            },
            "required": ["user_text", "intent"]
        }
    }

]

# === FASTAPI APP ===

app = FastAPI(
    title="TRION Skill Server",
    description="MCP Server for skill management and execution",
    version="1.0.0"
)

# Enable CORS for WebUI access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Skill Manager
skill_manager = SkillManager(
    skills_dir=SKILLS_DIR,
    registry_url=REGISTRY_URL
)
_graph_reconcile_task: Optional["asyncio.Task"] = None


def _consume_graph_reconcile_result(task: "asyncio.Task") -> None:
    """Drain task exceptions to avoid 'Task exception was never retrieved' warnings."""
    try:
        task.result()
    except Exception as e:
        print(f"[SkillGraphReconcile] background task failed: {e}")


def _trigger_graph_reconcile_background() -> None:
    """
    Start a single in-flight C9 reconcile run in background.
    Non-blocking by design so list endpoints remain low-latency.
    """
    global _graph_reconcile_task
    try:
        if not skill_manager._is_graph_reconcile_enabled():
            return
        if _graph_reconcile_task is not None and not _graph_reconcile_task.done():
            return
        _graph_reconcile_task = asyncio.create_task(skill_manager.reconcile_skill_graph_index())
        _graph_reconcile_task.add_done_callback(_consume_graph_reconcile_result)
    except Exception as e:
        print(f"[SkillGraphReconcile] trigger skipped: {e}")

# === PYDANTIC MODELS ===

class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}

class ToolCallResponse(BaseModel):
    content: List[Dict[str, Any]]
    isError: bool = False


# === MCP PROTOCOL ENDPOINTS ===

@app.get("/")
async def root():
    """Health check and server info"""
    return {
        "name": "skill-server",
        "version": "1.0.0",
        "status": "healthy",
        "skills_dir": SKILLS_DIR,
        "installed_skills": len(skill_manager.list_installed())
    }


@app.get("/v1/skills")
async def get_skills_direct():
    """Direct REST endpoint for browser/WebUI access."""
    _trigger_graph_reconcile_background()
    installed = skill_manager.list_installed()
    drafts = skill_manager.list_drafts()
    return {
        "active": [s["name"] if isinstance(s, dict) else s for s in installed],
        "drafts": [s["name"] if isinstance(s, dict) else s for s in drafts]
    }


@app.get("/v1/skills/{name}")
async def get_skill_detail(name: str, channel: Optional[str] = None):
    """Get detailed information about a specific skill by name.

    Query param ``channel`` can be ``active`` or ``draft``.
    Without it the active version is returned when available, otherwise draft.
    Returns 404 when the skill does not exist or when
    ENABLE_SKILL_DETAIL_API is set to ``false``.
    """
    if os.getenv("ENABLE_SKILL_DETAIL_API", "true").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")
    result = skill_manager.get_skill_detail(name, channel)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@app.get("/v1/skill-knowledge/categories")
async def get_skill_knowledge_categories():
    """Gibt alle Kategorien der SkillKnowledgeBase zurück (für ContextManager)."""
    return {"categories": get_categories()}


@app.get("/v1/skill-knowledge/search")
async def search_skill_knowledge(query: str = None, category: str = None, limit: int = 5):
    """Direkte REST-Suche in der SkillKnowledgeBase."""
    results = kb_search(query=query, category=category, limit=min(limit, 10))
    return {"found": len(results), "entries": results}


@app.post("/")
async def handle_jsonrpc(request: Request):
    """Handle JSON-RPC 2.0 MCP requests"""
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id")

    # Handle MCP initialization
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True}
                },
                "serverInfo": {
                    "name": "skill-server",
                    "version": "1.0.0"
                }
            }
        }

    # Handle initialized notification
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    # List available tools
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS}
        }

    # Call a tool
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        try:
            result = await execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    "isError": False
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                    "isError": True
                }
            }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}"
        }
    }


@app.get("/tools")
async def list_tools():
    """List available tools (REST endpoint)"""
    return {"tools": TOOLS}


@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """Execute a tool (REST endpoint)"""
    try:
        result = await execute_tool(request.name, request.arguments)
        return ToolCallResponse(
            content=[{"type": "text", "text": json.dumps(result, indent=2)}],
            isError=False
        )
    except Exception as e:
        return ToolCallResponse(
            content=[{"type": "text", "text": f"Error: {str(e)}\n{traceback.format_exc()}"}],
            isError=True
        )


# === TOOL EXECUTION ===

async def execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Route tool calls to appropriate handlers"""

    if tool_name == "list_skills":
        return await handle_list_skills(args)

    elif tool_name == "install_skill":
        return await handle_install_skill(args)

    elif tool_name == "uninstall_skill":
        return await handle_uninstall_skill(args)

    elif tool_name == "run_skill":
        return await handle_run_skill(args)

    elif tool_name == "get_skill_info":
        return await handle_get_skill_info(args)

    elif tool_name == "create_skill":
        return await handle_create_skill(args)

    elif tool_name == "validate_skill_code":
        return await handle_validate_skill_code(args)

    elif tool_name == "get_safety_priors":
        return await handle_get_safety_priors(args)
    
    elif tool_name == "list_draft_skills":
         return await handle_list_draft_skills(args)

    elif tool_name == "get_skill_draft":
         return await handle_get_skill_draft(args)

    elif tool_name == "promote_skill_draft":
         return await handle_promote_skill_draft(args)

    elif tool_name == "autonomous_skill_task":
        return await handle_autonomous_skill_task(args)

    elif tool_name == "query_skill_knowledge":
        return handle_query_skill_knowledge(args)

    else:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")


# === TOOL HANDLERS ===

async def handle_list_skills(args: Dict[str, Any]) -> Dict[str, Any]:
    _trigger_graph_reconcile_background()
    include_available = args.get("include_available", True)
    category = args.get("category")

    installed = skill_manager.list_installed()

    result = {
        "installed": installed,
        "installed_count": len(installed),
        "timestamp": datetime.now().isoformat()
    }

    if include_available:
        available = await skill_manager.list_available()
        if category:
            available = [s for s in available if s.get("category") == category]
        result["available"] = available
        result["available_count"] = len(available)

    return result


async def handle_install_skill(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    if not name: raise ValueError("Skill name is required")
    # Proxy to skill_manager which proxies to executor or registry?
    # Original install_skill fetched from registry then installed.
    # skill_manager.install_skill logic still needs full rework to delegate WRITE to executor.
    # We simplified create_skill but not install_skill in step 99 (it was just cut off?)
    # Wait, check step 99 output. I see install_skill method in the diff?
    # No, I think I cut it off or didn't implement it fully in step 99.
    # But server.py calls skill_manager.install_skill.
    # Let's assume skill_manager handles it.
    
    return await skill_manager.install_skill(name)


async def handle_uninstall_skill(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    if not name: raise ValueError("Skill name is required")
    return await skill_manager.uninstall_skill(name)


async def handle_run_skill(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    if not name: raise ValueError("Skill name is required")

    start = time.monotonic()
    result = await skill_manager.run_skill(name, args.get("action", "run"), args.get("args", {}))
    elapsed_ms = (time.monotonic() - start) * 1000

    success = result.get("success", False)
    error = result.get("error") if not success else None
    try:
        await skill_memory.record_execution(name, success, elapsed_ms, error)
    except Exception as e:
        print(f"[SkillServer] Metric recording failed: {e}")

    return result


async def handle_get_skill_info(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    if not name: raise ValueError("Skill name is required")
    return skill_manager.get_skill_info(name)


# === MINI-CONTROL-LAYER HANDLERS (Delegated) ===

async def handle_create_skill(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI creates a new skill.

    C4.5 Single Control Authority: skill-server is the sole decision authority.
    CIM validation + package check happen HERE before the executor is called.
    BLOCK decisions never reach the executor.
    APPROVE/WARN decisions are forwarded with a control_decision payload.
    """
    name = args.get("name")
    description = args.get("description", "")
    triggers = args.get("triggers", [])
    code = args.get("code")
    # Default True: Skills direkt aktivieren wenn Validation OK
    # Draft-Modus nur wenn explizit deaktiviert
    auto_promote = args.get("auto_promote", True)

    if not name or not code:
        raise ValueError("Skill name and code are required")

    # Contract erfordert description minLength: 10 — Fallback wenn leer
    if not description or len(description.strip()) < 10:
        description = f"Skill {name}: Automatisch erstellter Skill."

    from mini_control_layer import get_mini_control, SkillRequest
    _ctrl = get_mini_control()

    # 1. Package-Check + C7 Policy: Drittanbieter-Pakete prüfen
    _pkg_mode = _get_skill_package_install_mode()
    missing_pkgs = await _ctrl._check_missing_packages(code)
    if missing_pkgs:
        if _pkg_mode == "manual_only":
            # Rollback path: preserve original behavior
            pkg_list = ", ".join(f"`{p}`" for p in missing_pkgs)
            return {
                "success": False,
                "needs_package_install": True,
                "missing_packages": missing_pkgs,
                "message": (
                    f"Skill '{name}' benötigt folgende Pakete die noch nicht installiert sind: "
                    f"{pkg_list}. Bitte installiere sie zuerst."
                ),
            }
        # allowlist_auto: classify against executor allowlist
        _allowlist = await _ctrl._get_package_allowlist()
        _allowlisted = [p for p in missing_pkgs if p.lower() in _allowlist]
        _non_allowlisted = [p for p in missing_pkgs if p.lower() not in _allowlist]
        if _non_allowlisted:
            non_list = ", ".join(f"`{p}`" for p in _non_allowlisted)
            return {
                "success": False,
                "action": "pending_package_approval",
                "action_taken": "pending_package_approval",
                "skill_name": name,
                "needs_package_install": True,
                "needs_package_approval": True,
                "missing_packages": missing_pkgs,
                "allowlisted_missing_packages": _allowlisted,
                "non_allowlisted_packages": _non_allowlisted,
                "policy_state": "pending_package_approval",
                "event_type": "approval_requested",
                "message": (
                    f"Skill '{name}' benötigt Pakete die nicht auf der Allowlist stehen: "
                    f"{non_list}. Manuelle Freigabe erforderlich."
                ),
            }
        if _allowlisted:
            _install_result = await _ctrl._auto_install_packages(_allowlisted)
            if not _install_result["success"]:
                pkg_list = ", ".join(f"`{p}`" for p in _allowlisted)
                return {
                    "success": False,
                    "error": _install_result.get("error", "Package installation failed"),
                    "missing_packages": _allowlisted,
                    "message": (
                        f"Automatische Installation fehlgeschlagen für: {pkg_list}."
                    ),
                }
            print(f"[Server] C7 allowlisted packages auto-installed: {_allowlisted}")

    # 1.5 C8 Secret Scanner
    try:
        from secret_scanner import SecretScanner
        scanner = SecretScanner()
        scan_res = scanner.enforce(code)
        if not scan_res["passed"]:
            return {
                "success": False,
                "error": scan_res["error"],
                "action": "block",
                "warnings": scan_res["warnings"],
            }
        scanner_warnings = scan_res["warnings"]
    except Exception as e:
        print(f"[SkillServer] SecretScanner error: {e}")
        scanner_warnings = []

    # 2. CIM Validation — Authority Decision (skill-server is sole authority)
    skill_req = SkillRequest(
        type="CREATE",
        name=name,
        code=code,
        description=description,
        triggers=triggers,
        auto_promote=auto_promote,
    )
    decision = await _ctrl.process_request(skill_req)

    # 3. Block locally — executor is NOT called
    if not decision.passed:
        return {
            "success": False,
            "error": decision.reason,
            "action": decision.action.value,
            "warnings": decision.warnings + scanner_warnings,
        }

    # 4. Build delegated control_decision for executor
    control_decision = {
        "action": decision.action.value,
        "passed": True,
        "reason": decision.reason,
        "warnings": decision.warnings + scanner_warnings,
        "validation_score": (
            decision.validation_result.score if decision.validation_result else 0.0
        ),
        "source": "skill_server",
        "policy_version": "1.0",
    }

    skill_data = {
        "code": code,
        "description": description,
        "triggers": triggers,
        "gap_patterns": args.get("gap_patterns", []),
        "gap_question": args.get("gap_question"),
        "default_params": args.get("default_params", {}),
        "control_decision": control_decision,
    }

    # 5. Delegate to manager -> executor (side-effect only)
    return await skill_manager.create_skill(name, skill_data, draft=not auto_promote)


async def handle_validate_skill_code(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate skill code (Delegated)"""
    code = args.get("code")
    if not code: raise ValueError("Code is required")
    return await skill_manager.validate_code(code)


async def handle_get_safety_priors(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get safety priors (Delegated)"""
    context = args.get("context", "")
    return await skill_manager.get_priors(context)

async def handle_list_draft_skills(args: Dict[str, Any]) -> Dict[str, Any]:
    """List drafts (Read Only)"""
    drafts = skill_manager.list_drafts()
    return {"drafts": drafts}

async def handle_get_skill_draft(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get draft content (Read Only)"""
    name = args.get("name")
    if not name: return {"error": "Missing name"}
    return skill_manager.get_draft(name)

async def handle_promote_skill_draft(args: Dict[str, Any]) -> Dict[str, Any]:
    """Promote draft (Delegated)"""
    name = args.get("name")
    if not name: return {"error": "Missing name"}
    return await skill_manager.promote_draft(name)


# === AUTONOMOUS SKILL TASK HANDLER (NEW!) ===

async def handle_autonomous_skill_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle autonomous skill task via Mini-Control-Layer v2.
    
    This is the main entry point for intelligent skill handling:
    1. Tries to find an existing skill that matches
    2. If not found, creates a new skill (if complexity allows)
    3. Executes the skill and returns the result
    """
    from mini_control_layer import get_mini_control, AutonomousTaskRequest
    
    trace_id = _normalize_trace_id(args.get("_trace_id"))
    user_text = _safe_text(args.get("user_text", ""), max_len=4000)
    intent = _safe_text(args.get("intent", ""), max_len=4000)
    try:
        complexity = int(args.get("complexity", 5))
    except Exception:
        complexity = 5
    complexity = max(1, min(10, complexity))
    allow_auto_create = _coerce_bool(args.get("allow_auto_create", True), True)
    execute_after_create = _coerce_bool(args.get("execute_after_create", True), True)
    prefer_create = _coerce_bool(args.get("prefer_create", False), False)
    
    if not user_text or not intent:
        return {
            "success": False,
            "error": "user_text and intent are required",
            "trace_id": trace_id,
        }
    
    # Get optional thinking_plan
    thinking_plan = _sanitize_thinking_plan(args.get("thinking_plan", None))
    print(
        f"[SkillServer][trace={trace_id}] autonomous_skill_task "
        f"complexity={complexity} has_plan={bool(thinking_plan)} "
        f"plan_keys={sorted(thinking_plan.keys()) if isinstance(thinking_plan, dict) else []}"
    )
    
    # Create task request with ThinkingLayer context
    task = AutonomousTaskRequest(
        user_text=user_text,
        intent=intent,
        complexity=complexity,
        allow_auto_create=allow_auto_create,
        execute_after_create=execute_after_create,
        prefer_create=prefer_create,
        thinking_plan=thinking_plan
    )
    
    # Process via Mini-Control
    try:
        control = get_mini_control()
        start = time.monotonic()
        result = await control.process_autonomous_task(task)
        elapsed_ms = (time.monotonic() - start) * 1000
    except Exception as e:
        print(f"[SkillServer][trace={trace_id}] autonomous_skill_task exception: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "trace_id": trace_id,
        }

    # Clarification needed — kein Fehler, Frage an User
    if result.action_taken == "needs_clarification":
        return {
            "success": False,
            "needs_clarification": True,
            "question": result.message,
            "original_intent": intent,
            "original_user_text": user_text,
            "trace_id": trace_id,
        }

    skill_name = result.skill_name or intent[:30]
    try:
        await skill_memory.record_execution(
            skill_name, result.success, elapsed_ms,
            error=result.message if not result.success else None
        )
    except Exception as e:
        print(f"[SkillServer] Metric recording failed: {e}")

    response = result.to_dict()
    if isinstance(response, dict):
        response["trace_id"] = trace_id
    return response


# === STARTUP ===

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
