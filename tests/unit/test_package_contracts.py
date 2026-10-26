"""Packaged operator and service-image build contracts."""

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
REPO_ROOT = Path(__file__).resolve().parents[2]


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
    assert "COPY --from=ghcr.io/astral-sh/uv:" in content
    locked = content.index("RUN uv export --frozen --no-dev --no-emit-project --extra server")
    # Dependencies install from the lockfile before sources, so source edits reuse the layer.
    assert content.index("COPY pyproject.toml uv.lock ./") < locked
    project = content.index("RUN uv pip install --system --no-cache --no-deps .")
    for resource in ("COPY sage_run/", "COPY shared/", "COPY schemas/", "COPY README.md LICENSE"):
        assert locked < content.index(resource) < project


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
