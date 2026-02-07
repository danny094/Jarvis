# mcp-servers/skill-server/mini_control_layer.py
"""
Mini-Control-Layer for Skill Operations (v2 - Autonomous)

Lightweight decision layer that runs parallel to main pipeline.
Now with AUTONOMOUS skill discovery, creation, and execution.

Features:
- Skill Discovery: Find existing skills that match user intent
- Auto-Policy: Decide whether to auto-create based on complexity
- Code Generation: Route to qwen2.5-coder for code generation
- Orchestration: Full create-and-run workflow

Decision Points:
1. APPROVE: Skill passed all checks → execute/save directly
2. BLOCK: Critical/High issues → reject with reasons
3. WARN: Medium/Low issues → allow with warnings
4. ESCALATE: Complex decision → forward to main Control Layer
5. USE_EXISTING: Found matching skill → run it
6. CREATE_AND_RUN: No match → create new skill and run it
"""

import asyncio
import json
import re
import os
import httpx
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime

from skill_cim_light import SkillCIMLight, ValidationResult, get_skill_cim


# === CONFIGURATION ===

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
CODE_GEN_MODEL = os.getenv("CODE_GEN_MODEL", "qwen2.5-coder:3b")
SKILLS_DIR = os.getenv("SKILLS_DIR", "/skills")

# Auto-create threshold (complexity 1-10, lower = simpler)
AUTO_CREATE_THRESHOLD = int(os.getenv("AUTO_CREATE_THRESHOLD", "4"))


class ControlAction(Enum):
    """Possible actions from Mini-Control."""
    APPROVE = "approve"           # All good, proceed
    BLOCK = "block"               # Critical issues, reject
    WARN = "warn"                 # Minor issues, proceed with caution
    ESCALATE = "escalate"         # Needs main Control Layer decision
    USE_EXISTING = "use_existing" # Found matching skill
    CREATE_AND_RUN = "create_run" # Create new skill and execute


@dataclass
class SkillRequest:
    """Incoming skill operation request."""
    type: str  # CREATE, RUN, VALIDATE, EDIT, AUTONOMOUS
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    triggers: List[str] = field(default_factory=list)
    arguments: Dict[str, Any] = field(default_factory=dict)
    auto_promote: bool = False


@dataclass
class AutonomousTaskRequest:
    """Request for autonomous skill handling."""
    user_text: str
    intent: str
    complexity: int = 5  # 1-10 scale
    conversation_id: Optional[str] = None
    allow_auto_create: bool = True
    execute_after_create: bool = True


@dataclass
class AutonomousTaskResult:
    """Result of autonomous skill handling."""
    success: bool
    action_taken: str  # "used_existing", "created_new", "created_and_ran", "escalated"
    skill_name: Optional[str] = None
    skill_created: bool = False
    execution_result: Any = None
    error: Optional[str] = None
    validation_score: float = 0.0
    message: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "action_taken": self.action_taken,
            "skill_name": self.skill_name,
            "skill_created": self.skill_created,
            "execution_result": self.execution_result,
            "error": self.error,
            "validation_score": self.validation_score,
            "message": self.message
        }


@dataclass
class ControlDecision:
    """Decision from Mini-Control-Layer."""
    action: ControlAction
    passed: bool
    reason: str
    forward_to_main: bool = False
    summary: str = ""
    validation_result: Optional[ValidationResult] = None
    warnings: List[str] = field(default_factory=list)
    matched_skill: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            "action": self.action.value,
            "passed": self.passed,
            "reason": self.reason,
            "forward_to_main": self.forward_to_main,
            "summary": self.summary,
            "warnings": self.warnings,
            "validation": self.validation_result.to_dict() if self.validation_result else None,
            "matched_skill": self.matched_skill
        }


class SkillMiniControl:
    """
    Mini-Control-Layer for fast skill decision-making.
    
    Now with autonomous skill discovery and creation capabilities.
    """
    
    def __init__(self, cim: Optional[SkillCIMLight] = None, skills_dir: str = SKILLS_DIR):
        """Initialize with CIM instance."""
        self.cim = cim or get_skill_cim()
        self.skills_dir = Path(skills_dir)
        
        # Thresholds for decisions
        self.block_score_threshold = 0.3
        self.warn_score_threshold = 0.7
        self.auto_create_threshold = AUTO_CREATE_THRESHOLD
    
    # ================================================================
    # AUTONOMOUS TASK HANDLING (NEW!)
    # ================================================================
    
    async def process_autonomous_task(
        self, 
        task: AutonomousTaskRequest
    ) -> AutonomousTaskResult:
        """
        Process an autonomous skill task.
        
        Flow:
        1. Try to find matching existing skill
        2. If found → run it
        3. If not found → check if we should auto-create
        4. If auto-create → generate code, validate, install, run
        5. If not auto-create → escalate to main Control
        
        Args:
            task: AutonomousTaskRequest with user intent and complexity
            
        Returns:
            AutonomousTaskResult with action taken and result
        """
        print(f"[MiniControl] Processing autonomous task: {task.intent}")
        
        # 1. SKILL DISCOVERY
        matching_skill = await self._find_matching_skill(task.intent, task.user_text)
        
        if matching_skill:
            print(f"[MiniControl] Found matching skill: {matching_skill['name']}")
            
            # Run existing skill
            if task.execute_after_create:
                run_result = await self._run_skill(
                    matching_skill["name"], 
                    self._extract_args_from_text(task.user_text)
                )
                return AutonomousTaskResult(
                    success=run_result.get("success", False),
                    action_taken="used_existing",
                    skill_name=matching_skill["name"],
                    skill_created=False,
                    execution_result=run_result.get("result"),
                    error=run_result.get("error"),
                    message=f"Used existing skill '{matching_skill['name']}'"
                )
            else:
                return AutonomousTaskResult(
                    success=True,
                    action_taken="found_existing",
                    skill_name=matching_skill["name"],
                    skill_created=False,
                    message=f"Found matching skill '{matching_skill['name']}' - ready to run"
                )
        
        # 2. AUTO-CREATE POLICY
        should_auto = self._should_auto_create(task.complexity, task.allow_auto_create)
        
        if not should_auto:
            print(f"[MiniControl] Complexity {task.complexity} > threshold, escalating")
            return AutonomousTaskResult(
                success=False,
                action_taken="escalated",
                error="Task too complex for auto-creation",
                message=f"Complexity ({task.complexity}) exceeds auto-create threshold ({self.auto_create_threshold}). User confirmation required."
            )
        
        # 3. CODE GENERATION
        print(f"[MiniControl] Generating code with {CODE_GEN_MODEL}")
        
        skill_name = self._generate_skill_name(task.intent)
        generated_code = await self._generate_code_with_coder(task.intent, task.user_text)
        
        if not generated_code:
            return AutonomousTaskResult(
                success=False,
                action_taken="generation_failed",
                error="Code generation failed",
                message="Could not generate skill code"
            )
        
        # 4. VALIDATION
        print(f"[MiniControl] Validating generated code")
        validation = self.cim.validate_code(generated_code)
        
        if not validation.passed:
            return AutonomousTaskResult(
                success=False,
                action_taken="validation_failed",
                error=f"Code validation failed: {[i.description for i in validation.issues[:3]]}",
                validation_score=validation.score,
                message="Generated code did not pass safety validation"
            )
        
        # 5. INSTALLATION
        print(f"[MiniControl] Installing skill '{skill_name}'")
        install_result = await self._install_skill(
            skill_name, 
            generated_code, 
            task.intent,
            auto_promote=True
        )
        
        if not install_result.get("success", False):
            return AutonomousTaskResult(
                success=False,
                action_taken="install_failed",
                skill_name=skill_name,
                error=install_result.get("error", "Installation failed"),
                validation_score=validation.score
            )
        
        # 6. EXECUTION (if requested)
        if task.execute_after_create:
            print(f"[MiniControl] Executing skill '{skill_name}'")
            run_result = await self._run_skill(
                skill_name,
                self._extract_args_from_text(task.user_text)
            )
            
            return AutonomousTaskResult(
                success=run_result.get("success", False),
                action_taken="created_and_ran",
                skill_name=skill_name,
                skill_created=True,
                execution_result=run_result.get("result"),
                error=run_result.get("error"),
                validation_score=validation.score,
                message=f"Created and executed new skill '{skill_name}'"
            )
        
        return AutonomousTaskResult(
            success=True,
            action_taken="created_new",
            skill_name=skill_name,
            skill_created=True,
            validation_score=validation.score,
            message=f"Created new skill '{skill_name}' - ready to run"
        )
    
    # ================================================================
    # SKILL DISCOVERY
    # ================================================================
    
    async def _find_matching_skill(
        self, 
        intent: str, 
        user_text: str
    ) -> Optional[Dict]:
        """
        Find an existing skill that matches the user's intent.
        
        Uses keyword matching and description similarity.
        
        Args:
            intent: Extracted intent from ThinkingLayer
            user_text: Original user message
            
        Returns:
            Skill info dict if found, None otherwise
        """
        # Load installed skills
        installed = self._load_installed_skills()
        
        # Also check drafts (promoted ones)
        drafts = self._load_draft_skills()
        
        all_skills = {**installed, **drafts}
        
        if not all_skills:
            return None
        
        # Normalize search terms
        search_terms = self._extract_keywords(intent) + self._extract_keywords(user_text)
        search_terms = list(set([t.lower() for t in search_terms]))
        
        best_match = None
        best_score = 0
        
        for name, info in all_skills.items():
            score = self._calculate_match_score(name, info, search_terms)
            if score > best_score and score >= 0.3:  # Minimum threshold
                best_score = score
                best_match = {"name": name, **info, "match_score": score}
        
        return best_match
    
    def _load_installed_skills(self) -> Dict[str, Dict]:
        """Load installed skills from registry."""
        registry_file = self.skills_dir / "_registry" / "installed.json"
        if registry_file.exists():
            try:
                with open(registry_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _load_draft_skills(self) -> Dict[str, Dict]:
        """Load draft skills (for matching)."""
        drafts_dir = self.skills_dir / "_drafts"
        drafts = {}
        
        if drafts_dir.exists():
            for skill_dir in drafts_dir.iterdir():
                if skill_dir.is_dir():
                    manifest = skill_dir / "manifest.json"
                    if manifest.exists():
                        try:
                            with open(manifest, 'r') as f:
                                data = json.load(f)
                                drafts[skill_dir.name] = {
                                    "description": data.get("description", ""),
                                    "triggers": data.get("triggers", []),
                                    "is_draft": True
                                }
                        except:
                            pass
        return drafts
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        # Remove common words
        stopwords = {
            'ich', 'du', 'er', 'sie', 'es', 'wir', 'ihr', 'sie', 
            'ein', 'eine', 'einen', 'der', 'die', 'das', 'den', 'dem',
            'und', 'oder', 'aber', 'wenn', 'dann', 'dass', 'wie',
            'ist', 'sind', 'war', 'waren', 'wird', 'werden',
            'kann', 'können', 'möchte', 'möchten', 'soll', 'sollen',
            'bitte', 'mal', 'mir', 'mich', 'dir', 'dich',
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'can', 'could', 'should', 'may', 'might', 'must',
            'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'this', 'that', 'these', 'those', 'my', 'your', 'his', 'her',
            'for', 'to', 'of', 'in', 'on', 'at', 'with', 'from', 'by'
        }
        
        # Extract words
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        
        return keywords
    
    def _calculate_match_score(
        self, 
        skill_name: str, 
        skill_info: Dict, 
        search_terms: List[str]
    ) -> float:
        """Calculate how well a skill matches the search terms."""
        score = 0.0
        
        # Name matching (high weight)
        name_lower = skill_name.lower().replace('_', ' ')
        for term in search_terms:
            if term in name_lower:
                score += 0.4
        
        # Description matching (medium weight)
        desc = skill_info.get("description", "").lower()
        for term in search_terms:
            if term in desc:
                score += 0.2
        
        # Trigger matching (high weight)
        triggers = skill_info.get("triggers", [])
        for trigger in triggers:
            trigger_lower = trigger.lower()
            for term in search_terms:
                if term in trigger_lower:
                    score += 0.3
        
        return min(score, 1.0)  # Cap at 1.0

    # ================================================================
    # AUTO-CREATE POLICY
    # ================================================================
    
    def _should_auto_create(self, complexity: int, user_allows: bool) -> bool:
        """
        Decide if we should auto-create a skill.
        
        Args:
            complexity: Task complexity (1-10)
            user_allows: Whether user has enabled auto-creation
            
        Returns:
            True if we should auto-create
        """
        if not user_allows:
            return False
        
        return complexity <= self.auto_create_threshold
    
    def _generate_skill_name(self, intent: str) -> str:
        """Generate a valid skill name from intent."""
        # Extract key words
        keywords = self._extract_keywords(intent)[:3]
        
        if keywords:
            name = "_".join(keywords)
        else:
            name = "auto_skill"
        
        # Add timestamp for uniqueness
        timestamp = datetime.now().strftime("%H%M%S")
        name = f"{name}_{timestamp}"
        
        # Ensure valid Python identifier
        name = re.sub(r'[^a-z0-9_]', '', name.lower())
        
        return name
    
    # ================================================================
    # CODE GENERATION (qwen2.5-coder)
    # ================================================================
    
    async def _generate_code_with_coder(
        self, 
        intent: str, 
        user_text: str
    ) -> Optional[str]:
        """
        Generate skill code using qwen2.5-coder.
        
        Args:
            intent: What the skill should do
            user_text: Original user request for context
            
        Returns:
            Generated Python code or None if failed
        """
        prompt = f"""Du bist ein Python-Code-Generator für TRION Skills.

AUFGABE: Erstelle eine Python-Funktion basierend auf dieser Beschreibung:
Intent: {intent}
User Request: {user_text}

REGELN:
1. Erstelle EINE Hauptfunktion namens `run(**kwargs)` die das Ergebnis returned
2. Nur sichere Imports: json, math, datetime, re, collections, itertools, hashlib, base64
3. KEINE: os, sys, subprocess, socket, requests, eval, exec, open, __import__
4. Funktion muss einen Rückgabewert haben (return)
5. Dokumentiere mit einem kurzen Docstring
6. Handle Fehler mit try/except

BEISPIEL:
```python
def run(**kwargs):
    \"\"\"Berechnet die Fakultät einer Zahl.\"\"\"
    n = kwargs.get('n', 0)
    if not isinstance(n, int) or n < 0:
        return {{"error": "n muss eine positive Ganzzahl sein"}}
    
    result = 1
    for i in range(1, n + 1):
        result *= i
    
    return {{"result": result, "input": n}}
```

Generiere NUR den Python-Code, keine Erklärungen:
```python
"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": CODE_GEN_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,  # Lower = more deterministic
                            "num_predict": 1000
                        }
                    }
                )
                
                if response.status_code != 200:
                    print(f"[MiniControl] Ollama error: {response.status_code}")
                    return None
                
                data = response.json()
                generated = data.get("response", "")
                
                # Extract code from markdown blocks
                code = self._extract_code_from_response(generated)
                
                if code:
                    print(f"[MiniControl] Generated {len(code)} chars of code")
                    return code
                
                return None
                
        except Exception as e:
            print(f"[MiniControl] Code generation error: {e}")
            return None
    
    def _extract_code_from_response(self, response: str) -> Optional[str]:
        """Extract Python code from LLM response."""
        # Try to find code block
        patterns = [
            r'```python\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                code = match.group(1).strip()
                if 'def run' in code:
                    return code
        
        # If no code block, check if response itself is code
        if 'def run' in response:
            # Clean up
            lines = response.strip().split('\n')
            code_lines = []
            in_code = False
            
            for line in lines:
                if line.strip().startswith('def ') or in_code:
                    in_code = True
                    code_lines.append(line)
            
            if code_lines:
                return '\n'.join(code_lines)
        
        return None
    
    def _extract_args_from_text(self, user_text: str) -> Dict[str, Any]:
        """Extract potential arguments from user text."""
        args = {}
        
        # Try to find numbers
        numbers = re.findall(r'\b(\d+)\b', user_text)
        if numbers:
            # Use common argument names
            if len(numbers) == 1:
                args['n'] = int(numbers[0])
            else:
                args['a'] = int(numbers[0])
                args['b'] = int(numbers[1])
        
        # Try to find quoted strings
        strings = re.findall(r'"([^"]+)"', user_text)
        if strings:
            args['text'] = strings[0]
        
        return args
    
    # ================================================================
    # SKILL INSTALLATION & EXECUTION
    # ================================================================
    
    async def _install_skill(
        self, 
        name: str, 
        code: str, 
        description: str,
        auto_promote: bool = True
    ) -> Dict[str, Any]:
        """Install a skill via the Tool Executor."""
        from engine.skill_installer import SkillInstaller
        
        try:
            installer = SkillInstaller(skills_dir=str(self.skills_dir))
            
            manifest_data = {
                "description": description,
                "triggers": self._extract_keywords(description),
                "created_by": "mini_control_autonomous",
                "created_at": datetime.now().isoformat()
            }
            
            result = installer.save_skill(
                name=name,
                code=code,
                manifest_data=manifest_data,
                is_draft=not auto_promote
            )
            
            return {"success": True, **result}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _run_skill(
        self, 
        name: str, 
        args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run a skill via the Skill Runner."""
        from engine.skill_runner import get_skill_runner
        
        try:
            runner = get_skill_runner()
            result = await runner.run(
                skill_name=name,
                action="run",
                args=args
            )
            return result.to_dict()
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # ORIGINAL REQUEST HANDLING (unchanged)
    # ================================================================
    
    async def process_request(self, request: SkillRequest) -> ControlDecision:
        """
        Process a skill request and return decision.
        
        This is the main entry point for all skill operations.
        """
        if request.type == "CREATE":
            return await self._handle_create(request)
        elif request.type == "RUN":
            return await self._handle_run(request)
        elif request.type == "VALIDATE":
            return await self._handle_validate(request)
        elif request.type == "EDIT":
            return await self._handle_edit(request)
        elif request.type == "AUTONOMOUS":
            # Route to autonomous handler
            task = AutonomousTaskRequest(
                user_text=request.description or "",
                intent=request.description or "",
                complexity=5,
                execute_after_create=True
            )
            result = await self.process_autonomous_task(task)
            return ControlDecision(
                action=ControlAction.CREATE_AND_RUN if result.skill_created else ControlAction.USE_EXISTING,
                passed=result.success,
                reason=result.message,
                summary=result.message
            )
        else:
            return ControlDecision(
                action=ControlAction.ESCALATE,
                passed=False,
                reason=f"Unknown request type: {request.type}",
                forward_to_main=True,
                summary=f"Unknown operation '{request.type}' - escalating to main Control"
            )
    
    async def _handle_create(self, request: SkillRequest) -> ControlDecision:
        """Handle skill creation request."""
        if not request.code:
            return ControlDecision(
                action=ControlAction.BLOCK,
                passed=False,
                reason="No code provided for skill creation",
                summary="Skill creation failed: no code"
            )
        
        # Validate the code
        validation = self.cim.validate_code(request.code)
        
        # Make decision based on validation
        decision = self._decide_from_validation(validation, request)
        
        # Build summary for main pipeline
        if decision.passed:
            decision.summary = (
                f"Skill '{request.name}' validated ✓ "
                f"(score: {validation.score:.2f}, "
                f"priors: {len(validation.applied_priors)})"
            )
            if not request.auto_promote:
                decision.summary += " → saved as draft"
        else:
            issue_summary = ", ".join([
                f"{i.id}:{i.severity}" 
                for i in validation.issues[:3]
            ])
            decision.summary = (
                f"Skill '{request.name}' blocked: {issue_summary}"
            )
        
        return decision
    
    async def _handle_run(self, request: SkillRequest) -> ControlDecision:
        """Handle skill execution request."""
        warnings = []
        for key, value in request.arguments.items():
            if isinstance(value, str) and len(value) > 10000:
                warnings.append(f"Large argument '{key}' ({len(value)} chars)")
        
        return ControlDecision(
            action=ControlAction.APPROVE,
            passed=True,
            reason="Skill execution approved",
            forward_to_main=True,
            summary=f"Running skill '{request.name}'",
            warnings=warnings
        )
    
    async def _handle_validate(self, request: SkillRequest) -> ControlDecision:
        """Handle validation-only request (no save)."""
        if not request.code:
            return ControlDecision(
                action=ControlAction.BLOCK,
                passed=False,
                reason="No code provided for validation",
                summary="Validation failed: no code"
            )
        
        validation = self.cim.validate_code(request.code)
        decision = self._decide_from_validation(validation, request)
        decision.forward_to_main = False
        
        return decision
    
    async def _handle_edit(self, request: SkillRequest) -> ControlDecision:
        """Handle skill edit request."""
        return await self._handle_create(request)
    
    def _decide_from_validation(
        self, 
        validation: ValidationResult, 
        request: SkillRequest
    ) -> ControlDecision:
        """Make control decision based on validation result."""
        
        critical = sum(1 for i in validation.issues if i.severity.lower() == "critical")
        high = sum(1 for i in validation.issues if i.severity.lower() == "high")
        medium = sum(1 for i in validation.issues if i.severity.lower() == "medium")
        
        if critical > 0:
            return ControlDecision(
                action=ControlAction.BLOCK,
                passed=False,
                reason=f"Critical security issues found ({critical})",
                forward_to_main=False,
                validation_result=validation,
                warnings=[i.description for i in validation.issues if i.severity.lower() == "critical"]
            )
        
        if high > 0:
            return ControlDecision(
                action=ControlAction.BLOCK,
                passed=False,
                reason=f"High severity issues found ({high})",
                forward_to_main=False,
                validation_result=validation,
                warnings=[i.description for i in validation.issues if i.severity.lower() == "high"]
            )
        
        if validation.score < self.block_score_threshold:
            return ControlDecision(
                action=ControlAction.BLOCK,
                passed=False,
                reason=f"Score too low: {validation.score:.2f}",
                forward_to_main=False,
                validation_result=validation
            )
        
        if medium > 0 or validation.score < self.warn_score_threshold:
            return ControlDecision(
                action=ControlAction.WARN,
                passed=True,
                reason=f"Minor issues found ({medium} medium)",
                forward_to_main=True,
                validation_result=validation,
                warnings=[i.description for i in validation.issues if i.severity.lower() == "medium"]
            )
        
        return ControlDecision(
            action=ControlAction.APPROVE,
            passed=True,
            reason="All checks passed",
            forward_to_main=True,
            validation_result=validation
        )
    
    # ================================================================
    # UTILITY METHODS
    # ================================================================
    
    def get_review_checklist(self) -> List[Dict]:
        """Get review checklist from CIM."""
        return self.cim.get_review_checklist()
    
    def get_applicable_priors(self, context: str) -> List[Dict]:
        """Get relevant safety priors for a context."""
        return self.cim.get_applicable_priors(context)
    
    def validate_code_quick(self, code: str) -> Dict:
        """Quick validation for real-time feedback."""
        validation = self.cim.validate_code(code)
        return {
            "passed": validation.passed,
            "score": validation.score,
            "issue_count": len(validation.issues),
            "critical": sum(1 for i in validation.issues if i.severity.lower() == "critical"),
            "high": sum(1 for i in validation.issues if i.severity.lower() == "high"),
        }


# ================================================================
# SINGLETON INSTANCE
# ================================================================

_control_instance: Optional[SkillMiniControl] = None

def get_mini_control() -> SkillMiniControl:
    """Get singleton instance of SkillMiniControl."""
    global _control_instance
    if _control_instance is None:
        _control_instance = SkillMiniControl()
    return _control_instance


# ================================================================
# SYNC WRAPPER FOR NON-ASYNC CONTEXTS
# ================================================================

def process_skill_request_sync(request: SkillRequest) -> ControlDecision:
    """Synchronous wrapper for process_request."""
    control = get_mini_control()
    return asyncio.run(control.process_request(request))


def process_autonomous_task_sync(task: AutonomousTaskRequest) -> AutonomousTaskResult:
    """Synchronous wrapper for process_autonomous_task."""
    control = get_mini_control()
    return asyncio.run(control.process_autonomous_task(task))
