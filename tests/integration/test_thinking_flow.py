
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from core.models import CoreChatRequest, Message, MessageRole

# Wir testen die Logik in CoreBridge.process, basierend auf ThinkingLayer Output.

@pytest.fixture
def mock_thinking_plan_light():
    return {
        "intent": "Simple Hello",
        "needs_sequential_thinking": False,
        "hallucination_risk": "low", # Triggers SKIP_CONTROL_ON_LOW_RISK if enabled
        "suggested_cim_modes": ["light"]
    }

@pytest.fixture
def mock_thinking_plan_heavy():
    return {
        "intent": "Complex Analysis",
        "needs_sequential_thinking": True, # Triggers Sequential Thinking
        "hallucination_risk": "high",
        "suggested_cim_modes": ["heavy", "strategic"]
    }

@pytest.fixture
def mock_thinking_plan_medium():
    return {
        "intent": "Fact Query",
        "needs_sequential_thinking": False,
        "hallucination_risk": "medium", # Should trigger Control Layer
        "suggested_cim_modes": []
    }

@pytest.mark.asyncio
async def test_flow_light_skips_control(mock_thinking_plan_light):
    """Test: Light request skips Control Layer (if configured)."""
    
    with patch("core.bridge.ThinkingLayer"), \
         patch("core.bridge.ControlLayer"), \
         patch("core.bridge.OutputLayer"), \
         patch("core.bridge.get_hub"), \
         patch("core.bridge.SKIP_CONTROL_ON_LOW_RISK", True): # Force config
         
        from core.bridge import CoreBridge
        bridge = CoreBridge()
        
        # Setup Thinking Mock
        bridge.orchestrator.thinking.analyze = AsyncMock(return_value=mock_thinking_plan_light)
        bridge.orchestrator.output.generate = AsyncMock(return_value="Response")
        # Phase 2: Explicitly mock control methods to enable assert_not_called
        bridge.orchestrator.control.verify = AsyncMock()
        bridge.orchestrator.control._check_sequential_thinking = AsyncMock()
        
        # Request
        req = CoreChatRequest(
            model="test", 
            messages=[Message(role=MessageRole.USER, content="Hi")], 
            conversation_id="1"
        )
        
        await bridge.process(req)
        
        # Verify: Control was NOT called
        bridge.orchestrator.control.verify.assert_not_called()
        
        # Verify: Sequential was NOT called
        bridge.orchestrator.control._check_sequential_thinking.assert_not_called()

@pytest.mark.asyncio
async def test_flow_heavy_triggers_sequential(mock_thinking_plan_heavy):
    """Test: Heavy request triggers Sequential Thinking."""
    
    with patch("core.bridge.ThinkingLayer"), \
         patch("core.bridge.ControlLayer"), \
         patch("core.bridge.OutputLayer"), \
         patch("core.bridge.get_hub"):
         
        from core.bridge import CoreBridge
        bridge = CoreBridge()
        
        # Setup Thinking Mock
        bridge.orchestrator.thinking.analyze = AsyncMock(return_value=mock_thinking_plan_heavy)
        bridge.orchestrator.output.generate = AsyncMock(return_value="Response")
        
        # Setup Control Mock return values
        bridge.orchestrator.control._check_sequential_thinking = AsyncMock(return_value={"steps": ["1", "2"]})
        bridge.orchestrator.control.verify = AsyncMock(return_value={"approved": True})

        # Request
        req = CoreChatRequest(
            model="test", 
            messages=[Message(role=MessageRole.USER, content="Analyze X")], 
            conversation_id="1"
        )
        
        await bridge.process(req)
        
        # Verify: Sequential WAS called
        bridge.orchestrator.control._check_sequential_thinking.assert_called_once()
        
        # Check arguments passed to sequential
        call_kwargs = bridge.orchestrator.control._check_sequential_thinking.call_args.kwargs
        assert call_kwargs["user_text"] == "Analyze X"
        assert call_kwargs["thinking_plan"]["needs_sequential_thinking"] is True
        
        # Verify: Control Verify WAS also called (Sequential happens BEFORE verify)
        bridge.orchestrator.control.verify.assert_called_once()

@pytest.mark.asyncio
async def test_flow_medium_triggers_control(mock_thinking_plan_medium):
    """Test: Medium request triggers Control Layer verification (but no Sequential)."""
    
    with patch("core.bridge.ThinkingLayer"), \
         patch("core.bridge.ControlLayer"), \
         patch("core.bridge.OutputLayer"), \
         patch("core.bridge.get_hub"), \
         patch("core.bridge.ENABLE_CONTROL_LAYER", True):
         
        from core.bridge import CoreBridge
        bridge = CoreBridge()
        
        # Setup Thinking Mock
        bridge.orchestrator.thinking.analyze = AsyncMock(return_value=mock_thinking_plan_medium)
        bridge.orchestrator.output.generate = AsyncMock(return_value="Response")
        bridge.orchestrator.control.verify = AsyncMock(return_value={"approved": True})
        # Phase 2: Explicitly mock _check_sequential_thinking to enable assert_not_called
        bridge.orchestrator.control._check_sequential_thinking = AsyncMock()
        
        # Request
        req = CoreChatRequest(
            model="test", 
            messages=[Message(role=MessageRole.USER, content="Info")], 
            conversation_id="1"
        )
        
        await bridge.process(req)
        
        # Verify: Sequential NOT called
        bridge.orchestrator.control._check_sequential_thinking.assert_not_called()
        
        # Verify: Control Verify WAS called
        bridge.orchestrator.control.verify.assert_called_once()

