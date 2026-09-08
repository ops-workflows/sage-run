"""Unit coverage for external workflow repository validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.validate_workflow_repo import validate_workflow_repo

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
    assert "scripts/validate_workflow_repo.py" in makefile
