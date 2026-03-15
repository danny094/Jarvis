from __future__ import annotations

from unittest.mock import patch

from core.context_manager import ContextManager


def _policy(**overrides):
    base = {
        "enabled": True,
        "query": "hardware limits laws constraints",
        "graph_depth": 0,
        "graph_limit": 20,
        "semantic_enable": True,
        "semantic_limit": 8,
        "max_output_lines": 8,
        "noise_metadata_keys": ["tool_name", "execution", "mcp", "task_id", "archive_id"],
        "noise_prefixes": ["memory_search:"],
        "noise_contains_any": ["execution", "search memory"],
        "allow_name_colon_exec_pattern": True,
        "require_law_marker": True,
        "law_markers": ["must", "never", "law", "regel"],
    }
    base.update(overrides)
    return base


def test_load_trion_laws_merges_semantic_hits_and_filters_noise():
    cm = ContextManager()
    graph_results = [
        {"content": "memory_search: container list", "metadata": {}},
        {"content": "Rule: must verify host network via tools.", "metadata": {}},
        {"content": "tool_exec: execution result", "metadata": {"tool_name": "exec_in_container"}},
    ]
    semantic_results = [
        {"content": "Never claim host IP without tool evidence.", "metadata": {}, "similarity": 0.92},
        {"content": "observability snapshot", "metadata": {}},
    ]

    with patch("core.context_manager.load_trion_laws_policy", return_value=_policy(max_output_lines=2)), \
         patch("core.context_manager.graph_search", return_value=graph_results), \
         patch("core.context_manager.semantic_search", return_value=semantic_results):
        out = cm._load_trion_laws(query="host network ip")

    assert out.startswith("TRION-GESETZE")
    assert "memory_search:" not in out
    assert "tool_exec:" not in out
    assert "Never claim host IP without tool evidence." in out
    assert "Rule: must verify host network via tools." in out
    law_lines = [line for line in out.splitlines() if line.startswith("⚖️ ")]
    assert len(law_lines) == 2
    assert "Never claim host IP without tool evidence." in law_lines[0]


def test_load_trion_laws_returns_empty_when_only_noise_entries():
    cm = ContextManager()
    noisy_graph = [
        {"content": "memory_search: x", "metadata": {}},
        {"content": "tool_a: execution details", "metadata": {"tool_name": "container_list"}},
    ]

    with patch("core.context_manager.load_trion_laws_policy", return_value=_policy()), \
         patch("core.context_manager.graph_search", return_value=noisy_graph), \
         patch("core.context_manager.semantic_search", return_value=[]):
        out = cm._load_trion_laws(query="host network ip")

    assert out == ""


def test_is_noise_law_entry_respects_policy_markers():
    with patch(
        "core.context_manager.load_trion_laws_policy",
        return_value=_policy(require_law_marker=True, law_markers=["must"]),
    ):
        assert ContextManager._is_noise_law_entry("must verify outputs", {}) is False
        assert ContextManager._is_noise_law_entry("verify outputs", {}) is True
