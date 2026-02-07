"""
Unit Tests for PipelineOrchestrator

Tests the orchestration logic without full backend dependencies.
Uses mocking for layers and ContextManager.

Created by: Claude 2 (Parallel Development)
Date: 2026-02-05
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class MockContextResult:
    """Mock for ContextResult when not available"""
    def __init__(
        self,
        memory_data: str = "",
        memory_used: bool = False,
        system_tools: str = "",
        sources: list = None
    ):
        self.memory_data = memory_data
        self.memory_used = memory_used
        self.system_tools = system_tools
        self.sources = sources or []
    
    def to_dict(self):
        return {
            "memory_data": self.memory_data,
            "memory_used": self.memory_used,
            "system_tools": self.system_tools,
            "sources": self.sources
        }


class MockContextManager:
    """Mock ContextManager for testing"""
    def __init__(self):
        self.get_context_calls = []
    
    def get_context(self, query: str, thinking_plan: dict, conversation_id: str):
        self.get_context_calls.append({
            "query": query,
            "thinking_plan": thinking_plan,
            "conversation_id": conversation_id
        })
        return MockContextResult(
            memory_data="test memory data",
            memory_used=True,
            system_tools="",
            sources=["memory:test"]
        )


@pytest.fixture
def mock_context_manager():
    """Mocked ContextManager (Claude 1's component)"""
    return MockContextManager()


@pytest.fixture
def mock_layers():
    """Mock all three layers"""
    thinking = MagicMock()
    thinking.analyze = AsyncMock(return_value={
        "intent": "question",
        "needs_memory": True,
        "memory_keys": ["test_key"],
        "hallucination_risk": "medium",
        "needs_sequential_thinking": False
    })
    
    control = MagicMock()
    control.verify = AsyncMock(return_value={
        "approved": True,
        "corrections": {},
        "warnings": [],
        "final_instruction": "Answer normally"
    })
    control.apply_corrections = MagicMock(side_effect=lambda plan, ver: {**plan, "_verified": True})
    control._check_sequential_thinking = AsyncMock(return_value=None)
    control.set_mcp_hub = MagicMock()
    
    output = MagicMock()
    output.generate = AsyncMock(return_value="Generated response text")
    
    return {
        "thinking": thinking,
        "control": control,
        "output": output
    }


class TestPipelineOrchestratorBasic:
    """Basic orchestrator tests"""
    
    def test_mock_context_result(self):
        """Test MockContextResult works"""
        result = MockContextResult(
            memory_data="test",
            memory_used=True,
            system_tools="tools",
            sources=["a", "b"]
        )
        assert result.memory_data == "test"
        assert result.memory_used is True
        assert result.system_tools == "tools"
        assert result.sources == ["a", "b"]
    
    def test_mock_context_manager(self, mock_context_manager):
        """Test MockContextManager works"""
        result = mock_context_manager.get_context(
            query="test query",
            thinking_plan={"intent": "test"},
            conversation_id="conv123"
        )
        
        assert result.memory_used is True
        assert len(mock_context_manager.get_context_calls) == 1
        assert mock_context_manager.get_context_calls[0]["query"] == "test query"


class TestPipelineOrchestratorImport:
    """Test that orchestrator can be imported"""
    
    def test_import_orchestrator(self):
        """Should be able to import PipelineOrchestrator"""
        try:
            from core.orchestrator import PipelineOrchestrator
            assert PipelineOrchestrator is not None
        except ImportError as e:
            pytest.skip(f"Cannot import PipelineOrchestrator: {e}")
    
    def test_import_get_orchestrator(self):
        """Should be able to import get_orchestrator function"""
        try:
            from core.orchestrator import get_orchestrator
            assert get_orchestrator is not None
        except ImportError as e:
            pytest.skip(f"Cannot import get_orchestrator: {e}")


class TestThinkingLayerExecution:
    """Test thinking layer execution"""
    
    @pytest.mark.asyncio
    async def test_execute_thinking_layer(self, mock_layers):
        """Should call ThinkingLayer.analyze"""
        try:
            from core.orchestrator import PipelineOrchestrator
            
            with patch('core.orchestrator.ThinkingLayer', return_value=mock_layers["thinking"]), \
                 patch('core.orchestrator.ControlLayer', return_value=mock_layers["control"]), \
                 patch('core.orchestrator.OutputLayer', return_value=mock_layers["output"]), \
                 patch('core.orchestrator.get_hub', return_value=MagicMock()), \
                 patch('core.orchestrator.get_registry', return_value=MagicMock()), \
                 patch('core.orchestrator.ContextManager', return_value=MockContextManager()):
                
                orch = PipelineOrchestrator()
                result = await orch._execute_thinking_layer("Test query?")
                
                assert result["intent"] == "question"
                assert result["needs_memory"] is True
                mock_layers["thinking"].analyze.assert_called_once_with("Test query?")
        except ImportError as e:
            pytest.skip(f"Cannot test: {e}")


class TestOutputLayerExecution:
    """Test output layer execution"""
    
    @pytest.mark.asyncio
    async def test_execute_output_layer(self, mock_layers):
        """Should call OutputLayer.generate"""
        try:
            from core.orchestrator import PipelineOrchestrator
            
            with patch('core.orchestrator.ThinkingLayer', return_value=mock_layers["thinking"]), \
                 patch('core.orchestrator.ControlLayer', return_value=mock_layers["control"]), \
                 patch('core.orchestrator.OutputLayer', return_value=mock_layers["output"]), \
                 patch('core.orchestrator.get_hub', return_value=MagicMock()), \
                 patch('core.orchestrator.get_registry', return_value=MagicMock()), \
                 patch('core.orchestrator.ContextManager', return_value=MockContextManager()):
                
                orch = PipelineOrchestrator()
                result = await orch._execute_output_layer(
                    user_text="Test",
                    verified_plan={"intent": "greeting", "_verified": True},
                    memory_data="",
                    model="qwen3",
                    chat_history=[],
                    memory_required_but_missing=False
                )
                
                assert result == "Generated response text"
                mock_layers["output"].generate.assert_called_once()
        except ImportError as e:
            pytest.skip(f"Cannot test: {e}")


class TestControlLayerExecution:
    """Test control layer execution"""
    
    @pytest.mark.asyncio
    async def test_execute_control_layer_skip_disabled(self, mock_layers):
        """Should skip control layer when disabled"""
        try:
            from core.orchestrator import PipelineOrchestrator
            
            with patch('core.orchestrator.ThinkingLayer', return_value=mock_layers["thinking"]), \
                 patch('core.orchestrator.ControlLayer', return_value=mock_layers["control"]), \
                 patch('core.orchestrator.OutputLayer', return_value=mock_layers["output"]), \
                 patch('core.orchestrator.get_hub', return_value=MagicMock()), \
                 patch('core.orchestrator.get_registry', return_value=MagicMock()), \
                 patch('core.orchestrator.ContextManager', return_value=MockContextManager()), \
                 patch('core.orchestrator.ENABLE_CONTROL_LAYER', False):
                
                orch = PipelineOrchestrator()
                verification, verified_plan = await orch._execute_control_layer(
                    user_text="Test",
                    thinking_plan={"intent": "test", "hallucination_risk": "low"},
                    memory_data="",
                    conversation_id="conv123"
                )
                
                assert verification["approved"] is True
                assert verified_plan["_skipped"] is True
                # Control.verify should NOT have been called
                mock_layers["control"].verify.assert_not_called()
        except ImportError as e:
            pytest.skip(f"Cannot test: {e}")


@pytest.mark.skip(reason="Phase 2: process_stream now implemented")
class TestProcessStreamNotImplemented:
    """Test process_stream raises NotImplementedError"""
    
    @pytest.mark.asyncio
    async def test_process_stream_raises_not_implemented(self, mock_layers):
        """process_stream() should raise NotImplementedError"""
        try:
            from core.orchestrator import PipelineOrchestrator
            from core.models import CoreChatRequest
            
            with patch('core.orchestrator.ThinkingLayer', return_value=mock_layers["thinking"]), \
                 patch('core.orchestrator.ControlLayer', return_value=mock_layers["control"]), \
                 patch('core.orchestrator.OutputLayer', return_value=mock_layers["output"]), \
                 patch('core.orchestrator.get_hub', return_value=MagicMock()), \
                 patch('core.orchestrator.get_registry', return_value=MagicMock()), \
                 patch('core.orchestrator.ContextManager', return_value=MockContextManager()):
                
                orch = PipelineOrchestrator()
                request = CoreChatRequest(
                    messages=[{"role": "user", "content": "Hello"}],
                    model="qwen3",
                    conversation_id="test",
                    source_adapter="test"
                )
                
                with pytest.raises(NotImplementedError):
                    async for chunk in orch.process_stream(request):
                        pass
        except ImportError as e:
            pytest.skip(f"Cannot test: {e}")


class TestSaveMemory:
    """Test memory saving functionality"""
    
    def test_save_memory_with_new_fact(self, mock_layers):
        """Should save new fact when is_new_fact is True"""
        try:
            from core.orchestrator import PipelineOrchestrator
            
            with patch('core.orchestrator.ThinkingLayer', return_value=mock_layers["thinking"]), \
                 patch('core.orchestrator.ControlLayer', return_value=mock_layers["control"]), \
                 patch('core.orchestrator.OutputLayer', return_value=mock_layers["output"]), \
                 patch('core.orchestrator.get_hub', return_value=MagicMock()), \
                 patch('core.orchestrator.get_registry', return_value=MagicMock()), \
                 patch('core.orchestrator.ContextManager', return_value=MockContextManager()), \
                 patch('core.orchestrator.call_tool') as mock_call_tool, \
                 patch('core.orchestrator.autosave_assistant') as mock_autosave:
                
                orch = PipelineOrchestrator()
                orch._save_memory(
                    conversation_id="conv123",
                    verified_plan={
                        "is_new_fact": True,
                        "new_fact_key": "favorite_color",
                        "new_fact_value": "blue"
                    },
                    answer="Your favorite color is blue."
                )
                
                # Check call_tool was called for fact save
                mock_call_tool.assert_called_once()
                call_args = mock_call_tool.call_args
                assert call_args[0][0] == "memory_fact_save"
                assert call_args[0][1]["key"] == "favorite_color"
                assert call_args[0][1]["value"] == "blue"
                
                # Check autosave was called
                mock_autosave.assert_called_once()
        except ImportError as e:
            pytest.skip(f"Cannot test: {e}")
