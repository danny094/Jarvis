"""
Unit Tests for ContextManager

Tests context retrieval logic (Memory + System Knowledge)
without full backend dependencies.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from core.context_manager import ContextManager, ContextResult


class TestContextResult:
    """Test ContextResult data model"""
    
    def test_initialization_defaults(self):
        """Should initialize with default values"""
        result = ContextResult()
        assert result.memory_data == ""
        assert result.memory_used is False
        assert result.system_tools == ""
        assert result.sources == []
    
    def test_initialization_with_values(self):
        """Should initialize with provided values"""
        result = ContextResult(
            memory_data="test data",
            memory_used=True,
            system_tools="tool info",
            sources=["source1", "source2"]
        )
        assert result.memory_data == "test data"
        assert result.memory_used is True
        assert result.system_tools == "tool info"
        assert result.sources == ["source1", "source2"]
    
    def test_to_dict(self):
        """Should convert to dictionary"""
        result = ContextResult(
            memory_data="test",
            memory_used=True
        )
        d = result.to_dict()
        
        assert isinstance(d, dict)
        assert d["memory_data"] == "test"
        assert d["memory_used"] is True
        assert "system_tools" in d
        assert "sources" in d


class TestContextManager:
    """Test ContextManager initialization and basic methods"""
    
    def test_initialization(self):
        """ContextManager should initialize without errors"""
        cm = ContextManager()
        assert cm is not None
    
    @patch('core.context_manager.get_fact_for_query')
    @patch('core.context_manager.graph_search')
    def test_search_memory_multi_context_finds_fact(self, mock_graph, mock_fact):
        """Should find facts in memory"""
        mock_fact.return_value = "Danny likes pizza"
        mock_graph.return_value = None
        
        cm = ContextManager()
        content, found = cm._search_memory_multi_context(
            key="food_preference",
            conversation_id="test_conv",
            include_system=False
        )
        
        assert found is True
        assert "pizza" in content
        assert "food_preference" in content
    
    @patch('core.context_manager.get_fact_for_query')
    @patch('core.context_manager.graph_search')
    def test_search_memory_multi_context_finds_graph(self, mock_graph, mock_fact):
        """Should find results via graph search"""
        mock_fact.return_value = None
        mock_graph.return_value = [
            {"content": "User loves Italian food"},
            {"content": "User allergic to nuts"}
        ]
        
        cm = ContextManager()
        content, found = cm._search_memory_multi_context(
            key="dietary_preferences",
            conversation_id="test_conv",
            include_system=False
        )
        
        assert found is True
        assert "Italian food" in content
    
    @patch('core.context_manager.get_fact_for_query')
    def test_search_system_tools_with_keyword(self, mock_fact):
        """Should find tool info when keywords match"""
        mock_fact.return_value = "MCP Tools: sequential_thinking, memory_save, analyze"
        
        cm = ContextManager()
        result = cm._search_system_tools("What tools do you have?")
        
        assert "MCP Tools" in result
        assert "sequential_thinking" in result
    
    @patch('core.context_manager.get_fact_for_query')
    def test_search_system_tools_no_keyword(self, mock_fact):
        """Should return empty string when no keywords"""
        cm = ContextManager()
        result = cm._search_system_tools("Hello world")
        
        assert result == ""
        mock_fact.assert_not_called()
    
    def test_get_tool_context_alias(self):
        """get_tool_context should call _search_system_tools"""
        cm = ContextManager()
        
        with patch.object(cm, '_search_system_tools', return_value="test") as mock_search:
            result = cm.get_tool_context("test query")
            
            assert result == "test"
            mock_search.assert_called_once_with("test query")


class TestContextManagerIntegration:
    """Integration tests for get_context method"""
    
    def test_get_context_no_memory_needed(self):
        """Should skip memory when not needed"""
        cm = ContextManager()
        
        thinking_plan = {
            "needs_memory": False,
            "is_fact_query": False
        }
        
        with patch.object(cm, '_search_memory_multi_context') as mock_search:
            result = cm.get_context(
                query="Hello",
                thinking_plan=thinking_plan,
                conversation_id="test"
            )
            
            assert result.memory_used is False
            mock_search.assert_not_called()
    
    def test_get_context_with_memory_needed(self):
        """Should retrieve memory when thinking_plan indicates needs_memory"""
        cm = ContextManager()
        
        thinking_plan = {
            "needs_memory": True,
            "memory_keys": ["user_name", "favorite_food"],
            "is_fact_query": False
        }
        
        with patch.object(cm, '_search_memory_multi_context') as mock_search:
            mock_search.return_value = ("Danny loves pizza", True)
            
            result = cm.get_context(
                query="What do I like?",
                thinking_plan=thinking_plan,
                conversation_id="test"
            )
            
            assert result.memory_used is True
            assert "pizza" in result.memory_data
            assert mock_search.call_count == 2  # Called for each key
    
    def test_get_context_with_system_tools(self):
        """Should include system tools when relevant"""
        cm = ContextManager()
        
        thinking_plan = {
            "needs_memory": False,
            "is_fact_query": False
        }
        
        with patch.object(cm, '_search_system_tools') as mock_tools:
            mock_tools.return_value = "Available: tool1, tool2"
            
            result = cm.get_context(
                query="What tools can you use?",
                thinking_plan=thinking_plan,
                conversation_id="test"
            )
            
            assert result.memory_used is True
            assert result.system_tools == "Available: tool1, tool2"
            assert "system_tools" in result.sources
    
    def test_get_context_combined(self):
        """Should combine system tools and memory"""
        cm = ContextManager()
        
        thinking_plan = {
            "needs_memory": True,
            "memory_keys": ["test_key"],
            "is_fact_query": False
        }
        
        with patch.object(cm, '_search_system_tools') as mock_tools, \
             patch.object(cm, '_search_memory_multi_context') as mock_memory:
            
            mock_tools.return_value = "Tools info"
            mock_memory.return_value = ("Memory info", True)
            
            result = cm.get_context(
                query="Tell me about tools and my data",
                thinking_plan=thinking_plan,
                conversation_id="test"
            )
            
            assert result.memory_used is True
            assert result.system_tools == "Tools info"
            assert result.memory_data == "Memory info"
            assert len(result.sources) == 2


class TestContextManagerRequestRetrievalPhase:
    """Tests for request-scoped retrieval batching helpers."""

    def test_normalize_memory_keys_dedupes_and_strips(self):
        cm = ContextManager()
        out = cm._normalize_memory_keys([" foo ", "", "foo", "bar", None, "bar"])
        assert out == ["foo", "bar"]

    @patch("core.context_manager.get_memory_keys_max_per_request", return_value=2)
    def test_normalize_memory_keys_applies_cap(self, _mock_cap):
        cm = ContextManager()
        out = cm._normalize_memory_keys(["k1", "k2", "k3", "k4"])
        assert out == ["k1", "k2"]

    @patch("core.context_manager.search_memory_fallback")
    @patch("core.context_manager.semantic_search")
    @patch("core.context_manager.graph_search")
    @patch("core.context_manager.get_fact_for_query")
    def test_request_cache_reuses_backend_results(
        self,
        mock_fact,
        mock_graph,
        mock_semantic,
        mock_fallback,
    ):
        cm = ContextManager()
        request_cache = {}
        mock_fact.return_value = None
        mock_graph.return_value = []
        mock_semantic.return_value = [{"content": "hit"}]
        mock_fallback.return_value = ""

        content_1, found_1 = cm._search_memory_multi_context(
            key="k1",
            conversation_id="conv",
            include_system=False,
            request_cache=request_cache,
        )
        assert found_1 is True
        assert "hit" in content_1

        calls_after_first = (
            mock_fact.call_count,
            mock_graph.call_count,
            mock_semantic.call_count,
            mock_fallback.call_count,
        )

        content_2, found_2 = cm._search_memory_multi_context(
            key="k1",
            conversation_id="conv",
            include_system=False,
            request_cache=request_cache,
        )
        assert found_2 is True
        assert "hit" in content_2
        assert calls_after_first == (
            mock_fact.call_count,
            mock_graph.call_count,
            mock_semantic.call_count,
            mock_fallback.call_count,
        )

    def test_search_memory_keys_parallel_dedupes_duplicate_keys(self):
        cm = ContextManager()
        with patch.object(cm, "_search_memory_multi_context", return_value=("v", True)) as mock_search:
            results = cm._search_memory_keys_parallel(
                keys=["alpha", "alpha", "beta"],
                conversation_id="conv",
                include_system=True,
            )
        assert results["alpha"] == ("v", True)
        assert results["beta"] == ("v", True)
        assert mock_search.call_count == 2

    def test_compute_key_phase_wait_timeout_caps_long_remaining(self):
        cm = ContextManager()
        timeout = cm._compute_key_phase_wait_timeout(
            remaining_s=6.0,
            call_timeout_s=1.5,
            num_keys=4,
            max_workers=4,
        )
        assert timeout <= 1.8
        assert timeout > 0.0

    def test_search_memory_keys_parallel_uses_degraded_fanout_for_many_keys(self):
        cm = ContextManager()
        modes = []

        def _fake_multi(*args, **kwargs):
            mode = kwargs.get("fanout_mode")
            if mode is None and args:
                mode = args[-1]
            modes.append(mode or "")
            return ("", False)

        with patch.object(cm, "_search_memory_multi_context", side_effect=_fake_multi):
            cm._search_memory_keys_parallel(
                keys=["k1", "k2", "k3", "k4"],
                conversation_id="conv",
                include_system=True,
            )
        assert modes
        assert all(m == "degraded" for m in modes)

    def test_search_memory_keys_parallel_uses_full_fanout_for_small_keyset(self):
        cm = ContextManager()
        modes = []

        def _fake_multi(*args, **kwargs):
            mode = kwargs.get("fanout_mode")
            if mode is None and args:
                mode = args[-1]
            modes.append(mode or "")
            return ("", False)

        with patch.object(cm, "_search_memory_multi_context", side_effect=_fake_multi):
            cm._search_memory_keys_parallel(
                keys=["k1", "k2"],
                conversation_id="conv",
                include_system=True,
            )
        assert modes
        assert all(m == "full" for m in modes)
