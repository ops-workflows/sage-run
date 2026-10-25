"""Optional Docker Compose profiles derived from a workflow repository's platform config."""

from __future__ import annotations

from pathlib import Path

import yaml

MCP_PROFILES = {
    "salesforce": "salesforce",
    "splunk": "splunk",
    "cloudwatch": "cloudwatch",
    "gcp-logging": "gcp-logging",
    "jira": "jira",
    "github": "github",
}
CONNECTOR_PROFILES = {"gcp-pubsub": "gcp-pubsub", "servicenow": "servicenow"}
MODEL_BACKEND_PROFILES = {"model-gateway": "model-gateway", "local-llm": "local-llm"}


def compute_profiles(config: dict) -> list[str]:
    profiles: set[str] = set()
    for server_id in (config.get("mcps") or {}).get("enabled") or []:
        if server_id in MCP_PROFILES:
            profiles.add(MCP_PROFILES[server_id])
    connectors = config.get("connectors") or {}
    instances = connectors.get("instances") or {}
    for instance_id in connectors.get("enabled") or []:
        connector_type = (instances.get(instance_id) or {}).get("type")
        if connector_type in CONNECTOR_PROFILES:
            profiles.add(CONNECTOR_PROFILES[connector_type])
    for profile in (config.get("model_profiles") or {}).values():
        base_url = str((profile or {}).get("ANTHROPIC_BASE_URL") or "")
        for needle, profile_name in MODEL_BACKEND_PROFILES.items():
            if needle in base_url:
                profiles.add(profile_name)
    return sorted(profiles)


def workflow_profiles(workflow_repo: Path) -> list[str]:
    config_file = workflow_repo / "platform-config.yaml"
    try:
        config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {config_file}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"Expected a mapping in {config_file}")
    return compute_profiles(config)
