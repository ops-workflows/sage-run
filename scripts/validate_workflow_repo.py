#!/usr/bin/env python3
"""Validate syntax and workflow packages in an external SAGE Run workflow repository."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gateway.plugin_dir import validate_plugin_dir  # noqa: E402


def validate_workflow_repo(workflow_repo: Path) -> list[str]:
    workflow_repo = workflow_repo.resolve()
    errors: list[str] = []

    config_paths = sorted(
        (*workflow_repo.rglob("*.json"), *workflow_repo.rglob("*.yaml"), *workflow_repo.rglob("*.yml"))
    )
    for path in config_paths:
        if ".git" in path.parts:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_repo", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()

    errors = validate_workflow_repo(args.workflow_repo)
    for error in errors:
        print(error)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
