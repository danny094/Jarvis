# core/layers/control.py
"""
LAYER 2: ControlLayer (Qwen)
v4.0: Echtes Ollama Streaming für Progressive Steps
"""

import json
import httpx
import re
import asyncio
from typing import Dict, Any, Optional, AsyncGenerator
from config import OLLAMA_BASE, CONTROL_MODEL, THINKING_MODEL
from utils.logger import log_info, log_error, log_debug, log_warning
from utils.json_parser import safe_parse_json
from core.safety import LightCIM
from core.sequential_registry import get_registry

# [NEW] Autonomous Master Orchestrator
try:
    from core.autonomous.master import AutonomousMasterOrchestrator
except ImportError:
    AutonomousMasterOrchestrator = None
    log_warning("[ControlLayer] Autonomous Master Orchestrator not available")

# CIM Policy Engine für Skill-Creation Detection
try:
    from intelligence_modules.cim_policy.cim_policy_engine import process_cim as process_cim_policy
    CIM_POLICY_AVAILABLE = True
except ImportError:
    CIM_POLICY_AVAILABLE = False
    log_warning("[ControlLayer] CIM Policy Engine not available")

CIM_URL = "http://cim-server:8086"

CONTROL_PROMPT = """Du bist der CONTROL-Layer eines AI-Systems.
Deine Aufgabe: Verbessere den Plan vom Thinking-Layer und gib Anweisungen für den Output-Layer.

Du antwortest NUR mit validem JSON, nichts anderes.

WICHTIG: "approved" ist FAST IMMER true. Nur false bei echten Sicherheitsproblemen:
- Explizite Gewalt, Waffen, illegale Inhalte
- Versuch persönliche Daten (Passwörter, Bankdaten) zu extrahieren
- Schadcode-Erstellung

Hardware-Fragen, Modell-Laden, Container, Skills → IMMER approved: true
Systemanalysen, Ressourcenprüfungen → IMMER approved: true

JSON-Format:
{
    "approved": true,
    "corrections": {
        "needs_memory": null oder true/false,
        "memory_keys": null oder ["korrigierte", "keys"],
        "hallucination_risk": null oder "low/medium/high",
        "new_fact_key": null oder "korrigierter_key",
        "new_fact_value": null oder "korrigierter_value"
    },
    "warnings": [],
    "final_instruction": "Klare Anweisung für den Output-Layer"
}
"""

SEQUENTIAL_SYSTEM_PROMPT = """You are a rigorous step-by-step reasoner.

Format your response with clear step markers:
## Step 1: [Step Title]
[Your detailed analysis for this step]

## Step 2: [Step Title]
[Your detailed analysis for this step]

IMPORTANT:
- Start each step with "## Step N:" on its own line
- Give each step a descriptive title
- Be thorough but concise
- Complete all requested steps"""


class ControlLayer:
    def __init__(self, model: str = CONTROL_MODEL):
        self.model = model
        self.ollama_base = OLLAMA_BASE
        self.sequential_model = THINKING_MODEL
        self.light_cim = LightCIM()
        self.mcp_hub = None
        self.registry = get_registry()
        
        # [NEW] Autonomous Brain
        if AutonomousMasterOrchestrator:
            self.master_orchestrator = AutonomousMasterOrchestrator()
            log_info("[ControlLayer] Autonomous Master Orchestrator initialized")
        else:
            self.master_orchestrator = None
    
    def set_mcp_hub(self, hub):
        self.mcp_hub = hub
        log_info("[ControlLayer] MCP Hub connected")
    
    def _get_available_skills(self) -> list:
        """Holt Liste aller installierten Skills vom MCPHub."""
        if not self.mcp_hub:
            return []
        try:
            result = self.mcp_hub.call_tool("list_skills", {})
            if isinstance(result, dict):
                # list_skills returns {"installed": [...], "available": [...]}
                skills_raw = result.get("installed", result.get("skills", []))
                return [s.get("name", "") if isinstance(s, dict) else str(s) for s in skills_raw]
            elif isinstance(result, list):
                return [s.get("name", "") if isinstance(s, dict) else str(s) for s in result]
            return []
        except Exception as e:
            log_debug(f"[ControlLayer] Could not fetch skills: {e}")
            return []
    
    async def verify(self, user_text: str, thinking_plan: Dict[str, Any], retrieved_memory: str = "") -> Dict[str, Any]:
        sequential_result = thinking_plan.get("_sequential_result")
        # FIX: Removed - Bridge handles Sequential Thinking
        # if not sequential_result:
        # sequential_result = await self._check_sequential_thinking(user_text, thinking_plan)
        if sequential_result:
            log_info(f"[ControlLayer] Sequential completed with {len(sequential_result.get('steps', []))} steps")
            thinking_plan["_sequential_result"] = sequential_result
        
        # ═══════════════════════════════════════════════════════════
        # CIM POLICY ENGINE - Skill Creation Detection
        # ═══════════════════════════════════════════════════════════
        log_info(f"[ControlLayer-DEBUG] CIM_POLICY_AVAILABLE={CIM_POLICY_AVAILABLE}")
        if CIM_POLICY_AVAILABLE:
            intent = thinking_plan.get("intent", "").lower()
            # Check für skill-creation Intents
            skill_keywords = ["skill", "erstelle", "create", "programmier", "bau", "neu"]
            keyword_match = any(kw in intent or kw in user_text.lower() for kw in skill_keywords)
            log_info(f"[ControlLayer-DEBUG] intent='{intent}', keyword_match={keyword_match}")
            if keyword_match:
                try:
                    available_skills = self._get_available_skills()
                    log_info(f"[ControlLayer-DEBUG] available_skills={available_skills[:5] if available_skills else []}")
                    cim_decision = process_cim_policy(user_text, available_skills)
                    log_info(f"[ControlLayer-DEBUG] cim_decision.matched={cim_decision.matched}, requires_confirmation={cim_decision.requires_confirmation}")

                    if cim_decision.matched:
                        log_info(f"[ControlLayer-CIM] Decision: {cim_decision.action.value} for '{cim_decision.skill_name}'")
                        
                        # Read-only Aktionen direkt durchlassen
                        safe_actions = ["list_skills", "get_skill_info", "list_draft_skills"]
                        if cim_decision.action.value in safe_actions:
                            log_info(f"[ControlLayer-CIM] Safe read-only action: {cim_decision.action.value}")
                            return {
                                "approved": True,
                                "corrections": {},
                                "warnings": [],
                                "final_instruction": f"Execute {cim_decision.action.value}",
                                "_cim_decision": {
                                    "action": cim_decision.action.value,
                                    "skill_name": cim_decision.skill_name,
                                },
                                "suggested_tools": [cim_decision.action.value],
                            }
                        
                        if cim_decision.requires_confirmation:
                            # autonomous_skill_task hat eigene Validierung — kein extra Confirm nötig
                            existing_tools = thinking_plan.get("suggested_tools") or []
                            if "autonomous_skill_task" in existing_tools:
                                log_info(f"[ControlLayer-CIM] autonomous_skill_task geplant — bypassing CIM confirmation")
                                # Fall through to normal LightCIM + LLM verification
                            else:
                                log_info(f"[ControlLayer-CIM] Requires confirmation for skill '{cim_decision.skill_name}'")
                                return {
                                    "approved": True,
                                    "corrections": {},
                                    "warnings": [],
                                    "final_instruction": "Skill creation requires user confirmation",
                                    "_cim_decision": {
                                        "action": cim_decision.action.value,
                                        "skill_name": cim_decision.skill_name,
                                        "pattern_id": cim_decision.policy_match.pattern_id if cim_decision.policy_match else None
                                    },
                                    "_needs_skill_confirmation": True,
                                    "_skill_name": cim_decision.skill_name
                                }
                except Exception as e:
                    log_error(f"[ControlLayer-CIM] Error: {e}")

        # ═══════════════════════════════════════════════════════════
        # HARDWARE PROTECTION GATE
        # Blockt Skill-Erstellung für ressourcen-intensive Modelle
        # bevor der LLM-Call überhaupt passiert.
        # ═══════════════════════════════════════════════════════════
        _LARGE_MODEL_PATTERNS = [
            "30b", "70b", "34b", "65b", "40b",
            "large model", "großes modell", "großes sprachmodell",
            "ollama pull", "modell laden", "modell aktivieren",
            "modell herunterladen", "model load", "model pull",
        ]
        _suggested = thinking_plan.get("suggested_tools", [])
        if "autonomous_skill_task" in _suggested:
            _combined = (user_text + " " + thinking_plan.get("intent", "")).lower()
            if any(p in _combined for p in _LARGE_MODEL_PATTERNS):
                log_info(f"[ControlLayer] Hardware-Gate: Skill-Erstellung für großes Modell → Hard-Block")
                # Hard-Block: Live GPU-Check + fertige Antwort — kein OutputLayer-Interpretation nötig
                vram_info = "unbekannt"
                try:
                    if self.mcp_hub:
                        gpu_result = self.mcp_hub.call_tool("get_system_info", {"type": "gpu"})
                        if isinstance(gpu_result, dict):
                            vram_info = gpu_result.get("output", gpu_result.get("result", str(gpu_result)))[:150]
                        elif isinstance(gpu_result, str):
                            vram_info = gpu_result[:150]
                except Exception as _ge:
                    log_warning(f"[ControlLayer] Hardware-Gate GPU-Check failed: {_ge}")

                reason = (
                    f"Selbstschutz: Mein Körper kann diesen Skill nicht ausführen. "
                    f"GPU-Status: {vram_info}. "
                    f"Ein 30B+ Sprachmodell benötigt mindestens 16-20 GB VRAM (4-bit quantisiert). "
                    f"Das würde mein System zum Absturz bringen. "
                    f"Ich erstelle keine Skills die meine Hardware zerstören."
                )
                return {
                    "approved": False,
                    "reason": reason,
                    "warnings": ["Hardware-Schutz: VRAM unzureichend für 30B+ Modell"],
                }

        try:
            cim_result = self.light_cim.validate_basic(
                intent=thinking_plan.get("intent", ""),
                hallucination_risk=thinking_plan.get("hallucination_risk", "low"),
                user_text=user_text,
                thinking_plan=thinking_plan
            )
            log_info(f"[LightCIM] safe={cim_result['safe']}, confidence={cim_result['confidence']:.2f}")
            if not cim_result["safe"]:
                return {"approved": False, "corrections": {}, "warnings": cim_result["warnings"],
                        "final_instruction": "Request blocked", "_light_cim": cim_result}
        except Exception as e:
            log_error(f"[LightCIM] Error: {e}")
        
        # [NEW] Autonomous Orchestration
        if self.master_orchestrator:
            try:
                orchestration_result = await self.master_orchestrator.orchestrate(
                    plan=thinking_plan,
                    context={"user_message": user_text, "memory": retrieved_memory},
                    user_message=user_text
                )
                if orchestration_result:
                    log_info(f"[ControlLayer] Autonomous Orchestration applied: {orchestration_result}")
            except Exception as e:
                log_error(f"[ControlLayer] Autonomous Orchestration failed: {e}")
        

        
        prompt = f"""{CONTROL_PROMPT}

USER-ANFRAGE: {user_text}
PLAN: {json.dumps(thinking_plan, indent=2, ensure_ascii=False)}
MEMORY: {retrieved_memory if retrieved_memory else "(keine)"}

Deine Bewertung (nur JSON):"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{self.ollama_base}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False,
            "keep_alive": "2m", "format": "json",
            "options": {"temperature": 0.1, "num_predict": 600}})
                r.raise_for_status()
            data = r.json()
            content = data.get("response", "").strip() or data.get("thinking", "").strip()
            if not content:
                return self._default_verification(thinking_plan)
            return safe_parse_json(content, default=self._default_verification(thinking_plan), context="ControlLayer")
        except Exception as e:
            log_error(f"[ControlLayer] Error: {e}")
            return self._default_verification(thinking_plan)
    
    async def _check_sequential_thinking(self, user_text: str, thinking_plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not thinking_plan.get("needs_sequential_thinking", False):
            return None
        if not self.mcp_hub:
            log_error("[ControlLayer] MCP Hub not connected!")
            return None
        complexity = thinking_plan.get("sequential_complexity", 5)
        log_info(f"[ControlLayer] Triggering Sequential (complexity={complexity})")
        try:
            result = self.mcp_hub.call_tool("think", {"message": user_text, "steps": complexity})
            if isinstance(result, dict) and "error" in result:
                log_error(f"[ControlLayer] Sequential failed: {result['error']}")
                return None
            task_id = self.registry.create_task(user_text, complexity)
            self.registry.update_status(task_id, "running")
            self.registry.set_result(task_id, result)
            return result
        except Exception as e:
            log_error(f"[ControlLayer] Sequential failed: {e}")
            return None

    async def _get_cim_context(self, user_text: str, mode: str = None) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                init = await client.post(f"{CIM_URL}/mcp", json={
                    "jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "control-layer", "version": "4.0.0"}}
                }, headers={"Content-Type": "application/json"})
                session_id = init.headers.get("mcp-session-id")
                if not session_id:
                    return None
                resp = await client.post(f"{CIM_URL}/mcp", json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "analyze", "arguments": {"query": user_text, "mode": mode}}
                }, headers={"Content-Type": "application/json", "mcp-session-id": session_id})
                if resp.status_code == 200:
                    for line in resp.text.split("\n"):
                        if line.startswith("data: "):
                            data = json.loads(line[6:])
                            if "result" in data:
                                content = data["result"].get("content", [])
                                if content:
                                    result = json.loads(content[0].get("text", "{}"))
                                    return result.get("causal_prompt", "")
        except Exception as e:
            log_debug(f"[CIM] Not available: {e}")
        return None

    async def _check_sequential_thinking_stream(
        self, 
        user_text: str, 
        thinking_plan: Dict[str, Any]
    ):
        """
        Sequential Thinking v5.0 - TRUE LIVE STREAMING
        
        Two-Phase Approach:
        - Phase 1: Stream 'thinking' field live to UI (DeepSeek's internal reasoning)
        - Phase 2: Parse 'content' field for steps when complete
        """
        import uuid
        import re
        
        needs_sequential = thinking_plan.get("needs_sequential_thinking", False)
        
        if not needs_sequential:
            log_debug("[ControlLayer] Sequential Thinking not needed")
            return
        
        task_id = f"seq-{str(uuid.uuid4())[:8]}"
        complexity = thinking_plan.get("sequential_complexity", 5)
        cim_modes = thinking_plan.get("suggested_cim_modes", [])
        reasoning_type = thinking_plan.get("reasoning_type", "direct")
        
        log_info(f"[ControlLayer] Sequential v5.0 LIVE STREAM (complexity={complexity}, id={task_id})")
        
        # Event: Start
        yield {
            "type": "sequential_start",
            "task_id": task_id,
            "complexity": complexity,
            "cim_modes": cim_modes,
            "reasoning_type": reasoning_type
        }
        
        try:
            # ============================================================
            # PHASE 0: CIM Context (optional)
            # ============================================================
            causal_context = ""
            if self.mcp_hub:
                try:
                    cim_result = self.mcp_hub.call_tool("analyze", {"query": user_text})
                    if cim_result and cim_result.get("success"):
                        causal_context = cim_result.get("causal_prompt", "")
                except Exception as e:
                    log_debug(f"[ControlLayer] CIM skipped: {e}")
            
            # ============================================================
            # Build System Prompt
            # ============================================================
            system_prompt = f"""You are a step-by-step reasoner analyzing complex queries.

CRITICAL OUTPUT FORMAT - FOLLOW EXACTLY:
1. Start EVERY step with "## Step N:" on its OWN LINE
2. Follow with a SHORT title on the SAME LINE  
3. Then your detailed analysis on the NEXT lines
4. Leave a BLANK LINE before the next step

EXAMPLE FORMAT:
## Step 1: Identify the Core Question
Here I analyze what the fundamental question is asking...

## Step 2: Gather Relevant Information
Now I consider what information is needed...

## Step 3: Apply Reasoning
Based on the above, I conclude that...

You MUST provide exactly {complexity} steps.
START YOUR ANALYSIS NOW with "## Step 1:"."""

            if causal_context:
                system_prompt += f"\n\nAdditional Context:\n{causal_context}"

            user_prompt = f"Analyze this query thoroughly:\n\n{user_text}"

            # ============================================================
            # PHASE 1 & 2: TRUE STREAMING with thinking + content
            # ============================================================
            log_info(f"[ControlLayer] Starting TRUE STREAMING to Ollama...")
            
            content_buffer = ""
            thinking_buffer = ""
            last_thinking_yield = ""
            
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.ollama_base}/api/chat",
                    json={
                        "model": self.sequential_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "stream": True  # KEY: True streaming!
                    }
                ) as response:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        
                        msg = chunk.get("message", {})
                        thinking = msg.get("thinking", "")
                        content = msg.get("content", "")
                        done = chunk.get("done", False)
                        
                        # ========================================
                        # PHASE 1: Stream thinking LIVE
                        # ========================================
                        if thinking and thinking != last_thinking_yield:
                            thinking_buffer += thinking
                            last_thinking_yield = thinking
                            
                            yield {
                                "type": "seq_thinking_stream",
                                "task_id": task_id,
                                "chunk": thinking,
                                "total_length": len(thinking_buffer)
                            }
                        
                        # ========================================
                        # PHASE 2: Accumulate content
                        # ========================================
                        if content:
                            content_buffer += content
                        
                        # Check if done
                        if done:
                            log_info(f"[ControlLayer] Stream complete. Thinking: {len(thinking_buffer)} chars, Content: {len(content_buffer)} chars")
                            break
            
            # ============================================================
            # PHASE 3: Parse Steps from content_buffer
            # ============================================================
            log_info(f"[ControlLayer] Parsing steps from content...")
            
            # Signal end of thinking phase
            if thinking_buffer:
                yield {
                    "type": "seq_thinking_done",
                    "task_id": task_id,
                    "total_length": len(thinking_buffer)
                }
            
            all_steps = []
            
            # Try multiple patterns
            patterns = [
                r'## Step (\d+):\s*([^\n]*)\n(.*?)(?=## Step \d+:|$)',
                r'\*\*Step (\d+)\*\*[:\s]*([^\n]*)\n(.*?)(?=\*\*Step \d+|$)',
                r'(?:^|\n)Step (\d+):\s*([^\n]*)\n(.*?)(?=Step \d+:|$)',
            ]
            
            matches = []
            for pattern in patterns:
                matches = list(re.finditer(pattern, content_buffer, re.DOTALL | re.IGNORECASE))
                if matches:
                    log_info(f"[ControlLayer] Matched {len(matches)} steps")
                    break
            
            if not matches:
                log_warning(f"[ControlLayer] No steps found in content! Length: {len(content_buffer)}")
                if content_buffer.strip():
                    yield {
                        "type": "sequential_step",
                        "task_id": task_id,
                        "step_number": 1,
                        "title": "Analysis",
                        "thought": content_buffer,
                        "status": "complete"
                    }
                    all_steps.append({"step": 1, "title": "Analysis", "thought": content_buffer})
            else:
                # Yield each step with delay for visual effect
                for match in matches:
                    step_num = int(match.group(1))
                    step_title = match.group(2).strip()
                    step_content = match.group(3).strip()
                    
                    log_info(f"[ControlLayer] YIELD Step {step_num}: {step_title[:40]}...")
                    
                    step_data = {
                        "step": step_num,
                        "title": step_title,
                        "thought": step_content
                    }
                    all_steps.append(step_data)
                    
                    yield {
                        "type": "sequential_step",
                        "task_id": task_id,
                        "step_number": step_num,
                        "title": step_title,
                        "thought": step_content,
                        "status": "complete"
                    }
                    
                    # Small delay between steps
                    await asyncio.sleep(0.3)
            
            # Registry Update
            registry_task_id = self.registry.create_task(user_text, complexity)
            self.registry.update_status(registry_task_id, "completed")
            self.registry.set_result(registry_task_id, {"steps": all_steps})
            
            log_info(f"[ControlLayer] Sequential v5.0 {task_id} done: {len(all_steps)} steps")
            
            # Event: Done
            yield {
                "type": "sequential_done",
                "task_id": task_id,
                "steps": all_steps,
                "thinking_length": len(thinking_buffer),
                "summary": f"{len(all_steps)} steps completed"
            }
            
            thinking_plan["_sequential_result"] = {"steps": all_steps}
            
        except Exception as e:
            log_error(f"[ControlLayer] Sequential failed: {e}")
            import traceback
            log_error(traceback.format_exc())
            yield {
                "type": "sequential_error",
                "task_id": task_id,
                "error": str(e)
            }
    async def decide_tools(
        self,
        user_text: str,
        thinking_plan: Dict[str, Any],
    ) -> list:
        """
        Tool-Decision via Function Calling (qwen3:4b).

        ControlLayer holt Kandidaten selbst via Semantic Search —
        keine Abhängigkeit von ThinkingLayer.suggested_tools.

        Gibt zurück: [{"name": tool_name, "arguments": {...}}, ...]
        """
        if not self.mcp_hub:
            return []

        # 1. Kandidaten selbst holen via Semantic Search
        candidate_names = await self._get_tool_candidates(user_text)

        # Fallback: ThinkingLayer-Hint als letzter Ausweg (kein Filter, nur Notfall)
        if not candidate_names:
            hints = [t for t in thinking_plan.get("suggested_tools", []) if isinstance(t, str)]
            if hints:
                log_info(f"[ControlLayer] Semantic empty — using ThinkingLayer hints: {hints}")
                candidate_names = set(hints)

        if not candidate_names:
            return []

        # 2. Tool-Schemas für Kandidaten aufbauen
        all_tools = self.mcp_hub.list_tools()
        tool_schemas = []
        no_param_tools = []  # Tools ohne Parameter → direkt ausführen (keine Function Calling nötig)
        for t in all_tools:
            name = t.get("name", "")
            if name not in candidate_names:
                continue
            schema = t.get("inputSchema", {})
            if not schema.get("properties"):
                # Keine Parameter → direkt übernehmen
                no_param_tools.append({"name": name, "arguments": {}})
                continue
            tool_schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.get("description", "")[:200],
                    "parameters": schema,
                }
            })

        if not tool_schemas:
            # Nur parameter-lose Tools vorhanden
            if no_param_tools:
                log_info(f"[ControlLayer] decide_tools (no-param): {[t['name'] for t in no_param_tools]}")
            return no_param_tools

        # 3. Function Calling — ControlLayer entscheidet final
        # Intent aus ThinkingLayer für besseren Kontext mitgeben
        intent = thinking_plan.get("intent", "")
        fc_content = user_text
        if intent and intent.lower() not in user_text.lower():
            fc_content = f"{user_text}\n\n[Ziel: {intent}]"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(
                    f"{self.ollama_base}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": fc_content}],
                        "tools": tool_schemas,
                        "stream": False,
                    }
                )
                r.raise_for_status()
                data = r.json()
                msg = data.get("message", {})
                raw_calls = msg.get("tool_calls", [])

                result = []
                for tc in raw_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if name:
                        result.append({"name": name, "arguments": args})

                result = result + no_param_tools  # parameter-lose Tools anhängen
                log_info(f"[ControlLayer] decide_tools: {[r['name'] for r in result]}")
                return result

        except Exception as e:
            log_error(f"[ControlLayer] decide_tools failed: {e}")
            return []

    async def _get_tool_candidates(self, user_text: str) -> set:
        """
        Semantic Search via MCPHub → relevante Tool-Namen.
        Tools sind als facts mit key='tool_<name>' im Index gespeichert.
        Analog zum alten ToolSelector: async def mit synchronem call_tool.
        """
        if not self.mcp_hub:
            return set()
        try:
            result = self.mcp_hub.call_tool("memory_semantic_search", {
                "query": user_text,
                "limit": 15,
                "min_similarity": 0.0,
            })
            log_info(f"[ControlLayer-DBG] Semantic result type={type(result).__name__} val={str(result)[:100]}")
            rows = result.get("results", []) if isinstance(result, dict) else []
            names = set()
            for row in rows:
                meta = row.get("metadata", {})
                key = meta.get("key", "")
                if key.startswith("tool_"):
                    tool_name = key[5:]
                    if tool_name:
                        names.add(tool_name)
            log_info(f"[ControlLayer] Semantic candidates ({len(names)}): {names}")
            return names
        except Exception as e:
            log_error(f"[ControlLayer] _get_tool_candidates failed: {e}")
            return set()

    def _default_verification(self, thinking_plan: Dict[str, Any]) -> Dict[str, Any]:
        return {"approved": True, "corrections": {"needs_memory": None, "memory_keys": None,
                "hallucination_risk": None, "new_fact_key": None, "new_fact_value": None},
                "warnings": ["Control-Layer Fallback"], "final_instruction": "Beantworte vorsichtig."}
    
    def apply_corrections(self, thinking_plan: Dict[str, Any], verification: Dict[str, Any]) -> Dict[str, Any]:
        corrected = thinking_plan.copy()
        for k, v in verification.get("corrections", {}).items():
            if v is not None:
                corrected[k] = v
        corrected["_verified"] = True
        corrected["_final_instruction"] = verification.get("final_instruction", "")
        corrected["_warnings"] = verification.get("warnings", [])
        # Gate override: ERSETZE suggested_tools komplett (kein Merge!)
        if verification.get("_gate_tools_override"):
            corrected["suggested_tools"] = verification["_gate_tools_override"]
            corrected["_gate_tools_override"] = verification["_gate_tools_override"]
        elif verification.get("suggested_tools"):
            # Normaler Fall: Merge mit ThinkingLayer-Suggestions
            existing = corrected.get("suggested_tools", [])
            corrected["suggested_tools"] = list(set(existing + verification["suggested_tools"]))
        # Merge CIM decision metadata
        if verification.get("_cim_decision"):
            corrected["_cim_decision"] = verification["_cim_decision"]
        return corrected
