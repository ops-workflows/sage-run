from __future__ import annotations

from unittest.mock import MagicMock

import docker.errors
import pytest
from session_manager.runtime_launchers import (
    DockerRuntimeLauncher,
    RuntimeLaunchSpec,
    get_runtime_launcher,
    reset_runtime_launcher_for_tests,
)

pytestmark = pytest.mark.unit


def test_docker_launcher_translates_spec_to_container_run(monkeypatch):
    monkeypatch.setattr("session_manager.runtime_launchers.sys.platform", "linux")
    monkeypatch.delenv("SANDBOX_MODE", raising=False)
    monkeypatch.setenv("DOCKER_NETWORK", "test-network")
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    container = MagicMock()
    container.id = "container-id"
    container.short_id = "abc123"
    client.containers.run.return_value = container

    launcher = DockerRuntimeLauncher(client)
    handle = launcher.launch(
        RuntimeLaunchSpec(
            task_id="task-12345678",
            workflow="platform-test",
            image="runtime:latest",
            environment={"A": "1"},
            plugin_dir="/workflows/platform-test",
            shared_dir="/shared",
            memory_volume_name="agent-memory-platform-test",
            container_name="session-test",
        )
    )

    assert handle.id == "container-id"
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "runtime:latest"
    assert kwargs["environment"] == {"A": "1"}
    assert kwargs["volumes"]["/workflows/platform-test"] == {"bind": "/plugin-src", "mode": "ro"}
    assert kwargs["volumes"]["agent-memory-platform-test"] == {"bind": "/memory", "mode": "rw"}
    assert kwargs["network"] == "test-network"
    assert kwargs["extra_hosts"] == {"host.docker.internal": "host-gateway"}
    assert kwargs["labels"]["sage_run.runtime_provider"] == "docker"
    assert "security_opt" not in kwargs
    assert "cap_add" not in kwargs


def test_docker_launcher_uses_macos_sandbox_mode(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "macos")
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    container = MagicMock()
    container.id = "container-id"
    container.short_id = "abc123"
    client.containers.run.return_value = container

    DockerRuntimeLauncher(client).launch(
        RuntimeLaunchSpec(
            task_id="task-12345678",
            workflow="platform-test",
            image="runtime:latest",
            environment={},
        )
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["security_opt"] == ["seccomp=unconfined"]
    assert "cap_add" not in kwargs
    assert kwargs["environment"]["CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED"] == "1"


def test_docker_launcher_uses_gha_sandbox_mode(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "gha")
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    container = MagicMock()
    container.id = "container-id"
    container.short_id = "abc123"
    client.containers.run.return_value = container

    DockerRuntimeLauncher(client).launch(
        RuntimeLaunchSpec(
            task_id="task-12345678",
            workflow="platform-test",
            image="runtime:latest",
            environment={},
        )
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["security_opt"] == ["seccomp=unconfined", "apparmor=unconfined"]
    assert kwargs["cap_add"] == ["SYS_ADMIN"]
    assert kwargs["environment"]["CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED"] == "1"


def test_docker_launcher_uses_gvisor_compatibility_runtime_without_native_relaxations(monkeypatch):
    monkeypatch.setattr("session_manager.runtime_launchers.sys.platform", "linux")
    monkeypatch.setenv("SANDBOX_MODE", "gvisor")
    monkeypatch.setenv("DOCKER_NETWORK", "sage-run-network")
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    peer = MagicMock()
    peer.name = "deploy-mcp-salesforce-1"
    peer.attrs = {
        "NetworkSettings": {
            "Networks": {
                "sage-run-network": {
                    "IPAddress": "172.19.0.7",
                    "DNSNames": ["deploy-mcp-salesforce-1", "mcp-salesforce", "peer-id"],
                }
            }
        }
    }
    client.networks.get.return_value.containers = [peer]
    container = MagicMock()
    container.id = "container-id"
    container.short_id = "abc123"
    client.containers.run.return_value = container

    DockerRuntimeLauncher(client).launch(
        RuntimeLaunchSpec(
            task_id="task-12345678",
            workflow="platform-test",
            image="runtime:latest",
            environment={},
        )
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["runtime"] == "runsc-pr13532"
    assert "security_opt" not in kwargs
    assert "cap_add" not in kwargs
    assert "CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED" not in kwargs["environment"]
    assert kwargs["extra_hosts"] == {
        "host.docker.internal": "host-gateway",
        "deploy-mcp-salesforce-1": "172.19.0.7",
        "mcp-salesforce": "172.19.0.7",
        "peer-id": "172.19.0.7",
    }


def test_docker_launcher_preserves_docker_desktop_host_routing(monkeypatch):
    monkeypatch.setattr("session_manager.runtime_launchers.sys.platform", "darwin")
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    container = MagicMock()
    container.id = "container-id"
    container.short_id = "abc123"
    client.containers.run.return_value = container

    DockerRuntimeLauncher(client).launch(
        RuntimeLaunchSpec(
            task_id="task-12345678",
            workflow="platform-test",
            image="runtime:latest",
            environment={"A": "1"},
        )
    )

    assert "extra_hosts" not in client.containers.run.call_args.kwargs


def test_docker_launcher_mounts_workflow_bundle_instead_of_source_dirs():
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    container = MagicMock()
    container.id = "container-id"
    container.short_id = "abc123"
    client.containers.run.return_value = container

    launcher = DockerRuntimeLauncher(client)
    launcher.launch(
        RuntimeLaunchSpec(
            task_id="task-12345678",
            workflow="platform-test",
            image="runtime:latest",
            environment={"A": "1"},
            plugin_dir="/workflows/platform-test",
            shared_dir="/shared",
            workflow_bundle_path="/bundles/platform-test",
            workflow_bundle_checksum="sha256:abc",
            memory_volume_name="agent-memory-platform-test",
            container_name="session-test",
        )
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["volumes"] == {
        "/bundles/platform-test": {"bind": "/workflow-bundle", "mode": "ro"},
        "agent-memory-platform-test": {"bind": "/memory", "mode": "rw"},
    }
    assert kwargs["environment"]["WORKFLOW_BUNDLE_PATH"] == "/workflow-bundle"
    assert kwargs["environment"]["WORKFLOW_BUNDLE_URI"] == "file:///workflow-bundle"
    assert kwargs["environment"]["WORKFLOW_BUNDLE_CHECKSUM"] == "sha256:abc"


def test_runtime_launcher_defaults_to_docker(monkeypatch):
    from shared.lib.config import settings

    reset_runtime_launcher_for_tests()
    monkeypatch.setattr(settings, "runtime_launcher", "docker")
    monkeypatch.setattr("session_manager.runtime_launchers._get_docker_client", lambda: MagicMock())

    assert get_runtime_launcher().provider == "docker"
    reset_runtime_launcher_for_tests()


def _kubernetes_launcher():
    kubernetes_client = pytest.importorskip("kubernetes.client")
    from session_manager.runtime_launchers import KubernetesRuntimeLauncher

    launcher = KubernetesRuntimeLauncher.__new__(KubernetesRuntimeLauncher)
    launcher.client = kubernetes_client
    launcher.batch = MagicMock()
    launcher.batch.create_namespaced_job.side_effect = lambda namespace, body: body
    launcher.core = MagicMock()
    launcher.namespace = "sage-test"
    return launcher


def _launch_kubernetes_job(memory_volume_name: str | None = None):
    launcher = _kubernetes_launcher()
    launcher.launch(
        RuntimeLaunchSpec(
            task_id="task-12345678",
            workflow="platform-test",
            image="runtime:1.0.0",
            environment={"TASK_ID": "task-12345678"},
            memory_volume_name=memory_volume_name,
        )
    )
    return launcher.batch.create_namespaced_job.call_args.kwargs["body"]


def _env(container) -> dict[str, str]:
    return {item.name: item.value for item in container.env}


def test_kubernetes_launcher_gvisor_profile_runs_non_root_in_runtime_class(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "gvisor")

    job = _launch_kubernetes_job()

    pod = job.spec.template.spec
    assert pod.runtime_class_name == "gvisor"
    assert pod.automount_service_account_token is False
    assert pod.enable_service_links is False
    assert pod.security_context.run_as_non_root is True
    assert pod.security_context.run_as_user == 1000
    assert pod.security_context.run_as_group == 0
    assert pod.security_context.seccomp_profile is None
    runtime = pod.containers[0]
    assert runtime.security_context is None
    assert _env(runtime)["HOME"] == "/home/sage"
    assert "CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED" not in _env(runtime)
    assert job.spec.ttl_seconds_after_finished == 86400
    assert job.metadata.labels["sage_run.type"] == "agent-session"


def test_kubernetes_launcher_uses_configured_runtime_class_and_user(monkeypatch):
    from shared.lib.config import settings

    monkeypatch.setenv("SANDBOX_MODE", "gvisor")
    monkeypatch.setattr(settings, "kubernetes_runtime_class", "runsc-pr15008")
    monkeypatch.setattr(settings, "kubernetes_runtime_uid", 4242)
    monkeypatch.setattr(settings, "kubernetes_runtime_ttl_sec", 0)

    job = _launch_kubernetes_job()

    assert job.spec.template.spec.runtime_class_name == "runsc-pr15008"
    assert job.spec.template.spec.security_context.run_as_user == 4242
    assert job.spec.ttl_seconds_after_finished is None


@pytest.mark.parametrize("mode", ["local", "macos"])
def test_kubernetes_launcher_local_profile_relaxes_seccomp_only(monkeypatch, mode):
    monkeypatch.setenv("SANDBOX_MODE", mode)

    job = _launch_kubernetes_job()

    pod = job.spec.template.spec
    assert pod.runtime_class_name is None
    assert pod.security_context.seccomp_profile.type == "Unconfined"
    assert pod.containers[0].security_context is None
    assert _env(pod.containers[0])["CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED"] == "1"


@pytest.mark.parametrize("mode", ["ci", "gha"])
def test_kubernetes_launcher_ci_profile_mirrors_docker_gha_mode(monkeypatch, mode):
    monkeypatch.setenv("SANDBOX_MODE", mode)

    job = _launch_kubernetes_job()

    pod = job.spec.template.spec
    context = pod.containers[0].security_context
    assert pod.security_context.seccomp_profile.type == "Unconfined"
    assert context.capabilities.add == ["SYS_ADMIN"]
    assert context.app_armor_profile.type == "Unconfined"
    assert _env(pod.containers[0])["CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED"] == "1"


def test_kubernetes_launcher_memory_helpers_share_non_root_pod_identity(monkeypatch):
    from shared.lib.config import settings

    monkeypatch.setenv("SANDBOX_MODE", "gvisor")
    monkeypatch.setattr(settings, "kubernetes_memory_helper_image", "session-manager:1.0.0")

    job = _launch_kubernetes_job(memory_volume_name="agent-memory-platform-test")

    pod = job.spec.template.spec
    assert [container.name for container in pod.init_containers] == ["memory-restore"]
    assert [container.name for container in pod.containers] == ["agent-runtime", "memory-upload"]
    assert all(container.security_context is None for container in [*pod.init_containers, *pod.containers])
    assert pod.security_context.run_as_user == 1000


def test_unknown_sandbox_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("SANDBOX_MODE", "insecure")

    with pytest.raises(RuntimeError, match="Unsupported SANDBOX_MODE"):
        _launch_kubernetes_job()


def test_docker_launcher_uses_configured_gvisor_runtime(monkeypatch):
    from shared.lib.config import settings

    monkeypatch.setattr("session_manager.runtime_launchers.sys.platform", "linux")
    monkeypatch.setenv("SANDBOX_MODE", "gvisor")
    monkeypatch.setattr(settings, "gvisor_docker_runtime", "runsc-pr15008")
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    client.networks.get.return_value.containers = []

    DockerRuntimeLauncher(client).launch(
        RuntimeLaunchSpec(task_id="task-12345678", workflow="platform-test", image="runtime:latest", environment={})
    )

    assert client.containers.run.call_args.kwargs["runtime"] == "runsc-pr15008"


@pytest.mark.parametrize(
    ("mode", "security_opt"), [("local", ["seccomp=unconfined"]), ("ci", ["seccomp=unconfined", "apparmor=unconfined"])]
)
def test_docker_launcher_accepts_profile_names(monkeypatch, mode, security_opt):
    monkeypatch.setattr("session_manager.runtime_launchers.sys.platform", "linux")
    monkeypatch.setenv("SANDBOX_MODE", mode)
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("missing")

    DockerRuntimeLauncher(client).launch(
        RuntimeLaunchSpec(task_id="task-12345678", workflow="platform-test", image="runtime:latest", environment={})
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["security_opt"] == security_opt
    assert kwargs["environment"]["CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED"] == "1"
