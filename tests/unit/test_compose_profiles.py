"""Unit tests for optional Docker Compose profile derivation."""

import pytest

from sage_run.cli import main
from sage_run.profiles import compute_profiles, workflow_profiles


def test_compute_profiles_includes_github_mcp() -> None:
    config = {
        "mcps": {"enabled": ["message", "github", "splunk"]},
        "connectors": {"enabled": [], "instances": {}},
    }

    assert compute_profiles(config) == ["github", "splunk"]


def test_compute_profiles_maps_connector_types_and_model_backends() -> None:
    config = {
        "connectors": {
            "enabled": ["snow-main", "alerts"],
            "instances": {"snow-main": {"type": "servicenow"}, "alerts": {"type": "gcp-pubsub"}},
        },
        "model_profiles": {"default": {"ANTHROPIC_BASE_URL": "http://model-gateway:1235"}},
    }

    assert compute_profiles(config) == ["gcp-pubsub", "model-gateway", "servicenow"]


def test_profiles_command_prints_comma_separated_profiles(tmp_path, capsys) -> None:
    (tmp_path / "platform-config.yaml").write_text("mcps:\n  enabled: [jira, github]\n", encoding="utf-8")

    assert main(["profiles", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "github,jira"


@pytest.mark.parametrize("content", ["[unclosed", "- not-a-mapping\n"])
def test_profiles_reject_invalid_configuration(tmp_path, content):
    (tmp_path / "platform-config.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        workflow_profiles(tmp_path)
