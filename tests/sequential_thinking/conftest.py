import importlib.util
from pathlib import Path


def _legacy_sequential_module_available() -> bool:
    try:
        return importlib.util.find_spec("modules.sequential_thinking.engine") is not None
    except Exception:
        return False


def pytest_ignore_collect(collection_path: Path, config) -> bool:  # type: ignore[override]
    if _legacy_sequential_module_available():
        return False
    return collection_path.suffix == ".py" and collection_path.name.startswith("test_")
