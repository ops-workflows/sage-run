"""Named connections: shared integration settings and secrets in platform config.

A connection groups the environment variables one integration needs, for
example::

    connections:
      splunk:
        description: Corporate Splunk
        workflows: [online-alerts-investigator]
        env:
          SPLUNK_BASE_URL: https://splunk.example
        secrets:
          SPLUNK_PASSWORD:
            encrypted: ENC[age,...]

A workflow lists the connections it uses in ``agent.yaml`` (``connections:
[splunk]``). Its tasks receive those variables, so ``.mcp.json`` headers such as
``${SPLUNK_PASSWORD}`` expand as before and the secret names join the sandbox
credential deny-list. ``workflows`` restricts which workflows may use a
connection; omit it to allow all. A secret without an ``encrypted`` value (``null``
or only a ``description``) is declared but not populated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from shared.lib.crypto import decrypt_named_secrets

NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ConnectionConfigError(ValueError):
    """Invalid connection definition or reference."""


@dataclass(frozen=True)
class Connection:
    name: str
    env: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    workflows: tuple[str, ...] | None = None

    def allows(self, workflow: str) -> bool:
        return self.workflows is None or workflow in self.workflows

    @property
    def unset_secrets(self) -> list[str]:
        return sorted(name for name, spec in self.secrets.items() if not (spec or {}).get("encrypted"))


def parse_connections(platform_config: dict[str, Any]) -> dict[str, Connection]:
    section = platform_config.get("connections") or {}
    if not isinstance(section, dict):
        raise ConnectionConfigError("connections must be a mapping")
    connections: dict[str, Connection] = {}
    for name, spec in section.items():
        if not isinstance(name, str) or not NAME_PATTERN.match(name):
            raise ConnectionConfigError(f"Invalid connection name {name!r}")
        if not isinstance(spec, dict):
            raise ConnectionConfigError(f"Connection {name} must be a mapping")
        unknown = set(spec) - {"description", "workflows", "env", "secrets"}
        if unknown:
            raise ConnectionConfigError(f"Connection {name} has unknown keys: {', '.join(sorted(unknown))}")
        env = spec.get("env") or {}
        secrets = spec.get("secrets") or {}
        if not isinstance(env, dict) or not isinstance(secrets, dict):
            raise ConnectionConfigError(f"Connection {name}: env and secrets must be mappings")
        for variable in (*env, *secrets):
            if not isinstance(variable, str) or not ENV_NAME_PATTERN.match(variable):
                raise ConnectionConfigError(f"Connection {name}: invalid variable name {variable!r}")
        overlap = set(env) & set(secrets)
        if overlap:
            raise ConnectionConfigError(f"Connection {name}: {', '.join(sorted(overlap))} is both env and secret")
        for variable, value in env.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ConnectionConfigError(f"Connection {name}: env {variable} must be a scalar")
        normalized_secrets: dict[str, Any] = {}
        for variable, secret in secrets.items():
            if secret is not None and not (isinstance(secret, dict) and set(secret) <= {"encrypted", "description"}):
                raise ConnectionConfigError(f"Connection {name}: secret {variable} must be {{encrypted: ...}} or null")
            normalized_secrets[variable] = secret
        workflows = spec.get("workflows")
        valid_workflows = isinstance(workflows, list) and all(isinstance(item, str) for item in workflows)
        if workflows is not None and not valid_workflows:
            raise ConnectionConfigError(f"Connection {name}: workflows must be a list of names")
        connections[name] = Connection(
            name=name,
            env={key: "" if value is None else str(value) for key, value in env.items()},
            secrets=normalized_secrets,
            workflows=tuple(workflows) if workflows is not None else None,
        )
    return connections


def workflow_connection_names(agent_config: dict[str, Any]) -> list[str]:
    names = agent_config.get("connections") or []
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ConnectionConfigError("agent.yaml connections must be a list of connection names")
    return names


def resolve_workflow_connections(
    platform_config: dict[str, Any], workflow: str, agent_config: dict[str, Any]
) -> list[Connection]:
    """Return the workflow's connections, rejecting unknown, disallowed or conflicting ones."""
    available = parse_connections(platform_config)
    resolved: list[Connection] = []
    owners: dict[str, str] = {}
    for variable in (*(agent_config.get("env") or {}), *(agent_config.get("secrets") or {})):
        owners[str(variable)] = "agent.yaml"
    for name in workflow_connection_names(agent_config):
        connection = available.get(name)
        if connection is None:
            raise ConnectionConfigError(f"Workflow {workflow} uses unknown connection {name!r}")
        if not connection.allows(workflow):
            raise ConnectionConfigError(f"Connection {name} is not allowed for workflow {workflow}")
        for variable in (*connection.env, *connection.secrets):
            if variable in owners:
                raise ConnectionConfigError(
                    f"Workflow {workflow}: {variable} is provided by both {owners[variable]} and connection {name}"
                )
            owners[variable] = f"connection {name}"
        resolved.append(connection)
    return resolved


def connection_environment(connections: list[Connection], *, identity: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return (plain env, decrypted secrets) for a task; unset secrets are omitted."""
    env: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for connection in connections:
        env.update(connection.env)
        populated = {name: spec for name, spec in connection.secrets.items() if (spec or {}).get("encrypted")}
        secrets.update(decrypt_named_secrets(populated, identity=identity))
    return env, secrets


def connection_secret_names(connections: list[Connection]) -> set[str]:
    return {name for connection in connections for name in connection.secrets}
