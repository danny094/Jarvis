import asyncio
import importlib.util
import json
from pathlib import Path


def _load_protocol_routes_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "adapters" / "admin-api" / "protocol_routes.py"
    spec = importlib.util.spec_from_file_location("_protocol_routes_date_filter_test", module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _write_proto_file(base: Path, name: str) -> None:
    (base / name).write_text(
        "# Tagesprotokoll 2026-03-02\n\n## 10:15\n**User:** hi\n\n**Jarvis:** ok\n\n---\n",
        encoding="utf-8",
    )


def test_protocol_list_ignores_non_date_markdown_files(tmp_path, monkeypatch):
    mod = _load_protocol_routes_module()
    monkeypatch.setattr(mod, "PROTOCOL_DIR", tmp_path)
    monkeypatch.setattr(mod, "STATUS_FILE", tmp_path / ".protocol_status.json")

    _write_proto_file(tmp_path, "2026-03-02.md")
    _write_proto_file(tmp_path, "notes.md")
    (tmp_path / "rolling_summary.md").write_text("## 2026-03-02\nsummary", encoding="utf-8")

    resp = asyncio.run(mod.protocol_list())
    payload = json.loads(resp.body.decode("utf-8"))

    assert payload["dates"] == [
        {"date": "2026-03-02", "merged": False, "entry_count": 1}
    ]


def test_unmerged_count_ignores_non_date_markdown_files(tmp_path, monkeypatch):
    mod = _load_protocol_routes_module()
    monkeypatch.setattr(mod, "PROTOCOL_DIR", tmp_path)
    monkeypatch.setattr(mod, "STATUS_FILE", tmp_path / ".protocol_status.json")

    _write_proto_file(tmp_path, "2026-03-02.md")
    _write_proto_file(tmp_path, "notes.md")

    resp = asyncio.run(mod.protocol_unmerged_count())
    payload = json.loads(resp.body.decode("utf-8"))

    assert payload["unmerged_count"] == 1
