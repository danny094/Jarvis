# mcp-servers/skill-server/skill_cim_light.py
"""
Skill-CIM-Light: Lightweight Context & Validation Manager for Skills

NO AI REQUIRED - Pure rule-based validation using CSV datasets.
Runs parallel to main pipeline for fast skill validation.

Features:
- Anti-pattern detection in skill code
- Safety prior enforcement
- Code review procedure checks
- Cognitive prior matching

CSV Sources:
- code_anti_patterns.csv: Dangerous code patterns to block
- code_safety_priors.csv: Security principles to enforce
- code_review_procedures.csv: Review pipeline steps
- cognitive_priors.csv: Cognitive biases/priors from CIM
"""

import csv
import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class ValidationIssue:
    """Represents a validation issue found in code."""
    id: str
    severity: str  # low, medium, high, critical
    pattern: str
    description: str
    remediation: str
    matched_text: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of code validation."""
    passed: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    applied_priors: List[str] = field(default_factory=list)
    review_steps_passed: List[str] = field(default_factory=list)
    score: float = 1.0  # 0.0 = fail, 1.0 = perfect
    
    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "score": self.score,
            "issue_count": len(self.issues),
            "issues": [
                {
                    "id": i.id,
                    "severity": i.severity,
                    "pattern": i.pattern,
                    "description": i.description,
                    "remediation": i.remediation,
                    "matched": i.matched_text
                }
                for i in self.issues
            ],
            "applied_priors": self.applied_priors,
            "review_steps_passed": self.review_steps_passed
        }


class SkillCIMLight:
    """
    Lightweight CIM for Skill validation.
    
    No AI/LLM calls - pure CSV-based pattern matching.
    Designed for speed and determinism.
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize with CSV data directory."""
        if data_dir is None:
            data_dir = Path(__file__).parent / "data"
        
        self.data_dir = Path(data_dir)
        
        # Load all CSVs
        self.anti_patterns = self._load_csv("code_anti_patterns.csv")
        self.safety_priors = self._load_csv("code_safety_priors.csv")
        self.review_procedures = self._load_csv("code_review_procedures.csv")
        self.cognitive_priors = self._load_csv("cognitive_priors.csv")
        self.cim_anti_patterns = self._load_csv("cim_anti_patterns.csv")
        
        # Build lookup indices
        self._build_indices()
    
    def _load_csv(self, filename: str) -> List[Dict]:
        """Load CSV file into list of dicts."""
        filepath = self.data_dir / filename
        if not filepath.exists():
            return []
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except Exception as e:
            print(f"[SkillCIMLight] Error loading {filename}: {e}")
            return []
    
    def _build_indices(self):
        """Build fast-lookup indices for patterns."""
        # Index anti-patterns by their pattern/signature
        self.pattern_index = {}
        for ap in self.anti_patterns:
            pattern_id = ap.get("id", ap.get("pattern_id", ""))
            if pattern_id:
                self.pattern_index[pattern_id] = ap
        
        # Index safety priors by their ID
        self.prior_index = {}
        for sp in self.safety_priors:
            prior_id = sp.get("prior_id", "")
            if prior_id:
                self.prior_index[prior_id] = sp
    
    # ================================================================
    # VALIDATION METHODS
    # ================================================================
    
    def validate_code(self, code: str) -> ValidationResult:
        """
        Run all safety checks against code.
        
        Args:
            code: Python source code to validate
            
        Returns:
            ValidationResult with pass/fail and issues
        """
        issues = []
        applied_priors = []
        
        # 1. Anti-Pattern Check
        ap_issues = self._check_anti_patterns(code)
        issues.extend(ap_issues)
        
        # 2. Safety Prior Check
        prior_issues, priors_applied = self._check_safety_priors(code)
        issues.extend(prior_issues)
        applied_priors.extend(priors_applied)
        
        # 3. CIM Anti-Pattern Check (broader patterns)
        cim_issues = self._check_cim_anti_patterns(code)
        issues.extend(cim_issues)
        
        # Calculate score
        severity_weights = {"low": 0.1, "medium": 0.25, "high": 0.5, "critical": 1.0}
        total_penalty = sum(
            severity_weights.get(i.severity.lower(), 0.25) 
            for i in issues
        )
        score = max(0.0, 1.0 - total_penalty)
        
        # Determine pass/fail
        critical_count = sum(1 for i in issues if i.severity.lower() == "critical")
        high_count = sum(1 for i in issues if i.severity.lower() == "high")
        
        passed = critical_count == 0 and high_count == 0
        
        return ValidationResult(
            passed=passed,
            issues=issues,
            applied_priors=applied_priors,
            score=score
        )
    
    def _check_anti_patterns(self, code: str) -> List[ValidationIssue]:
        """Check code against anti-patterns CSV."""
        issues = []
        
        for pattern in self.anti_patterns:
            # Map CSV columns to internal names
            pattern_id = pattern.get("pattern_id", pattern.get("id", "unknown"))
            # negative_example contains the bad code snippet
            bad_pattern = pattern.get("negative_example", pattern.get("bad_example", pattern.get("pattern", "")))
            # pattern_signature is often just the function name like "eval()"
            signature = pattern.get("pattern_signature", "")
            
            severity = pattern.get("risk_severity", pattern.get("severity", "medium"))
            description = pattern.get("trigger_condition", pattern.get("description", ""))
            remediation = pattern.get("refactoring_steps", pattern.get("remediation", ""))
            
            # 1. Simple string match (if bad_pattern is a meaningful string)
            # Filter out generic examples like "user_expression" or placeholder text
            is_generic = "user_" in bad_pattern or "..." in bad_pattern
            if bad_pattern and len(bad_pattern) > 3 and not is_generic and bad_pattern in code:
                issues.append(ValidationIssue(
                    id=pattern_id,
                    severity=severity,
                    pattern=bad_pattern,
                    description=description,
                    remediation=remediation,
                    matched_text=bad_pattern
                ))
                continue
            
            # 2. Regex patterns (e.g., for eval(), exec(), etc.)
            function_patterns = {
                "eval(": r"\beval\s*\(",
                "exec(": r"\bexec\s*\(",
                "os.system(": r"\bos\.system\s*\(",
                "pickle.load": r"\bpickle\.load\s*\(",
                "yaml.load(": r"\byaml\.load\s*\([^)]*\)(?!\s*,\s*Loader)",
                "input(": r"\binput\s*\(",
                "while True:": r"\bwhile\s+True\s*:",
                "__import__": r"\b__import__\s*\(",
                "subprocess.call(shell=True)": r"\bsubprocess\.call\(.*shell\s*=\s*True.*\)",
                "verify=False": r"verify\s*=\s*False",
                "0.0.0.0": r"0\.0\.0\.0"
            }
            
            # Match if the pattern signature or negative example mentions the function
            term_found = False
            for func, regex in function_patterns.items():
                # Check if this CSV row is about this function
                # We check pattern_signature (e.g., "eval()") or negative_example
                if (func in signature) or (func in bad_pattern):
                    if re.search(regex, code):
                        issues.append(ValidationIssue(
                            id=pattern_id,
                            severity=severity,
                            pattern=func,
                            description=description,
                            remediation=remediation,
                            matched_text=func
                        ))
                        term_found = True
                        break
            
            if term_found:
                continue
                
        return issues
    
    def _check_safety_priors(self, code: str) -> tuple[List[ValidationIssue], List[str]]:
        """Check code against safety priors."""
        issues = []
        applied = []
        
        for prior in self.safety_priors:
            prior_id = prior.get("prior_id", "")
            principle = prior.get("principle_name", "")
            enforcement = prior.get("enforcement_mechanism", "")
            failure_mode = prior.get("failure_mode", "")
            tags = prior.get("embedding_tags", "[]")
            
            # Check if this prior is relevant based on code content
            try:
                tag_list = ast.literal_eval(tags) if tags.startswith("[") else tags.split(",")
            except:
                tag_list = []
            
            prior_relevant = False
            for tag in tag_list:
                tag = str(tag).strip().lower()
                if tag and tag in code.lower():
                    prior_relevant = True
                    break
            
            if prior_relevant:
                applied.append(prior_id)
                
                # Check for violations based on failure mode keywords
                if failure_mode:
                    failure_keywords = ["rce", "injection", "crash", "hang", "leak"]
                    for kw in failure_keywords:
                        if kw in failure_mode.lower():
                            # This is an important prior - check more carefully
                            if self._prior_might_be_violated(code, prior_id):
                                issues.append(ValidationIssue(
                                    id=prior_id,
                                    severity="high",
                                    pattern=principle,
                                    description=f"Potential violation of: {principle}",
                                    remediation=enforcement
                                ))
        
        return issues, applied
    
    def _prior_might_be_violated(self, code: str, prior_id: str) -> bool:
        """Heuristic check if a prior might be violated."""
        # PRIOR-001: Sandbox Isolation
        if prior_id == "PRIOR-001":
            dangerous = ["os.system", "subprocess.call", "socket.", "__import__"]
            return any(d in code for d in dangerous)
        
        # PRIOR-002: Deterministic Execution
        if prior_id == "PRIOR-002":
            random_calls = ["random.", "time.time()", "uuid.uuid4"]
            return any(r in code for r in random_calls)
        
        # PRIOR-003: No Implicit Side-Effects
        if prior_id == "PRIOR-003":
            side_effects = ["open(", "write(", "requests.", "urllib."]
            return any(s in code for s in side_effects)
        
        # PRIOR-004: Input Sanitization
        if prior_id == "PRIOR-004":
            if "input(" in code or "request." in code:
                # Check if there's validation nearby
                if "validate" not in code.lower() and "schema" not in code.lower():
                    return True
        
        return False
    
    def _check_cim_anti_patterns(self, code: str) -> List[ValidationIssue]:
        """Check against broader CIM anti-patterns (reasoning fallacies)."""
        issues = []
        
        # These are more about reasoning than code, but some apply
        for pattern in self.cim_anti_patterns:
            name = pattern.get("name", "")
            keywords = pattern.get("keywords", "").split(",")
            severity = pattern.get("severity", "medium")
            description = pattern.get("description", "")
            mitigation = pattern.get("mitigation", "")
            
            # Check if any keyword appears in comments/docstrings
            for kw in keywords:
                kw = kw.strip().lower()
                if kw and len(kw) > 3:  # Skip very short keywords
                    if kw in code.lower():
                        # Only flag if it's in a comment or string
                        if f'"{kw}' in code.lower() or f"'{kw}" in code.lower() or f"# {kw}" in code.lower():
                            issues.append(ValidationIssue(
                                id=f"CIM-{name[:10]}",
                                severity="low",  # Downgrade - these are hints
                                pattern=name,
                                description=description,
                                remediation=mitigation,
                                matched_text=kw
                            ))
                            break
        
        return issues
    
    # ================================================================
    # UTILITY METHODS
    # ================================================================
    
    def get_applicable_priors(self, context: str) -> List[Dict]:
        """
        Get safety priors relevant to a given context.
        
        Args:
            context: Description of what the skill does
            
        Returns:
            List of relevant safety priors
        """
        relevant = []
        context_lower = context.lower()
        
        for prior in self.safety_priors:
            tags = prior.get("embedding_tags", "[]")
            try:
                tag_list = ast.literal_eval(tags) if tags.startswith("[") else tags.split(",")
            except:
                tag_list = []
            
            for tag in tag_list:
                tag = str(tag).strip().lower()
                if tag and tag in context_lower:
                    relevant.append(prior)
                    break
        
        return relevant
    
    def get_review_checklist(self) -> List[Dict]:
        """Get the code review procedure checklist."""
        return [
            {
                "check_id": proc.get("check_id", ""),
                "phase": proc.get("phase", ""),
                "instruction": proc.get("instruction_prompt", ""),
                "pass_criteria": proc.get("pass_criteria", "")
            }
            for proc in self.review_procedures
        ]
    
    def get_math_tools(self) -> List[Dict]:
        """Get available causal math tools (for skill use)."""
        math_csv = self._load_csv("causal_math_registry.csv")
        return [
            {
                "tool_id": t.get("tool_id", ""),
                "name": t.get("tool_name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters_schema", "{}"),
                "usage": t.get("usage_example", "")
            }
            for t in math_csv
        ]


# ================================================================
# SINGLETON INSTANCE
# ================================================================

_cim_instance: Optional[SkillCIMLight] = None

def get_skill_cim() -> SkillCIMLight:
    """Get singleton instance of SkillCIMLight."""
    global _cim_instance
    if _cim_instance is None:
        _cim_instance = SkillCIMLight()
    return _cim_instance
