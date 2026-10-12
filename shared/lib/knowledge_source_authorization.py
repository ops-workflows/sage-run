"""Workflow-scoped source grants shared by graph and hybrid serving."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.lib.config import settings
from shared.lib.workflow_paths import WorkflowPackage, discover_workflow_packages

logger = logging.getLogger(__name__)
MAX_SOURCE_GRANTS = 100
SOURCE_ALIAS_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$"


class KnowledgeSourceAccessError(PermissionError):
    """A workflow lacks permission to use the requested source."""


@dataclass(frozen=True)
class KnowledgeSourceGrants:
    aliases: tuple[str, ...] = ()
    compatibility_all: bool = False

    def allows(self, alias: str) -> bool:
        return (
            isinstance(alias, str)
            and re.fullmatch(SOURCE_ALIAS_PATTERN, alias) is not None
            and (self.compatibility_all or alias in self.aliases)
        )


def source_grants(config: Any, *, require_explicit: bool = False) -> KnowledgeSourceGrants:
    if not isinstance(config, dict):
        return KnowledgeSourceGrants()
    if "knowledge" not in config:
        return KnowledgeSourceGrants(compatibility_all=not require_explicit)
    knowledge = config["knowledge"]
    if not isinstance(knowledge, dict) or set(knowledge) - {"sources"}:
        return KnowledgeSourceGrants()
    if "sources" not in knowledge:
        return KnowledgeSourceGrants(compatibility_all=not require_explicit)
    aliases = knowledge["sources"]
    if not isinstance(aliases, list) or len(aliases) > MAX_SOURCE_GRANTS:
        return KnowledgeSourceGrants()
    if any(not isinstance(alias, str) or re.fullmatch(SOURCE_ALIAS_PATTERN, alias) is None for alias in aliases):
        return KnowledgeSourceGrants()
    if len(set(aliases)) != len(aliases):
        return KnowledgeSourceGrants()
    return KnowledgeSourceGrants(aliases=tuple(aliases))


def workflow_source_grants(
    workflow: str,
    *,
    package_loader: Callable[[], list[WorkflowPackage]] | None = None,
    require_explicit: bool | None = None,
) -> KnowledgeSourceGrants:
    strict = (
        getattr(settings, "knowledge_require_explicit_source_grants", False)
        if require_explicit is None
        else require_explicit
    )
    try:
        packages = (package_loader or discover_workflow_packages)()
        package = next((item for item in packages if item.name == workflow), None)
        if package is None:
            return KnowledgeSourceGrants()
        mcp_config = json.loads((package.path / ".mcp.json").read_text(encoding="utf-8"))
        if not isinstance(mcp_config, dict) or not isinstance(mcp_config.get("mcpServers"), dict):
            return KnowledgeSourceGrants()
        if "knowledge" not in mcp_config["mcpServers"]:
            return KnowledgeSourceGrants()
        grants = source_grants(package.config, require_explicit=strict)
    except (OSError, ValueError, TypeError, AttributeError):
        logger.warning("Unable to validate Knowledge Source grants for workflow %s; denying access", workflow)
        return KnowledgeSourceGrants()
    if grants.compatibility_all:
        logger.warning("Workflow %s has no knowledge.sources; compatibility all-source access is deprecated", workflow)
    return grants
