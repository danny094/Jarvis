"""
Master Orchestrator - Autonomous AI coordination layer

Architecture Pattern: COMPOSITION (not parallel execution!)
- Master is CLIENT of PipelineOrchestrator
- Master decides "I need to do X" → calls pipeline.execute_request(X)
- CIM Policy enforcement happens automatically via Pipeline

Based on Gemini's architecture analysis and critical.md fixes.
"""
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
import json
import asyncio
import os
from utils.logger import log_info, log_error, log_warning


# ============================================================================
# STATE DEFINITIONS
# ============================================================================

class OrchestrationState(Enum):
    """Master Orchestrator states"""
    IDLE = "idle"                    # Waiting for objective
    OBSERVING = "observing"          # Analyzing context
    PLANNING = "planning"            # Creating action plan
    EXECUTING = "executing"          # Running sub-tasks
    REFLECTING = "reflecting"        # Analyzing results
    COMPLETED = "completed"          # Objective achieved
    FAILED = "failed"                # Objective failed


@dataclass
class MasterContext:
    """
    Shared context across Master Orchestrator lifecycle
    
    This is the "memory" of the autonomous loop.
    """
    objective: str                              # High-level goal
    state: OrchestrationState                   # Current state
    conversation_id: str                        # Conversation context
    steps_completed: List[Dict[str, Any]] = field(default_factory=list)  # History
    active_plan: Optional[Dict[str, Any]] = None  # Current execution plan
    loop_count: int = 0                         # Iteration counter
    max_loops: int = 10                         # Safety limit
    started_at: float = 0.0                     # Start timestamp
    observations: Dict[str, Any] = field(default_factory=dict)  # Current observations
    terminal_error_code: str = ""               # Stable terminal error code (if failed)
    terminal_error_detail: str = ""             # Human-readable terminal error detail
    stop_reason: str = ""                       # Terminal stop reason (success/failure)
    
    def __post_init__(self):
        """Initialize timestamp if not set"""
        if self.started_at == 0.0:
            self.started_at = time.time()
    
    def add_step(self, step: Dict[str, Any]):
        """Record a completed step"""
        self.steps_completed.append({
            **step,
            "completed_at": time.time(),
            "loop_iteration": self.loop_count
        })
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds"""
        return time.time() - self.started_at


# ============================================================================
# MASTER ORCHESTRATOR CLASS
# ============================================================================

class MasterOrchestrator:
    """
    Autonomous Master Orchestrator
    
    Responsibilities:
    - High-level objective decomposition
    - Autonomous loop execution
    - Pipeline coordination (via composition)
    - Long-term memory integration
    
    NOT responsible for:
    - Tool execution (Pipeline does this)
    - Policy enforcement (Pipeline does this)
    - Streaming (Pipeline does this)
    """
    

    def _load_settings(self):
        """Load Master Orchestrator settings from file"""
        settings_file = "/tmp/settings_master.json"
        default = {
            "enabled": True,
            "use_thinking_layer": False,
            "max_loops": 10,
            "completion_threshold": 2
        }
        
        if os.path.exists(settings_file):
            try:
                with open(settings_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log_warning(f"[MasterOrchestrator] Failed to load settings: {e}")
                return default
        return default

    def __init__(
        self,
        pipeline_orchestrator,
        event_sink: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None,
    ):
        """
        Initialize Master Orchestrator
        
        Args:
            pipeline_orchestrator: PipelineOrchestrator instance (composition!)
        """
        self.pipeline = pipeline_orchestrator
        self._event_sink = event_sink
        
        # Load settings
        self.settings = self._load_settings()
        
        # Will be initialized when needed
        self.task_archive = None
        self.pattern_detector = None
        
        thinking_status = 'ON' if self.settings.get('use_thinking_layer') else 'OFF'
        log_info(f"[MasterOrchestrator] Initialized (ThinkingLayer: {thinking_status}, MaxLoops: {self.settings.get('max_loops', 10)})")

    def set_event_sink(
        self,
        event_sink: Optional[Callable[[str, str, Dict[str, Any]], Any]],
    ) -> None:
        """Attach or replace telemetry sink for planning events."""
        self._event_sink = event_sink

    async def _emit_event(
        self,
        conversation_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Best-effort event emission for workspace/planning telemetry."""
        if not callable(self._event_sink):
            return
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return
        data = payload if isinstance(payload, dict) else {}
        try:
            result = self._event_sink(conv_id, str(event_type or "planning_event"), data)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            log_warning(f"[MasterOrchestrator] Event sink failed ({event_type}): {e}")

    @staticmethod
    def _set_terminal_error(
        context: MasterContext,
        code: str,
        detail: str = "",
    ) -> None:
        """Set terminal error only once to preserve first/root failure reason."""
        if not context.terminal_error_code:
            context.terminal_error_code = str(code or "autonomy_error").strip() or "autonomy_error"
        if detail and not context.terminal_error_detail:
            context.terminal_error_detail = str(detail).strip()[:400]

    @staticmethod
    def _set_stop_reason(context: MasterContext, reason: str) -> None:
        if reason:
            context.stop_reason = str(reason).strip()[:120]
    
    # ========================================================================
    # PUBLIC API
    # ========================================================================
    
    async def execute_objective(
        self,
        objective: str,
        conversation_id: str,
        max_loops: int = None
    ) -> Dict[str, Any]:
        """
        Execute a high-level objective autonomously
        
        This is the main entry point for autonomous execution.
        
        Args:
            objective: High-level goal (e.g., "Migrate database schema")
            conversation_id: Conversation context
            max_loops: Maximum iterations (safety limit)
        
        Returns:
            Execution summary with results and metadata
        """
        # Refresh settings for every objective run so /api/settings/master takes effect immediately.
        self.settings = self._load_settings()
        log_info(f"[MasterOrchestrator] Starting objective: {objective}")

        if not bool(self.settings.get("enabled", True)):
            msg = "Master orchestrator is disabled by settings"
            await self._emit_event(
                conversation_id,
                "planning_error",
                {"objective": objective, "error": msg},
            )
            return {
                "success": False,
                "objective": objective,
                "error": msg,
                "steps_completed": 0,
                "elapsed_time": 0.0,
                "final_state": OrchestrationState.FAILED.value,
            }
        
        # Initialize context
        # Use settings if max_loops not explicitly provided
        if max_loops is None:
            max_loops = self.settings.get("max_loops", 10)
        
        context = MasterContext(
            objective=objective,
            state=OrchestrationState.IDLE,
            conversation_id=conversation_id,
            max_loops=max_loops
        )

        await self._emit_event(
            conversation_id,
            "planning_start",
            {
                "objective": objective,
                "max_loops": max_loops,
                "state": context.state.value,
                "planning_mode": "deep" if bool(self.settings.get("use_thinking_layer", False)) else "fast",
            },
        )
        
        try:
            # Run autonomous loop
            result = await self._autonomous_loop(context)
            final_state = str(result.get("final_state") or context.state.value)
            error_code = str(result.get("error_code") or context.terminal_error_code or "").strip()
            stop_reason = str(result.get("stop_reason") or context.stop_reason or "").strip()
            success = final_state == OrchestrationState.COMPLETED.value and not error_code

            if success:
                log_info(f"[MasterOrchestrator] Objective completed in {context.get_elapsed_time():.1f}s")
                await self._emit_event(
                    conversation_id,
                    "planning_done",
                    {
                        "objective": objective,
                        "loops_executed": context.loop_count,
                        "steps_completed": len(context.steps_completed),
                        "final_state": final_state,
                        "stop_reason": stop_reason or "completed",
                    },
                )
            else:
                detail = str(result.get("error") or context.terminal_error_detail or "objective_not_completed")
                await self._emit_event(
                    conversation_id,
                    "planning_error",
                    {
                        "objective": objective,
                        "phase": "terminal",
                        "error": detail,
                        "error_code": error_code or "objective_not_completed",
                        "final_state": final_state,
                        "stop_reason": stop_reason or "terminal_failure",
                        "loops_executed": context.loop_count,
                    },
                )

            out = {
                "success": success,
                "objective": objective,
                "steps_completed": len(context.steps_completed),
                "elapsed_time": context.get_elapsed_time(),
                "final_state": final_state,
                "result": result,
                "stop_reason": stop_reason or ("completed" if success else "terminal_failure"),
            }
            if error_code:
                out["error_code"] = error_code
                out["error"] = str(result.get("error") or context.terminal_error_detail or "objective_not_completed")
            return out
            
        except Exception as e:
            log_error(f"[MasterOrchestrator] Objective failed: {e}")
            await self._emit_event(
                conversation_id,
                "planning_error",
                {
                    "objective": objective,
                    "error": str(e),
                    "loops_executed": context.loop_count,
                },
            )
            
            return {
                "success": False,
                "objective": objective,
                "error": str(e),
                "steps_completed": len(context.steps_completed),
                "elapsed_time": context.get_elapsed_time(),
                "final_state": OrchestrationState.FAILED.value
            }
    
    # ========================================================================
    # AUTONOMOUS LOOP (State Machine)
    # ========================================================================
    
    async def _autonomous_loop(self, context: MasterContext) -> Dict[str, Any]:
        """
        Main autonomous loop (State Machine)
        
        Loop flow:
        IDLE → OBSERVING → PLANNING → EXECUTING → REFLECTING
                                          ↑           ↓
                                          └───────────┘
                                        (loop until done)
        
        Safety mechanisms:
        - max_loops limit (prevents infinite loops)
        - Similarity detection (prevents repeated actions)
        - Early exit on completion
        """
        while context.loop_count < context.max_loops:
            context.loop_count += 1
            
            log_info(f"[MasterOrchestrator] Loop {context.loop_count}/{context.max_loops}")
            await self._emit_event(
                context.conversation_id,
                "planning_step",
                {
                    "phase": "loop",
                    "loop": context.loop_count,
                    "state": context.state.value,
                    "steps_completed": len(context.steps_completed),
                },
            )
            
            # State machine dispatch
            if context.state == OrchestrationState.IDLE:
                context.state = OrchestrationState.OBSERVING
            
            elif context.state == OrchestrationState.OBSERVING:
                await self._observe(context)
                context.state = OrchestrationState.PLANNING
            
            elif context.state == OrchestrationState.PLANNING:
                plan_created = await self._plan(context)
                if plan_created:
                    context.state = OrchestrationState.EXECUTING
                else:
                    # No more actions needed OR terminal planning error.
                    context.state = (
                        OrchestrationState.FAILED
                        if context.terminal_error_code
                        else OrchestrationState.COMPLETED
                    )
                    break
            
            elif context.state == OrchestrationState.EXECUTING:
                await self._execute(context)
                context.state = OrchestrationState.REFLECTING
            
            elif context.state == OrchestrationState.REFLECTING:
                should_continue = await self._reflect(context)
                if should_continue:
                    context.state = OrchestrationState.OBSERVING
                else:
                    context.state = (
                        OrchestrationState.FAILED
                        if context.terminal_error_code
                        else OrchestrationState.COMPLETED
                    )
                    break
            
            elif context.state in [OrchestrationState.COMPLETED, OrchestrationState.FAILED]:
                break
        
        # Check if we hit loop limit
        if (
            context.loop_count >= context.max_loops
            and context.state not in {OrchestrationState.COMPLETED, OrchestrationState.FAILED}
        ):
            log_warning(f"[MasterOrchestrator] Hit max loops ({context.max_loops})")
            self._set_terminal_error(
                context,
                "max_loops_reached",
                f"max_loops_reached:{context.max_loops}",
            )
            self._set_stop_reason(context, "max_loops_reached")
            context.state = OrchestrationState.FAILED
            await self._emit_event(
                context.conversation_id,
                "planning_error",
                {
                    "phase": "loop_guard",
                    "loop": context.loop_count,
                    "error": f"max_loops_reached:{context.max_loops}",
                    "error_code": "max_loops_reached",
                },
            )

        return {
            "loops_executed": context.loop_count,
            "final_state": context.state.value,
            "steps": context.steps_completed
            ,
            "error_code": context.terminal_error_code or None,
            "error": context.terminal_error_detail or None,
            "stop_reason": context.stop_reason or None,
        }
    
    # ========================================================================
    # STATE HANDLERS
    # ========================================================================
    
    async def _observe(self, context: MasterContext):
        """
        OBSERVE state: Analyze current context
        
        Actions:
        1. Load relevant memory from TaskArchive (Phase 2!)
        2. Analyze conversation history
        3. Check active workspace state
        4. Update context with observations
        """
        log_info("[MasterOrchestrator] OBSERVE: Analyzing context...")
        
        observations = {
            "objective": context.objective,
            "conversation_id": context.conversation_id,
            "steps_so_far": len(context.steps_completed),
            "elapsed_time": context.get_elapsed_time()
        }
        
        # ====================================================================
        # LOAD RELEVANT MEMORY (Phase 2 Integration!)
        # ====================================================================
        try:
            # Lazy load TaskArchive
            if self.task_archive is None:
                from core.lifecycle.archive import get_archive_manager
                self.task_archive = get_archive_manager()
            
            # Search for relevant past tasks (semantic search!)
            log_info(f"[MasterOrchestrator] Searching archive for: {context.objective}")
            
            relevant_tasks = self.task_archive.search_archive(
                query=context.objective,
                conversation_id=context.conversation_id,
                limit=3  # Top 3 most relevant
            )
            
            if relevant_tasks:
                log_info(f"[MasterOrchestrator] Found {len(relevant_tasks)} relevant past tasks")
                observations["past_tasks"] = relevant_tasks
            else:
                log_info("[MasterOrchestrator] No relevant past tasks found")
                observations["past_tasks"] = []
                
        except Exception as e:
            log_warning(f"[MasterOrchestrator] Failed to load archive: {e}")
            observations["past_tasks"] = []
        
        # ====================================================================
        # ANALYZE STEPS COMPLETED
        # ====================================================================
        if context.steps_completed:
            last_step = context.steps_completed[-1]
            observations["last_action"] = last_step.get("action", "unknown")
            observations["last_result"] = last_step.get("result", {})
            
            log_info(f"[MasterOrchestrator] Last action: {observations['last_action']}")
        
        # Store observations in context
        context.observations = observations
        
        log_info(f"[MasterOrchestrator] Observation complete: {len(observations)} data points")
    
    async def _plan(self, context: MasterContext) -> bool:
        """
        PLANNING state: Create action plan
        
        Uses observations to create next action(s).
        
        Returns:
            True if plan created, False if objective already achieved
        """
        log_info("[MasterOrchestrator] PLAN: Creating action plan...")
        await self._emit_event(
            context.conversation_id,
            "planning_step",
            {"phase": "planning", "loop": context.loop_count},
        )
        
        # ====================================================================
        # CHECK IF OBJECTIVE ACHIEVED
        # ====================================================================
        
        # Simple heuristic for now: if we've done 5+ steps, probably done
        if len(context.steps_completed) >= 5:
            log_info("[MasterOrchestrator] Objective likely achieved (5+ steps)")
            self._set_stop_reason(context, "max_steps_heuristic")
            await self._emit_event(
                context.conversation_id,
                "planning_step",
                {"phase": "planning", "decision": "stop", "reason": "max_steps_heuristic"},
            )
            return False
        
        # ====================================================================
        # LOOP DETECTION (Safety!)
        # ====================================================================
        
        # Check if we're repeating the same action
        if len(context.steps_completed) >= 2:
            last_actions = [
                step.get("action", "") 
                for step in context.steps_completed[-3:]
            ]
            
            # If last 3 actions are identical → stuck in loop!
            if len(set(last_actions)) == 1:
                log_warning(f"[MasterOrchestrator] Loop detected: {last_actions[0]} repeated 3x")
                self._set_terminal_error(context, "loop_detected", f"repeated_action:{last_actions[0]}")
                self._set_stop_reason(context, "loop_detected")
                await self._emit_event(
                    context.conversation_id,
                    "planning_error",
                    {
                        "phase": "planning",
                        "error": "loop_detected",
                        "error_code": "loop_detected",
                        "action": last_actions[0],
                    },
                )
                return False
        
        # ====================================================================
        # CREATE PLAN (Simple decomposition for now)
        # ====================================================================
        
        observations = context.observations
        
        # Extract next logical step from objective
        # TODO: In future, use LLM here for intelligent planning
        
        plan = {
            "objective": context.objective,
            "next_action": self._determine_next_action(context, observations),
            "expected_outcome": "Progress toward objective",
            "created_at": time.time()
        }
        
        context.active_plan = plan
        
        log_info(f"[MasterOrchestrator] Plan created: {plan['next_action']}")
        await self._emit_event(
            context.conversation_id,
            "planning_step",
            {
                "phase": "planning",
                "decision": "continue",
                "next_action": plan["next_action"],
            },
        )
        
        return True
    
    def _determine_next_action(
        self, 
        context: MasterContext, 
        observations: Dict[str, Any]
    ) -> str:
        """
        Determine next action based on context
        
        Simple heuristic-based planning for MVP.
        Future: Replace with LLM-based planning.
        """
        # If no steps yet, start with analysis
        if not context.steps_completed:
            return f"Analyze requirements for: {context.objective}"
        
        # If we have past tasks, use them
        past_tasks = observations.get("past_tasks", [])
        if past_tasks:
            return f"Review past approach: {past_tasks[0].get('content', 'unknown')[:50]}"
        
        # Default: Continue with next logical step
        step_num = len(context.steps_completed) + 1
        return f"Execute step {step_num} for: {context.objective}"
    
    async def _execute(self, context: MasterContext):
        """
        EXECUTE state: Run sub-tasks via Pipeline
        
        THIS IS WHERE COMPOSITION HAPPENS!
        Master calls Pipeline, Pipeline enforces CIM Policy automatically.
        
        Critical: This is NOT parallel execution - Master is CLIENT of Pipeline.
        """
        log_info("[MasterOrchestrator] EXECUTE: Running sub-tasks...")
        await self._emit_event(
            context.conversation_id,
            "planning_step",
            {"phase": "executing", "loop": context.loop_count},
        )
        
        if not context.active_plan:
            log_error("[MasterOrchestrator] No active plan to execute!")
            self._set_terminal_error(context, "missing_active_plan", "missing_active_plan")
            self._set_stop_reason(context, "missing_active_plan")
            await self._emit_event(
                context.conversation_id,
                "planning_error",
                {"phase": "executing", "error": "missing_active_plan", "error_code": "missing_active_plan"},
            )
            return
        
        action = context.active_plan.get("next_action", "unknown")
        
        log_info(f"[MasterOrchestrator] Executing action: {action}")
        await self._emit_event(
            context.conversation_id,
            "planning_step",
            {"phase": "executing", "action": action},
        )
        
        # ====================================================================
        # CALL PIPELINE (Composition Pattern!)
        # ====================================================================
        
        try:
            # Import here to avoid circular imports
            from core.models import CoreChatRequest, Message
            
            # Create request for Pipeline
            request = CoreChatRequest(model="llama3.1:8b", 
                conversation_id=context.conversation_id,
                messages=[
                    Message(
                        role="user",
                        content=action  # The action becomes user input!
                    )
                ],
                source_adapter="master_orchestrator",
                stream=False  # Master doesn't need streaming
            )
            
            log_info("[MasterOrchestrator] Calling Pipeline...")
            
            # THIS IS THE KEY: Master → Pipeline (not parallel!)
            result = await self.pipeline.process(request)
            
            log_info(f"[MasterOrchestrator] Pipeline completed: {result.done_reason}")
            
            # ================================================================
            # HANDLE POLICY VIOLATIONS (Gemini's Critical Point!)
            # ================================================================
            
            # Check if response indicates policy violation or error
            is_error = result.done_reason in ["error", "policy_violation"]
            
            if is_error:
                error_msg = result.content if result.content else "Unknown error"
                log_error(f"[MasterOrchestrator] Pipeline error: {error_msg}")
                await self._emit_event(
                    context.conversation_id,
                    "planning_error",
                    {
                        "phase": "executing",
                        "action": action,
                        "error": error_msg,
                        "done_reason": result.done_reason,
                    },
                )
                
                # Record error
                context.add_step({
                    "action": action,
                    "result": error_msg,
                    "success": False,
                    "done_reason": result.done_reason
                })
                
                # Continue (don't fail completely, let reflection decide)
                return
            
            # ================================================================
            # RECORD SUCCESS
            # ================================================================
            
            context.add_step({
                "action": action,
                "result": result.content,
                "success": True,
                "done_reason": result.done_reason
            })
            
            log_info(f"[MasterOrchestrator] Step completed successfully")
            await self._emit_event(
                context.conversation_id,
                "planning_step",
                {
                    "phase": "executing",
                    "action": action,
                    "status": "success",
                    "done_reason": result.done_reason,
                },
            )
            
        except Exception as e:
            log_error(f"[MasterOrchestrator] Execution failed: {e}")
            await self._emit_event(
                context.conversation_id,
                "planning_error",
                {
                    "phase": "executing",
                    "action": action,
                    "error": str(e),
                },
            )
            
            # Record failure
            context.add_step({
                "action": action,
                "result": str(e),
                "success": False
            })
            
            import traceback
            traceback.print_exc()
    
    async def _reflect(self, context: MasterContext) -> bool:
        """
        REFLECT state: Analyze results and decide next steps
        
        Actions:
        1. Analyze last step result
        2. Check if objective is achieved
        3. Decide: continue loop or stop
        
        Returns:
            True to continue loop, False if objective achieved
        """
        log_info("[MasterOrchestrator] REFLECT: Analyzing results...")
        await self._emit_event(
            context.conversation_id,
            "planning_step",
            {"phase": "reflecting", "loop": context.loop_count},
        )
        
        if not context.steps_completed:
            log_warning("[MasterOrchestrator] No steps to reflect on")
            self._set_terminal_error(context, "no_steps_to_reflect", "no_steps_to_reflect")
            self._set_stop_reason(context, "no_steps_to_reflect")
            await self._emit_event(
                context.conversation_id,
                "planning_error",
                {"phase": "reflecting", "error": "no_steps_to_reflect", "error_code": "no_steps_to_reflect"},
            )
            return False
        
        # ====================================================================
        # ANALYZE LAST STEP
        # ====================================================================
        
        last_step = context.steps_completed[-1]
        success = last_step.get("success", False)
        
        log_info(f"[MasterOrchestrator] Last step success: {success}")
        
        # ====================================================================
        # CHECK COMPLETION CRITERIA
        # ====================================================================
        
        # Simple heuristics for MVP:
        # 1. If last step failed → try again (up to max_loops)
        # 2. If 3+ successful steps → probably done
        # 3. If hit max_loops → stop
        
        successful_steps = sum(
            1 for step in context.steps_completed 
            if step.get("success", False)
        )
        
        log_info(f"[MasterOrchestrator] Successful steps: {successful_steps}/{len(context.steps_completed)}")
        
        completion_threshold = int(self.settings.get("completion_threshold", 2) or 2)
        if completion_threshold < 1:
            completion_threshold = 1

        if successful_steps >= completion_threshold:
            log_info(
                "[MasterOrchestrator] Objective likely achieved "
                f"({successful_steps}+ successes, threshold={completion_threshold})"
            )
            self._set_stop_reason(context, "completion_threshold_met")
            await self._emit_event(
                context.conversation_id,
                "planning_step",
                {
                    "phase": "reflecting",
                    "decision": "stop",
                    "reason": "completion_threshold_met",
                    "successful_steps": successful_steps,
                    "completion_threshold": completion_threshold,
                },
            )
            return False
        
        # Safety: Don't continue if too many failures
        failed_steps = len(context.steps_completed) - successful_steps
        if failed_steps >= 3:
            log_warning("[MasterOrchestrator] Too many failures (3+), stopping")
            self._set_terminal_error(context, "too_many_failures", f"failed_steps={failed_steps}")
            self._set_stop_reason(context, "too_many_failures")
            await self._emit_event(
                context.conversation_id,
                "planning_error",
                {
                    "phase": "reflecting",
                    "error": "too_many_failures",
                    "error_code": "too_many_failures",
                    "failed_steps": failed_steps,
                },
            )
            return False
        
        # ====================================================================
        # DECIDE: CONTINUE OR STOP
        # ====================================================================
        
        # If we're making progress, continue
        if success:
            log_info("[MasterOrchestrator] Progress made, continuing...")
            await self._emit_event(
                context.conversation_id,
                "planning_step",
                {"phase": "reflecting", "decision": "continue", "last_step_success": True},
            )
            return True
        else:
            log_warning("[MasterOrchestrator] Last step failed, but trying again...")
            await self._emit_event(
                context.conversation_id,
                "planning_step",
                {"phase": "reflecting", "decision": "continue", "last_step_success": False},
            )
            return True  # Give it another chance


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_master_instance = None

def get_master_orchestrator(pipeline_orchestrator):
    """
    Get singleton Master Orchestrator instance
    
    Args:
        pipeline_orchestrator: PipelineOrchestrator instance
    
    Returns:
        MasterOrchestrator instance
    """
    global _master_instance
    if _master_instance is None:
        _master_instance = MasterOrchestrator(pipeline_orchestrator)
    return _master_instance
