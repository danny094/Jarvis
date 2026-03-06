from __future__ import annotations

import importlib
import os
from unittest.mock import patch


def test_get_db_creates_parent_directory_for_file_db_path(tmp_path):
    mod = importlib.import_module("core.lifecycle.archive")
    prev_db_path = mod.DB_PATH
    prev_schema_ready = mod._EMBED_SCHEMA_READY
    db_path = tmp_path / "nested" / "memory.db"

    mod.DB_PATH = str(db_path)
    mod._EMBED_SCHEMA_READY = False
    try:
        conn = mod._get_db()
        conn.close()
        assert db_path.parent.exists()
        assert db_path.exists()
    finally:
        mod.DB_PATH = prev_db_path
        mod._EMBED_SCHEMA_READY = prev_schema_ready


def test_get_db_does_not_create_directory_for_memory_path():
    mod = importlib.import_module("core.lifecycle.archive")
    prev_db_path = mod.DB_PATH
    prev_schema_ready = mod._EMBED_SCHEMA_READY

    mod.DB_PATH = ":memory:"
    mod._EMBED_SCHEMA_READY = False
    try:
        with patch("core.lifecycle.archive.os.makedirs", side_effect=AssertionError("makedirs should not be called")):
            conn = mod._get_db()
            conn.close()
    finally:
        mod.DB_PATH = prev_db_path
        mod._EMBED_SCHEMA_READY = prev_schema_ready


def test_get_db_falls_back_when_primary_directory_is_not_writable(tmp_path):
    mod = importlib.import_module("core.lifecycle.archive")
    prev_db_path = mod.DB_PATH
    prev_schema_ready = mod._EMBED_SCHEMA_READY
    prev_warned = getattr(mod, "_DB_FALLBACK_WARNED", False)
    fallback_db = tmp_path / "fallback" / "memory.db"

    mod.DB_PATH = "/blocked/memory.db"
    mod._EMBED_SCHEMA_READY = False
    mod._DB_FALLBACK_WARNED = False
    real_makedirs = os.makedirs

    def _fake_makedirs(path, exist_ok=False):
        if str(path) == "/blocked":
            raise PermissionError("blocked for test")
        return real_makedirs(path, exist_ok=exist_ok)

    with patch.dict(
        os.environ,
        {"MEMORY_DB_FALLBACK_PATH": str(fallback_db)},
        clear=False,
    ), patch("core.lifecycle.archive.os.makedirs", side_effect=_fake_makedirs):
        conn = mod._get_db()
        conn.close()

    try:
        assert fallback_db.exists()
    finally:
        mod.DB_PATH = prev_db_path
        mod._EMBED_SCHEMA_READY = prev_schema_ready
        mod._DB_FALLBACK_WARNED = prev_warned
