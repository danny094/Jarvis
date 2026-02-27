from pathlib import Path


def _read_main() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "adapters" / "admin-api" / "main.py"
    return path.read_text(encoding="utf-8")


def test_done_branch_checked_before_generic_metadata_branch():
    src = _read_main()
    idx_done = src.index("if is_done:")
    idx_generic = src.index('elif chunk_type and chunk_type != "content" and metadata:')
    assert idx_done < idx_generic


def test_done_branch_emits_done_true():
    src = _read_main()
    done_block = src[src.index("if is_done:"): src.index("elif chunk_type == \"thinking_stream\":")]
    assert '"done": True' in done_block
