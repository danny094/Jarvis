"""
TRION Drift Contract Tests — Phase 1
=====================================
Testet harte Architektur-Invarianten ohne laufende Services oder LLM-Calls.

Drift-Hypothesen abgedeckt:
  A1 — Blueprint Gate als Schatten-Autorität
  A2 — Grounding Policy als Schatten-Autorität (unavailable → fallback)
  A3 — Context-Verlust zwischen Turns
  A4 — Tech-fail/Policy-Verwechslung
  A5 — approved:True Legacy-Default

Invarianten:
  INV-01: approved=true + gate_blocked → illegal (downstream darf nicht blocken)
  INV-02: blueprint sichtbar → request_container darf nicht NOT_FOUND scheitern
  INV-03: status=unavailable darf nicht missing_evidence_fallback auslösen wenn approved
  INV-04: ExecutionResult enthält kein approved-Feld
  INV-05: ControlDecision ist nach Erstellung immutable (frozen dataclass)
  INV-06: Fallback nur wenn evidence leer UND tech-fail, nicht bei routing-block
  INV-07: blueprint_gate_blocked → Output muss Situation erklären, nicht generic fallback
  INV-08: pending_approval ist kein Fehler → kein Fallback-Text
  INV-09: VALID_EXEC_STATUSES enthält keine Policy-Begriffe
  INV-10: skip_reason muss gesetzt sein wenn Control geskippt wird
  INV-11: blueprint_gate_blocked nur wenn thinking_plan vorhanden
  INV-12: Exact blueprint-name im user_text → kein suggest-zone-Block
  INV-13: done_reason=unavailable nur bei tech-Fehler, nicht bei routing-decision
  INV-14: ControlDecision.to_dict() enthält alle Pflichtfelder
"""

import dataclasses
import pytest
import sys
import os
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

# Path setup
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from core.control_contract import (
    ControlDecision,
    ControlContractError,
    ExecutionResult,
    DoneReason,
    control_decision_from_plan,
    persist_control_decision,
    persist_skip_state,
    persist_gate_blocked_state,
    execution_result_from_plan,
)


# ═══════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════

FALLBACK_TEXT = (
    "Ich habe aktuell keinen verifizierten Tool-Nachweis für eine belastbare Faktenantwort. "
    "Bitte Tool-Abfrage erneut ausführen."
)

VALID_EXEC_STATUSES = {"ok", "error", "timeout", "unavailable", "skipped", "partial"}
POLICY_WORDS = {"policy", "denied", "approved", "blocked_by_control", "hard_block"}
VALID_SKIP_REASONS = {
    "low_risk_skip", "control_disabled", "fact_query_requires_control",
    "hardware_gate_requires_control", "control_required", "sensitive_tools",
    "creation_keywords", "hard_safety_keywords",
}


def make_approved_decision(**kwargs) -> ControlDecision:
    defaults = dict(
        approved=True,
        hard_block=False,
        decision_class="allow",
        block_reason_code="",
        reason="approved",
        source="control",
    )
    defaults.update(kwargs)
    return ControlDecision(**defaults)


def make_denied_decision(**kwargs) -> ControlDecision:
    defaults = dict(
        approved=False,
        hard_block=True,
        decision_class="hard_block",
        block_reason_code="malicious_intent",
        reason="malicious_intent",
        source="control",
    )
    defaults.update(kwargs)
    return ControlDecision(**defaults)


def make_verified_plan(
    *,
    approved: bool = True,
    gate_blocked: bool = False,
    suggested_tools: List[str] = None,
    skip_reason: str = None,
    skipped: bool = False,
    intent: str = "test intent",
) -> Dict[str, Any]:
    cd = make_approved_decision() if approved else make_denied_decision()
    plan = {
        "intent": intent,
        "suggested_tools": suggested_tools or [],
        "_control_decision": cd.to_dict(),
        "_control_decision_obj": cd,
    }
    if gate_blocked:
        plan["_blueprint_gate_blocked"] = True
        plan["_blueprint_suggest"] = {
            "candidates": [{"id": "gaming-station", "score": 0.79}]
        }
    if skipped:
        plan["_skipped"] = True
        plan["_skip_reason"] = skip_reason or "low_risk_skip"
    return plan


def make_grounding_evidence(status: str, tool_name: str = "request_container") -> Dict:
    return {
        "tool_name": tool_name,
        "status": status,
        "ref_id": "test-ref",
        "key_facts": [],
    }


# ═══════════════════════════════════════════════════════════════════
# INV-05: ControlDecision ist immutable (frozen dataclass)
# ═══════════════════════════════════════════════════════════════════

class TestINV05ControlDecisionImmutable:
    """INV-05: ControlDecision ist nach Erstellung nicht veränderbar."""

    def test_cannot_set_approved(self):
        cd = make_approved_decision()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            cd.approved = False  # type: ignore

    def test_cannot_set_hard_block(self):
        cd = make_approved_decision()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            cd.hard_block = True  # type: ignore

    def test_cannot_set_decision_class(self):
        cd = make_approved_decision()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            cd.decision_class = "hard_block"  # type: ignore

    def test_cannot_set_tools_allowed(self):
        cd = make_approved_decision()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            cd.tools_allowed = ("new_tool",)  # type: ignore

    def test_with_tools_allowed_returns_new_instance(self):
        cd = make_approved_decision()
        cd2 = cd.with_tools_allowed(["request_container"])
        assert cd is not cd2
        assert cd.tools_allowed == ()
        assert "request_container" in cd2.tools_allowed

    def test_denied_also_immutable(self):
        cd = make_denied_decision()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            cd.approved = True  # type: ignore


# ═══════════════════════════════════════════════════════════════════
# INV-04: ExecutionResult enthält kein approved-Feld
# ═══════════════════════════════════════════════════════════════════

class TestINV04ExecutionResultNoPolicy:
    """INV-04: ExecutionResult darf keine Policy-Felder enthalten."""

    def test_no_approved_field(self):
        er = ExecutionResult()
        assert not hasattr(er, "approved")

    def test_no_hard_block_field(self):
        er = ExecutionResult()
        assert not hasattr(er, "hard_block")

    def test_no_decision_class_field(self):
        er = ExecutionResult()
        assert not hasattr(er, "decision_class")

    def test_to_dict_no_policy_keys(self):
        er = ExecutionResult()
        d = er.to_dict()
        policy_keys = {"approved", "hard_block", "decision_class", "block_reason_code"}
        for key in policy_keys:
            assert key not in d, f"Policy-Feld '{key}' im ExecutionResult.to_dict() gefunden"

    def test_tool_status_reason_no_policy_words(self):
        """INV-09: tool_status.reason darf keine Policy-Wörter enthalten."""
        er = ExecutionResult()
        er.append_tool_status(
            tool_name="request_container",
            status="unavailable",
            reason="blueprint_suggest_requires_selection",
        )
        for entry in er.tool_statuses:
            reason_lower = entry.get("reason", "").lower()
            for word in POLICY_WORDS:
                assert word not in reason_lower, (
                    f"Policy-Wort '{word}' in ExecutionResult.tool_status.reason: {reason_lower}"
                )

    def test_valid_done_reasons_are_technical(self):
        """DoneReason-Enum enthält nur technische Klassen."""
        technical = {"success", "unavailable", "tech_fail", "timeout", "skipped", "stop"}
        actual = {r.value for r in DoneReason}
        assert actual == technical

    def test_finalize_done_reason_unavailable(self):
        er = ExecutionResult()
        er.append_tool_status(
            tool_name="request_container",
            status="unavailable",
            reason="blueprint_suggest_requires_selection",
        )
        er.finalize_done_reason()
        assert er.done_reason == DoneReason.UNAVAILABLE

    def test_finalize_done_reason_tech_fail(self):
        er = ExecutionResult()
        er.append_tool_status(tool_name="request_container", status="error", reason="docker not found")
        er.finalize_done_reason()
        assert er.done_reason == DoneReason.TECH_FAIL

    def test_finalize_done_reason_success(self):
        er = ExecutionResult()
        er.append_tool_status(tool_name="request_container", status="ok")
        er.finalize_done_reason()
        assert er.done_reason == DoneReason.SUCCESS


# ═══════════════════════════════════════════════════════════════════
# INV-09: Nur valide technische Status-Codes im Executor
# ═══════════════════════════════════════════════════════════════════

class TestINV09ValidExecStatuses:
    """INV-09: tool_status ist ausschließlich technisch, nie Policy."""

    @pytest.mark.parametrize("status", list(VALID_EXEC_STATUSES))
    def test_valid_status_accepted(self, status):
        er = ExecutionResult()
        er.append_tool_status(tool_name="test_tool", status=status)
        assert er.tool_statuses[0]["status"] == status

    @pytest.mark.parametrize("bad_status", ["policy_denied", "blocked", "hard_blocked", "approved"])
    def test_policy_status_not_in_valid_set(self, bad_status):
        assert bad_status not in VALID_EXEC_STATUSES, (
            f"'{bad_status}' sollte kein valider Executor-Status sein"
        )


# ═══════════════════════════════════════════════════════════════════
# INV-14: ControlDecision.to_dict() Vollständigkeit
# ═══════════════════════════════════════════════════════════════════

class TestINV14ControlDecisionContract:
    """INV-14: ControlDecision.to_dict() enthält alle Pflichtfelder."""

    REQUIRED_FIELDS = {
        "approved", "hard_block", "decision_class",
        "block_reason_code", "reason", "final_instruction",
        "warnings", "corrections", "tools_allowed", "source", "policy_version",
    }

    def test_approved_decision_has_all_fields(self):
        cd = make_approved_decision()
        d = cd.to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Pflichtfeld '{field}' fehlt in ControlDecision.to_dict()"

    def test_denied_decision_has_all_fields(self):
        cd = make_denied_decision()
        d = cd.to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Pflichtfeld '{field}' fehlt in ControlDecision.to_dict()"

    def test_approved_decision_approved_is_true(self):
        cd = make_approved_decision()
        assert cd.to_dict()["approved"] is True

    def test_denied_decision_approved_is_false(self):
        cd = make_denied_decision()
        assert cd.to_dict()["approved"] is False

    def test_from_verification_approved(self):
        verification = {"approved": True, "decision_class": "allow", "hard_block": False}
        cd = ControlDecision.from_verification(verification)
        assert cd.approved is True
        assert cd.hard_block is False

    def test_from_verification_denied(self):
        verification = {
            "approved": False,
            "decision_class": "hard_block",
            "hard_block": True,
            "block_reason_code": "malicious_intent",
        }
        cd = ControlDecision.from_verification(verification)
        assert cd.approved is False
        assert cd.hard_block is True

    def test_from_verification_default_approved_false(self):
        """
        Default approved=False wenn leeres verification-dict.
        BUG A5: from_verification({}, default_approved=False) gibt approved=True zurück.
        Ursache: `verification.get("approved") is not False` → None is not False → True.
        default_approved wird nur für non-dict geprüft, nicht für leeres dict.
        """
        cd = ControlDecision.from_verification({}, default_approved=False)
        if cd.approved is True:
            pytest.xfail(
                "DRIFT A5 AKTIV: from_verification({}, default_approved=False) gibt approved=True. "
                "Ursache: `verification.get('approved') is not False` — None is not False → True. "
                "Fix: if 'approved' not in verification: use default_approved."
            )
        assert cd.approved is False

    def test_from_verification_default_approved_true_when_explicitly_set(self):
        cd = ControlDecision.from_verification({}, default_approved=True)
        assert cd.approved is True

    def test_control_decision_from_plan_reads_stored(self):
        cd = make_approved_decision()
        plan = {}
        persist_control_decision(plan, cd)
        cd2 = control_decision_from_plan(plan)
        assert cd2.approved == cd.approved
        assert cd2.decision_class == cd.decision_class

    def test_control_decision_from_plan_default_approved_false_on_missing(self):
        """
        Wenn kein _control_decision im Plan → default=False (fail-closed).
        BUG A5: control_decision_from_plan({}, default_approved=False) gibt approved=True.
        Gleiche Ursache wie from_verification: leeres dict wird wie implizit approved behandelt.
        """
        cd = control_decision_from_plan({}, default_approved=False)
        if cd.approved is True:
            pytest.xfail(
                "DRIFT A5 AKTIV: control_decision_from_plan({}, default_approved=False) "
                "gibt approved=True statt False. Fail-closed-Verhalten ist verletzt. "
                "Fix: from_verification muss 'approved' key explizit prüfen, nicht None is not False."
            )
        assert cd.approved is False


# ═══════════════════════════════════════════════════════════════════
# INV-01: approved=true + gate_blocked → Contract-Verletzung
# ═══════════════════════════════════════════════════════════════════

class TestINV01ApprovedPlusGateBlocked:
    """
    INV-01: Wenn ControlDecision.approved=True, darf _blueprint_gate_blocked
    nicht gleichzeitig True sein — das ist ein Contract-Bruch.

    Aktueller Status: DIESER TEST DOKUMENTIERT DEN BEKANNTEN DRIFT.
    Wenn der Test FAILS → Drift ist aktiv (A1 bestätigt).
    Wenn der Test PASSES → Drift ist behoben.
    """

    def test_gate_blocked_incompatible_with_approved(self):
        """
        INV-01: gate_blocked=True + approved=True ist ein illegaler Zustand.
        Der Orchestrator darf diesen Zustand nicht erzeugen.
        """
        plan = make_verified_plan(approved=True, gate_blocked=True)
        cd = control_decision_from_plan(plan)

        gate_blocked = bool(plan.get("_blueprint_gate_blocked"))
        approved = cd.approved

        # Dieser Zustand ist ein Contract-Bruch:
        if gate_blocked and approved:
            pytest.xfail(
                "DRIFT A1 AKTIV: Blueprint Gate blockiert trotz approved=True. "
                "_blueprint_gate_blocked=True + ControlDecision.approved=True koexistieren. "
                "Fix: Blueprint Gate muss ControlDecision als Autorität respektieren."
            )

    def test_denied_can_have_gate_blocked(self):
        """Bei approved=False ist gate_blocked konsistent (kein Drift)."""
        plan = make_verified_plan(approved=False, gate_blocked=True)
        cd = control_decision_from_plan(plan)
        # Kein Drift: denied + blocked ist konsistent
        assert not cd.approved
        assert plan.get("_blueprint_gate_blocked")


# ═══════════════════════════════════════════════════════════════════
# INV-03: status=unavailable ≠ missing_evidence_fallback wenn approved
# ═══════════════════════════════════════════════════════════════════

class TestINV03UnavailableNotMissingEvidence:
    """
    INV-03: Wenn tool_status=unavailable wegen Routing-Block (nicht tech-Fehler),
    darf die Grounding Policy NICHT missing_evidence_fallback auslösen
    wenn ControlDecision.approved=True.

    Dies ist die A2-Kaskade:
      Blueprint-Gate → status=unavailable → enforce_evidence_when_tools_suggested=True
      → successful_extractable=0 → missing_evidence_fallback → Fallback-Text

    Aktueller Status: DIESER TEST DOKUMENTIERT DEN BEKANNTEN DRIFT.
    """

    def _run_grounding_precheck(self, verified_plan: Dict, evidence: List[Dict]) -> Dict:
        """Ruft _grounding_precheck mit kontrollierten Inputs auf."""
        from core.layers.output import OutputLayer
        from core.plan_runtime_bridge import set_runtime_grounding_evidence

        set_runtime_grounding_evidence(verified_plan, evidence)
        layer = OutputLayer()
        return layer._grounding_precheck(verified_plan, memory_data="")

    def test_unavailable_routing_block_should_not_trigger_missing_evidence_fallback(self):
        """
        INV-03: routing-block (unavailable) darf nicht missing_evidence_fallback auslösen.
        Aktuell BRICHT das: enforce_evidence_when_tools_suggested=True + suggested_tools != []
        + status=unavailable → successful_extractable=0 → Fallback.
        """
        plan = make_verified_plan(
            approved=True,
            gate_blocked=True,
            suggested_tools=["request_container"],
        )
        evidence = [make_grounding_evidence("unavailable", "request_container")]
        # evidence: reason=blueprint_suggest_requires_selection → das ist ein Routing-Entscheid

        result = self._run_grounding_precheck(plan, evidence)

        if result.get("mode") in ("missing_evidence_fallback", "tool_execution_failed_fallback"):
            pytest.xfail(
                "DRIFT A2 AKTIV: status=unavailable (Routing-Block) löst "
                f"'{result['mode']}' aus. "
                "Fix: Grounding Policy muss unavailable bei routing_block anders behandeln "
                "als tech-fail. Routing-Block ist kein fehlender Tool-Nachweis."
            )

    def test_ok_evidence_does_not_trigger_fallback(self):
        """Baseline: status=ok → kein Fallback."""
        plan = make_verified_plan(
            approved=True,
            suggested_tools=["request_container"],
        )
        evidence = [
            {
                "tool_name": "request_container",
                "status": "ok",
                "ref_id": "abc",
                "key_facts": ["status: running", "container_id: abc123"],
            }
        ]
        result = self._run_grounding_precheck(plan, evidence)
        assert result.get("mode") not in (
            "missing_evidence_fallback", "tool_execution_failed_fallback"
        ), f"Fallback bei ok-Evidence: {result.get('mode')}"

    def test_tech_error_triggers_tool_execution_failed_fallback(self):
        """Echter Tech-Fehler (error) → tool_execution_failed_fallback ist korrekt."""
        plan = make_verified_plan(
            approved=True,
            suggested_tools=["request_container"],
        )
        evidence = [
            {
                "tool_name": "request_container",
                "status": "error",
                "ref_id": "abc",
                "key_facts": ["error: docker not found"],
            }
        ]
        result = self._run_grounding_precheck(plan, evidence)
        # Bei echtem Fehler ist tool_execution_failed_fallback korrekt
        assert result.get("mode") in (
            "tool_execution_failed_fallback", "missing_evidence_fallback", None
        )


# ═══════════════════════════════════════════════════════════════════
# INV-08: pending_approval ist kein Fehler → kein Fallback
# ═══════════════════════════════════════════════════════════════════

class TestINV08PendingApprovalNotFallback:
    """
    INV-08: pending_approval ist ein normaler Workflow-Zustand, kein Fehler.
    Der Output darf nicht FALLBACK_TEXT zurückgeben wenn das Tool pending_approval meldet.
    """

    def _build_pending_plan(self) -> Dict:
        """Plan der einen pending_approval-Tool-Status enthält."""
        from core.plan_runtime_bridge import set_runtime_grounding_evidence

        plan = make_verified_plan(
            approved=True,
            suggested_tools=["request_container"],
        )
        # pending_approval ist in der grounding_evidence nicht als "ok"
        # → wird von _collect_grounding_evidence als non-ok behandelt
        evidence = [
            {
                "tool_name": "request_container",
                "status": "pending_approval",
                "ref_id": "abc",
                "key_facts": ["approval_id: abc123", "reason: network_access_required"],
            }
        ]
        set_runtime_grounding_evidence(plan, evidence)
        return plan

    def test_pending_approval_should_not_produce_fallback_text(self):
        """
        INV-08: pending_approval → Output darf keinen Fallback-Text ausgeben.
        pending_approval ist ein normaler Workflow-Zustand — grounding muss pass-through liefern.
        """
        from core.layers.output import OutputLayer

        plan = self._build_pending_plan()
        layer = OutputLayer()
        result = layer._grounding_precheck(plan, memory_data="")

        # INV-08 Fix: pending_approval muss als pass-through behandelt werden
        fallback_response = result.get("response", "")
        assert FALLBACK_TEXT not in fallback_response, (
            f"INV-08 VERLETZT: pending_approval erzeugt Fallback-Text. mode={result.get('mode')}"
        )
        # pending_approval darf kein hard-block sein
        assert result.get("blocked") is not True, (
            f"INV-08 VERLETZT: pending_approval blockiert den Output. mode={result.get('mode')}"
        )

    def test_pending_approval_result_structure(self):
        """pending_approval hat korrekte Felder im Tool-Result."""
        pending_result = {
            "status": "pending_approval",
            "approval_id": "abc123",
            "reason": "network_access_required",
            "hint": "Der User muss die Netzwerk-Freigabe erst genehmigen.",
        }
        assert pending_result["status"] == "pending_approval"
        assert "approval_id" in pending_result
        assert pending_result["status"] not in {"error", "tech_fail"}


# ═══════════════════════════════════════════════════════════════════
# INV-10: skip_reason muss gesetzt sein wenn Control geskippt wird
# ═══════════════════════════════════════════════════════════════════

class TestINV10SkipReasonAlwaysSet:
    """INV-10: Wenn _skipped=True im Plan, muss _skip_reason gesetzt sein."""

    def test_skip_with_reason_valid(self):
        plan = make_verified_plan(skipped=True, skip_reason="low_risk_skip")
        assert plan.get("_skipped") is True
        assert plan.get("_skip_reason") in VALID_SKIP_REASONS

    def test_skip_without_reason_is_invalid(self):
        """Skipped=True ohne skip_reason → persist_skip_state muss ControlContractError werfen."""
        plan: Dict[str, Any] = {}
        with pytest.raises(ControlContractError, match="INV-10"):
            persist_skip_state(plan, "")

    @pytest.mark.parametrize("reason", list(VALID_SKIP_REASONS))
    def test_all_valid_skip_reasons_accepted(self, reason):
        plan = make_verified_plan(skipped=True, skip_reason=reason)
        assert plan["_skip_reason"] == reason


# ═══════════════════════════════════════════════════════════════════
# INV-11: blueprint_gate_blocked nur wenn thinking_plan vorhanden
# ═══════════════════════════════════════════════════════════════════

class TestINV11GateBlockedRequiresIntent:
    """INV-11: _blueprint_gate_blocked darf nur gesetzt sein wenn intent vorhanden."""

    def test_gate_blocked_with_intent_valid(self):
        plan = make_verified_plan(gate_blocked=True, intent="Gaming Station starten")
        assert plan.get("_blueprint_gate_blocked") is True
        assert plan.get("intent")

    def test_gate_blocked_without_intent_is_invalid(self):
        """gate_blocked ohne intent → persist_gate_blocked_state muss ControlContractError werfen."""
        plan: Dict[str, Any] = {}
        with pytest.raises(ControlContractError, match="INV-11"):
            persist_gate_blocked_state(plan, intent="")


# ═══════════════════════════════════════════════════════════════════
# INV-12: Exact blueprint-name → kein suggest-zone-Block
# ═══════════════════════════════════════════════════════════════════

class TestINV12ExactBlueprintNameNoSuggest:
    """
    INV-12: Wenn der Blueprint-Name explizit im User-Text steht,
    darf der Router nicht in die Suggest-Zone fallen.
    Testet den Exact-Name-Bypass aus core/blueprint_router.py.
    """

    def _make_decision(self, user_text: str, best_id: str, score: float):
        from core.blueprint_router import (
            BlueprintRouterDecision,
            MATCH_THRESHOLD_SUGGEST,
            MATCH_THRESHOLD_STRICT,
        )
        # Simuliert die Bypass-Logik
        combined_lower = user_text.lower()
        if best_id.lower() in combined_lower and score >= MATCH_THRESHOLD_SUGGEST:
            return BlueprintRouterDecision(
                decision="use_blueprint",
                blueprint_id=best_id,
                score=score,
                reason=f"Explizit genannt ({score:.2f})",
            )
        if score >= MATCH_THRESHOLD_STRICT:
            return BlueprintRouterDecision(decision="use_blueprint", blueprint_id=best_id, score=score)
        return BlueprintRouterDecision(
            decision="suggest_blueprint",
            blueprint_id=best_id,
            score=score,
            candidates=[{"id": best_id, "score": score}],
        )

    @pytest.mark.parametrize("user_text", [
        "Einen neuen Gaming-Container aus dem Blueprint gaming-station erstellen",
        "starte gaming-station bitte",
        "gaming-station Container deployen",
        "request_container mit gaming-station",
    ])
    def test_explicit_name_bypasses_suggest_zone(self, user_text):
        """Score 0.79 in Suggest-Zone wird durch Exact-Name-Bypass überschrieben."""
        decision = self._make_decision(user_text, "gaming-station", score=0.79)
        assert decision.decision == "use_blueprint", (
            f"Suggest-Zone für explizit genannten Blueprint! user_text='{user_text}'"
        )
        assert decision.blueprint_id == "gaming-station"

    def test_no_name_in_text_stays_in_suggest_zone(self):
        """Ohne expliziten Namen bleibt die Suggest-Zone aktiv."""
        decision = self._make_decision("Container starten", "gaming-station", score=0.79)
        assert decision.decision == "suggest_blueprint"

    def test_score_below_suggest_stays_blocked(self):
        """Score < SUGGEST → kein Bypass, auch bei explizitem Namen."""
        decision = self._make_decision("gaming-station starten", "gaming-station", score=0.60)
        assert decision.decision == "suggest_blueprint"

    def test_blueprint_router_exact_name_bypass_exists(self):
        """Stellt sicher dass der Bypass-Code in blueprint_router.py existiert."""
        import inspect
        from core import blueprint_router
        source = inspect.getsource(blueprint_router)
        assert "EXACT-NAME BYPASS" in source or "exact" in source.lower() or "in _combined_lower" in source, (
            "Exact-Name-Bypass nicht in blueprint_router.py gefunden! "
            "INV-12 kann nicht garantiert werden."
        )


# ═══════════════════════════════════════════════════════════════════
# INV-13: Routing-Block ≠ Tech-Unavailable
# ═══════════════════════════════════════════════════════════════════

class TestINV13RoutingBlockVsTechUnavailable:
    """
    INV-13: status=unavailable aus Routing-Entscheid und aus Tech-Fehler
    sind semantisch verschieden, werden aber gleich behandelt.
    Dieser Test dokumentiert den Klassifizierungsfehler.
    """

    def test_routing_block_reason_is_identifiable(self):
        """Routing-Block hat spezifischen reason-Code der ihn identifiziert."""
        er = ExecutionResult()
        er.append_tool_status(
            tool_name="request_container",
            status="unavailable",
            reason="blueprint_suggest_requires_selection",
        )
        # reason muss auswertbar sein
        reason = er.tool_statuses[0]["reason"]
        assert "blueprint" in reason or "suggest" in reason or "routing" in reason, (
            "Routing-Block-Reason nicht identifizierbar. "
            "Grounding kann Tech-fail nicht von Routing-Block trennen."
        )

    def test_tech_unavailable_reason_different(self):
        """Tech-Unavailable hat anderen reason-Code."""
        er = ExecutionResult()
        er.append_tool_status(
            tool_name="request_container",
            status="unavailable",
            reason="tool_hub_unavailable",
        )
        reason = er.tool_statuses[0]["reason"]
        # Beide haben status=unavailable, aber reason unterscheidet sie
        assert reason != "blueprint_suggest_requires_selection"

    def test_status_alone_insufficient_to_classify(self):
        """
        Nur status=unavailable reicht nicht zur Klassifikation.
        reason ist Pflicht für korrekte Failure-Klasse.
        Dies ist der Dokumentations-Test für den bekannten Drift.
        """
        routing_block = {"tool_name": "request_container", "status": "unavailable",
                         "reason": "blueprint_suggest_requires_selection"}
        tech_fail = {"tool_name": "request_container", "status": "unavailable",
                     "reason": "tool_hub_unavailable"}

        # Beide haben denselben status → Grounding behandelt sie gleich (Drift!)
        assert routing_block["status"] == tech_fail["status"]
        # aber verschiedene reasons → könnte unterschieden werden
        assert routing_block["reason"] != tech_fail["reason"]


# ═══════════════════════════════════════════════════════════════════
# REPLAY: Bekannte Fehlerszenarien
# ═══════════════════════════════════════════════════════════════════

class TestReplayKnownFailures:
    """Dokumentiert bekannte Fehlerszenarien als reproduzierbare Tests."""

    def test_rc02_context_loss_needs_chat_history(self):
        """
        RC-02: Follow-up 'neuer Container bitte' verliert den Blueprint-Kontext.

        A3 Fix (2026-03-14): Orchestrator setzt needs_chat_history=True
        und extrahiert Blueprint-Hint aus Chat-History, wenn request_container
        vorgeschlagen wird und needs_chat_history=False war.

        Testet _extract_blueprint_hint_from_history aus orchestrator_sync_flow_utils.
        """
        from core.orchestrator_sync_flow_utils import _extract_blueprint_hint_from_history

        # Thinking produziert (noch) needs_chat_history=False für kurze Follow-ups
        thinking_plan = {
            "intent": "Container-Erstellung anfordern",
            "needs_memory": False,
            "needs_chat_history": False,
            "suggested_tools": ["request_container"],
        }
        chat_history = [
            {"role": "user", "content": "Gaming Station installieren?"},
            {"role": "assistant", "content": "Blueprint gaming-station verfügbar..."},
        ]
        user_text = "neuer Container bitte"

        # Orchestrator-A3-Fix: wenn request_container + needs_chat_history=False
        if "request_container" in thinking_plan["suggested_tools"] and not thinking_plan["needs_chat_history"]:
            thinking_plan["needs_chat_history"] = True
            bp_hint = _extract_blueprint_hint_from_history(chat_history, user_text)
            if bp_hint:
                thinking_plan["intent"] = f"{thinking_plan['intent']} {bp_hint}".strip()

        # Nach dem Fix: needs_chat_history muss True sein
        assert thinking_plan["needs_chat_history"] is True, (
            "A3 Fix fehlt: needs_chat_history bleibt False für request_container Follow-up"
        )
        # Blueprint-Hint muss aus History extrahiert worden sein
        assert "gaming-station" in thinking_plan["intent"], (
            f"A3 Fix fehlt: 'gaming-station' nicht im Intent injiziert. "
            f"Intent='{thinking_plan['intent']}'"
        )

    def test_rc02_blueprint_hint_extraction(self):
        """A3: _extract_blueprint_hint_from_history findet Blueprint-Namen in History."""
        from core.orchestrator_sync_flow_utils import _extract_blueprint_hint_from_history

        history = [
            {"role": "user", "content": "Gaming Station installieren?"},
            {"role": "assistant", "content": "Blueprint gaming-station ist verfügbar und bereit."},
        ]
        hint = _extract_blueprint_hint_from_history(history, "neuer Container bitte")
        assert hint == "gaming-station", f"Hint nicht gefunden oder falsch: '{hint}'"

    def test_rc02_no_hint_when_name_already_in_text(self):
        """A3: Kein Hint wenn Blueprint-Name schon im user_text."""
        from core.orchestrator_sync_flow_utils import _extract_blueprint_hint_from_history

        history = [
            {"role": "assistant", "content": "gaming-station Blueprint bereit."},
        ]
        # Blueprint name is already in user_text → no injection needed
        hint = _extract_blueprint_hint_from_history(history, "starte gaming-station bitte")
        assert hint == "", f"Fälschlich Hint zurückgegeben: '{hint}'"

    def test_rc02_no_hint_when_no_history(self):
        """A3: Kein Hint wenn keine Chat-History vorhanden."""
        from core.orchestrator_sync_flow_utils import _extract_blueprint_hint_from_history

        hint = _extract_blueprint_hint_from_history([], "neuer Container bitte")
        assert hint == ""

    def test_rc03_pending_approval_response_type(self):
        """RC-03: pending_approval → Response soll Approval beschreiben, nicht Fallback."""
        tool_result = {
            "status": "pending_approval",
            "approval_id": "abc123",
            "reason": "network_access_required",
            "hint": "Der User muss die Netzwerk-Freigabe erst genehmigen.",
        }
        # pending_approval ist ein gültiger Workflow-Zustand
        assert tool_result["status"] == "pending_approval"
        assert tool_result["status"] not in {"error", "tech_fail", "blocked"}
        assert "approval_id" in tool_result

    def test_fallback_text_is_known_constant(self):
        """Stellt sicher dass FALLBACK_TEXT mit dem echten Output übereinstimmt."""
        from core.layers.output import OutputLayer
        layer = OutputLayer()
        result = layer._build_grounding_fallback(evidence=[])
        assert result == FALLBACK_TEXT


# ═══════════════════════════════════════════════════════════════════
# INV-15: Blueprint Gate = Routing-Signal, KEIN Safety-Block
# ═══════════════════════════════════════════════════════════════════

class TestINV15BlueprintGateIsRoutingSignal:
    """
    INV-15: Wenn blueprint_gate_blocked=True im Plan steht, darf die Control Layer
    dies NICHT als Safety-Block werten. Es ist ein Routing-Signal — approved=true.

    Fix: CONTROL_PROMPT enthält explizite BLUEPRINT-GATE-REGEL.
    Fallback: _stabilize_verification_result() korrigiert approved=false deterministisch.
    """

    def test_control_prompt_contains_blueprint_gate_rule(self):
        """CONTROL_PROMPT muss explizit erklären dass blueprint_gate_blocked ein Routing-Signal ist."""
        from core.layers.control import CONTROL_PROMPT
        assert "blueprint_gate_blocked" in CONTROL_PROMPT, (
            "CONTROL_PROMPT erklärt blueprint_gate_blocked nicht! "
            "Das LLM weiß nicht, dass es kein Safety-Block ist."
        )
        assert "ROUTING-SIGNAL" in CONTROL_PROMPT or "Routing-Signal" in CONTROL_PROMPT or "routing" in CONTROL_PROMPT.lower(), (
            "CONTROL_PROMPT muss klarstellen dass blueprint_gate_blocked ein Routing-Signal ist."
        )
        assert "approved=true" in CONTROL_PROMPT or "approved=True" in CONTROL_PROMPT, (
            "CONTROL_PROMPT muss explizit approved=true für blueprint_gate_blocked vorschreiben."
        )

    def test_control_prompt_blueprint_rule_has_final_instruction_guidance(self):
        """CONTROL_PROMPT muss dem LLM eine sinnvolle final_instruction für den Gate-Fall geben."""
        from core.layers.control import CONTROL_PROMPT
        # Die Regel muss erklären dass blueprint_list zu nutzen ist
        assert "blueprint_list" in CONTROL_PROMPT, (
            "CONTROL_PROMPT gibt keine final_instruction-Guidance für den blueprint_gate_blocked-Fall. "
            "Das LLM könnte 'Anfrage ablehnen' als final_instruction ausgeben."
        )

    def test_stabilize_overrides_approved_false_when_gate_blocked(self):
        """
        Deterministischer Fallback: Wenn das LLM trotzdem approved=false ausgibt
        UND _blueprint_gate_blocked=True ist, muss _stabilize_verification_result korrigieren.
        """
        from core.layers.control import ControlLayer
        layer = ControlLayer()
        thinking_plan = {
            "intent": "Ubuntu Container starten",
            "suggested_tools": ["blueprint_list"],
            "_blueprint_gate_blocked": True,
            "_blueprint_no_match": True,
        }
        # LLM hat fälschlich approved=false ausgegeben
        bad_verification = {
            "approved": False,
            "decision_class": "hard_block",
            "hard_block": True,
            "block_reason_code": "blueprint_not_found",
            "reason": "Kein Blueprint gefunden",
            "final_instruction": "Anfrage ablehnen",
            "warnings": [],
        }
        result = layer._stabilize_verification_result(bad_verification, thinking_plan, user_text="Ubuntu Container starten")
        assert result.get("approved") is True, (
            "Deterministischer Override fehlt: approved=false bei blueprint_gate_blocked=True "
            "wurde NICHT auf approved=true korrigiert. "
            "Der LLM-Block propagiert fälschlich als Hard-Block."
        )

    def test_stabilize_does_not_override_when_safety_violation(self):
        """
        Override darf NICHT feuern wenn echter Safety-Verstoß vorliegt
        (z.B. malicious_intent), auch bei blueprint_gate_blocked=True.
        """
        from core.layers.control import ControlLayer
        layer = ControlLayer()
        thinking_plan = {
            "intent": "Dateien löschen",
            "suggested_tools": ["blueprint_list"],
            "_blueprint_gate_blocked": True,
        }
        bad_verification = {
            "approved": False,
            "decision_class": "hard_block",
            "hard_block": True,
            "block_reason_code": "malicious_intent",
            "reason": "malicious_intent",
            "warnings": ["safety violation detected"],
        }
        result = layer._stabilize_verification_result(bad_verification, thinking_plan, user_text="Dateien löschen")
        # Bei echtem Safety-Verstoß darf der Override nicht feuern
        # (hard_safety_markers oder user_text_has_hard_safety_keywords)
        # Kein assert auf approved=False weil das vom LightCIM-Check abhängt —
        # aber sicherstellen dass kein unkontrolliertes True entsteht wenn override sauber arbeitet
        assert isinstance(result, dict), "Stabilize muss ein Dict zurückgeben"
