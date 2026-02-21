from typing import Dict, Any, List
from .patterns import SemanticPatternDetector
from core.tools.fast_lane.definitions import get_fast_lane_tools_summary
from utils.logger import log_info, log_warning

class AutonomousMasterOrchestrator:
    """
    The Brain of TRION v2.0.
    Coordinates patterns, proactive actions, and fast lane optimization.
    """
    def __init__(self):
        self.pattern_detector = SemanticPatternDetector()
        self.fast_lane_tools = {t["name"] for t in get_fast_lane_tools_summary()}
        
        # Load CIM Policy Engine (if available)
        try:
            from intelligence_modules.cim_policy.cim_policy_engine import process_cim as process_cim_policy
            self.cim_policy = process_cim_policy
            self.cim_available = True
            log_info("[MasterOrchestrator] CIM Policy Engine loaded")
        except ImportError:
            self.cim_policy = None
            self.cim_available = False
            log_warning("[MasterOrchestrator] CIM Policy Engine not available")
        
    async def orchestrate(self, plan: Dict[str, Any], context: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        """
        Main orchestration loop called by Control Layer.
        Modifies the plan in-place and returns orchestration metadata.
        """
        # 1. Detect Patterns
        patterns = await self.pattern_detector.detect(user_message, context)
        
        # 2. Fast Lane Optimization
        # Mark tools suitable for native execution
        if "suggested_tools" in plan:
            for tool in plan["suggested_tools"]:
                if isinstance(tool, dict) and tool.get("name") in self.fast_lane_tools:
                    # Inject flag for PipelineOrchestrator
                    tool["fast_lane"] = True
                    # Also inject mcp name if missing (some LLMs omit it)
                    if "mcp" not in tool:
                        tool["mcp"] = "fast-lane"
                    log_info(f"[MasterOrchestrator] Marked {tool['name']} for Fast Lane")
        
        # 3. Proactive Actions (EXTENDED WITH CIM CHECKS!)
        new_tools = []
        for pattern in patterns:
            if pattern["type"] == "system_maintenance":
                # Proactively add container_stats
                new_tools.append({
                    "name": "container_stats",
                    "mcp": "container-commander",
                    "args": {"container_id": "all"},
                    "reason": "Proactive system status check"
                })
                log_info("[MasterOrchestrator] Added proactive container_stats")
            
            elif pattern["type"] == "repeated_task":
                # ════════════════════════════════════════════════════
                # SKILL CREATION - REQUIRES CIM POLICY CHECK!
                # ════════════════════════════════════════════════════
                
                if self.cim_available:
                    # Check CIM Policy BEFORE suggesting skill creation
                    task_description = pattern.get("description", "Unknown task")
                    
                    try:
                        cim_decision = self.cim_policy(
                            f"Create skill for: {task_description}",
                            available_skills=[]
                        )
                        
                        if cim_decision.requires_confirmation:
                            # User approval required
                            new_tools.append({
                                "name": "autonomous_skill_task",
                                "mcp": "skill-server",
                                "args": {"task": task_description},
                                "reason": "Repeated task detected",
                                "requires_user_approval": True,  # CRITICAL!
                            })
                            log_info(f"[MasterOrchestrator] Skill creation requires user approval: {task_description}")
                        
                        elif cim_decision.matched and hasattr(cim_decision.action, 'value') and cim_decision.action.value == "block":
                            # Blocked by CIM Policy
                            log_info(f"[MasterOrchestrator] Skill creation blocked by CIM: {task_description}")
                            continue
                        
                        else:
                            # Allowed by CIM
                            new_tools.append({
                                "name": "autonomous_skill_task",
                                "mcp": "skill-server",
                                "args": {"task": task_description},
                                "reason": "Repeated task detected - CIM approved"
                            })
                            log_info(f"[MasterOrchestrator] Skill creation approved: {task_description}")
                    
                    except Exception as e:
                        log_warning(f"[MasterOrchestrator] CIM check failed, requiring user approval by default: {e}")
                        # Safe default: require user approval
                        new_tools.append({
                            "name": "autonomous_skill_task",
                            "mcp": "skill-server",
                            "args": {"task": task_description},
                            "reason": "Repeated task detected",
                            "requires_user_approval": True,  # SAFE DEFAULT!
                        })
                
                else:
                    # No CIM available - require user approval by default (safe!)
                    task_description = pattern.get("description", "Unknown task")
                    new_tools.append({
                        "name": "autonomous_skill_task",
                        "mcp": "skill-server",
                        "args": {"task": task_description},
                        "reason": "Repeated task detected",
                        "requires_user_approval": True,  # SAFE DEFAULT!
                    })
                    log_info(f"[MasterOrchestrator] Skill creation requires user approval (no CIM): {task_description}")
        
        if new_tools:
            if "suggested_tools" not in plan:
                plan["suggested_tools"] = []
            plan["suggested_tools"].extend(new_tools)
            log_info(f"[MasterOrchestrator] Added {len(new_tools)} proactive actions")
            
        return {
            "patterns_detected": [p["type"] for p in patterns],
            "proactive_actions_count": len(new_tools),
            "fast_lane_tools_marked": sum(1 for t in plan.get("suggested_tools", []) if isinstance(t, dict) and t.get("fast_lane"))
        }
