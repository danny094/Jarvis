import json

import pytest

import container_commander.home_memory as hm


def _write_identity(path, *, max_note_size_kb: int = 10) -> None:
    payload = {
        "container_id": "trion-home",
        "home_path": str(path.parent.parent / "home"),
        "capabilities": {
            "importance_threshold": 0.72,
            "forced_keywords": ["merk dir", "vergiss nicht", "wichtig", "merke"],
            "redact_patterns": ["token", "secret", "password", "api_key", "Bearer"],
            "max_note_size_kb": max_note_size_kb,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def test_remember_note_respects_threshold_and_forced_keywords(monkeypatch, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected"})

    out_skip = hm.remember_note(
        content="kurze notiz ohne trigger",
        importance=0.20,
        identity_path=str(identity_path),
    )
    assert out_skip["saved"] is False
    assert out_skip["reason"] == "below_threshold"

    out_forced = hm.remember_note(
        content="Merk dir: user prefers compact APIs",
        importance=0.20,
        category="user_preference",
        identity_path=str(identity_path),
    )
    assert out_forced["saved"] is True
    assert out_forced["note"]["trigger"] == "forced"

    recent = hm.recent_notes(limit=5, identity_path=str(identity_path))
    assert recent["count"] == 1
    assert "compact APIs" in recent["notes"][0]["content"]


def test_remember_note_blocks_sensitive_content(monkeypatch, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected"})

    with pytest.raises(hm.MemoryPolicyError) as exc:
        hm.remember_note(
            content="My password is 1234",
            importance=0.95,
            identity_path=str(identity_path),
        )
    assert exc.value.error_code == "policy_denied"
    assert exc.value.details.get("matched_pattern", "").lower() == "password"


def test_remember_note_blocks_oversized_payload(monkeypatch, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path, max_note_size_kb=1)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected"})

    large = "x" * 1300
    with pytest.raises(hm.MemoryPolicyError) as exc:
        hm.remember_note(
            content=large,
            importance=0.95,
            identity_path=str(identity_path),
        )
    assert exc.value.error_code == "bad_request"
    assert exc.value.details.get("max_note_size_kb") == 1


def test_recall_notes_matches_terms_and_category(monkeypatch, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected"})

    hm.remember_note(
        content="Node service uses redis cache",
        category="project_fact",
        importance=0.9,
        identity_path=str(identity_path),
    )
    hm.remember_note(
        content="User likes short answers",
        category="user_preference",
        importance=0.9,
        identity_path=str(identity_path),
    )

    out = hm.recall_notes(
        query="redis service",
        category="project_fact",
        identity_path=str(identity_path),
    )
    assert out["count"] == 1
    assert "redis" in out["notes"][0]["content"].lower()


def test_remember_note_emits_saved_and_skipped_events(monkeypatch, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected"})

    events = []
    monkeypatch.setattr(hm, "_emit_ws_activity", lambda event, level="info", message="", **data: events.append((event, level, message, data)))

    hm.remember_note(
        content="normal low-signal message",
        importance=0.10,
        identity_path=str(identity_path),
    )
    hm.remember_note(
        content="merk dir: user likes fast feedback",
        importance=0.20,
        identity_path=str(identity_path),
    )

    names = [e[0] for e in events]
    assert "memory_skipped" in names
    assert "memory_saved" in names


def test_remember_note_emits_denied_event_on_sensitive_content(monkeypatch, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected"})

    events = []
    monkeypatch.setattr(hm, "_emit_ws_activity", lambda event, level="info", message="", **data: events.append((event, level, message, data)))

    with pytest.raises(hm.MemoryPolicyError):
        hm.remember_note(
            content="secret token value",
            importance=0.95,
            identity_path=str(identity_path),
        )

    assert events
    assert events[-1][0] == "memory_denied"
    assert events[-1][1] in {"warn", "error"}
