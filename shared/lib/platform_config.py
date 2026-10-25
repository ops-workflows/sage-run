"""Platform configuration: a base file plus an optional per-environment overlay.

``platform-config.yaml`` holds the base (development/test) configuration with
secrets encrypted to the development key. ``platform-config-<env>.yaml`` (for
example ``platform-config-prod.yaml``) overrides values for an environment and
must override every encrypted value, so a host holds only that environment's
key. ``SAGE_RUN_ENV`` selects the overlay; workflow sync snapshots the merged
result for tasks.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

ENVIRONMENT_VAR = "SAGE_RUN_ENV"
ENCRYPTED_PREFIX = "ENC["


def selected_environment(environment: str | None = None) -> str:
    value = environment if environment is not None else os.environ.get(ENVIRONMENT_VAR, "")
    return value.strip().lower()


def overlay_path(base_path: Path | str, environment: str) -> Path:
    base_path = Path(base_path)
    return base_path.with_name(f"{base_path.stem}-{environment}{base_path.suffix}")


def read_yaml_mapping(path: Path | str) -> dict[str, Any]:
    """Return the YAML mapping in ``path``; raise ``ValueError`` for invalid content."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge mappings recursively; overlay lists and scalars replace base values."""
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_platform_config(path: Path | str, *, environment: str | None = None) -> dict[str, Any]:
    """Load the base config merged with the selected environment overlay, when present.

    A missing overlay is not an error: release snapshots are already merged.
    """
    path = Path(path)
    if not path.exists():
        return {}
    config = read_yaml_mapping(path)
    env = selected_environment(environment)
    overlay = overlay_path(path, env) if env else None
    if overlay is not None and overlay.exists():
        config = deep_merge(config, read_yaml_mapping(overlay))
    return config


def encrypted_value_paths(data: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Return the key paths of every ``ENC[...]`` string in ``data``."""
    if isinstance(data, dict):
        return [path for key, value in data.items() for path in encrypted_value_paths(value, (*prefix, str(key)))]
    if isinstance(data, list):
        return [
            path for index, value in enumerate(data) for path in encrypted_value_paths(value, (*prefix, str(index)))
        ]
    if isinstance(data, str) and data.startswith(ENCRYPTED_PREFIX) and not data.startswith("ENC[plain,"):
        return [prefix]
    return []


def secrets_not_overridden(base: dict[str, Any], overlay: dict[str, Any]) -> list[str]:
    """Encrypted base values that the overlay leaves in place (they need the base key)."""
    overlay_secret_paths = set(encrypted_value_paths(overlay))
    merged = deep_merge(base, overlay)
    return [".".join(path) for path in encrypted_value_paths(merged) if path not in overlay_secret_paths]
