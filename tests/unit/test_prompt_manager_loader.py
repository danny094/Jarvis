import pytest

from intelligence_modules import prompt_manager
from intelligence_modules.prompt_manager import loader
from intelligence_modules.prompt_manager.errors import (
    PromptFrontmatterError,
    PromptNotFoundError,
    PromptRenderError,
)


def write_prompt(root, category, name, content):
    path = root / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{name}.md").write_text(content, encoding="utf-8")


def test_load_prompt_renders_declared_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)
    write_prompt(
        tmp_path,
        "contracts",
        "container",
        """---
scope: container_contract
target: output_layer
variables: ["required_tools", "truth_mode"]
---

Use {required_tools}.
Truth mode: {truth_mode}.
""",
    )

    rendered = prompt_manager.load_prompt(
        "contracts",
        "container",
        required_tools="runtime inventory",
        truth_mode="strict",
    )

    assert rendered == "Use runtime inventory.\nTruth mode: strict."


def test_load_prompt_accepts_md_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)
    write_prompt(
        tmp_path,
        "layers",
        "output",
        """---
variables: []
---

Static text.
""",
    )

    assert prompt_manager.load_prompt("layers", "output.md") == "Static text."


def test_load_prompt_missing_template_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)

    with pytest.raises(PromptNotFoundError, match="Prompt template not found"):
        prompt_manager.load_prompt("contracts", "missing")


def test_load_prompt_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)

    with pytest.raises(PromptNotFoundError, match="Invalid prompt"):
        prompt_manager.load_prompt("../contracts", "container")


def test_load_prompt_missing_variable_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)
    write_prompt(
        tmp_path,
        "contracts",
        "container",
        """---
variables: ["required_tools"]
---

Use {required_tools}.
""",
    )

    with pytest.raises(PromptRenderError, match="Missing required prompt variable"):
        prompt_manager.load_prompt("contracts", "container")


def test_load_prompt_undeclared_placeholder_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)
    write_prompt(
        tmp_path,
        "contracts",
        "container",
        """---
variables: []
---

Use {required_tools}.
""",
    )

    with pytest.raises(PromptRenderError, match="undeclared variable"):
        prompt_manager.load_prompt("contracts", "container", required_tools="tools")


def test_load_prompt_invalid_frontmatter_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)
    write_prompt(
        tmp_path,
        "contracts",
        "broken",
        """---
variables: ["missing"
---

Body.
""",
    )

    with pytest.raises(PromptFrontmatterError, match="Invalid frontmatter value"):
        prompt_manager.load_prompt("contracts", "broken")


def test_load_prompt_requires_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "PROMPTS_ROOT", tmp_path)
    write_prompt(tmp_path, "contracts", "plain", "Body without metadata.")

    with pytest.raises(PromptFrontmatterError, match="must start with frontmatter"):
        prompt_manager.load_prompt("contracts", "plain")
