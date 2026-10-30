"""Remote deploy planning: values, secrets handed to the host, checkout sync script."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest

from sage_run import remote
from sage_run.deployment import checkout_lock
from sage_run.local import Instance

pytestmark = pytest.mark.unit
GIT = shutil.which("git") or "git"


def test_remote_values_use_host_checkout_release_images_and_ui_host_port(tmp_path):
    config = {
        "mcps": {"enabled": ["message"]},
        "deployment": {
            "public_url": "https://sage.example",
            "sandbox_profile": "gvisor",
            "ui": {"host_ip": "10.0.0.2", "host_port": 80},
        },
    }
    instance = Instance(tmp_path, "corp", sandbox_profile="", local=False)

    values = remote.remote_values(
        instance,
        config,
        checkout="/var/lib/sage-run/corp/workflow-repo",
        repo_url="git@x:o/r.git",
        ref="main",
        version="1.0.0",
    )

    assert values["workflowRepo"] == {
        "hostPath": "/var/lib/sage-run/corp/workflow-repo",
        "source": "remote",
        "url": "git@x:o/r.git",
        "ref": "main",
    }
    assert values["images"] == {"tag": "1.0.0"}
    assert values["ingress"] == {"enabled": False}
    assert values["controlPlaneUi"] == {"hostIP": "10.0.0.2", "hostPort": 80}
    assert values["runtime"] == {"sandboxProfile": "gvisor"}
    assert values["env"]["GATEWAY_PUBLIC_BASE_URL"] == "https://sage.example"


def test_only_infrastructure_ciphertexts_are_sent_to_the_host():
    config = {
        "secrets": {
            "LLM_API_KEY": {"encrypted": "ENC[age,llm]"},
            "PG_PASSWORD": {"encrypted": "ENC[age,pg]"},
            "message_bus_bot_token": {"encrypted": "ENC[age,bot]"},
        }
    }
    assert remote.infrastructure_ciphertexts(config) == {"LLM_API_KEY": "ENC[age,llm]", "PG_PASSWORD": "ENC[age,pg]"}
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        remote.infrastructure_ciphertexts({"secrets": {}})


def test_host_program_compiles_and_never_prints_values():
    compile(remote._INSTANCE_KEY_PROGRAM, "<host>", "exec")
    printed = [line for line in remote._INSTANCE_KEY_PROGRAM.splitlines() if "print(" in line]
    assert printed == ['print("instance secret updated:", ", ".join(sorted(data)))']
    compile(remote._VERIFY_KEY_PROGRAM, "<verify>", "exec")
    assert [line for line in remote._VERIFY_KEY_PROGRAM.splitlines() if "print(" in line] == []


def test_materialise_extracts_the_committed_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (["init", "-q"], ["config", "user.email", "t@x"], ["config", "user.name", "t"]):
        subprocess.run([GIT, "-C", str(repo), *command], check=True)  # noqa: S603
    (repo / "platform-config.yaml").write_text("config: {}\n", encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "add", "."], check=True)  # noqa: S603
    subprocess.run([GIT, "-C", str(repo), "commit", "-qm", "c"], check=True)  # noqa: S603
    (repo / "platform-config.yaml").write_text("uncommitted\n", encoding="utf-8")

    remote.materialise(repo, "HEAD", tmp_path / "tree")

    assert (tmp_path / "tree/platform-config.yaml").read_text(encoding="utf-8") == "config: {}\n"


def test_ssh_lock_script_and_python_writer_use_the_same_atomic_guard(tmp_path, monkeypatch):
    repo = tmp_path / "workflow repo"
    (repo / ".git").mkdir(parents=True)
    process = MagicMock()
    process.stdout.readline.return_value = "locked\n"
    factory = MagicMock(return_value=process)
    with monkeypatch.context() as patch:
        patch.setattr(remote.subprocess, "Popen", factory)
        with remote.remote_deploy_lock("test-host", str(repo), plan_only=False):
            pass
    command = factory.call_args.args[0][-1]
    holder = shlex.split(command.split("sudo sh -c ", 1)[1])[0]
    shell = shutil.which("sh") or "sh"
    result = subprocess.run([shell, "-c", holder], input="", capture_output=True, text=True, check=True)  # noqa: S603
    assert result.stdout.strip() == "locked"
    assert not (repo / ".git/sage-run-deploy.lock.d").exists()
    with checkout_lock(repo):
        result = subprocess.run([shell, "-c", holder], input="", capture_output=True, text=True)  # noqa: S603
        assert result.returncode != 0
        assert "lock exists" in result.stderr
        assert (repo / ".git/sage-run-deploy.lock.d").is_dir()


def _create_remote_test_repo(tmp_path, *, version="0.1.3"):
    repo = tmp_path / "corp-sage-workflows"
    repo.mkdir()
    for command in (["init", "-q", "-b", "main"], ["config", "user.email", "t@x"], ["config", "user.name", "t"]):
        subprocess.run([GIT, "-C", str(repo), *command], check=True)  # noqa: S603
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "corp-sage-workflows"\nversion = "0.1.0"\n'
        f'requires-python = ">=3.12"\ndependencies = ["sage-run=={version}"]\n',
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "sage-run"\nversion = "{version}"\n'
        'source = { registry = "https://pypi.org/simple" }\n',
        encoding="utf-8",
    )
    fake_cipher = "ENC[age,-----BEGIN AGE ENCRYPTED FILE-----\\ncmVjaXBpZW50\\n-----END AGE ENCRYPTED FILE-----]"
    (repo / "platform-config.yaml").write_text(
        f"secrets:\n  LLM_API_KEY:\n    encrypted: {fake_cipher}\n  PG_PASSWORD:\n    encrypted: {fake_cipher}\n",
        encoding="utf-8",
    )
    (repo / "workflows").mkdir(parents=True)
    (repo / "workflows" / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "add", "."], check=True)  # noqa: S603
    subprocess.run([GIT, "-C", str(repo), "commit", "-qm", "init"], check=True)  # noqa: S603
    return repo


def test_remote_deploy_plan_only_and_drift_preflight(tmp_path, monkeypatch, capsys):
    from contextlib import nullcontext

    repo = _create_remote_test_repo(tmp_path, version="1.0.2")
    ssh_commands = []
    drift_output = [""]

    def fake_ssh(host, script, *, stdin=None, capture=False):
        ssh_commands.append(script)
        if "status --porcelain" in script:
            return drift_output[0]
        if "rev-parse HEAD" in script:
            return "1111111111111111111111111111111111111111\n"
        if script == "mktemp -d":
            return "/tmp/sage-plan-tmp\n"
        if "kubectl -n corp-sage-workflows get " in script:
            return '{"items":[]}'
        if "helm --kubeconfig /etc/rancher/k3s/k3s.yaml --namespace corp-sage-workflows list" in script:
            return "sage-run\n"
        if "get manifest sage-run" in script:
            return "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: gateway\nspec:\n  replicas: 1\n"
        if "get values sage-run -o json" in script:
            return '{"images":{"tag":"1.0.1"}}'
        if "template sage-run" in script:
            return "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: gateway\nspec:\n  replicas: 2\n"
        return ""

    monkeypatch.setattr(remote, "_ssh", fake_ssh)
    monkeypatch.setattr(remote, "remote_deploy_lock", lambda *args, **kwargs: nullcontext())
    rc = remote.deploy(
        repo,
        host="10.0.0.10",
        environment="prod",
        ref="main",
        name=None,
        image_tag=None,
        version="1.0.2",
        plan_only=True,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Platform version: 1.0.1 -> 1.0.2" in out
    assert "roll: Deployment/gateway" in out
    assert not any("upgrade --install" in cmd for cmd in ssh_commands)
    assert not any("create namespace" in cmd for cmd in ssh_commands)

    # Dirty remote checkout must fail before chart upload or mutation
    ssh_commands.clear()
    drift_output[0] = " M platform-config.yaml\n"
    with pytest.raises(ValueError, match=r"\[drift\]"):
        remote.deploy(
            repo,
            host="10.0.0.10",
            environment="prod",
            ref="main",
            name=None,
            image_tag=None,
            version="1.0.2",
            plan_only=False,
        )
    assert not any("upgrade --install" in cmd for cmd in ssh_commands)
