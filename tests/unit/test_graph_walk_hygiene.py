"""Tests für Fix 1+2: Tombstone-Filter und source_id-Deduplizierung in memory_graph_search.

Diese Tests prüfen die Logik direkt ohne Full-MCP-Stack: die Filterung und Deduplizierung
werden mit denselben Input-Strukturen getestet, die graph_walk() liefert.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Hilfsfunktionen: repliziert die Tombstone+Dedup-Logik aus tools.py
# (damit Tests auch ohne komplexe MCP-Imports laufen)
# ---------------------------------------------------------------------------

def _apply_tombstone_and_dedup(graph_results):
    """Exakte Kopie der Logik aus sql-memory/memory_mcp/tools.py (Fix 1+2)."""
    # Tombstone-Filter
    live_results = [
        n for n in graph_results
        if "tombstone" not in (n.get("content") or "").lower()
    ]

    # Deduplizierung by source_id: höchste Confidence gewinnt
    seen_source_ids: dict = {}
    for n in live_results:
        sid = n.get("source_id") or ""
        if not sid:
            continue
        existing = seen_source_ids.get(sid)
        if existing is None or n.get("confidence", 0.5) > existing.get("confidence", 0.5):
            seen_source_ids[sid] = n

    deduped = []
    for n in live_results:
        sid = n.get("source_id") or ""
        if not sid:
            deduped.append(n)
        elif seen_source_ids.get(sid) is n:
            deduped.append(n)

    combined = [
        {
            "content": node["content"],
            "type": node["source_type"],
            "depth": node.get("depth", 0),
            "node_id": node["id"],
        }
        for node in deduped
    ]
    return combined


def _make_node(node_id, content, source_id=None, confidence=0.5, source_type="skill"):
    return {
        "id": node_id,
        "content": content,
        "source_type": source_type,
        "source_id": source_id,
        "confidence": confidence,
        "depth": 0,
    }


# ---------------------------------------------------------------------------
# Test 1: Tombstone-Node wird herausgefiltert
# ---------------------------------------------------------------------------

def test_tombstone_node_filtered():
    """graph_walk gibt Tombstone-Node zurück → darf nicht in combined landen."""
    live_node = _make_node(1, "Normaler Skill: Rechnen", source_id="skill-1")
    tombstone_node = _make_node(2, "Skill xyz: tombstone (ghost_skill)", source_id="skill-deleted")

    combined = _apply_tombstone_and_dedup([live_node, tombstone_node])

    contents = [r["content"] for r in combined]
    assert any("Normaler Skill" in c for c in contents), f"Live-Node fehlt: {contents}"
    assert not any("tombstone" in c.lower() for c in contents), \
        f"Tombstone-Node darf nicht in combined landen: {contents}"
    assert len(combined) == 1


def test_tombstone_case_insensitive():
    """Tombstone-Filter ist case-insensitiv (TOMBSTONE, Tombstone, tombstone)."""
    nodes = [
        _make_node(1, "Skill TOMBSTONE (ghost)", source_id="a"),
        _make_node(2, "Skill Tombstone: marker", source_id="b"),
        _make_node(3, "Normaler Skill", source_id="c"),
    ]
    combined = _apply_tombstone_and_dedup(nodes)
    assert len(combined) == 1
    assert combined[0]["content"] == "Normaler Skill"


# ---------------------------------------------------------------------------
# Test 2: Duplikat-source_id → nur höchste Confidence bleibt
# ---------------------------------------------------------------------------

def test_duplicate_source_id_deduped():
    """2 Nodes mit gleicher source_id → nur der mit höherer Confidence bleibt."""
    low_conf = _make_node(76, "Skill A (alt)", source_id="skill-abc", confidence=0.4)
    high_conf = _make_node(122, "Skill A (neu)", source_id="skill-abc", confidence=0.9)

    combined = _apply_tombstone_and_dedup([low_conf, high_conf])

    assert len(combined) == 1, f"Erwartet 1 Result, got {len(combined)}: {combined}"
    assert "Skill A (neu)" in combined[0]["content"], \
        f"Höchste Confidence muss gewinnen: {combined}"


def test_duplicate_source_id_first_processed_wins_on_tie():
    """Bei gleicher Confidence bleibt der erste Node (existing stays wenn equal)."""
    n1 = _make_node(1, "Skill A (first)", source_id="skill-tie", confidence=0.5)
    n2 = _make_node(2, "Skill A (second)", source_id="skill-tie", confidence=0.5)

    combined = _apply_tombstone_and_dedup([n1, n2])
    assert len(combined) == 1
    # n1 kommt zuerst → bleibt (da >, nicht >=)
    assert combined[0]["content"] == "Skill A (first)"


# ---------------------------------------------------------------------------
# Test 3: Normale Nodes passieren unverändert
# ---------------------------------------------------------------------------

def test_normal_nodes_pass_through():
    """Normale Nodes ohne tombstone und mit unterschiedlichen source_ids — alle enthalten."""
    nodes = [
        _make_node(1, "Skill Alpha", source_id="skill-alpha"),
        _make_node(2, "Skill Beta", source_id="skill-beta"),
        _make_node(3, "Skill Gamma", source_id=None),  # kein source_id → immer behalten
    ]

    combined = _apply_tombstone_and_dedup(nodes)

    assert len(combined) == 3, f"Alle 3 Nodes erwartet, got {len(combined)}"
    contents = [r["content"] for r in combined]
    assert any("Alpha" in c for c in contents)
    assert any("Beta" in c for c in contents)
    assert any("Gamma" in c for c in contents), "Node ohne source_id muss enthalten sein"


def test_no_source_id_nodes_always_kept():
    """Nodes ohne source_id werden nie dedupliziert — auch wenn mehrere davon existieren."""
    nodes = [
        _make_node(1, "Anon A", source_id=None),
        _make_node(2, "Anon B", source_id=None),
        _make_node(3, "Anon C", source_id=""),
    ]
    combined = _apply_tombstone_and_dedup(nodes)
    assert len(combined) == 3


def test_empty_graph_results_returns_empty():
    """Leere graph_walk-Ergebnisse → leere combined-Liste."""
    combined = _apply_tombstone_and_dedup([])
    assert combined == []
