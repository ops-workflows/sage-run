"""Validate an existing workflow repository without contacting platform services."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from shared.lib.plugin_validation import validate_plugin_dir


def validate_workflow_repo(workflow_repo: Path) -> list[str]:
    workflow_repo = workflow_repo.resolve()
    errors: list[str] = []

    config_paths = sorted(
        (*workflow_repo.rglob("*.json"), *workflow_repo.rglob("*.yaml"), *workflow_repo.rglob("*.yml"))
    )
    for path in config_paths:
        if {".git", ".venv", "node_modules"}.intersection(path.relative_to(workflow_repo).parts):
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                if path.suffix == ".json":
                    json.load(handle)
                else:
                    list(yaml.safe_load_all(handle))
        except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
            errors.append(f"{path.relative_to(workflow_repo)}: {exc}")

    workflows_dir = workflow_repo / "workflows"
    if not workflows_dir.is_dir():
        errors.append("Missing workflows directory")
        return errors
    for workflow in sorted(workflows_dir.iterdir()):
        if workflow.is_dir():
            errors.extend(f"{workflow.name}: {error}" for error in validate_plugin_dir(workflow))
    return errors
