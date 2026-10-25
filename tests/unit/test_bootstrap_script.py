"""Unit tests for the packaged operator bootstrap."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

from sage_run.bootstrap import (
    BootstrapConfig,
    build_bootstrap_env,
    main,
    normalize_age_identity,
    prepare_workflow_repo,
    render_compose_env,
    render_k8s_secret_script,
    write_artifact,
)

pytestmark = pytest.mark.unit
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_session_manager_receives_knowledge_source_bucket_in_compose_and_helm():
    compose = yaml.safe_load((REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))
    session_manager_env = compose["services"]["session-manager"]["environment"]
    assert session_manager_env["OBJECT_STORE_ENDPOINT"] == "minio:9000"
    assert "OBJECT_STORE_ACCESS_KEY" in session_manager_env
    assert "KNOWLEDGE_SOURCE_OBJECT_STORE_BUCKET" in session_manager_env

    helm_helpers = (REPO_ROOT / "deploy/k8s/sage-run/templates/_helpers.tpl").read_text(encoding="utf-8")
    expected = (
        "- name: KNOWLEDGE_SOURCE_OBJECT_STORE_BUCKET\n"
        "  value: {{ .Values.knowledgeSources.objectStoreBucket | quote }}"
    )
    assert expected in helm_helpers
    session_manager = (REPO_ROOT / "deploy/k8s/sage-run/templates/session-manager.yaml").read_text(encoding="utf-8")
    assert 'include "sage-run.commonEnv"' in session_manager


def test_compose_services_receive_workflow_repository_metadata():
    compose = yaml.safe_load((REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))

    gateway_environment = compose["services"]["gateway"]["environment"]
    assert gateway_environment["WORKFLOW_REPO_SOURCE"] == "${WORKFLOW_REPO_SOURCE:-local}"
    assert gateway_environment["WORKFLOW_REPO_DISPLAY_PATH"] == "${HOST_WORKFLOW_REPO_PATH:-}"
    assert (
        "${HOST_WORKFLOW_REPO_PATH:-../examples/workflow-repo}:/app/workflows"
        in compose["services"]["gateway"]["volumes"]
    )

    for service_name in ("gateway", "session-manager"):
        environment = compose["services"][service_name]["environment"]
        assert environment["WORKFLOW_REPO_URL"] == "${WORKFLOW_REPO_URL:-}"
        assert environment["WORKFLOW_REPO_REF"] == "${WORKFLOW_REPO_REF:-}"
        assert "WORKFLOW_ROOT" not in environment
        assert "WORKFLOW_REPO_PATHS" not in environment
        assert "WORKFLOW_REPO_LOCAL_PATH" not in environment

    assert compose["services"]["session-manager"]["environment"]["WORKFLOW_REPO_SOURCE"] == "local"


def _remote_config(**overrides) -> BootstrapConfig:
    base = {
        "target": "kubernetes",
        "source": "remote",
        "repo_url": "https://github.com/acme/workflows.git",
        "repo_ref": "v1.2.3",
        "repo_pat": "ghp_token",
        "local_path": "/home/op/corp-workflows",
        "age_identity": "AGE-SECRET-KEY-1EXAMPLE",
        "llm_api_key": "sk-model-key",
        "pg_password": "postgres-secret",
        "object_store_secret_key": "object-store-secret",
    }
    base.update(overrides)
    return BootstrapConfig(**base)


def _local_config(**overrides) -> BootstrapConfig:
    base = {
        "target": "compose",
        "source": "local",
        "gateway_public_base_url": "https://gateway.example.test",
        "control_plane_ui_url": "http://localhost:3000",
        "sandbox_mode": "macos",
        "local_path": "/home/op/corp-workflows",
        "age_identity": "AGE-SECRET-KEY-1EXAMPLE",
        "llm_api_key": "sk-model-key",
        "pg_password": "postgres-secret",
        "object_store_secret_key": "object-store-secret",
    }
    base.update(overrides)
    return BootstrapConfig(**base)


# ── Validation ──────────────────────────────────────────────────────


def test_validate_accepts_remote_source_for_compose_target():
    _remote_config(target="compose").validate()


def test_validate_requires_repo_url_for_remote_source():
    config = _remote_config(repo_url="")
    with pytest.raises(ValueError, match="Workflow repo URL is required"):
        config.validate()


def test_validate_requires_local_path_for_local_source():
    config = _local_config(local_path="")
    with pytest.raises(ValueError, match="Local workflow-repo checkout path is required"):
        config.validate()


def test_validate_requires_bootstrap_secrets():
    with pytest.raises(ValueError, match="AGE identity is required"):
        _remote_config(age_identity="").validate()
    with pytest.raises(ValueError, match="LLM API key is required"):
        _remote_config(llm_api_key="").validate()
    with pytest.raises(ValueError, match="Postgres password is required"):
        _remote_config(pg_password="").validate()
    with pytest.raises(ValueError, match="Object-store secret key is required"):
        _remote_config(object_store_secret_key="").validate()


def test_validate_accepts_valid_remote_kubernetes_config():
    _remote_config().validate()  # does not raise


def test_validate_accepts_valid_local_compose_config():
    _local_config().validate()  # does not raise


def test_validate_accepts_compose_using_workflow_deployment_settings():
    _local_config(gateway_public_base_url="", control_plane_ui_url="", sandbox_mode="").validate()


@pytest.mark.parametrize("field", ["gateway_public_base_url", "control_plane_ui_url"])
@pytest.mark.parametrize("value", ["https://", "file:///tmp/config", "localhost:3000"])
def test_validate_rejects_invalid_url_override(field: str, value: str):
    with pytest.raises(ValueError, match=r"must be an HTTP\(S\) URL"):
        _local_config(**{field: value}).validate()


def test_validate_rejects_unknown_sandbox_override():
    with pytest.raises(ValueError, match="Sandbox mode"):
        _local_config(sandbox_mode="unknown").validate()


# ── normalize_age_identity ──────────────────────────────────────────


def test_normalize_age_identity_passes_through_raw_key():
    assert normalize_age_identity("AGE-SECRET-KEY-1EXAMPLE") == "AGE-SECRET-KEY-1EXAMPLE"


def test_normalize_age_identity_passes_through_existing_file_prefix():
    assert normalize_age_identity("file:/etc/sage-run/key.txt") == "file:/etc/sage-run/key.txt"


def test_normalize_age_identity_reads_existing_path(tmp_path: Path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("AGE-SECRET-KEY-1EXAMPLE\n", encoding="utf-8")
    assert normalize_age_identity(str(key_file)) == "AGE-SECRET-KEY-1EXAMPLE"


def test_normalize_age_identity_leaves_nonexistent_path_as_raw_value():
    assert normalize_age_identity("not-a-real-path-or-key") == "not-a-real-path-or-key"


# ── build_bootstrap_env ──────────────────────────────────────────────


def test_build_bootstrap_env_remote_source_includes_repo_pointer():
    env = build_bootstrap_env(_remote_config())
    assert env["WORKFLOW_REPO_URL"] == "https://github.com/acme/workflows.git"
    assert env["WORKFLOW_REPO_REF"] == "v1.2.3"
    assert "WORKFLOW_REPO_PAT" not in env
    assert env["AGE_IDENTITY"] == "AGE-SECRET-KEY-1EXAMPLE"
    assert env["LLM_API_KEY"] == "sk-model-key"
    assert env["PG_PASSWORD"] == "postgres-secret"
    assert env["OBJECT_STORE_SECRET_KEY"] == "object-store-secret"


def test_build_bootstrap_env_remote_compose_retains_repository_metadata():
    env = build_bootstrap_env(_remote_config(target="compose"))

    assert env["WORKFLOW_REPO_SOURCE"] == "remote"
    assert env["WORKFLOW_REPO_URL"] == "https://github.com/acme/workflows.git"
    assert env["WORKFLOW_REPO_REF"] == "v1.2.3"
    assert env["HOST_WORKFLOW_REPO_PATH"] == "/home/op/corp-workflows"
    assert "HOST_PLATFORM_CONFIG_FILE" not in env
    assert "WORKFLOW_COMPOSE_ENV_FILE" not in env
    assert "WORKFLOW_COMPOSE_OVERRIDE_FILE" not in env


def test_build_bootstrap_env_remote_source_omits_pat_when_blank():
    env = build_bootstrap_env(_remote_config(repo_pat=""))
    assert "WORKFLOW_REPO_PAT" not in env


def test_build_bootstrap_env_local_compose_sets_host_bind_mount_vars():
    env = build_bootstrap_env(
        _local_config(repo_url="https://github.com/acme/corp-workflows.git", repo_pat="github-pr-token")
    )
    assert env["WORKFLOW_REPO_SOURCE"] == "local"
    assert env["WORKFLOW_REPO_URL"] == "https://github.com/acme/corp-workflows.git"
    assert "WORKFLOW_REPO_PAT" not in env
    assert env["HOST_WORKFLOW_REPO_PATH"] == "/home/op/corp-workflows"
    assert "HOST_PLATFORM_CONFIG_FILE" not in env
    assert "WORKFLOW_COMPOSE_ENV_FILE" not in env
    assert "WORKFLOW_COMPOSE_OVERRIDE_FILE" not in env
    assert env["CONTROL_PLANE_UI_URL"] == "http://localhost:3000"
    assert env["GATEWAY_PUBLIC_BASE_URL"] == "https://gateway.example.test"
    assert env["SANDBOX_MODE"] == "macos"
    assert "WORKFLOW_REPO_PATHS" not in env


@pytest.mark.parametrize("source", ["local", "remote"])
def test_build_bootstrap_env_compose_uses_committed_defaults(source: str):
    env = build_bootstrap_env(
        _local_config(
            source=source,
            repo_url="https://github.com/acme/workflows.git",
            gateway_public_base_url="",
            control_plane_ui_url="",
            sandbox_mode="",
        )
    )
    assert "CONTROL_PLANE_UI_URL" not in env
    assert "GATEWAY_PUBLIC_BASE_URL" not in env
    assert "SANDBOX_MODE" not in env
    assert "OIDC_CLIENT_SECRET" not in env
    assert "OAUTH2_PROXY_COOKIE_SECRET" not in env


def test_build_bootstrap_env_remote_compose_accepts_explicit_host_overrides():
    env = build_bootstrap_env(
        _remote_config(
            target="compose",
            gateway_public_base_url="https://gateway.example.com/",
            control_plane_ui_url="https://console.example.com/",
            sandbox_mode="gvisor",
        )
    )
    assert env["GATEWAY_PUBLIC_BASE_URL"] == "https://gateway.example.com"
    assert env["CONTROL_PLANE_UI_URL"] == "https://console.example.com"
    assert env["SANDBOX_MODE"] == "gvisor"


def test_build_bootstrap_env_local_kubernetes_sets_workflow_repo_paths():
    env = build_bootstrap_env(_local_config(target="kubernetes"))
    assert env["WORKFLOW_REPO_PATHS"] == "/home/op/corp-workflows"
    assert "HOST_WORKFLOW_REPO_PATH" not in env


def test_deployments_do_not_expose_bootstrap_pat_to_runtime():
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "WORKFLOW_REPO_PAT:" not in compose
    assert "WORKFLOW_REPO_PAT" not in render_k8s_secret_script(build_bootstrap_env(_remote_config()))


def test_prepare_remote_repo_uses_pat_only_in_clone_environment(monkeypatch, tmp_path: Path):
    checkout = tmp_path / "workflows"
    config = _remote_config(local_path=str(checkout))
    calls = []

    monkeypatch.setattr("sage_run.bootstrap.shutil.which", lambda name: "/usr/bin/git")

    def run(command, *, check, env):
        calls.append((command, env))
        if command[1] == "clone":
            (checkout / ".git").mkdir(parents=True)

    monkeypatch.setattr("sage_run.bootstrap.subprocess.run", run)

    assert prepare_workflow_repo(config) == checkout
    clone_command, clone_environment = calls[0]
    assert clone_command == [
        "/usr/bin/git",
        "clone",
        "https://github.com/acme/workflows.git",
        str(checkout),
    ]
    assert clone_environment["GITHUB_APP_INSTALLATION_TOKEN"] == "ghp_token"
    assert config.repo_pat not in " ".join(clone_command)


# ── Render functions ──────────────────────────────────────────────────


def test_render_compose_env_shape():
    content = render_compose_env({"AGE_IDENTITY": "abc", "LLM_API_KEY": "xyz"})
    assert "AGE_IDENTITY=abc" in content
    assert "LLM_API_KEY=xyz" in content
    assert content.startswith("# Generated by sage-run bootstrap")


def test_render_k8s_secret_script_contains_kubectl_apply():
    content = render_k8s_secret_script({"AGE_IDENTITY": "abc"}, secret_name="my-secret", namespace="ops")
    assert "kubectl create secret generic my-secret" in content
    assert "--namespace ops" in content
    assert "--from-literal=AGE_IDENTITY='abc'" in content
    assert "kubectl apply -f -" in content


def test_render_scripts_quote_values_with_special_characters():
    content = render_k8s_secret_script({"LLM_API_KEY": "it's a 'secret'"})
    assert "it'\\''s a '\\''secret'\\''" in content


# ── write_artifact ──────────────────────────────────────────────────


def test_write_artifact_compose_target_writes_compose_env(tmp_path: Path):
    path = write_artifact(_local_config(), output_dir=tmp_path)
    assert path == tmp_path / "compose.env"
    assert path.exists()
    assert "HOST_WORKFLOW_REPO_PATH=" in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o600


def test_write_artifact_kubernetes_target_writes_executable_script(tmp_path: Path):
    path = write_artifact(_remote_config(), output_dir=tmp_path)
    assert path == tmp_path / "dist" / "bootstrap" / "k8s-secret.sh"
    assert path.exists()
    assert path.stat().st_mode & 0o111  # executable bit set
    assert path.stat().st_mode & 0o777 == 0o700
    assert "sage-run-config" in path.read_text(encoding="utf-8")


def test_write_artifact_kubernetes_target_uses_configured_namespace(tmp_path: Path):
    path = write_artifact(_remote_config(namespace="test-namespace"), output_dir=tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "--namespace test-namespace" in content
    assert "--from-literal=KUBERNETES_NAMESPACE='test-namespace'" in content


# ── main() (prompt-only) ─────────────────────────────────────────────


def test_main_writes_compose_artifact(monkeypatch, tmp_path: Path, capsys):
    artifact = tmp_path / "compose.env"
    monkeypatch.setattr("sage_run.bootstrap.gather_config_interactively", _local_config)
    monkeypatch.setattr("sage_run.bootstrap.write_artifact", lambda config, *, output_dir: artifact)

    exit_code = main(output_dir=tmp_path)
    assert exit_code == 0
    output = capsys.readouterr().out
    assert str(artifact) in output
    assert "make up BOOTSTRAP_OUTPUT_DIR=" in output


def test_main_reports_invalid_prompted_configuration(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr("sage_run.bootstrap.gather_config_interactively", lambda: _remote_config(local_path=""))

    exit_code = main(output_dir=tmp_path)
    assert exit_code == 1
    assert "Local workflow-repo checkout path is required" in capsys.readouterr().err


def test_write_artifact_creates_private_external_directory(tmp_path: Path):
    output_dir = tmp_path / "private-instance"
    artifact = write_artifact(_local_config(), output_dir=output_dir)
    assert artifact.parent == output_dir
    assert output_dir.stat().st_mode & 0o777 == 0o700
    assert artifact.stat().st_mode & 0o777 == 0o600


def test_write_artifact_preserves_existing_configuration(tmp_path: Path):
    artifact = write_artifact(_local_config(), output_dir=tmp_path)
    original = artifact.read_bytes()
    with pytest.raises(FileExistsError):
        write_artifact(_local_config(llm_api_key="different-value"), output_dir=tmp_path)
    assert artifact.read_bytes() == original


def test_write_artifact_does_not_follow_existing_symlink(tmp_path: Path):
    original = tmp_path / "original.env"
    original.write_text("keep-original\n", encoding="utf-8")
    (tmp_path / "compose.env").symlink_to(original)
    with pytest.raises(FileExistsError):
        write_artifact(_local_config(), output_dir=tmp_path)
    assert original.read_text(encoding="utf-8") == "keep-original\n"


def test_main_refuses_existing_artifact_before_prompting(monkeypatch, tmp_path: Path, capsys):
    (tmp_path / "compose.env").write_text("keep-original\n", encoding="utf-8")
    monkeypatch.setattr("sage_run.bootstrap.gather_config_interactively", lambda: pytest.fail("Unexpected prompt"))
    assert main(output_dir=tmp_path) == 1
    assert "already exists" in capsys.readouterr().err


@pytest.mark.parametrize("artifact_name", ["compose.env", "dist/bootstrap/k8s-secret.sh"])
def test_main_refuses_dangling_symlink_before_prompting(monkeypatch, tmp_path: Path, capsys, artifact_name: str):
    artifact = tmp_path / artifact_name
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.symlink_to(tmp_path / "missing-target")
    monkeypatch.setattr("sage_run.bootstrap.gather_config_interactively", lambda: pytest.fail("Unexpected prompt"))
    assert main(output_dir=tmp_path) == 1
    assert artifact.is_symlink()
    assert "already exists" in capsys.readouterr().err


def test_bootstrap_cli_uses_explicit_output_directory(monkeypatch, tmp_path: Path):
    from sage_run.cli import main as cli_main

    calls = []
    monkeypatch.setattr("sage_run.bootstrap.main", lambda *, output_dir: calls.append(output_dir) or 0)
    assert cli_main(["bootstrap", "--output-dir", str(tmp_path)]) == 0
    assert calls == [tmp_path.resolve()]


def test_bootstrap_cli_requires_output_directory():
    from sage_run.cli import main as cli_main

    with pytest.raises(SystemExit) as error:
        cli_main(["bootstrap"])
    assert error.value.code == 2


def test_make_bootstrap_uses_private_state_directory():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "BOOTSTRAP_OUTPUT_DIR ?= $(HOME)/.local/state/sage-run/local" in makefile
    assert "COMPOSE_BOOTSTRAP_ENV_FILE ?= $(BOOTSTRAP_OUTPUT_DIR)/compose.env" in makefile
    assert 'bootstrap --output-dir "$(BOOTSTRAP_OUTPUT_DIR)"' in makefile


def test_operator_dependencies_exclude_service_stack():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert set(project["dependencies"]) == {
        "httpx>=0.27.0",
        "pyyaml>=6.0.1",
        "pydantic>=2.9.0",
        "jsonschema>=4.23.0",
        "pyrage>=1.1.0",
        "PyJWT[crypto]>=2.9.0",
        "ruamel-yaml>=0.18",
    }
    assert "claude-agent-sdk==0.2.110" in project["optional-dependencies"]["server"]
    assert "graphifyy==0.9.56" in project["optional-dependencies"]["server"]


@pytest.mark.parametrize(
    "dockerfile",
    [
        "gateway/Dockerfile",
        "session-manager/Dockerfile",
        "knowledge-indexer/Dockerfile",
        "connectors/gcp-pubsub-connector/Dockerfile",
        "connectors/servicenow-connector/Dockerfile",
    ],
)
def test_service_images_install_server_dependencies(dockerfile: str):
    content = (REPO_ROOT / dockerfile).read_text(encoding="utf-8")
    assert 'pip install --no-cache-dir ".[server,' in content
    for resource in ("COPY sage_run/", "COPY shared/", "COPY schemas/", "COPY README.md LICENSE"):
        assert content.index(resource) < content.index("RUN pip install")


def test_source_development_and_ci_install_server_dependencies():
    for file_path in (REPO_ROOT / "Makefile", REPO_ROOT / ".github/workflows/ci.yml"):
        content = file_path.read_text(encoding="utf-8")
        assert "--extra dev --extra server" in content


def test_operator_wheel_includes_schemas_without_service_modules():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(config["tool"]["hatch"]["build"]["targets"]["wheel"]["only-include"]) == {
        "sage_run",
        "shared",
        "schemas",
    }


def test_docker_context_excludes_local_secrets_and_caches():
    ignored = set((REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {".git", ".venv", "**/compose.env", "**/key.txt", "**/node_modules", "backups"} <= ignored
