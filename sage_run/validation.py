"""Validate an existing workflow repository without contacting platform services."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sage_run.local import deployment_settings, workflow_mcps
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
_SAGE_RUN_SPEC = re.compile(r"^sage-run(?:\[[A-Za-z0-9_,-]+\])?(.*)$")
_EXACT_RELEASE_PIN = re.compile(r"^==([0-9]+\.[0-9]+\.[0-9]+)$")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_workflow_repo(workflow_repo: Path, *, require_pin: bool = False) -> list[str]:
    return validate_workflow_repo_report(workflow_repo, require_pin=require_pin).errors


def validate_dependency_pin(workflow_repo: Path, report: ValidationReport, *, require: bool = False) -> str | None:
    """Validate pyproject.toml and uv.lock agreement for the pinned sage-run release."""
    pyproject_path = workflow_repo / "pyproject.toml"
    lock_path = workflow_repo / "uv.lock"
    if not require and not pyproject_path.exists() and not lock_path.exists():
        return None
    if not pyproject_path.is_file():
        report.errors.append("Missing pyproject.toml (workflow repositories must pin sage-run==<release>)")
        return None
    if not lock_path.is_file():
        report.errors.append("Missing uv.lock (commit uv.lock alongside pyproject.toml)")
        return None
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        report.errors.append(f"pyproject.toml: {exc}")
        return None
    try:
        lock_data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        report.errors.append(f"uv.lock: {exc}")
        return None

    project = pyproject.get("project")
    dependencies = project.get("dependencies") if isinstance(project, dict) else None
    if not isinstance(dependencies, list):
        report.errors.append("pyproject.toml: project.dependencies must be a list")
        return None

    pinned_versions: list[str] = []
    invalid_specs: list[str] = []
    for raw_dep in dependencies:
        if not isinstance(raw_dep, str):
            continue
        compact = "".join(raw_dep.split())
        match = _SAGE_RUN_SPEC.match(compact)
        if not match:
            continue
        pin_match = _EXACT_RELEASE_PIN.match(match.group(1))
        if pin_match:
            pinned_versions.append(pin_match.group(1))
        else:
            invalid_specs.append(raw_dep)

    if invalid_specs or len(pinned_versions) != 1:
        report.errors.append(
            "pyproject.toml: project.dependencies must contain an exact release pin 'sage-run==<X.Y.Z>'"
        )
        return None
    pinned_version = pinned_versions[0]

    uv_tool = (pyproject.get("tool") or {}).get("uv")
    uv_sources = uv_tool.get("sources") if isinstance(uv_tool, dict) else None
    if isinstance(uv_sources, dict) and "sage-run" in uv_sources:
        report.errors.append("pyproject.toml: tool.uv.sources must not override sage-run with a local or git source")
        return None

    packages = lock_data.get("package")
    if not isinstance(packages, list):
        report.errors.append("uv.lock: missing [[package]] entries")
        return None

    sage_packages = [pkg for pkg in packages if isinstance(pkg, dict) and pkg.get("name") == "sage-run"]
    if len(sage_packages) != 1:
        report.errors.append("uv.lock: missing locked package entry for sage-run")
        return None

    sage_pkg = sage_packages[0]
    locked_version = str(sage_pkg.get("version") or "")
    if locked_version != pinned_version:
        report.errors.append(
            f"uv.lock: locked sage-run version ({locked_version or 'missing'}) "
            f"does not match pyproject.toml pin ({pinned_version})"
        )
        return None

    source = sage_pkg.get("source")
    forbidden_source_keys = {"editable", "path", "directory", "git", "url", "virtual"}
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("registry"), str)
        or not source.get("registry")
        or forbidden_source_keys.intersection(source)
    ):
        report.errors.append("uv.lock: sage-run must resolve from a published registry, not a local or git source")
        return None

    root_packages = [
        pkg
        for pkg in packages
        if isinstance(pkg, dict)
        and isinstance(pkg.get("source"), dict)
        and ("virtual" in pkg["source"] or "editable" in pkg["source"])
    ]
    if root_packages:
        root_deps = root_packages[0].get("dependencies") or []
        if not any(isinstance(dep, dict) and dep.get("name") == "sage-run" for dep in root_deps):
            report.errors.append("uv.lock: root project dependencies do not include sage-run; re-run 'uv lock'")
            return None

    return pinned_version


def validate_workflow_repo_report(workflow_repo: Path, *, require_pin: bool = False) -> ValidationReport:
    workflow_repo = workflow_repo.resolve()
    report = ValidationReport()
    validate_dependency_pin(workflow_repo, report, require=require_pin)

    config_paths = sorted(
        (*workflow_repo.rglob("*.json"), *workflow_repo.rglob("*.yaml"), *workflow_repo.rglob("*.yml"))
    )
    for path in config_paths:
        if {".git", ".venv", "node_modules", ".pytest_cache", ".ruff_cache"}.intersection(
            path.relative_to(workflow_repo).parts
        ):
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
    _validate_configuration(
        report, base, workflows, workflow_repo=workflow_repo, label="platform-config.yaml", warn=True
    )

    for overlay_file in sorted(workflow_repo.glob("platform-config-*.yaml")):
        try:
            overlay = read_yaml_mapping(overlay_file)
        except ValueError as exc:
            report.errors.append(str(exc))
            continue
        _validate_overlay(report, base, overlay, overlay_file.name)
        _validate_configuration(
            report,
            deep_merge(base, overlay),
            workflows,
            workflow_repo=workflow_repo,
            label=overlay_file.name,
            warn=False,
        )
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
    report: ValidationReport,
    config: dict,
    workflows: list[Path],
    *,
    workflow_repo: Path,
    label: str,
    warn: bool,
) -> None:
    try:
        deployment_settings(config)
    except ValueError as exc:
        report.errors.append(f"{label}: {exc}")
    try:
        workflow_mcps(workflow_repo, config)
    except ValueError as exc:
        report.errors.append(f"{label}: {exc}")
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
