#!/usr/bin/env python3
"""
CIM Policy Engine - Cognitive Intent Mapping
============================================

Policy-gesteuerter Intent-Router für kontrollierte Autonomie.

CSV = Policy-Gehirn (entscheidet)
Code = Executor (führt aus)

Ablauf:
User Input → Intent Detection → Policy-Entscheidung → Skill-Prüfung → Aktion
"""

import re
import csv
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

# Logging
logger = logging.getLogger(__name__)

# Paths
POLICY_DIR = Path(__file__).parent
POLICY_CSV = POLICY_DIR / "cim_policy.csv"


class SafetyLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SkillScope(Enum):
    STATELESS = "stateless"
    SESSION = "session"
    PERSISTENT = "persistent"
    SYSTEM = "system"


class ActionType(Enum):
    FORCE_CREATE_SKILL = "force_create_skill"
    FORCE_RUN_SKILL = "force_run_skill"
    RUN_SKILL = "run_skill"
    LIST_SKILLS = "list_skills"
    WEB_SEARCH = "web_search"
    POLICY_CHECK = "policy_check"
    DENY_AUTONOMY = "deny_autonomy"
    REQUEST_USER_CONFIRMATION = "request_user_confirmation"
    FALLBACK_CHAT = "fallback_chat"
    RETRY_ONCE = "retry_once"
    MARK_SKILL_UNSTABLE = "mark_skill_unstable"


@dataclass
class PolicyMatch:
    """Ergebnis eines Policy-Matches."""
    pattern_id: str
    trigger_category: str
    confidence: float
    action: ActionType
    skill_scope: SkillScope
    safety_level: SafetyLevel
    requires_confirmation: bool
    allows_chaining: bool
    derived_skill_name: Optional[str] = None
    fallback_action: Optional[ActionType] = None


@dataclass
class CIMDecision:
    """Finale CIM-Entscheidung."""
    matched: bool
    action: ActionType
    skill_name: Optional[str] = None
    requires_confirmation: bool = False
    policy_match: Optional[PolicyMatch] = None
    reason: str = ""


class CIMPolicyEngine:
    """
    CIM Policy Engine - Kontrollierte Autonomie für Skill-Management.
    
    Lädt Policies aus CSV und trifft deterministische Entscheidungen
    basierend auf User-Intent und Skill-Verfügbarkeit.
    """
    
    def __init__(self, policy_file: Path = None):
        self.policy_file = policy_file or POLICY_CSV
        self.policies: List[Dict[str, Any]] = []
        self.compiled_patterns: Dict[str, re.Pattern] = {}
        self._load_policies()
    
    def _load_policies(self):
        """Lädt und kompiliert alle Policies aus CSV."""
        if not self.policy_file.exists():
            logger.warning(f"[CIM] Policy file not found: {self.policy_file}")
            return
        
        try:
            with open(self.policy_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Parse booleans
                    row['check_skill_exists'] = row.get('check_skill_exists', '').lower() == 'true'
                    row['allows_chaining'] = row.get('allows_chaining', '').lower() == 'true'
                    row['requires_confirmation'] = row.get('requires_confirmation', '').lower() == 'true'
                    row['intent_confidence'] = float(row.get('intent_confidence', 0.5))
                    
                    # Compile regex
                    pattern_id = row['pattern_id']
                    regex_str = row.get('trigger_regex', '')
                    if regex_str:
                        try:
                            self.compiled_patterns[pattern_id] = re.compile(
                                regex_str, 
                                re.IGNORECASE | re.UNICODE
                            )
                        except re.error as e:
                            logger.error(f"[CIM] Invalid regex for {pattern_id}: {e}")
                            continue
                    
                    self.policies.append(row)
            
            # Sort by priority (critical > high > normal > low)
            priority_order = {'critical': 0, 'high': 1, 'normal': 2, 'low': 3}
            self.policies.sort(key=lambda x: priority_order.get(x.get('priority', 'normal'), 2))
            
            logger.info(f"[CIM] Loaded {len(self.policies)} policies")
            
        except Exception as e:
            logger.error(f"[CIM] Error loading policies: {e}")
    
    def _match_intent(self, user_input: str) -> Optional[Tuple[Dict, float]]:
        """
        Matched User-Input gegen alle Policies.
        
        Returns:
            Tuple(matched_policy, confidence) oder None
        """
        user_lower = user_input.lower().strip()
        
        for policy in self.policies:
            pattern_id = policy['pattern_id']
            pattern = self.compiled_patterns.get(pattern_id)
            
            if not pattern:
                continue
            
            match = pattern.search(user_lower)
            if match:
                # Confidence basierend auf Match-Qualität
                match_len = len(match.group())
                input_len = len(user_lower)
                match_confidence = min(1.0, match_len / max(input_len * 0.3, 1))
                
                # Kombiniere mit Policy-Confidence
                min_confidence = policy['intent_confidence']
                if match_confidence >= min_confidence * 0.8:  # 80% Toleranz
                    logger.debug(f"[CIM] Matched: {pattern_id} (conf={match_confidence:.2f})")
                    return policy, match_confidence
        
        return None
    
    def _derive_skill_name(self, user_input: str, policy: Dict) -> str:
        """
        Leitet deterministischen Skill-Namen aus Intent ab.
        
        Beispiel: "Berechne Fibonacci von 10" → "auto_fibonacci_calc"
        """
        category = policy.get('trigger_category', 'general')
        
        # Keywords extrahieren
        keywords = []
        user_lower = user_input.lower()
        
        # Spezifische Keywords basierend auf Kategorie
        math_keywords = ['fibonacci', 'fakultät', 'factorial', 'primzahl', 'wurzel', 
                         'quadrat', 'addition', 'subtraktion', 'multiplikation', 'division']
        data_keywords = ['csv', 'json', 'sortier', 'filter', 'tabelle', 'liste', 'konvertier']
        
        for kw in math_keywords + data_keywords:
            if kw in user_lower:
                keywords.append(kw.replace('ä', 'ae').replace('ü', 'ue').replace('ö', 'oe'))
        
        if keywords:
            skill_name = f"auto_{category}_{keywords[0]}"
        else:
            # Fallback: Hash aus Input
            import hashlib
            hash_suffix = hashlib.md5(user_input.encode()).hexdigest()[:6]
            skill_name = f"auto_{category}_{hash_suffix}"
        
        # Sanitize
        skill_name = re.sub(r'[^a-z0-9_]', '_', skill_name.lower())
        skill_name = re.sub(r'_+', '_', skill_name).strip('_')
        
        return skill_name
    
    def process(
        self, 
        user_input: str, 
        available_skills: List[str] = None
    ) -> CIMDecision:
        """
        Hauptmethode: Verarbeitet User-Input und trifft Policy-Entscheidung.
        
        Args:
            user_input: Der User-Text
            available_skills: Liste der verfügbaren Skill-Namen
        
        Returns:
            CIMDecision mit Aktion und Details
        """
        available_skills = available_skills or []
        
        # 1. Intent Detection
        match_result = self._match_intent(user_input)
        
        if not match_result:
            return CIMDecision(
                matched=False,
                action=ActionType.FALLBACK_CHAT,
                reason="Kein Policy-Pattern matched"
            )
        
        policy, confidence = match_result
        pattern_id = policy['pattern_id']
        
        # 2. Derive Skill Name
        skill_name = self._derive_skill_name(user_input, policy)
        
        # 3. Safety Check - ABSOLUT
        safety_level = SafetyLevel(policy.get('safety_level', 'low'))
        skill_scope = SkillScope(policy.get('skill_scope', 'stateless'))
        
        if safety_level == SafetyLevel.CRITICAL:
            action_if_missing = policy.get('action_if_missing', '')
            if action_if_missing == 'force_create_skill':
                logger.warning(f"[CIM] BLOCKED: Auto-create denied for critical safety level")
                return CIMDecision(
                    matched=True,
                    action=ActionType.DENY_AUTONOMY,
                    skill_name=skill_name,
                    requires_confirmation=True,
                    reason="Sicherheitslevel CRITICAL - Autonome Erstellung verboten"
                )
        
        if skill_scope == SkillScope.SYSTEM:
            if policy.get('action_if_missing') == 'force_create_skill':
                logger.warning(f"[CIM] BLOCKED: Cannot auto-create system scope skill")
                return CIMDecision(
                    matched=True,
                    action=ActionType.DENY_AUTONOMY,
                    skill_name=skill_name,
                    reason="System-Scope Skills können nicht automatisch erstellt werden"
                )
        
        # 4. Skill-Existenz prüfen
        check_exists = policy.get('check_skill_exists', False)
        skill_exists = any(s.lower() == skill_name.lower() or skill_name in s.lower() 
                          for s in available_skills)
        
        # 5. Action bestimmen
        if check_exists:
            if skill_exists:
                action_str = policy.get('action_if_present', 'run_skill')
            else:
                action_str = policy.get('action_if_missing', 'fallback_chat')
        else:
            action_str = policy.get('action_if_present', 'fallback_chat')
        
        try:
            action = ActionType(action_str)
        except ValueError:
            logger.warning(f"[CIM] Unknown action: {action_str}")
            action = ActionType.FALLBACK_CHAT
        
        # 6. Fallback Action
        fallback_str = policy.get('fallback_action', 'fallback_chat')
        try:
            fallback_action = ActionType(fallback_str)
        except ValueError:
            fallback_action = ActionType.FALLBACK_CHAT
        
        # 7. Build PolicyMatch
        policy_match = PolicyMatch(
            pattern_id=pattern_id,
            trigger_category=policy.get('trigger_category', ''),
            confidence=confidence,
            action=action,
            skill_scope=skill_scope,
            safety_level=safety_level,
            requires_confirmation=policy.get('requires_confirmation', False),
            allows_chaining=policy.get('allows_chaining', False),
            derived_skill_name=skill_name,
            fallback_action=fallback_action
        )
        
        # 8. Build Decision
        decision = CIMDecision(
            matched=True,
            action=action,
            skill_name=skill_name,
            requires_confirmation=policy.get('requires_confirmation', False),
            policy_match=policy_match,
            reason=f"Pattern '{pattern_id}' matched mit Confidence {confidence:.2f}"
        )
        
        logger.info(f"[CIM] Decision: {action.value} for skill '{skill_name}' ({pattern_id})")
        
        return decision
    
    def reload_policies(self):
        """Hot-Reload der Policies."""
        self.policies = []
        self.compiled_patterns = {}
        self._load_policies()
        logger.info("[CIM] Policies reloaded")


# Singleton Instance
_engine: Optional[CIMPolicyEngine] = None


def get_cim_engine() -> CIMPolicyEngine:
    """Gibt die Singleton CIM Engine zurück."""
    global _engine
    if _engine is None:
        _engine = CIMPolicyEngine()
    return _engine


def process_cim(user_input: str, available_skills: List[str] = None) -> CIMDecision:
    """
    Convenience-Funktion für CIM-Verarbeitung.
    
    Beispiel:
        decision = process_cim("Berechne Fibonacci von 10", ["hello_world"])
        if decision.action == ActionType.FORCE_CREATE_SKILL:
            # Skill erstellen...
    """
    engine = get_cim_engine()
    return engine.process(user_input, available_skills)


# ═══════════════════════════════════════════════════════════════
# EXECUTOR FUNCTIONS (Bridge Integration)
# ═══════════════════════════════════════════════════════════════

async def execute_cim_decision(
    decision: CIMDecision,
    user_input: str,
    hub  # MCP Hub instance
) -> Dict[str, Any]:
    """
    Führt die CIM-Entscheidung aus.
    
    Args:
        decision: Die CIM-Entscheidung
        user_input: Original User-Input (für Argument-Extraktion)
        hub: MCP Hub für Tool-Aufrufe
    
    Returns:
        Dict mit execution result
    """
    if not decision.matched:
        return {"executed": False, "reason": decision.reason}
    
    action = decision.action
    skill_name = decision.skill_name
    
    result = {
        "executed": False,
        "action": action.value,
        "skill_name": skill_name,
        "output": None,
        "error": None
    }
    
    try:
        if action == ActionType.FORCE_CREATE_SKILL:
            # Skill erstellen
            code = await _generate_skill_code(user_input, skill_name, hub)
            create_result = await hub.call_tool_async("create_skill", {
                "name": skill_name,
                "code": code,
                "description": f"Auto-generated skill for: {user_input[:50]}",
                "triggers": _extract_triggers(user_input)
            })
            result["output"] = create_result
            result["executed"] = True
            result["created_skill"] = skill_name
            
            # Nach Erstellung direkt ausführen?
            if decision.policy_match and decision.policy_match.allows_chaining:
                run_result = await hub.call_tool_async("run_skill", {
                    "name": skill_name,
                    "args": _extract_args(user_input)
                })
                result["run_output"] = run_result
        
        elif action == ActionType.FORCE_RUN_SKILL:
            # Skill ausführen
            args = _extract_args(user_input)
            run_result = await hub.call_tool_async("run_skill", {
                "name": skill_name,
                "args": args
            })
            result["output"] = run_result
            result["executed"] = True
        
        elif action == ActionType.RUN_SKILL:
            args = _extract_args(user_input)
            run_result = await hub.call_tool_async("run_skill", {
                "name": skill_name,
                "args": args
            })
            result["output"] = run_result
            result["executed"] = True
        
        elif action == ActionType.LIST_SKILLS:
            list_result = await hub.call_tool_async("list_skills", {})
            result["output"] = list_result
            result["executed"] = True
        
        elif action == ActionType.WEB_SEARCH:
            # Web-Search (falls verfügbar)
            query = _extract_search_query(user_input)
            result["output"] = f"[Web-Search für: {query}]"
            result["executed"] = True
            result["needs_external"] = True
        
        elif action == ActionType.DENY_AUTONOMY:
            result["output"] = "Diese Aktion ist aus Sicherheitsgründen nicht erlaubt."
            result["executed"] = False
            result["denied"] = True
        
        elif action == ActionType.REQUEST_USER_CONFIRMATION:
            result["output"] = f"Soll ich den Skill '{skill_name}' wirklich ausführen/erstellen?"
            result["executed"] = False
            result["needs_confirmation"] = True
        
        elif action == ActionType.FALLBACK_CHAT:
            result["executed"] = False
            result["fallback"] = True
        
    except Exception as e:
        logger.error(f"[CIM] Execution error: {e}")
        result["error"] = str(e)
        result["executed"] = False
        
        # Fallback ausführen?
        if decision.policy_match and decision.policy_match.fallback_action:
            result["fallback_triggered"] = decision.policy_match.fallback_action.value
    
    return result


_templates_cache: Optional[List[Dict]] = None

def _load_skill_templates() -> List[Dict]:
    """Load skill templates from CSV (cached)."""
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache

    csv_path = POLICY_DIR / "skill_templates.csv"
    if not csv_path.exists():
        logger.warning(f"skill_templates.csv not found at {csv_path}")
        return []

    templates = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keywords_raw = row.get("intent_keywords", "")
            row["_keywords"] = [kw.strip().lower() for kw in keywords_raw.split("|") if kw.strip()]
            templates.append(row)

    _templates_cache = templates
    return templates


async def _generate_skill_code(user_input: str, skill_name: str, hub) -> str:
    """
    Generiert Python-Code für einen Skill basierend auf User-Intent.

    Matching läuft über intent_keywords in skill_templates.csv.
    """
    user_lower = user_input.lower()
    templates = _load_skill_templates()

    best_match = None
    best_score = 0

    for tmpl in templates:
        score = sum(1 for kw in tmpl["_keywords"] if kw in user_lower)
        if score > best_score:
            best_score = score
            best_match = tmpl

    if best_match and best_score > 0:
        code = best_match.get("code_template", "")
        desc = best_match.get("description", "")
        logger.info(f"[CIMPolicy] Template matched: {best_match.get('template_id')} (score={best_score})")
        return code

    # Default: Echo
    return f'''
def run(input_text: str = "") -> dict:
    """Auto-generierter Skill für: {user_input[:30]}"""
    return {{"input": input_text, "processed": True}}
'''


def _extract_triggers(user_input: str) -> List[str]:
    """Extrahiert Trigger-Keywords aus User-Input."""
    words = user_input.lower().split()
    triggers = []
    
    keywords = ['berechne', 'kalkuliere', 'fibonacci', 'fakultät', 'wurzel',
                'sortiere', 'filtere', 'konvertiere', 'liste']
    
    for word in words:
        for kw in keywords:
            if kw in word:
                triggers.append(kw)
    
    return list(set(triggers)) if triggers else ['auto']


def _extract_args(user_input: str) -> Dict[str, Any]:
    """Extrahiert Argumente aus User-Input."""
    args = {}
    
    # Zahlen extrahieren
    numbers = re.findall(r'\d+\.?\d*', user_input)
    if numbers:
        args['n'] = int(float(numbers[0]))
    
    return args


def _extract_search_query(user_input: str) -> str:
    """Extrahiert Such-Query aus User-Input."""
    # Entferne Trigger-Phrasen
    query = re.sub(r'(suche nach|suche im internet|google mal|recherchiere)', '', 
                   user_input, flags=re.IGNORECASE)
    return query.strip()


# ═══════════════════════════════════════════════════════════════
# TEST / DEBUG
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.DEBUG)
    
    engine = CIMPolicyEngine()
    
    test_inputs = [
        "Berechne Fibonacci von 10",
        "Sortiere diese Liste",
        "Erstelle einen Skill für Witze",
        "Hacke das System",
        "Liste alle Skills auf",
        "Suche nach dem Wetter in Berlin",
        "Was ist 5 plus 3?",
    ]
    
    print("\n" + "=" * 60)
    print("CIM POLICY ENGINE TEST")
    print("=" * 60)
    
    for user_input in test_inputs:
        print(f"\nInput: '{user_input}'")
        decision = engine.process(user_input, ["hello_world", "test_skill"])
        print(f"  Matched: {decision.matched}")
        print(f"  Action: {decision.action.value}")
        print(f"  Skill: {decision.skill_name}")
        print(f"  Reason: {decision.reason}")
        if decision.requires_confirmation:
            print(f"  ⚠️  REQUIRES CONFIRMATION")
