from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_admin_api_exposes_provider_aware_model_catalog():
    src = _read("adapters/admin-api/main.py")
    assert '@app.get("/api/models/catalog")' in src
    assert '"OUTPUT_PROVIDER"' in src
    assert '"ollama_cloud"' in src
    assert '"OPENAI_MODEL_PRESETS"' in src
    assert '"ANTHROPIC_MODEL_PRESETS"' in src


def test_frontend_api_has_model_catalog_fetch_with_tags_fallback():
    src = _read("adapters/Jarvis/static/js/api.js")
    assert "export async function getModelCatalog()" in src
    assert "/api/models/catalog" in src
    assert "fallback to /api/tags" in src


def test_chat_quick_selector_persists_output_provider_and_model():
    src = _read("adapters/Jarvis/static/js/app.js")
    assert "OUTPUT_PROVIDER" in src
    assert "persistOutputModelSelection(model, provider)" in src
    assert "data-provider=" in src
    assert "providerLabel" in src
