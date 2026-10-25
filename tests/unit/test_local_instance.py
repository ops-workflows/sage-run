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
    render_values,
)

pytestmark = pytest.mark.unit
CHART = Path(__file__).resolve().parents[2] / "deploy/k8s/sage-run"
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


def test_render_values_mounts_working_tree_and_exposes_instance_host(tmp_path):
    instance = Instance(tmp_path, "corp-dev", images={"registry": "", "tag": "dev-abc", "pullPolicy": "Never"})
    deployment_env = {
        "HINDSIGHT_API_LLM_MODEL": "model",
        "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "768",
        "SANDBOX_MODE": "gvisor",
        "INGRESS_BIND_ADDRESS": "10.0.0.1",
    }

    values = render_values(instance, CONFIG, deployment_env)

    assert values["workflowRepo"] == {"hostPath": str(tmp_path), "source": "local"}
    assert values["runtime"] == {"sandboxProfile": "local"}
    assert values["ingress"] == {"enabled": True, "host": "corp-dev.localhost"}
    assert values["env"] == {
        "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "768",
        "CONTROL_PLANE_UI_URL": "http://corp-dev.localhost",
        "GATEWAY_PUBLIC_BASE_URL": "http://corp-dev.localhost",
    }
    assert values["infrastructure"]["hindsight"]["env"] == {"HINDSIGHT_API_LLM_MODEL": "model"}
    assert values["mcps"]["splunk"] == {"enabled": True}
    assert values["mcps"]["jira"] == {"enabled": False}
    assert values["connectors"] == {"servicenow": {"enabled": True}, "gcp-pubsub": {"enabled": False}}
    assert "secret" not in json.dumps(values).lower()


def test_bootstrap_secret_keeps_existing_passwords_and_requires_operator_keys():
    existing = {"PG_PASSWORD": "kept", "AGE_IDENTITY": "old"}
    data = bootstrap_secret_data(existing, {"AGE_IDENTITY": "AGE-SECRET-KEY-1", "LLM_API_KEY": "llm"})
    assert data["PG_PASSWORD"] == "kept"
    assert data["AGE_IDENTITY"] == "AGE-SECRET-KEY-1"
    assert len(data["OBJECT_STORE_SECRET_KEY"]) >= 24
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        bootstrap_secret_data({}, {"AGE_IDENTITY": "x"})


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_chart_renders_local_instance_with_compose_service_names(tmp_path):
    values = render_values(Instance(tmp_path, "corp-dev", images={"registry": "", "tag": "dev-abc"}), CONFIG, {})
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
    role = next(doc for doc in documents if doc["kind"] == "Role")
    assert {
        "apiGroups": ["batch"],
        "resources": ["jobs"],
        "verbs": ["create", "get", "list", "watch", "delete"],
    } in role["rules"]
