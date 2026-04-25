from container_commander.models import NetworkMode


def test_ubuntu_network_blueprint_is_seeded_for_existing_stores(tmp_path, monkeypatch):
    import container_commander.blueprint_store as store
    from container_commander.trust import evaluate_blueprint_trust

    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "commander.db"))
    monkeypatch.setattr(store, "_INIT_DONE", False)

    store.ensure_store_initialized(seed_defaults=True)
    shell = store.get_blueprint("shell-sandbox")
    assert shell is not None

    # Simulate an older install that already had default blueprints before the
    # Ubuntu network blueprint existed.
    conn = store._get_conn()
    try:
        conn.execute("DELETE FROM blueprints WHERE id = ?", ("ubuntu-network",))
        conn.commit()
    finally:
        conn.close()
    assert store.get_blueprint("ubuntu-network") is None

    store.seed_default_blueprints()

    ubuntu = store.get_blueprint("ubuntu-network")
    assert ubuntu is not None
    assert ubuntu.network == NetworkMode.BRIDGE
    assert "ubuntu:24.04" in ubuntu.dockerfile
    assert 'CMD ["sleep", "infinity"]' in ubuntu.dockerfile
    assert "apt-get" in ubuntu.allowed_exec
    assert "curl" in ubuntu.allowed_exec
    assert "network" in ubuntu.tags

    trust = evaluate_blueprint_trust(ubuntu)
    assert trust["level"] == "verified"
    assert trust["source"] == "official-set"
