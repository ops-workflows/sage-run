"""Validate an existing workflow repository without contacting platform services."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from shared.lib.connections import ConnectionConfigError, parse_connections, resolve_workflow_connections
from shared.lib.platform_config import deep_merge, read_yaml_mapping, secrets_not_overridden
from shared.lib.plugin_validation import validate_plugin_dir

# Variables the platform sets for every task, available to .mcp.json headers.
RUNTIME_VARIABLES = {
    "TASK_ID",
    "TASK_PROMPT",
    "TASK_WORKFLOW",
    "MAX_TURNS",
    "MESSAGE_CHANNEL",
    "MESSAGE_CHANNEL_ID",
    "MESSAGE_THREAD_ID",
    "MESSAGE_TEAM_ID",
    "MESSAGE_TEAM_NAME",
    "CONTROL_PLANE_UI_URL",
    "HINDSIGHT_URL",
    "GATEWAY_EVENT_URL",
    "EVENT_COLLECTOR_URL",
}
_VARIABLE_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_workflow_repo(workflow_repo: Path) -> list[str]:
    return validate_workflow_repo_report(workflow_repo).errors


def validate_workflow_repo_report(workflow_repo: Path) -> ValidationReport:
    workflow_repo = workflow_repo.resolve()
    report = ValidationReport()

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
            report.errors.append(f"{path.relative_to(workflow_repo)}: {exc}")

    workflows_dir = workflow_repo / "workflows"
    if not workflows_dir.is_dir():
        report.errors.append("Missing workflows directory")
        return report
    workflows = [workflow for workflow in sorted(workflows_dir.iterdir()) if workflow.is_dir()]
    for workflow in workflows:
        report.errors.extend(f"{workflow.name}: {error}" for error in validate_plugin_dir(workflow))
    if report.errors:
        return report

    base_file = workflow_repo / "platform-config.yaml"
    if not base_file.is_file():
        return report
    try:
        base = read_yaml_mapping(base_file)
    except ValueError as exc:
        report.errors.append(str(exc))
        return report
    _validate_configuration(report, base, workflows, label="platform-config.yaml", warn=True)

    for overlay_file in sorted(workflow_repo.glob("platform-config-*.yaml")):
        try:
            overlay = read_yaml_mapping(overlay_file)
        except ValueError as exc:
            report.errors.append(str(exc))
            continue
        _validate_overlay(report, base, overlay, overlay_file.name)
        _validate_configuration(report, deep_merge(base, overlay), workflows, label=overlay_file.name, warn=False)
    return report


def _validate_overlay(report: ValidationReport, base: dict, overlay: dict, name: str) -> None:
    base_key = str((base.get("config") or {}).get("AGE_PUBLIC_KEY") or "")
    overlay_key = str((overlay.get("config") or {}).get("AGE_PUBLIC_KEY") or "")
    if not overlay_key:
        report.errors.append(f"{name}: config.AGE_PUBLIC_KEY must name this environment's key")
    elif overlay_key == base_key:
        report.errors.append(f"{name}: config.AGE_PUBLIC_KEY must differ from the base (development) key")
    for path in secrets_not_overridden(base, overlay):
        report.errors.append(f"{name}: encrypted value {path} is not overridden, so it needs the development key")


def _validate_configuration(
    report: ValidationReport, config: dict, workflows: list[Path], *, label: str, warn: bool
) -> None:
    try:
        connections = parse_connections(config)
    except ConnectionConfigError as exc:
        report.errors.append(f"{label}: {exc}")
        return
    if warn:
        for connection in connections.values():
            for secret in connection.unset_secrets:
                report.warnings.append(f"{label}: connection {connection.name} secret {secret} is not set")
    platform_variables = set(RUNTIME_VARIABLES)
    platform_variables |= {str(key) for key in (config.get("runtime_env") or {})}
    for profile in (config.get("model_profiles") or {}).values():
        if isinstance(profile, dict):
            platform_variables |= {str(key) for key in profile if str(key).isupper()}

    for workflow in workflows:
        agent_config = yaml.safe_load((workflow / "agent.yaml").read_text(encoding="utf-8")) or {}
        try:
            resolved = resolve_workflow_connections(config, workflow.name, agent_config)
        except ConnectionConfigError as exc:
            report.errors.append(f"{label}: {exc}")
            continue
        if not warn:
            continue
        provided = platform_variables | {str(key) for key in (agent_config.get("env") or {})}
        provided |= {str(key) for key in (agent_config.get("secrets") or {})}
        for connection in resolved:
            provided |= {*connection.env, *connection.secrets}
        mcp_file = workflow / ".mcp.json"
        referenced = (
            set(_VARIABLE_REFERENCE.findall(mcp_file.read_text(encoding="utf-8"))) if mcp_file.exists() else set()
        )
        for variable in sorted(referenced - provided):
            report.warnings.append(
                f"{workflow.name}: .mcp.json uses ${{{variable}}}, which no connection, env or platform value provides"
            )
