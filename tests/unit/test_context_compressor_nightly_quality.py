import asyncio
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path


def _load_mod():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "core" / "context_compressor.py"
    spec = importlib.util.spec_from_file_location("_ctx_compressor_nightly_test", module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_prepare_nightly_messages_tags_verified_and_unverified():
    mod = _load_mod()
    messages = [
        {"time": "10:00", "role": "User", "text": "Bitte merke dir das für später."},
        {"time": "10:01", "role": "Jarvis", "text": 'run_skill: {"success": true, "result": "GPU 68.0%"}'},
        {"time": "10:02", "role": "Jarvis", "text": "Mir geht es super und ich bin cloud-weit aktiv."},
    ]
    prepared = mod._prepare_nightly_messages(messages)
    roles = [m["role"] for m in prepared["messages"]]
    assert "USER" in roles
    assert "TRION_VERIFIED" in roles
    assert "TRION_UNVERIFIED" in roles
    assert prepared["evidence_count"] == 2
    assert prepared["unverified_count"] == 1


def test_validate_summary_payload_accepts_normalized_numbers():
    mod = _load_mod()
    payload = mod._normalize_summary_payload(
        {"verified_facts": ["GPU Auslastung: 68 %"], "decisions": [], "open_tasks": [], "important_context": [], "uncertain_claims": []}
    )
    result = mod._validate_summary_payload(payload, "GPU Auslastung 68.0%")
    assert result["ok"] is True


def test_validate_summary_payload_rejects_unknown_numeric_claims():
    mod = _load_mod()
    payload = mod._normalize_summary_payload(
        {"verified_facts": ["CPU Auslastung: 50 %"], "decisions": [], "open_tasks": [], "important_context": [], "uncertain_claims": []}
    )
    result = mod._validate_summary_payload(payload, "CPU Auslastung 0.5%")
    assert result["ok"] is False
    assert result["reason"] == "unknown_numeric_claims"


def test_summarize_yesterday_uses_fallback_and_writes_rich_status(tmp_path, monkeypatch):
    mod = _load_mod()
    monkeypatch.setattr(mod, "PROTOCOL_DIR", tmp_path)
    monkeypatch.setattr(mod, "ROLLING_SUMMARY_FILE", tmp_path / "rolling_summary.md")

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    protocol_file = tmp_path / f"{yesterday}.md"
    protocol_file.write_text(
        (
            f"# Tagesprotokoll {yesterday}\n\n"
            "## 10:00\n**User:** bitte merke dir dass wir später 1+1 berechnen\n\n"
            '**Jarvis:** run_skill: {"success": true, "result": "CPU 0.5%"}\n\n---\n'
        ),
        encoding="utf-8",
    )

    async def _fake_summary(_messages):
        return mod._normalize_summary_payload(
            {
                "verified_facts": ["CPU Auslastung 50 %"],
                "decisions": [],
                "open_tasks": [],
                "important_context": [],
                "uncertain_claims": [],
            }
        )

    monkeypatch.setattr(mod, "_summarize_structured", _fake_summary)

    ran = asyncio.run(mod.summarize_yesterday(force=True))
    assert ran is True

    status_path = tmp_path / ".daily_summary_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["fallback_used"] is True
    assert status["validation_passed"] is False
    assert status["validation_reason"] == "unknown_numeric_claims"
    assert status["prepared_message_count"] >= 1

    out = (tmp_path / "rolling_summary.md").read_text(encoding="utf-8")
    assert f"## {yesterday}" in out
    assert "**Verified Facts**" in out
    assert "**Uncertain Claims**" in out
