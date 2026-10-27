"""Unit coverage for external workflow repository validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from sage_run.validation import validate_workflow_repo

pytestmark = pytest.mark.unit


def _copy_valid_workflow(repo: Path, test_plugin_dir: Path) -> Path:
    workflow = repo / "workflows" / "platform-test"
    workflow.parent.mkdir(parents=True)
    shutil.copytree(test_plugin_dir, workflow)
    return workflow


def test_validate_workflow_repo_accepts_valid_package(tmp_path: Path, test_plugin_dir: Path) -> None:
    _copy_valid_workflow(tmp_path, test_plugin_dir)
    (tmp_path / "platform-config.yaml").write_text(
        "memory: {}\nconnections:\n  test-connection:\n    env: {TEST_CONNECTION_URL: https://x.invalid}\n",
        encoding="utf-8",
    )

    assert validate_workflow_repo(tmp_path) == []


def test_validate_workflow_repo_reports_config_syntax(tmp_path: Path, test_plugin_dir: Path) -> None:
    _copy_valid_workflow(tmp_path, test_plugin_dir)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    errors = validate_workflow_repo(tmp_path)

    assert any(error.startswith("broken.json:") for error in errors)


def test_validate_workflow_repo_requires_workflows_directory(tmp_path: Path) -> None:
    assert validate_workflow_repo(tmp_path) == ["Missing workflows directory"]


def test_validate_workflow_repo_reports_package_schema_errors(tmp_path: Path, test_plugin_dir: Path) -> None:
    workflow = _copy_valid_workflow(tmp_path, test_plugin_dir)
    config = {"name": "Not_Valid", "description": "Invalid workflow"}
    (workflow / "agent.yaml").write_text(json.dumps(config), encoding="utf-8")

    errors = validate_workflow_repo(tmp_path)

    assert any(error.startswith("platform-test: agent.yaml schema violation") for error in errors)


@pytest.mark.parametrize("field", ["approval_timeout_sec", "clarification_timeout_sec"])
@pytest.mark.parametrize("value", [1, 120, 604800, 0, 604801, True, "120"])
def test_workflow_schema_validates_human_wait_limits(tmp_path, test_plugin_dir, field, value):
    workflow = _copy_valid_workflow(tmp_path, test_plugin_dir)
    path = workflow / "agent.yaml"
    agent = yaml.safe_load(path.read_text())
    agent.setdefault("runtime", {})[field] = value
    path.write_text(yaml.safe_dump(agent))
    errors = validate_workflow_repo(tmp_path)
    if type(value) is int and 1 <= value <= 604800:
        assert errors == []
    else:
        assert any("schema violation" in error for error in errors)


def test_example_workflow_repo_makefile_has_lint_and_format_targets(repo_root: Path) -> None:
    makefile = (repo_root / "examples/workflow-repo/Makefile").read_text(encoding="utf-8")

    assert "lint: check-venv" in makefile
    assert "format: check-venv" in makefile
    assert "-m sage_run validate ." in makefile


def test_example_repository_validates_and_inherits_the_platform_runtime(repo_root: Path) -> None:
    repo = repo_root / "examples/workflow-repo"
    assert validate_workflow_repo(repo) == []
    agent = yaml.safe_load((repo / "workflows/example-workflow/agent.yaml").read_text(encoding="utf-8"))
    assert agent["name"] == "example-workflow"
    assert not agent["runtime"].get("container_image")
    assert agent["connections"] == ["custom-example"]


def test_example_overlay_replaces_all_secrets_and_discovers_workflow_mcp(repo_root: Path) -> None:
    from sage_run.local import workflow_mcps
    from shared.lib.platform_config import deep_merge, secrets_not_overridden

    repo = repo_root / "examples/workflow-repo"
    base = yaml.safe_load((repo / "platform-config.yaml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load((repo / "platform-config-prod.yaml").read_text(encoding="utf-8"))
    assert secrets_not_overridden(base, overlay) == []
    assert base["config"]["AGE_PUBLIC_KEY"] != overlay["config"]["AGE_PUBLIC_KEY"]
    merged = deep_merge(base, overlay)
    assert merged["deployment"]["sandbox_profile"] == "gvisor"
    servers = workflow_mcps(repo, merged)
    assert len(servers["custom-example"].pop("checksum")) == 64
    assert servers == {
        "custom-example": {"dir": "mcps/custom-mcp-example", "module": "mcp_custom_example", "port": 8110}
    }
    headers = json.loads((repo / "workflows/example-workflow/.mcp.json").read_text(encoding="utf-8"))
    assert headers["mcpServers"]["custom-example"]["headers"]["Authorization"] == "Bearer ${CUSTOM_EXAMPLE_TOKEN}"


@pytest.mark.parametrize("directory", [".git", ".venv", "node_modules"])
def test_validation_ignores_dependency_and_git_metadata(tmp_path: Path, test_plugin_dir: Path, directory: str):
    _copy_valid_workflow(tmp_path, test_plugin_dir)
    ignored = tmp_path / directory
    ignored.mkdir()
    (ignored / "broken.json").write_text("{", encoding="utf-8")
    assert validate_workflow_repo(tmp_path) == []


def test_validate_cli_returns_failure_for_invalid_repo(tmp_path: Path, capsys):
    from sage_run.cli import main

    assert main(["validate", str(tmp_path)]) == 1
    assert "Missing workflows directory" in capsys.readouterr().out


def test_validate_cli_defaults_to_current_directory(monkeypatch, tmp_path: Path, test_plugin_dir: Path):
    from sage_run.cli import main

    _copy_valid_workflow(tmp_path, test_plugin_dir)
    monkeypatch.chdir(tmp_path)
    assert main(["validate"]) == 0


def test_gateway_and_operator_share_package_validation():
    from gateway.plugin_dir import validate_plugin_dir as gateway_validate
    from shared.lib.plugin_validation import validate_plugin_dir

    assert gateway_validate is validate_plugin_dir
