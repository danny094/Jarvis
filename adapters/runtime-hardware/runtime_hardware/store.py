from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict


logger = logging.getLogger(__name__)


class StateStore:
    def __init__(self, *, config_dir: str, state_dir: str) -> None:
        self.config_dir = Path(config_dir)
        self.state_dir = Path(state_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "StateStore":
        config_dir = os.environ.get("RUNTIME_HARDWARE_CONFIG_DIR", "/app/data/config")
        state_dir = os.environ.get("RUNTIME_HARDWARE_STATE_DIR", "/app/data/state")
        try:
            return cls(config_dir=config_dir, state_dir=state_dir)
        except PermissionError:
            fallback_root = Path(os.getcwd()) / ".runtime-hardware"
            return cls(
                config_dir=str(fallback_root / "config"),
                state_dir=str(fallback_root / "state"),
            )

    def write_json(self, name: str, payload: Dict[str, Any]) -> str:
        target = self.state_dir / name
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            tmp.replace(target)
            return str(target)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            logger.warning("runtime-hardware state write skipped for %s: %s", target, exc)
            return ""

    def read_json(self, name: str) -> Dict[str, Any]:
        target = self.state_dir / name
        if not target.exists():
            return {}
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return {}
