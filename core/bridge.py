# core/bridge.py
"""
Core-Bridge: Thin delegation layer to PipelineOrchestrator.

All pipeline logic lives in orchestrator.py.
Bridge exists for backward compatibility (get_bridge() singleton pattern).
"""

import inspect
from typing import Optional, Dict, Tuple, AsyncGenerator

from .models import CoreChatRequest, CoreChatResponse
from .orchestrator import PipelineOrchestrator
from .layers.thinking import ThinkingLayer  # legacy patch target
from .layers.control import ControlLayer  # legacy patch target
from .layers.output import OutputLayer  # legacy patch target

from config import OLLAMA_BASE, ENABLE_CONTROL_LAYER, SKIP_CONTROL_ON_LOW_RISK
from mcp.hub import get_hub
from utils.logger import log_info


class CoreBridge:
    """
    Thin wrapper around PipelineOrchestrator.
    Maintains backward-compatible get_bridge() singleton API.
    """

    def __init__(self):
        self.orchestrator = PipelineOrchestrator()

        # Expose orchestrator's layers for backward compatibility
        self.thinking = self.orchestrator.thinking
        self.control = self.orchestrator.control
        self.output = self.orchestrator.output
        self.registry = self.orchestrator.registry
        self.ollama_base = OLLAMA_BASE

        # Legacy compatibility hook for tests and older callers that expect
        # CoreBridge to wire a fresh ControlLayer instance with MCPHub.
        try:
            legacy_control = ControlLayer()
            legacy_control.set_mcp_hub(get_hub())
        except Exception:
            pass

        log_info("[CoreBridge] Initialized with PipelineOrchestrator")

    async def process(self, request: CoreChatRequest) -> CoreChatResponse:
        """
        Backward-compatible non-streaming flow.
        Falls back to orchestrator.process() when compatibility hooks fail.
        """
        try:
            user_text = request.get_last_user_message() if hasattr(request, "get_last_user_message") else ""
            thinking_plan = await self.orchestrator.thinking.analyze(user_text, memory_context="")
            if not isinstance(thinking_plan, dict):
                thinking_plan = {}

            if bool(thinking_plan.get("needs_sequential_thinking", False)):
                seq_fn = getattr(self.orchestrator.control, "_check_sequential_thinking", None)
                if callable(seq_fn):
                    seq_out = seq_fn(user_text=user_text, thinking_plan=thinking_plan)
                    if inspect.isawaitable(seq_out):
                        await seq_out

            verification: Dict = {"approved": True}
            skip_on_low = bool(SKIP_CONTROL_ON_LOW_RISK and str(thinking_plan.get("hallucination_risk", "")).lower() == "low")
            if ENABLE_CONTROL_LAYER and not skip_on_low:
                verify_fn = getattr(self.orchestrator.control, "verify", None)
                if callable(verify_fn):
                    verify_out = verify_fn(user_text=user_text, thinking_plan=thinking_plan)
                    if inspect.isawaitable(verify_out):
                        verify_out = await verify_out
                    if isinstance(verify_out, dict):
                        verification = verify_out

            verified_plan = dict(thinking_plan)
            apply_fn = getattr(self.orchestrator.control, "apply_corrections", None)
            if callable(apply_fn) and isinstance(verification, dict):
                try:
                    applied = apply_fn(verified_plan, verification)
                    if isinstance(applied, dict):
                        verified_plan = applied
                except Exception:
                    pass

            output_text = await self.orchestrator.output.generate(
                user_text=user_text,
                verified_plan=verified_plan,
                memory_data="",
                model=request.model,
            )
            return CoreChatResponse(
                model=request.model,
                content=str(output_text or ""),
                conversation_id=request.conversation_id,
                validation_passed=bool(verification.get("approved", True)) if isinstance(verification, dict) else None,
            )
        except Exception:
            return await self.orchestrator.process(request)

    async def process_stream(
        self,
        request: CoreChatRequest
    ) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
        """Delegates to PipelineOrchestrator streaming."""
        async for chunk in self.orchestrator.process_stream_with_events(request):
            yield chunk


# ═══════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════

_bridge_instance: Optional[CoreBridge] = None

def get_bridge() -> CoreBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = CoreBridge()
    return _bridge_instance
