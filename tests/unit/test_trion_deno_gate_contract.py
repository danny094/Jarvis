from pathlib import Path


def test_deno_gate_supports_local_or_container_fallback():
    root = Path(__file__).resolve().parents[2]
    src = (root / "scripts" / "test_trion_deno_runtime_gate.sh").read_text(encoding="utf-8")
    assert "if command -v deno >/dev/null 2>&1; then" in src
    assert "docker exec trion-runtime deno --version" in src
    assert "docker cp" in src
    assert "DENO_DIR=/tmp/deno-dir deno test -A /tmp/test_deno_runtime.ts" in src
