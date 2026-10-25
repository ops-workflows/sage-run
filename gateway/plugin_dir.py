"""Plugin directory helpers for SAGE Run.

Plugins use a flat layout convention:

    agents/           — agent definitions (*.md with YAML frontmatter)
    skills/           — plugin-specific domain skills (*/SKILL.md)
    hooks/hooks.json  — hook event → command registrations
    settings.json     — Claude project settings (permissions, sandbox, agent)
    .mcp.json         — MCP server definitions
    agent.yaml        — platform config (secrets, schedules, messaging)

The runtime's _prepare_workspace() assembles the .claude/ project structure
expected by Claude Code from this flat layout at session start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from shared.lib.plugin_validation import validate_plugin_dir as validate_plugin_dir
from shared.lib.workflow_paths import discover_workflow_packages


@dataclass(frozen=True)
class DedupePolicy:
    """Treat a routed alert as a duplicate of a recent task sharing the same key values."""

    key: tuple[str, ...]
    window_sec: int
    statuses: str = "active"
    action: str = "merge"


DEDUPE_KEY_PARTS = frozenset({"sender", "alert.source", "alert.identity", "alert.account"})
_DEDUPE_LABEL_PART = re.compile(r"^label:[A-Za-z][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class MessageRoute:
    """A workflow-owned rule for turning a human message into a task."""

    workflow: str
    channel: str
    trigger_words: tuple[str, ...] = ()
    rule_id: str = ""
    provider: str = ""
    priority: int = 0
    match_type: str = "prefix"
    pattern: str = ""
    trusted_user_ids: tuple[str, ...] = ()
    trusted_webhook_ids: tuple[str, ...] = ()
    trusted_webhook_names: tuple[str, ...] = ()
    allow_bot: bool = False
    root_posts_only: bool = False
    preserve_full_body: bool = False
    allowed_accounts: tuple[str, ...] = ()
    allowed_environments: tuple[str, ...] = ()
    required_labels: tuple[tuple[str, tuple[str, ...]], ...] = ()
    dedupe: tuple[DedupePolicy, ...] = ()
    allowed_usernames: tuple[str, ...] | None = None


def read_platform_config(plugin_dir: Path) -> dict:
    """Read agent.yaml for platform-level config (secrets, schedules, runtime).

    Returns the parsed YAML config, or empty dict if not found.
    """
    agent_yaml_path = plugin_dir / "agent.yaml"
    if not agent_yaml_path.exists():
        return {}
    return yaml.safe_load(agent_yaml_path.read_text()) or {}


def discover_plugin_configs(plugins_dir: Path) -> list[tuple[str, dict]]:
    """Return discovered workflow configs from a plugins root directory."""
    return [(package.name, package.config) for package in discover_workflow_packages([plugins_dir])]


def discover_all_plugin_configs() -> list[tuple[str, dict]]:
    """Return workflow configs from all configured workflow repository roots."""
    return [(package.name, package.config) for package in discover_workflow_packages()]


def _messaging_config(config: dict) -> dict:
    messaging = config.get("messaging") or {}
    return messaging if isinstance(messaging, dict) else {}


def normalize_invocation_username(value: str) -> str:
    return value.strip().removeprefix("@").casefold()


def _channel_policies(messaging: dict) -> dict[str, tuple[str, ...]]:
    raw_policies = messaging.get("channel_policies", {})
    if not isinstance(raw_policies, dict) or len(raw_policies) > 100:
        raise ValueError("messaging.channel_policies must be a map of at most 100 channels")
    policies: dict[str, tuple[str, ...]] = {}
    for raw_channel, policy in raw_policies.items():
        if not isinstance(raw_channel, str) or not raw_channel.strip() or not isinstance(policy, dict):
            raise ValueError("Invalid messaging channel policy")
        channel = raw_channel.strip().lower()
        values = policy.get("allowed_usernames")
        if set(policy) != {"allowed_usernames"} or not isinstance(values, list) or len(values) > 500:
            raise ValueError("Channel policy must contain allowed_usernames (at most 500 names)")
        names: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("Allowed usernames must be strings")
            name = normalize_invocation_username(value)
            if not re.fullmatch(r"[a-z0-9._-]{1,64}", name) or name in names:
                raise ValueError("Allowed usernames must be valid, unique normalized Mattermost usernames")
            names.append(name)
        if channel in policies:
            raise ValueError("Channel policies must have unique normalized channel names")
        policies[channel] = tuple(names)
    return policies


def _message_routes(workflows: list[tuple[str, dict]]) -> list[MessageRoute]:
    routes: list[MessageRoute] = []
    for workflow, config in workflows:
        messaging = _messaging_config(config)
        policies = _channel_policies(messaging)
        triggers = tuple(
            trigger
            for raw_trigger in messaging.get("trigger_words", ["@agent"])
            if (trigger := str(raw_trigger).strip().lower())
        )
        for raw_channel in messaging.get("channels") or []:
            channel = str(raw_channel).strip().lower()
            if channel and triggers:
                routes.append(
                    MessageRoute(
                        workflow=workflow,
                        channel=channel,
                        trigger_words=triggers,
                        allowed_usernames=policies.get(channel),
                    )
                )
        for raw_rule in messaging.get("rules") or []:
            if not isinstance(raw_rule, dict) or raw_rule.get("enabled", True) is False:
                continue
            rule_id = str(raw_rule.get("id") or "").strip()
            match = raw_rule.get("match") if isinstance(raw_rule.get("match"), dict) else {}
            match_type = str(match.get("type") or "").strip().lower()
            pattern = str(match.get("pattern") or "").strip()
            if not rule_id or match_type not in {"prefix", "regex"} or not pattern:
                raise ValueError(f"Workflow {workflow!r} has an invalid messaging rule")
            if len(pattern) > 256:
                raise ValueError(f"Workflow {workflow!r} messaging rule {rule_id!r} pattern is too long")
            if match_type == "regex":
                if any(token in pattern for token in ("(", ")", "{", "}", "|", "+")) or pattern.count("*") > 8:
                    raise ValueError(f"Workflow {workflow!r} messaging rule {rule_id!r} uses unsupported regex syntax")
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(
                        f"Workflow {workflow!r} messaging rule {rule_id!r} has invalid regex: {exc}"
                    ) from exc

            trusted = raw_rule.get("trusted_senders")
            trusted = trusted if isinstance(trusted, dict) else {}
            constraints = raw_rule.get("constraints")
            constraints = constraints if isinstance(constraints, dict) else {}
            raw_labels = constraints.get("labels")
            required_labels = tuple(
                (str(key).strip().lower(), tuple(str(value).strip().lower() for value in values if str(value).strip()))
                for key, values in (raw_labels.items() if isinstance(raw_labels, dict) else ())
                if str(key).strip() and isinstance(values, list)
            )
            dedupe = _dedupe_policies(workflow, rule_id, raw_rule.get("dedupe"))
            rule_channels = raw_rule.get("channels") or messaging.get("channels") or []
            for raw_channel in rule_channels:
                channel = str(raw_channel).strip().lower()
                if not channel:
                    continue
                routes.append(
                    MessageRoute(
                        workflow=workflow,
                        channel=channel,
                        rule_id=rule_id,
                        allowed_usernames=policies.get(channel),
                        provider=str(raw_rule.get("provider") or "").strip().lower(),
                        priority=int(raw_rule.get("priority") or 0),
                        match_type=match_type,
                        pattern=pattern,
                        trusted_user_ids=tuple(
                            str(value).strip() for value in trusted.get("user_ids") or [] if str(value).strip()
                        ),
                        trusted_webhook_ids=tuple(
                            str(value).strip() for value in trusted.get("webhook_ids") or [] if str(value).strip()
                        ),
                        trusted_webhook_names=tuple(
                            str(value).strip() for value in trusted.get("webhook_names") or [] if str(value).strip()
                        ),
                        allow_bot=bool(raw_rule.get("allow_bot", False)),
                        root_posts_only=bool(raw_rule.get("root_posts_only", False)),
                        preserve_full_body=bool(raw_rule.get("preserve_full_body", False)),
                        allowed_accounts=tuple(
                            str(value).strip() for value in constraints.get("accounts") or [] if str(value).strip()
                        ),
                        allowed_environments=tuple(
                            str(value).strip().lower()
                            for value in constraints.get("environments") or []
                            if str(value).strip()
                        ),
                        required_labels=required_labels,
                        dedupe=dedupe,
                    )
                )
    return routes


def _dedupe_policies(workflow: str, rule_id: str, raw: object) -> tuple[DedupePolicy, ...]:
    if raw is None:
        return ()
    error = f"Workflow {workflow!r} messaging rule {rule_id!r} has an invalid dedupe policy"
    if not isinstance(raw, list) or len(raw) > 3:
        raise ValueError(error)
    policies = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(error)
        key = tuple(str(part).strip() for part in item.get("key") or [])
        window_sec = item.get("window_sec")
        statuses = str(item.get("statuses") or "active")
        action = str(item.get("action") or "merge")
        if (
            not key
            or any(part not in DEDUPE_KEY_PARTS and not _DEDUPE_LABEL_PART.fullmatch(part) for part in key)
            or not isinstance(window_sec, int)
            or not 1 <= window_sec <= 86_400
            or statuses not in {"active", "any"}
            or action not in {"merge", "reply"}
        ):
            raise ValueError(error)
        policies.append(DedupePolicy(key=key, window_sec=window_sec, statuses=statuses, action=action))
    return tuple(policies)


def discover_message_routes(plugins_dir: Path) -> list[MessageRoute]:
    """Return workflow-owned channel and trigger rules from agent.yaml files."""
    return _message_routes(discover_plugin_configs(plugins_dir))


def discover_all_message_routes() -> list[MessageRoute]:
    return _message_routes([(package.name, package.config) for package in discover_workflow_packages()])


def read_plugin_files(plugin_dir: Path) -> dict[str, str]:
    """Read all text plugin files into a relative_path → content mapping."""
    files: dict[str, str] = {}

    for path in sorted(plugin_dir.rglob("*")):
        if path.is_file() and not path.name.startswith(".git"):
            rel_path = str(path.relative_to(plugin_dir))
            if path.suffix in (".py", ".md", ".json", ".yaml", ".yml", ".txt"):
                files[rel_path] = path.read_text()

    return files
