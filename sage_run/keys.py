"""Operator secret tooling: environment keys and encrypted config values."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from shared.lib.crypto import encrypt_secret
from shared.lib.platform_config import overlay_path


def generate_key(out: Path) -> str:
    """Write a new age identity to ``out`` (mode 0600, never overwritten); return its public key."""
    from pyrage import x25519

    identity = x25519.Identity.generate()
    out = out.expanduser()
    out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    public_key = str(identity.to_public())
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"# public key: {public_key}\n{identity}\n")
    return public_key


def config_file(workflow_repo: Path, environment: str) -> Path:
    base = workflow_repo / "platform-config.yaml"
    return base if environment in {"", "dev", "base"} else overlay_path(base, environment)


def _round_trip_yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def set_secret(
    workflow_repo: Path,
    *,
    environment: str,
    name: str,
    value: str,
    connection: str | None = None,
) -> Path:
    """Encrypt ``value`` to the environment's key and store it in its config file."""
    path = config_file(workflow_repo, environment)
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    yaml = _round_trip_yaml()
    data = yaml.load(path.read_text(encoding="utf-8")) or CommentedMap()
    public_key = str(((data.get("config") or {}).get("AGE_PUBLIC_KEY")) or "")
    if not public_key.startswith("age1"):
        raise ValueError(f"{path.name} has no config.AGE_PUBLIC_KEY recipient")
    if connection:
        connections = data.setdefault("connections", CommentedMap())
        target = connections.setdefault(connection, CommentedMap()).setdefault("secrets", CommentedMap())
    else:
        target = data.setdefault("secrets", CommentedMap())
    entry = target.get(name)
    if not isinstance(entry, dict):
        entry = CommentedMap()
        target[name] = entry
    entry["encrypted"] = encrypt_secret(value, public_key=public_key)
    with path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)
    return path


def read_value(value_file: Path | None) -> str:
    value = value_file.expanduser().read_text(encoding="utf-8") if value_file else getpass.getpass("Secret value: ")
    if not value:
        raise ValueError("Secret value cannot be empty")
    return value
