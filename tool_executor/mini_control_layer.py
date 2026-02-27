"""
Compatibility wrapper for the unified Mini-Control implementation.

Canonical runtime logic lives in `mini_control_core.py`.
This wrapper intentionally keeps legacy import paths stable.
"""

import mini_control_core as _core
from mini_control_core import *  # noqa: F401,F403

# Backward-compatible export for tests/modules that still access private constants.
_KNOWN_INSTALLED = _core._KNOWN_INSTALLED
