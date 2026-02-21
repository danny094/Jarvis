#!/usr/bin/env python3
"""
scripts/digest_worker.py — Standalone entry-point for digest sidecar (Phase 8 Operational).

Usage:
    python scripts/digest_worker.py

Required env vars:
    DIGEST_ENABLE=true
    DIGEST_DAILY_ENABLE=true
    DIGEST_RUN_MODE=sidecar

Optional:
    DIGEST_WEEKLY_ENABLE=true
    DIGEST_ARCHIVE_ENABLE=true
    DIGEST_CATCHUP_MAX_DAYS=7
    DIGEST_TZ=Europe/Berlin

The worker runs catch-up on startup, then schedules at 04:00 DIGEST_TZ daily.
Rollback: set DIGEST_RUN_MODE=off or remove from docker-compose.
"""
import sys
import os

# Add project root to Python path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from utils.logger import log_info
from core.digest.worker import DigestWorker

if __name__ == "__main__":
    log_info("[DigestWorker] Sidecar entry-point starting")
    worker = DigestWorker()
    worker.run_loop()
