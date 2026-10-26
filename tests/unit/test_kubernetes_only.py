"""Serving is Kubernetes-only; Docker is confined to the test harness."""

import ast
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("command", ["bootstrap", "profiles"])
def test_retired_operator_commands_are_not_available(command):
    from sage_run.cli import main

    with pytest.raises(SystemExit) as error:
        main([command])
    assert error.value.code == 2


@pytest.mark.parametrize("provider", ["docker", "", "unknown"])
def test_runtime_launcher_rejects_retired_or_unknown_backends(monkeypatch, provider):
    from session_manager.runtime_launchers import get_runtime_launcher, reset_runtime_launcher_for_tests

    from shared.lib.config import settings

    reset_runtime_launcher_for_tests()
    monkeypatch.setattr(settings, "runtime_launcher", provider)
    with pytest.raises(RuntimeError, match="Unsupported runtime launcher"):
        get_runtime_launcher()
    reset_runtime_launcher_for_tests()


def test_test_database_fixture_is_not_a_serving_stack():
    config = yaml.safe_load((ROOT / "tests/compose.yaml").read_text())
    assert set(config["services"]) == {"postgres"}
    postgres = config["services"]["postgres"]
    assert all(port.startswith("127.0.0.1:") for port in postgres["ports"])
    assert "@sha256:" in postgres["image"]
    assert not (ROOT / "deploy/docker-compose.yml").exists()


def test_docker_sdk_is_a_test_dependency_only():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "docker>=7.1.0" in project["optional-dependencies"]["dev"]
    assert not any(dependency.startswith("docker") for dependency in project["optional-dependencies"]["server"])
    for path in (ROOT / "session-manager").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "docker" for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "docker", path
