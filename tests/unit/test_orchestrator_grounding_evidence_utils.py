import json

from core.orchestrator_grounding_evidence_utils import build_grounding_evidence_entry


def test_grounding_evidence_entry_prefers_result_lines_for_key_facts():
    raw = json.dumps(
        {
            "success": True,
            "result": "CPU: X\nRAM: Y\nGPU: Z\nStorage: Q",
        }
    )
    entry = build_grounding_evidence_entry("run_skill", raw, "ok", "ref-1")
    facts = entry.get("key_facts", [])
    assert any("GPU: Z" in line for line in facts)
    assert entry.get("structured", {}).get("result")


def test_grounding_evidence_entry_formats_list_skills_summary():
    raw = json.dumps(
        {
            "installed": [{"name": "a"}, {"name": "b"}],
            "installed_count": 2,
            "available": [],
            "available_count": 0,
        }
    )
    entry = build_grounding_evidence_entry("list_skills", raw, "ok", "ref-2")
    assert "installed_count: 2" in entry.get("key_facts", [])
    assert "available_count: 0" in entry.get("key_facts", [])
    assert entry.get("structured", {}).get("installed_names") == ["a", "b"]
