#!/usr/bin/env python3
"""
Sync or check mini_control_core.py parity between services.

Single source of truth:
  mcp-servers/skill-server/mini_control_core.py
"""

from __future__ import annotations

import hashlib
import sys
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "mcp-servers" / "skill-server" / "mini_control_core.py"
TARGET = REPO_ROOT / "tool_executor" / "mini_control_core.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_only() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing source: {SOURCE}")
    if not TARGET.exists():
        print(f"missing target: {TARGET}")
        return 1
    src_hash = _sha256(SOURCE)
    dst_hash = _sha256(TARGET)
    print(f"sha256 source={src_hash}")
    print(f"sha256 target={dst_hash}")
    if src_hash != dst_hash:
        print("mini_control_core drift detected. Run scripts/sync_mini_control_core.py")
        return 1
    print("mini_control_core parity OK")
    return 0


def _sync() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing source: {SOURCE}")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, TARGET)

    src_hash = _sha256(SOURCE)
    dst_hash = _sha256(TARGET)
    print(f"synced: {SOURCE} -> {TARGET}")
    print(f"sha256 source={src_hash}")
    print(f"sha256 target={dst_hash}")
    return 0 if src_hash == dst_hash else 1


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] in {"--check", "check"}:
        return _check_only()
    return _sync()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
