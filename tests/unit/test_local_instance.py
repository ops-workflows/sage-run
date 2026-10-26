"""Local Kubernetes instance: naming, values and secrets (no cluster required)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from sage_run.local import (
    Instance,
    bootstrap_secret_data,
    enabled_components,
    instance_name,
    read_identity,
    render_values,
    workflow_mcps,
)

pytestmark = pytest.mark.unit
CHART = Path(__file__).resolve().parents[2] / "sage_run/chart"
CONFIG = {
    "mcps": {"enabled": ["message", "memory", "splunk", "github"]},
    "connectors": {
        "enabled": ["snow"],
        "instances": {"snow": {"type": "servicenow"}, "unused": {"type": "gcp-pubsub"}},
    },
}


def test_instance_name_defaults_to_repo_folder_with_dev_suffix(tmp_path):
    assert instance_name(tmp_path / "Corp_Sage-Workflows") == "corp-sage-workflows-dev"
    assert instance_name(tmp_path / "x", "ps-dev") == "ps-dev"
    with pytest.raises(ValueError):
        instance_name(tmp_path / "x", "-" * 70)


def test_enabled_components_always_include_core_mcps():
    mcps, connectors = enabled_components(CONFIG)
    assert mcps == {"message", "memory", "knowledge", "platform", "splunk", "github"}
    assert connectors == {"servicenow"}


def test_render_values_mounts_working_tree_and_reads_deployment_settings(tmp_path):
    instance = Instance(tmp_path, "corp-dev", images={"registry": "", "tag": "dev-abc", "pullPolicy": "Never"})
    config = {
        **CONFIG,
        "deployment": {
            "public_url": "https://corp.example",
            "sandbox_profile": "gvisor",
            "env": {"KNOWLEDGE_EMBEDDINGS_DIMENSIONS": 768},
            "hindsight": {"env": {"HINDSIGHT_API_LLM_MODEL": "model"}},
            "extra_hosts": {"logs.example": "10.0.0.5"},
            "service_env": {"mcp-splunk": {"SSL_CERT_FILE": "/app/workflows/certs/ca.pem"}},
        },
    }

    values = render_values(instance, config)

    assert values["workflowRepo"] == {"hostPath": str(tmp_path), "source": "local"}
    assert values["runtime"] == {"sandboxProfile": "local"}
    assert values["ingress"] == {"enabled": True, "host": "corp-dev.localhost"}
    assert values["env"] == {
        "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "768",
        "CONTROL_PLANE_UI_URL": "http://corp-dev.localhost",
        "GATEWAY_PUBLIC_BASE_URL": "http://corp-dev.localhost",
    }
    assert values["infrastructure"]["hindsight"]["env"] == {"HINDSIGHT_API_LLM_MODEL": "model"}
    assert values["hostAliases"] == [{"ip": "10.0.0.5", "hostnames": ["logs.example"]}]
    assert values["serviceEnv"] == {"mcp-splunk": {"SSL_CERT_FILE": "/app/workflows/certs/ca.pem"}}
    assert values["mcps"]["splunk"] == {"enabled": True}
    assert values["mcps"]["jira"] == {"enabled": False}
    assert values["connectors"] == {"servicenow": {"enabled": True}, "gcp-pubsub": {"enabled": False}}
    assert "secret" not in json.dumps(values).lower()

    remote = render_values(Instance(tmp_path, "corp", sandbox_profile="", local=False), config)
    assert remote["runtime"] == {"sandboxProfile": "gvisor"}
    assert remote["env"]["CONTROL_PLANE_UI_URL"] == "https://corp.example"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_source_and_config_checksums_change_pod_templates_not_deployment_metadata(tmp_path):
    (tmp_path / "mcps/smoke").mkdir(parents=True)
    source = tmp_path / "mcps/smoke/mcp_smoke.py"
    source.write_text("app = first\n")
    (tmp_path / "workflows/test").mkdir(parents=True)
    (tmp_path / "workflows/test/.mcp.json").write_text('{"url": "http://mcp-smoke:8112/mcp"}')
    config = {"mcps": {"enabled": ["smoke"]}}

    def templates(config):
        values = render_values(Instance(tmp_path, "checksum-test"), config)
        path = tmp_path / "values.json"
        path.write_text(json.dumps(values))
        output = subprocess.run(  # noqa: S603 - fixed Helm template command
            [shutil.which("helm") or "helm", "template", "sage-run", str(CHART), "-f", str(path)],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        return {
            doc["metadata"]["name"]: doc["spec"]["template"]
            for doc in yaml.safe_load_all(output)
            if doc and doc["kind"] == "Deployment"
        }

    before = templates(config)
    source.write_text("app = second\n")
    after = templates(config)
    assert {name for name in before if before[name] != after[name]} == {"mcp-smoke"}
    changed = templates({**config, "runtime_env": {"TEST": "changed"}})
    assert {"gateway", "session-manager", "knowledge-indexer", "mcp-message", "mcp-smoke"} <= {
        name for name in after if after[name] != changed[name]
    }


@pytest.mark.parametrize(
    "deployment",
    [{"unknown": 1}, {"env": []}, {"sandbox_profile": "none"}, {"hindsight": {"env": "x"}}],
)
def test_invalid_deployment_settings_are_rejected(tmp_path, deployment):
    with pytest.raises(ValueError):
        render_values(Instance(tmp_path, "x"), {"deployment": deployment})


def test_bootstrap_secret_decrypts_infrastructure_secrets_and_keeps_existing_passwords():
    config = {
        "secrets": {
            "LLM_API_KEY": {"encrypted": "ENC[plain,llm]"},
            "PG_PASSWORD": {"encrypted": "ENC[plain,pg]"},
            "message_bus_bot_token": {"encrypted": "ENC[plain,not-infrastructure]"},
        }
    }
    data = bootstrap_secret_data({"OBJECT_STORE_SECRET_KEY": "kept", "PG_PASSWORD": "old"}, "AGE-SECRET-KEY-1X", config)
    assert data == {
        "AGE_IDENTITY": "AGE-SECRET-KEY-1X",
        "LLM_API_KEY": "llm",
        "PG_PASSWORD": "pg",
        "OBJECT_STORE_SECRET_KEY": "kept",
    }
    generated = bootstrap_secret_data({}, "AGE-SECRET-KEY-1X", config)
    assert len(generated["OBJECT_STORE_SECRET_KEY"]) >= 24
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        bootstrap_secret_data({}, "AGE-SECRET-KEY-1X", {"secrets": {}})


def test_read_identity_extracts_key_lines(tmp_path):
    key_file = tmp_path / "dev.agekey"
    key_file.write_text("# public key: age1abc\nAGE-SECRET-KEY-1XYZ\n", encoding="utf-8")
    assert read_identity(key_file) == "AGE-SECRET-KEY-1XYZ"
    with pytest.raises(ValueError, match="not found"):
        read_identity(tmp_path / "missing")


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
@pytest.mark.parametrize("host_port", [0, 80])
def test_host_bound_ui_releases_port_before_replacement(host_port):
    rendered = subprocess.run(  # noqa: S603 - fixed Helm invocation
        [
            shutil.which("helm") or "helm",
            "template",
            "sage-run",
            str(CHART),
            "--set",
            "workflowRepo.hostPath=/workflows",
            "--set",
            f"controlPlaneUi.hostPort={host_port}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    ui = next(
        doc
        for doc in yaml.safe_load_all(rendered)
        if doc and doc["kind"] == "Deployment" and doc["metadata"]["name"] == "control-plane-ui"
    )
    strategy = ui["spec"].get("strategy", {}).get("type", "RollingUpdate")
    assert strategy == ("Recreate" if host_port else "RollingUpdate")


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_chart_renders_local_instance_with_compose_service_names(tmp_path):
    values = render_values(Instance(tmp_path, "corp-dev", images={"registry": "", "tag": "dev-abc"}), CONFIG)
    values_file = tmp_path / "values.json"
    values_file.write_text(json.dumps(values), encoding="utf-8")

    helm = shutil.which("helm") or "helm"
    rendered = subprocess.run(  # noqa: S603 - fixed helm invocation
        [helm, "template", "sage-run", str(CHART), "--namespace", "corp-dev", "-f", str(values_file)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    documents = [doc for doc in yaml.safe_load_all(rendered) if doc]
    services = {doc["metadata"]["name"] for doc in documents if doc["kind"] == "Service"}
    assert {"gateway", "postgres", "minio", "hindsight", "control-plane-ui", "mcp-splunk", "mcp-github"} <= services
    assert "mcp-jira" not in services

    for doc in documents:
        pod = (doc.get("spec") or {}).get("template", {}).get("spec") or {}
        for container in [*pod.get("containers", []), *pod.get("initContainers", [])]:
            names = [item["name"] for item in container.get("env", [])]
            assert len(names) == len(set(names)), (doc["metadata"]["name"], names)

    deployments = {doc["metadata"]["name"]: doc for doc in documents if doc["kind"] == "Deployment"}
    assert "servicenow-connector" in deployments
    session_manager = deployments["session-manager"]["spec"]["template"]["spec"]
    env = {item["name"]: item.get("value") for item in session_manager["containers"][0]["env"]}
    assert env["SANDBOX_MODE"] == "local"
    assert env["RUNTIME_IMAGE"] == "sage-run-agent-runtime:dev-abc"
    assert env["PLATFORM_CONFIG_FILE"] == "/app/workflows/platform-config.yaml"
    assert session_manager["volumes"][0]["hostPath"]["path"] == str(tmp_path)
    assert deployments["gateway"]["spec"]["strategy"]["type"] == "Recreate"
    assert all(doc["spec"]["template"]["spec"]["enableServiceLinks"] is False for doc in deployments.values())
    role = next(doc for doc in documents if doc["kind"] == "Role" and doc["metadata"]["name"] == "sage-run-sessions")
    assert {
        "apiGroups": ["batch"],
        "resources": ["jobs"],
        "verbs": ["create", "get", "list", "watch", "delete"],
    } in role["rules"]


def test_workflow_mcps_come_from_repo_sources_and_mcp_json_ports(tmp_path):
    (tmp_path / "mcps/ticket-triage").mkdir(parents=True)
    (tmp_path / "mcps/ticket-triage/mcp_ticket_triage.py").write_text("app = None\n", encoding="utf-8")
    (tmp_path / "mcps/unused").mkdir(parents=True)
    (tmp_path / "mcps/unused/mcp_unused.py").write_text("app = None\n", encoding="utf-8")
    (tmp_path / "workflows/triage").mkdir(parents=True)
    mcp_json = {"mcpServers": {"triage": {"type": "http", "url": "http://mcp-ticket-triage:8111/mcp"}}}
    (tmp_path / "workflows/triage/.mcp.json").write_text(json.dumps(mcp_json), encoding="utf-8")
    config = {"mcps": {"enabled": ["message", "ticket-triage"]}}

    server = workflow_mcps(tmp_path, config)["ticket-triage"]
    checksum = server.pop("checksum")
    assert len(checksum) == 64
    assert server == {"dir": "mcps/ticket-triage", "module": "mcp_ticket_triage", "port": 8111}
    source = tmp_path / "mcps/ticket-triage/mcp_ticket_triage.py"
    source.write_text("app = changed\n", encoding="utf-8")
    assert workflow_mcps(tmp_path, config)["ticket-triage"]["checksum"] != checksum
    (tmp_path / "workflows/triage/.mcp.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="must reference"):
        workflow_mcps(tmp_path, config)
