"""Deployment validation, serialized writers and API Job lifecycle."""

from __future__ import annotations

import base64
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from sage_run.deployment import checkout_lock, job_manifest, job_status, validate_ref

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("ref", ["main", "v1.2.3", "v2026-prod"])
def test_remote_refs(ref):
    assert validate_ref(ref, remote=True) == ref


@pytest.mark.parametrize("ref", ["", "--upload-pack=sh", "other-branch", "main~1", "vfoo/bar", "vfoo\nbar"])
def test_remote_refs_reject_unsafe_or_unapproved_values(ref):
    with pytest.raises(ValueError):
        validate_ref(ref, remote=True)


def test_local_uses_working_tree():
    assert validate_ref("", remote=False) == "working-tree"
    with pytest.raises(ValueError):
        validate_ref("main", remote=False)


def test_resource_plan_reports_actual_actions_without_leaking_manifest_values():
    from sage_run.deployment import deployment_plan

    before = """
kind: Deployment
metadata: {name: gateway}
spec: {template: {spec: {containers: [{image: before}]}}}
---
kind: Secret
metadata: {name: credentials}
data: {key: private-before}
---
kind: Deployment
metadata: {name: removed}
"""
    after = before.replace("image: before", "image: after").replace("private-before", "private-after")
    after = after.split("---\nkind: Deployment\nmetadata: {name: removed}")[0]
    after += "---\nkind: Deployment\nmetadata: {name: added}\n"
    plan = deployment_plan(before, after)
    assert plan == {
        "create": ["Deployment/added"],
        "roll": ["Deployment/gateway"],
        "update": ["Secret/credentials"],
        "delete": ["Deployment/removed"],
    }
    assert "private" not in json.dumps(plan)


def test_job_avoids_helm_upgrade_when_values_and_resources_are_unchanged(monkeypatch):
    from sage_run import incluster

    run = MagicMock(return_value="kind: ConfigMap\nmetadata: {name: runtime}\ndata: {image: pinned}\n")
    monkeypatch.setattr(incluster, "_run", run)
    incluster._helm_values({"images": {"tag": "pinned"}}, previous_values={"images": {"tag": "pinned"}})
    assert all("upgrade" not in call.args for call in run.call_args_list)


def test_checkout_lock_rejects_competing_writers_and_releases_on_failure(tmp_path):
    (tmp_path / ".git").mkdir()
    with checkout_lock(tmp_path), pytest.raises(ValueError, match="Another"), checkout_lock(tmp_path):
        pytest.fail("Acquired another writer's lock")
    with pytest.raises(RuntimeError), checkout_lock(tmp_path):
        raise RuntimeError("test")
    with checkout_lock(tmp_path):
        pass


@pytest.fixture
def gateway():
    return {
        "metadata": {"annotations": {"sage-run/node": "serving-node"}},
        "spec": {
            "template": {
                "metadata": {"labels": {"component": "gateway"}},
                "spec": {
                    "containers": [
                        {
                            "name": "gateway",
                            "image": "ghcr.io/ops-workflows/sage-run-gateway@sha256:pinned",
                            "ports": [{"containerPort": 8080}],
                            "readinessProbe": {"tcpSocket": {"port": 8080}},
                            "env": [
                                {"name": "SAGE_RUN_BACKUP_HOST_PATH", "value": "/var/backups/sage-run/corp/managed"},
                                {"name": "SAGE_RUN_BACKUP_HINDSIGHT", "value": "true"},
                            ],
                            "envFrom": [{"secretRef": {"name": "sage-run-bootstrap"}}],
                            "volumeMounts": [
                                {"name": "workflow-repo", "mountPath": "/app/workflows", "readOnly": True}
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "workflow-repo", "hostPath": {"path": "/var/lib/sage-run/corp/workflow-repo"}}
                    ],
                    "enableServiceLinks": False,
                },
            }
        },
    }


def test_job_uses_running_digest_and_serving_node_without_mutating_gateway(gateway):
    original = copy.deepcopy(gateway)
    job = job_manifest(gateway, namespace="corp", ref="v1.2.3")
    assert gateway == original
    spec = job["spec"]["template"]["spec"]
    container = spec["containers"][0]
    assert spec["nodeName"] == "serving-node"
    assert spec["serviceAccountName"] == "sage-run-deployer"
    assert container["image"].endswith("@sha256:pinned")
    assert "readinessProbe" not in container and "ports" not in container
    assert container["command"][-1] == "v1.2.3"
    assert container["volumeMounts"][0]["readOnly"] is False
    assert any(item["name"] == "backup-hindsight" for item in spec["volumes"])
    assert any(item.get("hostPath", {}).get("path") == "/var/backups/sage-run/corp/managed" for item in spec["volumes"])
    assert job["spec"]["backoffLimit"] == 0
    assert job["metadata"]["name"] != job_manifest(gateway, namespace="corp", ref="main")["metadata"]["name"]


def test_job_status_does_not_treat_pod_completion_or_creation_as_success():
    job = {"metadata": {"name": "deploy"}, "status": {"succeeded": 1}}
    assert job_status(job)["status"] == "pending"
    job["status"]["conditions"] = [{"type": "Complete", "status": "True"}]
    assert job_status(job)["status"] == "succeeded"
    job["status"]["conditions"] = [{"type": "Failed", "status": "True", "message": "backup failed"}]
    assert job_status(job)["status"] == "failed"
    assert job_status(job)["error"] == "backup failed"


def test_api_rejects_concurrent_deployments(monkeypatch):
    from gateway import deployments

    monkeypatch.setattr(deployments.settings, "workflow_repo_managed", True)
    monkeypatch.setattr(deployments.settings, "workflow_repo_source", "remote")
    batch, apps, core, api = (MagicMock() for _ in range(4))
    api.sanitize_for_serialization.side_effect = lambda value: value
    batch.list_namespaced_job.return_value = {"items": [{"metadata": {"name": "deploy"}, "status": {"active": 1}}]}
    monkeypatch.setattr(deployments, "_clients", lambda: (batch, apps, core, api))
    with pytest.raises(HTTPException) as error:
        deployments._operation(ref="main")
    assert error.value.status_code == 409
    batch.create_namespaced_job.assert_not_called()


def test_platform_pin_change_is_rejected_before_apply(tmp_path):
    from sage_run.incluster import validate_platform_pin

    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["sage-run==2.0.0"]\n')
    with pytest.raises(ValueError, match="CLI upgrade"):
        validate_platform_pin(tmp_path, "1.0.1")


def test_managed_discovery_never_fetches_or_moves_the_checkout(tmp_path, monkeypatch):
    from shared.lib import workflow_paths

    monkeypatch.setattr(workflow_paths.settings, "workflow_repo_managed", True)
    monkeypatch.setattr(workflow_paths.settings, "workflow_repo_source", "remote")
    monkeypatch.setattr(workflow_paths.settings, "workflow_repo_url", "https://github.com/example/repo")
    monkeypatch.setattr(workflow_paths.settings, "workflow_repo_local_path", str(tmp_path))
    assert workflow_paths._sync_configured_workflow_repo() == tmp_path
    with pytest.raises(RuntimeError, match="deployment-managed"):
        workflow_paths.sync_workflow_repo_to_ref("main")


@pytest.mark.parametrize("enabled", [False, True])
def test_ssh_backup_uses_serving_hindsight_state_and_incoming_image(gateway, enabled, monkeypatch):
    from sage_run import remote

    created = []

    def ssh(host, command, *, stdin=None, capture=False):
        if "get deployment gateway" in command:
            return json.dumps(gateway)
        if "get pods" in command:
            return json.dumps({"items": [{"metadata": {}, "spec": {"nodeName": "serving-node"}}]})
        if "helm get values" in command:
            return json.dumps({"infrastructure": {"hindsight": {"enabled": enabled}}})
        if "create -f -" in command:
            created.append(json.loads(stdin))
        if "get job" in command:
            return json.dumps({"status": {"conditions": [{"type": "Complete", "status": "True"}]}})
        return ""

    monkeypatch.setattr(remote, "_ssh", ssh)
    remote.pre_deploy_backup(
        "test-host",
        "corp",
        {
            "images": {"tag": "incoming"},
            "backups": {"hostPath": "/var/backups/sage-run/corp/managed"},
            "infrastructure": {"hindsight": {"enabled": not enabled}},
        },
        remote_tmp="/tmp/test-deploy",
    )
    spec = created[0]["spec"]["template"]["spec"]
    assert any(item["name"] == "backup-hindsight" for item in spec["volumes"]) is enabled
    assert spec["containers"][0]["image"].endswith(":incoming")
    assert spec["containers"][0]["envFrom"] == gateway["spec"]["template"]["spec"]["containers"][0]["envFrom"]


@pytest.fixture
def cluster_deploy(tmp_path, monkeypatch):
    from sage_run import incluster

    (tmp_path / ".git").mkdir()
    for key, value in {
        "workflow_repo_local_path": str(tmp_path),
        "workflow_repo_source": "remote",
        "workflow_repo_managed": True,
        "kubernetes_namespace": "corp",
    }.items():
        monkeypatch.setattr(incluster.settings, key, value)
    current = {
        "images": {"tag": "pinned"},
        "workflowRepo": {"hostPath": "/srv/workflows", "ref": "main"},
        "deployer": {"enabled": True},
        "backups": {"enabled": True},
        "infrastructure": {},
        **dict.fromkeys(
            ("mcps", "connectors", "workflowMcps", "env", "serviceEnv", "hostAliases", "configChecksums"), {}
        ),
    }
    encoded = {key: base64.b64encode(b"unchanged").decode() for key in ("PG_PASSWORD", "OBJECT_STORE_SECRET_KEY")}
    run = MagicMock(side_effect=[json.dumps(current), '{"items":[]}', json.dumps({"data": encoded}), ""])
    git = MagicMock(side_effect=lambda checkout, *args: "original" if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(incluster, "_run", run)
    monkeypatch.setattr(incluster, "_git", git)
    monkeypatch.setattr(incluster, "_fetch_commit", lambda *args: "candidate")
    monkeypatch.setattr(incluster, "materialise", lambda repo, commit, tree: tree.mkdir())
    monkeypatch.setattr(incluster, "_phase", MagicMock())
    monkeypatch.setattr(incluster, "load_platform_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(incluster, "bootstrap_secret_data", lambda old, *args: old)
    monkeypatch.setattr(incluster, "render_values", lambda *args: copy.deepcopy(current))
    from sage_run import validation

    monkeypatch.setattr(validation, "validate_workflow_repo_report", lambda tree: SimpleNamespace(errors=[]))
    backup = MagicMock()
    helm = MagicMock()
    activation = AsyncMock()
    monkeypatch.setattr(incluster, "create_backup", backup)
    monkeypatch.setattr(incluster, "_helm_values", helm)
    monkeypatch.setattr(incluster, "activate_checkout", activation)
    return SimpleNamespace(module=incluster, run=run, git=git, backup=backup, helm=helm, activation=activation)


def test_backup_failure_never_mutates_checkout_or_release(cluster_deploy):
    deployment = cluster_deploy
    deployment.backup.side_effect = OSError("backup failed")
    with pytest.raises(OSError, match="backup failed"):
        deployment.module.deploy_in_cluster("main")
    deployment.helm.assert_not_called()
    deployment.activation.assert_not_called()
    assert not any("checkout" in call.args[1:] for call in deployment.git.call_args_list)
    assert all("apply" not in call.args for call in deployment.run.call_args_list)


def test_database_activation_failure_restores_checkout_and_helm_and_reports_failure(cluster_deploy):
    from sqlalchemy.exc import SQLAlchemyError

    deployment = cluster_deploy
    deployment.activation.side_effect = [SQLAlchemyError("activation failed"), None]
    with pytest.raises(SQLAlchemyError, match="activation failed"):
        deployment.module.deploy_in_cluster("main")
    assert deployment.helm.call_count == 2
    assert deployment.helm.call_args.args[0]["workflowRepo"]["ref"] == "main"
    assert [call.args[1:] for call in deployment.git.call_args_list if "checkout" in call.args] == [
        ("checkout", "--detach", "candidate"),
        ("checkout", "--detach", "original"),
    ]
    assert deployment.activation.await_count == 2


def test_extra_manifest_subpath_change_rolls_only_its_pod_template(tmp_path):
    from sage_run.deployment import extra_manifests

    directory = tmp_path / "deploy/k8s"
    directory.mkdir(parents=True)
    (tmp_path / "Caddyfile").write_text("old")
    (directory / "ingress.yaml").write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: ingress}\n"
        "spec:\n  template:\n    spec:\n"
        "      volumes: [{name: repo, hostPath: {path: '${WORKFLOW_REPO_PATH}'}}]\n"
        "      containers:\n        - name: ingress\n"
        "          volumeMounts: [{name: repo, subPath: Caddyfile, mountPath: /etc/Caddyfile}]\n"
    )
    first = extra_manifests(tmp_path, host_checkout="/srv/workflows", namespace="corp")
    (tmp_path / "Caddyfile").write_text("new")
    second = extra_manifests(tmp_path, host_checkout="/srv/workflows", namespace="corp")
    key = ("Deployment", "ingress")
    assert first[key]["spec"]["template"] != second[key]["spec"]["template"]
    assert first[key]["metadata"]["labels"] == {"sage-run/extra": "corp"}


def test_extra_manifest_cannot_target_another_namespace(tmp_path):
    from sage_run.deployment import extra_manifests

    directory = tmp_path / "deploy/k8s"
    directory.mkdir(parents=True)
    (directory / "escape.yaml").write_text("kind: Secret\nmetadata: {name: key, namespace: other}\n")
    with pytest.raises(ValueError, match="supported resources"):
        extra_manifests(tmp_path, host_checkout="/srv/workflows", namespace="corp")


def test_extra_manifests_cannot_implicitly_adopt_unrelated_resources():
    from sage_run.deployment import owned_extras

    key = ("Deployment", "ingress")
    resource = {"kind": key[0], "metadata": {"name": key[1]}}
    with pytest.raises(ValueError, match="extra ownership"):
        owned_extras([resource], "corp", desired={key: {}})
    assert owned_extras([resource], "corp", desired={}) == {}
    resource["metadata"]["labels"] = {"sage-run/extra": "corp"}
    assert key in owned_extras([resource], "corp", desired={key: {}})


def test_logs_are_decoded_and_failed_job_is_preserved(monkeypatch):
    from gateway import deployments

    monkeypatch.setattr(deployments.settings, "workflow_repo_managed", True)
    batch, apps, core, api = (MagicMock() for _ in range(4))
    api.sanitize_for_serialization.side_effect = lambda value: value
    batch.list_namespaced_job.return_value = {
        "items": [
            {
                "metadata": {"name": "deploy"},
                "status": {"conditions": [{"type": "Failed", "status": "True", "message": "backup failed"}]},
            }
        ]
    }
    core.list_namespaced_pod.return_value = {
        "items": [{"metadata": {"name": "deploy-pod"}, "status": {"phase": "Failed"}}]
    }
    core.read_namespaced_pod_log.return_value.data = b"backup failed\n"
    monkeypatch.setattr(deployments, "_clients", lambda: (batch, apps, core, api))
    result = deployments._operation(logs=True)["deployment"]
    assert result["status"] == "failed"
    assert result["logs"] == "backup failed\n"
    core.read_namespaced_pod_log.return_value.release_conn.assert_called_once()
