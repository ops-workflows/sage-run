from __future__ import annotations

import logging

import pytest

from shared.lib.platform_secrets import map_external_identity_groups

pytestmark = pytest.mark.unit


def test_maps_external_memberships_to_canonical_application_groups(tmp_path):
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        """
identity:
  group_mapping:
    platform-admin:
      - entra-platform-admins
    workflow-operator:
      - entra-workflow-operators
    task-viewer:
      - entra-task-readers
    unknown-group:
      - entra-unknown
""".lstrip(),
        encoding="utf-8",
    )

    groups = map_external_identity_groups(
        str(config),
        ["entra-task-readers", "unrelated", "entra-platform-admins", "entra-task-readers"],
    )

    assert groups == ["platform-admin", "task-viewer"]


@pytest.mark.parametrize(
    "config_text",
    [
        "config: {}\n",
        "identity: []\n",
        "identity:\n  group_mapping: invalid\n",
        "identity:\n  group_mapping:\n    task-viewer: entra-task-readers\n",
    ],
)
def test_missing_or_invalid_mapping_returns_no_application_groups(tmp_path, config_text, caplog):
    config = tmp_path / "platform-config.yaml"
    config.write_text(config_text, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        groups = map_external_identity_groups(str(config), ["entra-task-readers"])

    assert groups == []


def test_missing_platform_config_returns_no_application_groups(tmp_path):
    groups = map_external_identity_groups(str(tmp_path / "missing.yaml"), ["entra-platform-admins"])

    assert groups == []
