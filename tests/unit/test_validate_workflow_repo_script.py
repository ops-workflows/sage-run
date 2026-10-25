"""Unit coverage for external workflow repository validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sage_run.validation import validate_workflow_repo

pytestmark = pytest.mark.unit


def _copy_valid_workflow(repo: Path, test_plugin_dir: Path) -> Path:
    workflow = repo / "workflows" / "platform-test"
    workflow.parent.mkdir(parents=True)
    shutil.copytree(test_plugin_dir, workflow)
    return workflow


def test_validate_workflow_repo_accepts_valid_package(tmp_path: Path, test_plugin_dir: Path) -> None:
    _copy_valid_workflow(tmp_path, test_plugin_dir)
    (tmp_path / "platform-config.yaml").write_text("memory: {}\n", encoding="utf-8")

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


def test_example_workflow_repo_makefile_has_lint_and_format_targets(repo_root: Path) -> None:
    makefile = (repo_root / "examples/workflow-repo/Makefile").read_text(encoding="utf-8")

    assert "lint: check-venv" in makefile
    assert "format: check-venv" in makefile
    assert "-m sage_run validate ." in makefile


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
