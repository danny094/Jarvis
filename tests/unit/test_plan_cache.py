import os

from core.plan_cache import PlanCache, SqlitePlanCache, make_plan_cache


def test_plan_cache_memory_roundtrip():
    cache = PlanCache(ttl_seconds=60)
    cache.set("hello", {"intent": "x"})
    assert cache.get("hello") == {"intent": "x"}


def test_sqlite_plan_cache_roundtrip(tmp_path):
    db = tmp_path / "plan_cache.sqlite"
    cache = SqlitePlanCache(
        ttl_seconds=60,
        db_path=str(db),
        namespace="test_ns",
    )
    cache.set("hello", {"intent": "y"})
    assert cache.get("hello") == {"intent": "y"}


def test_make_plan_cache_falls_back_to_memory_for_unknown_backend(monkeypatch):
    monkeypatch.setenv("TRION_PLAN_CACHE_BACKEND", "unknown")
    cache = make_plan_cache(ttl_seconds=60, namespace="fallback")
    assert isinstance(cache, PlanCache)


def test_make_plan_cache_uses_sqlite_backend(monkeypatch, tmp_path):
    db = tmp_path / "shared.sqlite"
    monkeypatch.setenv("TRION_PLAN_CACHE_BACKEND", "sqlite")
    monkeypatch.setenv("TRION_PLAN_CACHE_DB", str(db))
    cache = make_plan_cache(ttl_seconds=60, namespace="sqlite_ns")
    assert isinstance(cache, SqlitePlanCache)
