"""Remote deploy planning: values, secrets handed to the host, checkout sync script."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from sage_run import remote
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
