"""Platform config overlays, named connections, validation rules and key tooling."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import pytest
import yaml

from sage_run.keys import generate_key, set_secret
from sage_run.validation import validate_workflow_repo_report
from shared.lib.connections import (
    ConnectionConfigError,
    connection_environment,
    connection_secret_names,
    parse_connections,
    resolve_workflow_connections,
)
from shared.lib.crypto import decrypt_secret, derive_age_public_key, encrypt_secret
from shared.lib.platform_config import deep_merge, load_platform_config, secrets_not_overridden

pytestmark = pytest.mark.unit

CONNECTIONS = {
    "connections": {
        "splunk": {
            "workflows": ["alerts"],
            "env": {"SPLUNK_BASE_URL": "https://splunk.invalid"},
            "secrets": {"SPLUNK_PASSWORD": {"encrypted": "ENC[plain,pw]"}, "SPLUNK_TOKEN": None},
        },
        "jira": {"env": {"JIRA_BASE_URL": "https://jira.invalid"}, "secrets": {"JIRA_TOKEN": {"description": "x"}}},
    }
}


def test_overlay_merges_mappings_and_replaces_lists(tmp_path, monkeypatch):
    (tmp_path / "platform-config.yaml").write_text(
        yaml.safe_dump({"config": {"A": "1", "B": "2"}, "mcps": {"enabled": ["a", "b"]}}), encoding="utf-8"
    )
    (tmp_path / "platform-config-prod.yaml").write_text(
        yaml.safe_dump({"config": {"B": "prod"}, "mcps": {"enabled": ["c"]}}), encoding="utf-8"
    )
    base = tmp_path / "platform-config.yaml"
    assert load_platform_config(base, environment="")["config"] == {"A": "1", "B": "2"}
    merged = load_platform_config(base, environment="prod")
    assert merged["config"] == {"A": "1", "B": "prod"}
    assert merged["mcps"]["enabled"] == ["c"]
    monkeypatch.setenv("SAGE_RUN_ENV", "prod")
    assert load_platform_config(base)["config"]["B"] == "prod"
    assert load_platform_config(base, environment="staging")["config"]["B"] == "2"


def test_secrets_not_overridden_lists_base_ciphertexts_left_in_place():
    base = {"secrets": {"A": {"encrypted": "ENC[age,a]"}, "B": {"encrypted": "ENC[age,b]"}, "P": "ENC[plain,x]"}}
    overlay = {"secrets": {"A": {"encrypted": "ENC[age,prod]"}}}
    assert secrets_not_overridden(base, overlay) == ["secrets.B.encrypted"]
    assert deep_merge(base, overlay)["secrets"]["A"]["encrypted"] == "ENC[age,prod]"


def test_connections_resolve_env_and_decrypted_secrets_for_allowed_workflow():
    resolved = resolve_workflow_connections(CONNECTIONS, "alerts", {"connections": ["splunk", "jira"]})
    env, secrets = connection_environment(resolved, identity="")
    assert env == {"SPLUNK_BASE_URL": "https://splunk.invalid", "JIRA_BASE_URL": "https://jira.invalid"}
    assert secrets == {"SPLUNK_PASSWORD": "pw"}
    assert connection_secret_names(resolved) == {"SPLUNK_PASSWORD", "SPLUNK_TOKEN", "JIRA_TOKEN"}
    assert sorted(parse_connections(CONNECTIONS)["splunk"].unset_secrets) == ["SPLUNK_TOKEN"]


@pytest.mark.parametrize(
    ("agent", "message"),
    [
        ({"connections": ["missing"]}, "unknown connection"),
        ({"connections": ["splunk"]}, "not allowed"),
        ({"connections": ["jira"], "env": {"JIRA_BASE_URL": "x"}}, "provided by both"),
        ({"connections": "jira"}, "must be a list"),
    ],
)
def test_connection_references_fail_closed(agent, message):
    with pytest.raises(ConnectionConfigError, match=message):
        resolve_workflow_connections(CONNECTIONS, "other", agent)


@pytest.mark.parametrize(
    "spec",
    [
        {"Bad_Name": {}},
        {"x": {"unknown": 1}},
        {"x": {"env": {"A": "1"}, "secrets": {"A": None}}},
        {"x": {"secrets": {"A": "ENC[plain,raw]"}}},
        {"x": {"env": {"lower": "1"}}},
    ],
)
def test_invalid_connection_definitions_are_rejected(spec):
    with pytest.raises(ConnectionConfigError):
        parse_connections({"connections": spec})


def _repo(tmp_path: Path, test_plugin_dir: Path, base: dict, overlay: dict | None = None) -> Path:
    workflow = tmp_path / "workflows" / "platform-test"
    workflow.parent.mkdir(parents=True)
    shutil.copytree(test_plugin_dir, workflow)
    (tmp_path / "platform-config.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    if overlay is not None:
        (tmp_path / "platform-config-prod.yaml").write_text(yaml.safe_dump(overlay), encoding="utf-8")
    return tmp_path


def _base(dev_key: str) -> dict:
    return {
        "config": {"AGE_PUBLIC_KEY": dev_key},
        "connections": {
            "test-connection": {
                "env": {"TEST_CONNECTION_URL": "https://x.invalid"},
                "secrets": {"TEST_CONNECTION_SECRET": {"encrypted": "ENC[age,dev]"}},
            }
        },
        "secrets": {"bot": {"encrypted": "ENC[age,dev-bot]"}},
    }


def test_validation_requires_prod_overlay_to_replace_every_secret(tmp_path, test_plugin_dir):
    overlay = {"config": {"AGE_PUBLIC_KEY": "age1prod"}, "secrets": {"bot": {"encrypted": "ENC[age,prod-bot]"}}}
    report = validate_workflow_repo_report(_repo(tmp_path, test_plugin_dir, _base("age1dev"), overlay))
    assert report.errors == [
        "platform-config-prod.yaml: encrypted value "
        "connections.test-connection.secrets.TEST_CONNECTION_SECRET.encrypted is not overridden, "
        "so it needs the development key"
    ]


def test_validation_rejects_missing_or_reused_overlay_key(tmp_path, test_plugin_dir):
    report = validate_workflow_repo_report(_repo(tmp_path, test_plugin_dir, _base("age1dev"), {"config": {}}))
    assert any("AGE_PUBLIC_KEY must name" in error for error in report.errors)
    shutil.rmtree(tmp_path / "workflows")
    (tmp_path / "platform-config-prod.yaml").unlink()
    report = validate_workflow_repo_report(
        _repo(tmp_path, test_plugin_dir, _base("age1dev"), {"config": {"AGE_PUBLIC_KEY": "age1dev"}})
    )
    assert any("must differ" in error for error in report.errors)


def test_validation_warns_about_unprovided_mcp_header_variables(tmp_path, test_plugin_dir):
    base = _base("age1dev")
    del base["connections"]["test-connection"]["env"]
    report = validate_workflow_repo_report(_repo(tmp_path, test_plugin_dir, base))
    assert not report.errors
    assert any("${TEST_CONNECTION_URL}" in warning for warning in report.warnings)
    assert any("${FAKE_MCP_HOST}" in warning for warning in report.warnings)


def test_generate_key_is_private_and_never_overwritten(tmp_path):
    key_file = tmp_path / "keys" / "prod.agekey"
    public_key = generate_key(key_file)
    assert public_key.startswith("age1")
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert derive_age_public_key(identity=key_file.read_text()) == public_key
    with pytest.raises(FileExistsError):
        generate_key(key_file)


def test_set_secret_encrypts_to_the_environment_key_and_keeps_comments(tmp_path):
    dev_key, prod_key = tmp_path / "dev.agekey", tmp_path / "prod.agekey"
    dev_public, prod_public = generate_key(dev_key), generate_key(prod_key)
    (tmp_path / "platform-config.yaml").write_text(
        f"# base comment\nconfig:\n  AGE_PUBLIC_KEY: {dev_public}\nsecrets: {{}}\n", encoding="utf-8"
    )
    (tmp_path / "platform-config-prod.yaml").write_text(
        f"# prod comment\nconfig:\n  AGE_PUBLIC_KEY: {prod_public}\n", encoding="utf-8"
    )

    set_secret(tmp_path, environment="prod", name="SPLUNK_PASSWORD", value="s3cret", connection="splunk")
    set_secret(tmp_path, environment="dev", name="bot", value="dev-bot")

    prod_text = (tmp_path / "platform-config-prod.yaml").read_text(encoding="utf-8")
    assert prod_text.startswith("# prod comment")
    ciphertext = yaml.safe_load(prod_text)["connections"]["splunk"]["secrets"]["SPLUNK_PASSWORD"]["encrypted"]
    assert decrypt_secret(ciphertext, identity=prod_key.read_text()) == "s3cret"
    base = yaml.safe_load((tmp_path / "platform-config.yaml").read_text(encoding="utf-8"))
    assert decrypt_secret(base["secrets"]["bot"]["encrypted"], identity=dev_key.read_text()) == "dev-bot"
    assert json.dumps(base).count("s3cret") == 0
    assert encrypt_secret("x", public_key=prod_public).startswith("ENC[age,")
