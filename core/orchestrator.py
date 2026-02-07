"""
PipelineOrchestrator: Manages the 3-Layer execution pipeline

Responsibilities:
- Orchestrate Thinking -> Control -> Output layers
- Handle streaming logic
- Manage chunking for large documents
- Intent confirmation integration

Created by: Claude 2 (Parallel Development)
Date: 2026-02-05
Part of: CoreBridge Refactoring Phase 1
"""

import json
import threading
from datetime import datetime
from typing import AsyncGenerator, Tuple, Dict, Any, Optional, List

from core.models import CoreChatRequest, CoreChatResponse
from core.context_manager import ContextManager, ContextResult
from core.layers.thinking import ThinkingLayer
from core.layers.control import ControlLayer
from core.layers.output import OutputLayer
from core.tool_selector import ToolSelector
from config import (
    OLLAMA_BASE,
    ENABLE_CONTROL_LAYER,
    SKIP_CONTROL_ON_LOW_RISK,
    ENABLE_CHUNKING,
    CHUNKING_THRESHOLD,
)
from utils.logger import log_info, log_warn, log_error, log_debug
from mcp.client import (
    autosave_assistant,
    call_tool,
)
from mcp.hub import get_hub
from core.sequential_registry import get_registry

# Intent System (optional)
try:
    from core.intent_models import SkillCreationIntent, IntentState, IntentOrigin
    from core.intent_store import get_intent_store
    INTENT_SYSTEM_AVAILABLE = True
except ImportError:
    INTENT_SYSTEM_AVAILABLE = False
    log_warn("[Orchestrator] Intent System not available")

# CIM Policy Engine (optional)
try:
    from intelligence_modules.cim_policy.cim_policy_engine import (
        process_cim, ActionType, CIMDecision
    )
    CIM_AVAILABLE = True
except ImportError:
    CIM_AVAILABLE = False


class PipelineOrchestrator:
    """
    Orchestrates the 3-Layer Pipeline:
    1. Thinking Layer (DeepSeek - Planning)
    2. Control Layer (Qwen - Verification)
    3. Output Layer (User Model - Generation)
    
    Delegates context retrieval to ContextManager.
    """
    
    def __init__(self, context_manager: ContextManager = None):
        """
        Initialize orchestrator with layers.
        
        Args:
            context_manager: Injected ContextManager (Dependency Injection)
                           If None, creates new instance
        """
        # Context Manager (from Claude 1's work)
        self.context = context_manager or ContextManager()
        
        # Layers
        self.thinking = ThinkingLayer()
        self.control = ControlLayer()
        self.output = OutputLayer()
        self.tool_selector = ToolSelector()
        self.registry = get_registry()
        
        # Inject MCP Hub for Sequential Thinking
        hub = get_hub()
        self.control.set_mcp_hub(hub)
        self.ollama_base = OLLAMA_BASE
        
        log_info("[PipelineOrchestrator] Initialized with 3 layers + ContextManager")

    # ===============================================================
    # SHARED HELPERS
    # ===============================================================

    def _detect_tools_by_keyword(self, user_text: str) -> list:
        """Keyword-based tool detection fallback when Thinking suggests none."""
        user_lower = user_text.lower()
        if any(kw in user_lower for kw in ["skill", "skills", "fähigkeit"]):
            if any(kw in user_lower for kw in ["zeig", "list", "welche", "hast du", "installiert", "verfügbar"]):
                return ["list_skills"]
            elif any(kw in user_lower for kw in ["erstell", "create", "bau", "mach"]):
                return ["autonomous_skill_task"]
        elif any(kw in user_lower for kw in ["erinnerst du", "weißt du noch", "was weißt du über"]):
            return ["memory_graph_search"]
        elif any(kw in user_lower for kw in ["merk dir", "speicher", "remember"]):
            return ["memory_fact_save"]
        # Container Commander — Blueprint listing
        elif any(kw in user_lower for kw in ["blueprint", "blueprints", "container-typ", "container typen"]):
            return ["blueprint_list"]
        elif any(kw in user_lower for kw in ["welche container", "verfügbare container", "was für container", "container liste", "welche sandbox", "verfügbare sandbox"]):
            return ["blueprint_list"]
        # Container Commander — Start/Deploy
        elif any(kw in user_lower for kw in [
            "starte container", "start container", "deploy container", "container starten",
            "starte einen", "deploy blueprint", "brauche sandbox", "brauche container",
            "python container", "node container", "python sandbox", "node sandbox",
            "starte python", "starte node", "starte sandbox"
        ]):
            return ["request_container"]
        # Container Commander — Stop
        elif any(kw in user_lower for kw in ["stoppe container", "stop container", "container stoppen", "beende container", "container beenden"]):
            return ["stop_container"]
        # Container Commander — Stats
        elif any(kw in user_lower for kw in ["container stats", "container status", "container auslastung", "container efficiency"]):
            return ["container_stats"]
        # Container Commander — Logs
        elif any(kw in user_lower for kw in ["container log", "container logs", "container ausgabe"]):
            return ["container_logs"]
        # Container Commander — Snapshots
        elif any(kw in user_lower for kw in ["snapshot", "snapshots", "snapshot list", "volume backup"]):
            return ["snapshot_list"]
        # Container Commander — Code execution (triggers deploy + exec chain)
        elif any(kw in user_lower for kw in [
            "berechne", "berechnung", "rechne", "ausführen", "execute",
            "führe aus", "run code", "code ausführen", "programmier",
            "fibonacci", "fakultät", "führe code", "code schreiben und ausführen"
        ]):
            return ["request_container", "exec_in_container"]
        return []

    def _build_tool_args(self, tool_name: str, user_text: str) -> dict:
        """Build tool arguments from user text (simple heuristic)."""
        if tool_name == "run_skill":
            return {"skill_name": user_text.strip(), "arguments": {}}
        elif tool_name == "get_skill_info":
            return {"skill_name": user_text.strip()}
        elif tool_name == "create_skill":
            return {"description": user_text.strip()}
        elif tool_name == "autonomous_skill_task":
            return {"task_description": user_text.strip()}
        elif tool_name in ("memory_search", "memory_graph_search"):
            return {"query": user_text.strip()}
        elif tool_name in ("memory_save", "memory_fact_save"):
            return {
                "conversation_id": "auto",
                "role": "user",
                "content": user_text.strip(),
            }
        # Container Commander
        elif tool_name == "blueprint_list":
            tag = ""
            for t in ["python", "node", "database", "latex", "web"]:
                if t in user_text.lower():
                    tag = t
                    break
            return {"tag": tag} if tag else {}
        elif tool_name == "request_container":
            # Detect which blueprint from user text
            user_lower = user_text.lower()
            if any(kw in user_lower for kw in ["python", "pandas", "numpy", "berechn", "fibonacci", "fakultät"]):
                return {"blueprint_id": "python-sandbox"}
            elif any(kw in user_lower for kw in ["node", "javascript", "js", "npm"]):
                return {"blueprint_id": "node-sandbox"}
            elif any(kw in user_lower for kw in ["datenbank", "database", "sql", "sqlite", "postgres"]):
                return {"blueprint_id": "db-sandbox"}
            elif any(kw in user_lower for kw in ["latex", "pdf", "dokument"]):
                return {"blueprint_id": "latex-builder"}
            elif any(kw in user_lower for kw in ["scrape", "web", "crawl"]):
                return {"blueprint_id": "web-scraper"}
            return {"blueprint_id": "python-sandbox"}  # Default
        elif tool_name == "exec_in_container":
            # Build a meaningful python command from user intent
            user_lower = user_text.lower()
            cmd = "python3 -c 'print(42)'"
            if "fibonacci" in user_lower:
                n = 20
                for w in user_text.split():
                    try:
                        n = int(w)
                        break
                    except ValueError:
                        pass
                cmd = "python3 -c 'a,b=0,1\nfor _ in range(" + str(n) + "):\n print(a)\n a,b=b,a+b'"
            elif "fakult" in user_lower or "factorial" in user_lower:
                n = 100
                for w in user_text.split():
                    try:
                        n = int(w)
                        break
                    except ValueError:
                        pass
                cmd = "python3 -c 'import math; print(math.factorial(" + str(n) + "))'"
            elif "primzahl" in user_lower or "prime" in user_lower:
                cmd = "python3 -c 'primes=[i for i in range(2,100) if all(i%j for j in range(2,i))]; print(primes)'"
            return {"container_id": "PENDING", "command": cmd}
        elif tool_name == "stop_container":
            return {"container_id": "PENDING"}
        elif tool_name == "container_stats":
            return {"container_id": "PENDING"}
        elif tool_name == "container_logs":
            return {"container_id": "PENDING", "tail": 50}
        # TRION Home Tools (Heuristic Fix)
        elif tool_name == "home_write":
            import time
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            # Try to extract a filename if provided, otherwise default
            path = f"notes/note_{timestamp}.md"
            content = user_text.strip()
            
            # Simple extraction for "path='foo'" or similar pattern provided by user text
            import re
            path_match = re.search(r"path=['\"]?([^'\"]+)['\"]?", user_text)
            if path_match:
                path = path_match.group(1)
                
            return {
                "path": path,
                "content": content
            }
        elif tool_name == "home_read":
            # Default to most recent note if not specified
            path = "notes"
            if "notes" in user_text:
                for w in user_text.split():
                    if "notes/" in w:
                        path = w.strip(".,;\"'")
                        break
            elif "project" in user_text:
                path = "projects"
            elif "script" in user_text:
                path = "scripts"
            elif "config" in user_text:
                path = ".config"
                
            return {"path": path}
        elif tool_name == "home_list":
            path = "."
            if "notes" in user_text: path = "notes"
            elif "projects" in user_text: path = "projects"
            elif "scripts" in user_text: path = "scripts"
            elif "config" in user_text: path = ".config"
            return {"path": path}
        return {}

    def _execute_tools_sync(self, suggested_tools: list, user_text: str) -> str:
        """Execute tools and return combined context string."""
        tool_context = ""
        tool_hub = get_hub()
        tool_hub.initialize()
        
        # Track container_id from request_container for chained calls
        _last_container_id = None

        for tool_name in suggested_tools:
            try:
                tool_args = self._build_tool_args(tool_name, user_text)
                # Chain: inject container_id from previous request_container
                if _last_container_id and tool_args.get("container_id") == "PENDING":
                    tool_args["container_id"] = _last_container_id
                elif tool_args.get("container_id") == "PENDING":
                    log_info(f"[Orchestrator] Skipping {tool_name} - no container_id yet")
                    continue

                # ── Container Verify-Step (Phase 1: fail-only) ──
                if tool_name == "exec_in_container" and tool_args.get("container_id"):
                    cid = tool_args["container_id"]
                    if cid != _last_container_id:  # Skip verify for freshly started containers
                        if not self._verify_container_running(cid):
                            log_warn(f"[Orchestrator-Verify] Container {cid[:12]} NOT running — aborting exec")
                            stop_event = json.dumps({
                                "container_id": cid,
                                "stopped_at": datetime.utcnow().isoformat() + "Z",
                                "reason": "verify_failed",
                            }, ensure_ascii=False)
                            self._save_workspace_entry(
                                "_container_events", stop_event, "container_stopped", "orchestrator"
                            )
                            tool_context += f"\n### VERIFY-FEHLER ({tool_name}): Container {cid[:12]} ist nicht mehr aktiv.\n"
                            continue

                log_info(f"[Orchestrator] Calling tool: {tool_name}({tool_args})")
                result = tool_hub.call_tool(tool_name, tool_args)

                # Track container_id from deploy result
                if tool_name == "request_container" and isinstance(result, dict):
                    _last_container_id = result.get("container_id", "") or result.get("container", {}).get("container_id", "")

                result_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
                if len(result_str) > 3000:
                    result_str = result_str[:3000] + "... (gekürzt)"

                tool_context += f"\n### TOOL-ERGEBNIS ({tool_name}):\n{result_str}\n"
                log_info(f"[Orchestrator] Tool {tool_name} OK: {len(result_str)} chars")

                # ── Container Session Tracking ──
                container_evt = self._build_container_event_content(
                    tool_name, result, user_text, tool_args
                )
                if container_evt:
                    self._save_workspace_entry(
                        "_container_events",
                        container_evt["content"],
                        container_evt["entry_type"],
                        "orchestrator",
                    )
                    log_info(f"[Orchestrator] Container event: {container_evt['entry_type']}")

            except Exception as e:
                log_error(f"[Orchestrator] Tool {tool_name} failed: {e}")
                tool_context += f"\n### TOOL-FEHLER ({tool_name}): {str(e)}\n"

        return tool_context

    def _build_container_event_content(
        self,
        tool_name: str,
        result: dict,
        user_text: str,
        tool_args: dict,
    ) -> Optional[dict]:
        """
        Build a workspace event dict for container lifecycle events.
        Returns None if tool_name is not a container lifecycle tool.
        """
        if tool_name == "request_container" and isinstance(result, dict):
            cid = result.get("container_id", "")
            if result.get("status") == "running" and cid:
                return {
                    "entry_type": "container_started",
                    "content": json.dumps({
                        "container_id": cid,
                        "blueprint": tool_args.get("blueprint_id", "unknown"),
                        "name": result.get("name", ""),
                        "purpose": user_text[:200],
                        "ttl_seconds": result.get("ttl_seconds"),
                        "started_at": datetime.utcnow().isoformat() + "Z",
                    }, ensure_ascii=False),
                }
        elif tool_name == "stop_container" and isinstance(result, dict):
            cid = result.get("container_id", "")
            if result.get("stopped") and cid:
                return {
                    "entry_type": "container_stopped",
                    "content": json.dumps({
                        "container_id": cid,
                        "stopped_at": datetime.utcnow().isoformat() + "Z",
                        "reason": "user_stopped",
                    }, ensure_ascii=False),
                }
        return None

    def _verify_container_running(self, container_id: str) -> bool:
        """
        Phase-1 Verify: Check if a container is actually running via Engine.
        Uses container_stats as a lightweight ping.
        Returns True if container exists and is running, False otherwise.
        Does NOT attempt repair (Phase-1 policy: fail-only).
        """
        try:
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("container_stats", {"container_id": container_id})
            if isinstance(result, dict) and not result.get("error"):
                log_info(f"[Orchestrator-Verify] Container {container_id[:12]} confirmed running")
                return True
            log_warn(f"[Orchestrator-Verify] Container {container_id[:12]} NOT running: {result}")
            return False
        except Exception as e:
            log_warn(f"[Orchestrator-Verify] Check failed for {container_id[:12]}: {e}")
            return False

    def _save_workspace_entry(
        self,
        conversation_id: str,
        content: str,
        entry_type: str = "observation",
        source_layer: str = "thinking"
    ) -> Optional[Dict]:
        """
        Save a workspace entry via MCP (fire-and-forget).
        Returns the event dict to yield, or None on failure.
        """
        try:
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("workspace_save", {
                "conversation_id": conversation_id,
                "content": content,
                "entry_type": entry_type,
                "source_layer": source_layer,
            })
            raw = result.get("structuredContent", result) if isinstance(result, dict) else {}
            entry_id = raw.get("id")
            if entry_id:
                return {
                    "type": "workspace_update",
                    "entry_id": entry_id,
                    "content": content,
                    "entry_type": entry_type,
                    "source_layer": source_layer,
                    "conversation_id": conversation_id,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
        except Exception as e:
            log_error(f"[Orchestrator-Workspace] Save failed: {e}")
        return None

    def _extract_workspace_observations(self, thinking_plan: Dict) -> Optional[str]:
        """Extract noteworthy observations from thinking plan for workspace."""
        parts = []
        intent = thinking_plan.get("intent")
        if intent and intent != "unknown":
            parts.append(f"**Intent:** {intent}")

        memory_keys = thinking_plan.get("memory_keys", [])
        if memory_keys:
            parts.append(f"**Memory keys:** {', '.join(memory_keys)}")

        risk = thinking_plan.get("hallucination_risk", "")
        if risk == "high":
            parts.append(f"**Risk:** High hallucination risk detected")

        needs_seq = thinking_plan.get("needs_sequential_thinking", False)
        if needs_seq:
            parts.append("**Sequential thinking** required")

        if not parts:
            return None
        return "\n".join(parts)

    # ===============================================================
    # INTENT CONFIRMATION
    # ===============================================================
    # ===============================================================
    
    async def _check_pending_confirmation(
        self, 
        user_text: str, 
        conversation_id: str
    ) -> Optional[CoreChatResponse]:
        """Check if user is responding to a pending confirmation."""
        if not INTENT_SYSTEM_AVAILABLE:
            return None
        store = get_intent_store()
        pending = store.get_pending_for_conversation(conversation_id)
        
        if not pending:
            return None
        
        intent = pending[-1]
        text_lower = user_text.lower().strip()
        
        # Positive confirmation
        if text_lower in ["ja", "yes", "ok", "bestaetigen", "mach", "los", "ja bitte", "klar"]:
            intent.confirm()
            try:
                hub = get_hub()
                log_info(f"[Orchestrator-Intent] Using autonomous_skill_task for: {intent.user_text[:50]}...")
                
                task_args = {
                    "user_text": intent.user_text,
                    "intent": intent.reason or intent.skill_name,
                    "complexity": getattr(intent, "complexity", 5),
                    "allow_auto_create": True,
                    "execute_after_create": True
                }
                
                if hasattr(intent, "thinking_plan") and intent.thinking_plan:
                    task_args["thinking_plan"] = intent.thinking_plan
                
                result = hub.call_tool("autonomous_skill_task", task_args)
                
                if isinstance(result, dict):
                    if result.get("success"):
                        intent.mark_executed()
                        store.update_state(intent.id, IntentState.EXECUTED)
                        
                        skill_name = result.get("skill_name", intent.skill_name)
                        exec_result = result.get("execution_result", {})
                        validation_score = result.get("validation_score", 0)
                        
                        log_info(f"[Orchestrator-Intent] Skill {skill_name} created (score: {validation_score})")
                        
                        response_text = f"✅ Skill **{skill_name}** wurde erstellt und ausgeführt!\n\n"
                        response_text += f"**Validation Score:** {validation_score:.0%}\n\n"
                        if exec_result:
                            response_text += f"**Ergebnis:**\n```json\n{json.dumps(exec_result, indent=2, ensure_ascii=False)[:500]}\n```"
                        
                        return CoreChatResponse(
                            model="system",
                            content=response_text,
                            conversation_id=conversation_id
                        )
                    else:
                        error = result.get("error", "Unknown error")
                        log_error(f"[Orchestrator-Intent] autonomous_skill_task failed: {error}")
                        intent.mark_failed()
                        store.update_state(intent.id, IntentState.FAILED)
                        return CoreChatResponse(
                            model="system",
                            content=f"❌ Skill-Erstellung fehlgeschlagen: {error}",
                            conversation_id=conversation_id
                        )
                
                intent.mark_executed()
                store.update_state(intent.id, IntentState.EXECUTED)
                return CoreChatResponse(
                    model="system",
                    content="✅ Skill-Anfrage wurde verarbeitet.",
                    conversation_id=conversation_id
                )
            except Exception as e:
                log_error(f"[Orchestrator-Intent] Create failed: {e}")
                store.update_state(intent.id, IntentState.FAILED)
                return CoreChatResponse(
                    model="system",
                    content=f"❌ Fehler beim Erstellen: {e}",
                    conversation_id=conversation_id
                )
        
        # Negative response
        elif text_lower in ["nein", "no", "abbrechen", "cancel", "stop", "nee"]:
            intent.reject()
            store.update_state(intent.id, IntentState.REJECTED)
            log_info(f"[Orchestrator-Intent] Skill {intent.skill_name} creation rejected")
            return CoreChatResponse(
                model="system",
                content="❌ Skill-Erstellung abgebrochen.",
                conversation_id=conversation_id
            )
        
        return None
    
    # ===============================================================
    # PUBLIC API
    # ===============================================================
    
    async def process(self, request: CoreChatRequest) -> CoreChatResponse:
        """
        Standard (non-streaming) pipeline execution.
        
        Pipeline:
        1. Intent Confirmation Check
        2. Thinking Layer -> Plan
        3. Context Retrieval (via ContextManager)
        4. Control Layer -> Verify
        5. Output Layer -> Generate
        6. Memory Save
        """
        log_info(f"[Orchestrator] Processing request from {request.source_adapter}")
        
        user_text = request.get_last_user_message()
        conversation_id = request.conversation_id
        
        # ===============================================================
        # STEP 1: Intent Confirmation Check
        # ===============================================================
        if INTENT_SYSTEM_AVAILABLE:
            confirmation_result = await self._check_pending_confirmation(
                user_text, conversation_id
            )
            if confirmation_result:
                log_info("[Orchestrator] Returning confirmation result")
                return confirmation_result
        
        # ===============================================================
        # STEP 2: Thinking Layer
        # ===============================================================
        # ===============================================================
        # STEP 1.5: Tool Selector (Layer 0)
        # ===============================================================
        selected_tools = await self.tool_selector.select_tools(user_text)
        
        # ===============================================================
        # STEP 2: Thinking Layer
        # ===============================================================
        thinking_plan = await self.thinking.analyze(user_text, available_tools=selected_tools)
        
        # ===============================================================
        # STEP 3: Context Retrieval (via ContextManager!)
        # ===============================================================
        log_info("[Orchestrator] === CONTEXT RETRIEVAL ===")
        context_result = self.context.get_context(
            query=user_text,
            thinking_plan=thinking_plan,
            conversation_id=conversation_id
        )
        
        retrieved_memory = context_result.memory_data
        if context_result.system_tools:
            retrieved_memory = context_result.system_tools + "\n" + retrieved_memory
        memory_used = context_result.memory_used
        
        log_info(f"[Orchestrator-Context] memory_used={memory_used}, sources={context_result.sources}")
        
        # ===============================================================
        # STEP 4: Control Layer
        # ===============================================================
        verification, verified_plan = await self._execute_control_layer(
            user_text,
            thinking_plan,
            retrieved_memory,
            conversation_id
        )
        
        # Blocked check
        if not verification.get("approved"):
            if thinking_plan.get("hallucination_risk") == "high" and not memory_used:
                log_warn("[Orchestrator] BLOCKED - High hallucination risk without memory")
                return CoreChatResponse(
                    model=request.model,
                    content="Das kann ich leider nicht beantworten, da ich diese Information nicht gespeichert habe.",
                    conversation_id=conversation_id,
                    done=True,
                    done_reason="blocked",
                    memory_used=False,
                )
        
        # Extra memory lookup if Control corrected
        if verification.get("corrections", {}).get("memory_keys"):
            extra_keys = verification["corrections"]["memory_keys"]
            for key in extra_keys:
                if key not in thinking_plan.get("memory_keys", []):
                    log_info(f"[Orchestrator-Control] Extra memory lookup: {key}")
                    # Use ContextManager for extra lookup
                    extra_context = self.context.get_context(
                        query=key,
                        thinking_plan={"needs_memory": True, "memory_keys": [key]},
                        conversation_id=conversation_id
                    )
                    if extra_context.memory_used:
                        retrieved_memory += extra_context.memory_data
                        memory_used = True
        
        # ===============================================================
        # STEP 4.5: TOOL EXECUTION
        # ===============================================================
        suggested_tools = verified_plan.get("suggested_tools", [])
        
        # Validate: filter out hallucinated tool names
        if suggested_tools:
            tool_hub_v = get_hub()
            tool_hub_v.initialize()
            valid_tools = [t for t in suggested_tools if tool_hub_v.get_mcp_for_tool(t)]
            if valid_tools != suggested_tools:
                log_info(f"[Orchestrator] Filtered invalid tools: {set(suggested_tools) - set(valid_tools)}")
            suggested_tools = valid_tools
        
        if not suggested_tools:
            suggested_tools = self._detect_tools_by_keyword(user_text)
            if suggested_tools:
                log_info(f"[Orchestrator] Fallback tool detection: {suggested_tools}")

        tool_context = ""
        if suggested_tools:
            log_info(f"[Orchestrator] === TOOL EXECUTION: {suggested_tools} ===")
            tool_context = self._execute_tools_sync(suggested_tools, user_text)

        if tool_context:
            retrieved_memory += tool_context
            verified_plan["_tool_results"] = tool_context
        
        # ===============================================================
        # STEP 5: Output Layer
        # ===============================================================
        needs_memory = thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query")
        high_risk = thinking_plan.get("hallucination_risk") == "high"
        memory_required_but_missing = needs_memory and high_risk and not memory_used
        
        answer = await self._execute_output_layer(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=retrieved_memory,
            model=request.model,
            chat_history=request.messages,
            memory_required_but_missing=memory_required_but_missing
        )
        
        # ===============================================================
        # STEP 6: Memory Save
        # ===============================================================
        self._save_memory(conversation_id, verified_plan, answer)
        
        # ===============================================================
        # RETURN
        # ===============================================================
        return CoreChatResponse(
            model=request.model,
            content=answer,
            conversation_id=conversation_id,
            done=True,
            done_reason="stop",
            memory_used=memory_used,
            validation_passed=True,
        )
    
    # ===============================================================
    # STREAMING PIPELINE
    # ===============================================================

    async def process_stream_with_events(
        self,
        request: CoreChatRequest
    ) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
        """
        Phase 3: Native event-rich streaming (ported from bridge.py).
        
        Features:
        - Intent confirmation check
        - Chunking for large inputs
        - Live streaming thinking
        - Sequential thinking events  
        - Control layer with skill confirmation
        - Output streaming
        - Memory save
        """
        import time
        from config import ENABLE_CONTROL_LAYER, SKIP_CONTROL_ON_LOW_RISK
        
        _t0 = time.time()
        log_info("[Orchestrator] process_stream_with_events (Phase 3)")
        
        user_text = request.get_last_user_message()
        conversation_id = request.conversation_id
        
        # ═══════════════════════════════════════════════════
        # STEP 0: INTENT CONFIRMATION
        # ═══════════════════════════════════════════════════
        if INTENT_SYSTEM_AVAILABLE:
            try:
                result = await self._check_pending_confirmation(user_text, conversation_id)
                if result:
                    yield (result.content, False, {"type": "content"})
                    yield ("", True, {"done_reason": "confirmation_executed"})
                    return
            except Exception as e:
                log_info(f"[Orchestrator] Intent check skipped: {e}")
        
        # ═══════════════════════════════════════════════════
        # STEP 0.5: CHUNKING (large inputs)
        # ═══════════════════════════════════════════════════
        chunking_context = None
        
        try:
            from utils.chunker import needs_chunking, count_tokens
            if ENABLE_CHUNKING and needs_chunking(user_text, CHUNKING_THRESHOLD):
                log_info(f"[Orchestrator] Chunking: {count_tokens(user_text)} tokens")
                async for event in self._process_chunked_stream(user_text, conversation_id, request):
                    chunk_text, is_done, metadata = event
                    yield event
                    if metadata.get("type") == "chunking_done":
                        chunking_context = {
                            "aggregated_summary": metadata.get("aggregated_summary", ""),
                            "thinking_result": metadata.get("thinking_result", {}),
                        }
        except Exception as e:
            log_info(f"[Orchestrator] Chunking skipped: {e}")
        
        # ═══════════════════════════════════════════════════
        # STEP 1: THINKING LAYER (STREAMING)
        # ═══════════════════════════════════════════════════
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 1 THINKING")
        
        thinking_plan = {}
        
        if chunking_context and chunking_context.get("thinking_result"):
            log_info("[Orchestrator] Layer 1 SKIPPED (using chunking result)")
            thinking_plan = chunking_context["thinking_result"]
            yield ("", False, {"type": "thinking_done", "thinking": thinking_plan, "source": "chunking"})
        else:
            log_info("[Orchestrator] === LAYER 1: THINKING (STREAMING) ===")
            
            # Layer 0: Tool Selection
            selected_tools = await self.tool_selector.select_tools(user_text)
            if selected_tools:
                yield ("", False, {"type": "tool_selection", "tools": selected_tools})

            async for chunk, is_done, plan in self.thinking.analyze_stream(user_text, available_tools=selected_tools):
                if not is_done:
                    yield ("", False, {"type": "thinking_stream", "thinking_chunk": chunk})
                else:
                    thinking_plan = plan
                    yield ("", False, {
                        "type": "thinking_done",
                        "thinking": {
                            "intent": thinking_plan.get("intent", "unknown"),
                            "needs_memory": thinking_plan.get("needs_memory", False),
                            "memory_keys": thinking_plan.get("memory_keys", []),
                            "hallucination_risk": thinking_plan.get("hallucination_risk", "medium"),
                            "needs_sequential_thinking": thinking_plan.get("needs_sequential_thinking", False),
                        }
                    })
        
        # ═══════════════════════════════════════════════════
        # WORKSPACE: Save thinking observations
        # ═══════════════════════════════════════════════════
        obs_text = self._extract_workspace_observations(thinking_plan)
        if obs_text:
            ws_event = self._save_workspace_entry(
                conversation_id, obs_text, "observation", "thinking"
            )
            if ws_event:
                yield ("", False, ws_event)

        # ═══════════════════════════════════════════════════
        # STEP 1.5: CONTEXT RETRIEVAL (ContextManager API)
        # ═══════════════════════════════════════════════════
        context_result = self.context.get_context(
            query=user_text,
            thinking_plan=thinking_plan,
            conversation_id=conversation_id
        )
        memory_context = context_result.memory_data
        tools_context = context_result.system_tools
        full_context = memory_context + tools_context
        memory_used = context_result.memory_used
        
        # ═══════════════════════════════════════════════════
        # STEP 1.75: SEQUENTIAL THINKING (STREAMING)
        # ═══════════════════════════════════════════════════
        if thinking_plan.get('needs_sequential_thinking') or thinking_plan.get('sequential_thinking_required'):
            log_info("[Orchestrator] Sequential Thinking detected")
            try:
                sequential_input = user_text
                if chunking_context and chunking_context.get("aggregated_summary"):
                    sequential_input = f"User: {thinking_plan.get('intent')}\n{chunking_context['aggregated_summary']}"
                async for event in self.control._check_sequential_thinking_stream(
                    user_text=sequential_input,
                    thinking_plan=thinking_plan
                ):
                    yield ("", False, event)
            except Exception as e:
                log_info(f"[Orchestrator] Sequential error: {e}")
        
        # ═══════════════════════════════════════════════════
        # STEP 2: CONTROL LAYER
        # ═══════════════════════════════════════════════════
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 2 CONTROL")
        
        skip_control = not ENABLE_CONTROL_LAYER
        if not skip_control and SKIP_CONTROL_ON_LOW_RISK and thinking_plan.get("hallucination_risk") == "low":
            skill_keywords = ["skill", "erstelle", "create", "programmier"]
            if not any(kw in user_text.lower() for kw in skill_keywords):
                skip_control = True
                log_info("[Orchestrator] Layer 2 SKIPPED (low-risk)")
        
        if skip_control:
            verified_plan = thinking_plan.copy()
            verified_plan["_skipped"] = True
            verification = {"approved": True}
        else:
            log_info("[Orchestrator] === LAYER 2: CONTROL ===")
            verification = await self.control.verify(user_text, thinking_plan, full_context)
            verified_plan = self.control.apply_corrections(thinking_plan, verification)
        
        log_info(f"[Orchestrator] Control approved={verification.get('approved')}")
        yield ("", False, {"type": "control", "approved": verification.get("approved", True), "skipped": skip_control})

        # WORKSPACE: Save control layer decision if not skipped
        if not skip_control:
            corrections = verification.get("corrections", {})
            warnings = verification.get("warnings", [])
            if corrections or warnings:
                ctrl_parts = []
                if warnings:
                    ctrl_parts.append(f"**Warnings:** {', '.join(str(w) for w in warnings)}")
                if corrections:
                    ctrl_parts.append(f"**Corrections:** {json.dumps(corrections, ensure_ascii=False)[:300]}")
                ws_event = self._save_workspace_entry(
                    conversation_id, "\n".join(ctrl_parts), "observation", "control"
                )
                if ws_event:
                    yield ("", False, ws_event)

        # Skill confirmation
        if verified_plan.get("_pending_intent"):
            pending = verified_plan["_pending_intent"]
            yield (f"🛠️ Möchtest du den Skill **{pending.get('skill_name')}** erstellen? (Ja/Nein)", False, {"type": "content"})
            yield ("", True, {"type": "confirmation_pending", "intent_id": pending.get("id")})
            return
        
        if not verification.get("approved", True):
            yield (verification.get("message", "Nicht genehmigt"), True, {"type": "error"})
            return
        
        # ═══════════════════════════════════════════════════
        # STEP 2.5: TOOL EXECUTION
        # ═══════════════════════════════════════════════════
        tool_context = ""
        suggested_tools = verified_plan.get("suggested_tools", [])
        
        # Validate: filter out hallucinated tool names
        if suggested_tools:
            tool_hub_v = get_hub()
            tool_hub_v.initialize()
            valid_tools = [t for t in suggested_tools if tool_hub_v.get_mcp_for_tool(t)]
            if valid_tools != suggested_tools:
                log_info(f"[Orchestrator] Filtered invalid tools: {set(suggested_tools) - set(valid_tools)}")
            suggested_tools = valid_tools
        
        if not suggested_tools:
            suggested_tools = self._detect_tools_by_keyword(user_text)
            if suggested_tools:
                log_info(f"[Orchestrator] Fallback tool detection: {suggested_tools}")

        if suggested_tools:
            log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: TOOL EXECUTION")
            log_info(f"[Orchestrator] === TOOL EXECUTION: {suggested_tools} ===")
            yield ("", False, {"type": "tool_start", "tools": suggested_tools})

            tool_hub = get_hub()
            tool_hub.initialize()
            _last_container_id = None

            for tool_name in suggested_tools:
                try:
                    tool_args = self._build_tool_args(tool_name, user_text)

                    # Chain: inject container_id from previous request_container
                    if _last_container_id and tool_args.get("container_id") == "PENDING":
                        tool_args["container_id"] = _last_container_id
                    elif tool_args.get("container_id") == "PENDING":
                        log_info(f"[Orchestrator] Skipping {tool_name} - no container_id yet")
                        continue

                    # ── Container Verify-Step (Phase 1: fail-only) ──
                    if tool_name == "exec_in_container" and tool_args.get("container_id"):
                        cid = tool_args["container_id"]
                        if cid != _last_container_id:  # Skip verify for freshly started containers
                            if not self._verify_container_running(cid):
                                log_warn(f"[Orchestrator-Verify] Container {cid[:12]} NOT running — aborting exec")
                                stop_event = json.dumps({
                                    "container_id": cid,
                                    "stopped_at": datetime.utcnow().isoformat() + "Z",
                                    "reason": "verify_failed",
                                }, ensure_ascii=False)
                                ws_ev = self._save_workspace_entry(
                                    "_container_events", stop_event, "container_stopped", "orchestrator"
                                )
                                if ws_ev:
                                    yield ("", False, ws_ev)
                                tool_context += f"\n### VERIFY-FEHLER ({tool_name}): Container {cid[:12]} ist nicht mehr aktiv.\n"
                                yield ("", False, {"type": "tool_result", "tool": tool_name, "success": False, "error": "container_not_running"})
                                continue

                    log_info(f"[Orchestrator] Calling tool: {tool_name}({tool_args})")
                    result = tool_hub.call_tool(tool_name, tool_args)
                    
                    # Track container_id from deploy result
                    if tool_name == "request_container" and isinstance(result, dict):
                        _last_container_id = result.get("container_id", "") or result.get("container", {}).get("container_id", "")

                    result_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
                    if len(result_str) > 3000:
                        result_str = result_str[:3000] + "... (gekuerzt)"

                    tool_context += f"\n### TOOL-ERGEBNIS ({tool_name}):\n{result_str}\n"
                    log_info(f"[Orchestrator] Tool {tool_name} OK: {len(result_str)} chars")
                    yield ("", False, {"type": "tool_result", "tool": tool_name, "success": True})

                    # ── Container Session Tracking (stream path) ──
                    container_evt = self._build_container_event_content(
                        tool_name, result, user_text, tool_args
                    )
                    if container_evt:
                        ws_ev = self._save_workspace_entry(
                            "_container_events",
                            container_evt["content"],
                            container_evt["entry_type"],
                            "orchestrator",
                        )
                        if ws_ev:
                            yield ("", False, ws_ev)
                        log_info(f"[Orchestrator] Container event: {container_evt['entry_type']}")

                except Exception as e:
                    log_error(f"[Orchestrator] Tool {tool_name} failed: {e}")
                    tool_context += f"\n### TOOL-FEHLER ({tool_name}): {str(e)}\n"
                    yield ("", False, {"type": "tool_result", "tool": tool_name, "success": False, "error": str(e)})

        if tool_context:
            full_context += tool_context
            verified_plan["_tool_results"] = tool_context

            # WORKSPACE: Save tool execution results as note
            tool_summary = f"**Tools executed:** {', '.join(suggested_tools)}\n\n{tool_context[:500]}"
            ws_event = self._save_workspace_entry(
                conversation_id, tool_summary, "note", "control"
            )
            if ws_event:
                yield ("", False, ws_event)

        # ═══════════════════════════════════════════════════
        # STEP 3: OUTPUT LAYER (STREAMING)
        # ═══════════════════════════════════════════════════
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: LAYER 3 OUTPUT")
        log_info("[Orchestrator] === LAYER 3: OUTPUT ===")
        
        full_response = ""
        first_chunk = True
        
        async for chunk in self.output.generate_stream(user_text=user_text,
            verified_plan=verified_plan,
            memory_data=full_context,
            model=request.model
        ):
            if first_chunk:
                log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: FIRST OUTPUT CHUNK")
                first_chunk = False
            full_response += chunk
            yield (chunk, False, {"type": "content"})
        
        log_info(f"[Orchestrator] Output: {len(full_response)} chars")
        
        # ═══════════════════════════════════════════════════
        # STEP 4: MEMORY SAVE
        # ═══════════════════════════════════════════════════
        self._save_memory(
            conversation_id=conversation_id,
            answer=full_response,
            verified_plan=verified_plan
        )
        
        # ═══════════════════════════════════════════════════
        # DONE
        # ═══════════════════════════════════════════════════
        yield ("", True, {"type": "done", "done_reason": "stop", "memory_used": memory_used, "model": request.model})
        log_info(f"[TIMING] T+{time.time()-_t0:.2f}s: COMPLETE")


    # ===============================================================
    # CHUNKING (moved from bridge.py)
    # ===============================================================

    async def _process_chunked_stream(
        self,
        user_text: str,
        conversation_id: str,
        request: CoreChatRequest
    ) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
        """
        Verarbeitet lange Texte mit MCP document-processor.

        v3 Workflow (MCP-BASED):
        1. Preprocess via MCP (~1 Sek)
        2. Structure Analysis via MCP (~1 Sek)
        3. EIN LLM-Aufruf mit kompakter Summary (~15-20 Sek)
        4. Ergebnis zurueck
        """
        log_info("[Orchestrator-Chunking] v3 MCP-basierte Analyse startet...")

        hub = get_hub()

        # PHASE 1: Preprocessing via MCP
        yield ("", False, {
            "type": "document_analysis_start",
            "message": "Preprocessing document...",
        })

        try:
            preprocess_result = hub.call_tool("preprocess", {
                "text": user_text,
                "add_paragraph_ids": True,
                "normalize_whitespace": True,
                "remove_artifacts": True
            })
            processed_text = preprocess_result.get("text", user_text)
            log_info(f"[Orchestrator-Chunking] Preprocessed: {len(processed_text)} chars")
        except Exception as e:
            log_error(f"[Orchestrator-Chunking] Preprocess failed: {e}, using raw text")
            processed_text = user_text

        # PHASE 2: Structure Analysis via MCP
        yield ("", False, {
            "type": "document_analysis_progress",
            "message": "Analyzing document structure...",
        })

        try:
            structure = hub.call_tool("analyze_structure", {
                "text": processed_text
            })

            log_info(f"[Orchestrator-Chunking] Structure: {structure.get('heading_count', 0)} Headings, "
                    f"{structure.get('code_blocks', 0)} Code-Bloecke, "
                    f"Complexity {structure.get('complexity', 0)}/10")

            compact_summary = self._build_summary_from_structure(structure)

        except Exception as e:
            log_error(f"[Orchestrator-Chunking] Structure analysis failed: {e}")
            structure = {
                "heading_count": 0,
                "code_blocks": 0,
                "complexity": 5,
                "keywords": [],
                "intro": processed_text[:500]
            }
            compact_summary = f"Text ({len(processed_text)} chars)"

        yield ("", False, {
            "type": "document_analysis_done",
            "structure": {
                "total_chars": structure.get("total_chars", len(processed_text)),
                "total_tokens": structure.get("total_tokens", len(processed_text) // 4),
                "total_lines": structure.get("total_lines", processed_text.count('\n')),
                "heading_count": structure.get("heading_count", 0),
                "headings": structure.get("headings", [])[:10],
                "code_blocks": structure.get("code_blocks", 0),
                "code_languages": structure.get("languages", []),
                "keywords": structure.get("keywords", []),
                "estimated_complexity": structure.get("complexity", 5),
            },
            "message": f"Struktur erkannt: {structure.get('heading_count', 0)} Abschnitte, {structure.get('code_blocks', 0)} Code-Bloecke",
        })

        # PHASE 3: EIN LLM-Aufruf mit kompakter Info
        yield ("", False, {
            "type": "thinking_start",
            "message": "Analysiere Inhalt...",
        })

        analysis_prompt = f"""Analysiere folgendes Dokument anhand der Struktur-Uebersicht:

{compact_summary}

Der User hat dieses Dokument gesendet. Was ist sein wahrscheinlicher Intent?
Braucht die Antwort Sequential Thinking (schrittweises Reasoning)?"""

        thinking_result = await self.thinking.analyze(analysis_prompt)

        log_info(f"[Orchestrator-Chunking] ThinkingLayer: intent={thinking_result.get('intent')}, "
                f"needs_sequential={thinking_result.get('needs_sequential_thinking')}")

        yield ("", False, {
            "type": "chunking_done",
            "conversation_id": conversation_id,
            "method": "mcp_v3",
            "aggregated_summary": compact_summary,
            "structure": {
                "headings": structure.get("headings", []),
                "keywords": structure.get("keywords", []),
                "complexity": structure.get("complexity", 5),
            },
            "thinking_result": thinking_result,
            "needs_sequential_any": thinking_result.get('needs_sequential_thinking', False) or thinking_result.get('sequential_thinking_required', False),
            "max_complexity": structure.get("complexity", 5),
        })

    def _build_summary_from_structure(self, structure: Dict) -> str:
        """Build compact summary from MCP structure analysis."""
        lines = []
        lines.append("# Document Overview")
        lines.append(f"- Size: {structure.get('total_chars', 0)} chars, {structure.get('total_tokens', 0)} tokens")
        lines.append(f"- Complexity: {structure.get('complexity', 0)}/10")

        if structure.get('headings'):
            lines.append(f"\n## Structure ({len(structure['headings'])} headings):")
            for h in structure['headings'][:5]:
                lines.append(f"- {h.get('level', 1)*'#'} {h.get('text', '')}")

        if structure.get('keywords'):
            lines.append(f"\n## Keywords: {', '.join(structure['keywords'][:10])}")

        if structure.get('intro'):
            lines.append(f"\n## Intro:\n{structure['intro'][:300]}...")

        return '\n'.join(lines)

    # ===============================================================
    # PRIVATE PIPELINE STEPS
    # ===============================================================

    async def _execute_thinking_layer(self, user_text: str) -> Dict:
        """Execute Thinking Layer (Step 1)."""
        log_info("[Orchestrator] === LAYER 1: THINKING ===")
        thinking_plan = await self.thinking.analyze(user_text)
        
        log_info(f"[Orchestrator-Thinking] intent={thinking_plan.get('intent')}")
        log_info(f"[Orchestrator-Thinking] needs_memory={thinking_plan.get('needs_memory')}")
        log_info(f"[Orchestrator-Thinking] memory_keys={thinking_plan.get('memory_keys')}")
        log_info(f"[Orchestrator-Thinking] hallucination_risk={thinking_plan.get('hallucination_risk')}")
        
        return thinking_plan
    
    async def _execute_control_layer(
        self,
        user_text: str,
        thinking_plan: Dict,
        memory_data: str,
        conversation_id: str
    ) -> Tuple[Dict, Dict]:
        """Execute Control Layer (Step 2)."""
        
        # Skip logic
        skip_control = False
        hallucination_risk = thinking_plan.get("hallucination_risk", "medium")
        
        if not ENABLE_CONTROL_LAYER:
            skip_control = True
            log_info("[Orchestrator] === LAYER 2: CONTROL === DISABLED (config)")
        elif SKIP_CONTROL_ON_LOW_RISK and hallucination_risk == "low":
            skip_control = True
            log_info("[Orchestrator] === LAYER 2: CONTROL === SKIPPED (low-risk)")
        
        # Sequential Thinking Check (BEFORE Control!)
        if thinking_plan.get("needs_sequential_thinking") or thinking_plan.get("sequential_thinking_required"):
            log_info("[Orchestrator] Sequential Thinking detected - executing BEFORE Control...")
            sequential_result = await self.control._check_sequential_thinking(
                user_text=user_text,
                thinking_plan=thinking_plan
            )
            if sequential_result:
                thinking_plan["_sequential_result"] = sequential_result
                log_info(f"[Orchestrator] Sequential completed: {len(sequential_result.get('steps', []))} steps")
        
        if skip_control:
            verified_plan = thinking_plan.copy()
            verified_plan["_verified"] = False
            verified_plan["_skipped"] = True
            verified_plan["_final_instruction"] = ""
            verified_plan["_warnings"] = []
            verification = {"approved": True, "corrections": {}}
        else:
            log_info("[Orchestrator] === LAYER 2: CONTROL ===")
            verification = await self.control.verify(
                user_text,
                thinking_plan,
                memory_data
            )
            log_info(f"[Orchestrator-Control] approved={verification.get('approved')}")
            log_info(f"[Orchestrator-Control] warnings={verification.get('warnings', [])}")
            # Apply corrections
            verified_plan = self.control.apply_corrections(thinking_plan, verification)
            # Skill Confirmation Handling
            if verification.get("_needs_skill_confirmation") and INTENT_SYSTEM_AVAILABLE:
                skill_name = verification.get("_skill_name", "unknown")
                log_info(f"[Orchestrator] Creating SkillCreationIntent for '{skill_name}'")
                
                intent = SkillCreationIntent(
                    skill_name=skill_name,
                    origin=IntentOrigin.USER,
                    reason=verification.get("_cim_decision", {}).get("pattern_id", "control_layer"),
                    
                    conversation_id=conversation_id,
                    thinking_plan=thinking_plan,
                    complexity=thinking_plan.get("sequential_complexity", 5)
                )
                store = get_intent_store()
                store.add(intent)
                
                verified_plan["_pending_intent"] = intent.to_dict()
                log_info(f"[Orchestrator] Intent {intent.id[:8]} added to verified_plan")
        
        return verification, verified_plan
    
    async def _execute_output_layer(
        self,
        user_text: str,
        verified_plan: Dict,
        memory_data: str,
        model: str,
        chat_history: list,
        memory_required_but_missing: bool = False
    ) -> str:
        """Execute Output Layer (Step 3)."""
        log_info("[Orchestrator] === LAYER 3: OUTPUT ===")
        
        if memory_required_but_missing:
            log_info("[Orchestrator-Output] WARNING: Memory required but not found!")
        
        answer = await self.output.generate(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=memory_data,
            model=model,
            memory_required_but_missing=memory_required_but_missing,
            chat_history=chat_history
        )
        
        log_info(f"[Orchestrator-Output] Generated {len(answer)} chars")
        return answer
    
    def _save_memory(
        self,
        conversation_id: str,
        verified_plan: Dict,
        answer: str
    ):
        """Save facts and assistant response to memory."""
        
        # Save new facts
        if verified_plan.get("is_new_fact"):
            fact_key = verified_plan.get("new_fact_key")
            fact_value = verified_plan.get("new_fact_value")
            if fact_key and fact_value:
                log_info(f"[Orchestrator-Save] Saving fact: {fact_key}={fact_value}")
                try:
                    fact_args = {
                        "conversation_id": conversation_id,
                        "subject": "Danny",
                        "key": fact_key,
                        "value": fact_value,
                        "layer": "ltm",
                    }
                    call_tool("memory_fact_save", fact_args)
                except Exception as e:
                    log_error(f"[Orchestrator-Save] Error: {e}")
        
        # Autosave assistant response
        try:
            autosave_assistant(
                conversation_id=conversation_id,
                content=answer,
                layer="stm",
            )
        except Exception as e:
            log_error(f"[Orchestrator-Autosave] Error: {e}")
