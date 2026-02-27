from __future__ import annotations

import hashlib
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_mini_control_core_kept_in_sync_across_services():
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / "mcp-servers" / "skill-server" / "mini_control_core.py"
    target = repo_root / "tool_executor" / "mini_control_core.py"

    assert source.exists(), f"missing source: {source}"
    assert target.exists(), f"missing target: {target}"
    assert _sha256(source) == _sha256(target), (
        "mini_control_core drift detected. Run scripts/sync_mini_control_core.py"
    )


def test_wrapper_imports_core_implementation():
    repo_root = Path(__file__).resolve().parents[2]
    ss_wrapper = repo_root / "mcp-servers" / "skill-server" / "mini_control_layer.py"
    te_wrapper = repo_root / "tool_executor" / "mini_control_layer.py"

    ss_src = ss_wrapper.read_text(encoding="utf-8")
    te_src = te_wrapper.read_text(encoding="utf-8")

    assert "from mini_control_core import *" in ss_src
    assert "from mini_control_core import *" in te_src

