"""Pure workflow-package validation shared by operators and platform services."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import jsonschema
import yaml


@lru_cache(maxsize=1)
def _agent_yaml_schema() -> dict:
    return json.loads(files("schemas").joinpath("agent-yaml-schema.json").read_text(encoding="utf-8"))


def validate_plugin_dir(plugin_dir: Path) -> list[str]:
    """Validate that a plugin directory has required files in flat layout."""
    errors: list[str] = []

    agent_yaml_path = plugin_dir / "agent.yaml"
    if not agent_yaml_path.exists():
        errors.append("Missing agent.yaml (platform config)")
    else:
        try:
            agent_config = yaml.safe_load(agent_yaml_path.read_text()) or {}
            jsonschema.validate(agent_config, _agent_yaml_schema())
        except yaml.YAMLError as exc:
            errors.append(f"agent.yaml is not valid YAML: {exc}")
        except jsonschema.ValidationError as exc:
            location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
            errors.append(f"agent.yaml schema violation at {location}: {exc.message}")

    if not (plugin_dir / ".mcp.json").exists():
        errors.append("Missing .mcp.json (MCP server config)")
    if not (plugin_dir / "settings.json").exists():
        errors.append("Missing settings.json (Claude project settings)")

    agents_dir = plugin_dir / "agents"
    if not (agents_dir.exists() and list(agents_dir.glob("*.md"))):
        errors.append("Missing agents/*.md — no agent definitions found")

    mcp_json_path = plugin_dir / ".mcp.json"
    if mcp_json_path.exists():
        try:
            config = json.loads(mcp_json_path.read_text())
            if "mcpServers" not in config:
                errors.append(".mcp.json missing 'mcpServers' key")
        except json.JSONDecodeError as exc:
            errors.append(f".mcp.json is not valid JSON: {exc}")

    hooks_json_path = plugin_dir / "hooks" / "hooks.json"
    if hooks_json_path.exists():
        try:
            json.loads(hooks_json_path.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f"hooks/hooks.json is not valid JSON: {exc}")

    return errors
