"""Release publication contracts without uploading any artifacts."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def release_workflow():
    return yaml.safe_load((REPO_ROOT / ".github/workflows/release.yml").read_text())


def test_release_event_and_publication_permissions(release_workflow):
    assert release_workflow["on"] == {"release": {"types": ["published"]}}
    assert release_workflow["permissions"] == {"contents": "read"}
    jobs = release_workflow["jobs"]
    assert jobs["verify"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["images"]["needs"] == ["verify", "package"]
    assert jobs["images"]["permissions"] == {"contents": "read", "packages": "write"}
    assert jobs["pypi"]["needs"] == ["package", "images"]
    assert jobs["pypi"]["environment"]["name"] == "pypi"
    assert jobs["pypi"]["permissions"] == {"id-token": "write"}
    publisher = jobs["pypi"]["steps"][-1]
    assert publisher["uses"] == "pypa/gh-action-pypi-publish@release/v1"
    assert "with" not in publisher


def test_release_images_cover_compose_and_runtime(release_workflow):
    compose = yaml.safe_load((REPO_ROOT / "deploy/docker-compose.yml").read_text())
    expected = {
        (REPO_ROOT / "deploy" / service["build"]["context"] / service["build"]["dockerfile"]).resolve()
        for service in compose["services"].values()
        if "build" in service
    }
    expected.add(REPO_ROOT / "runtime/Dockerfile")
    images = release_workflow["jobs"]["images"]
    targets = images["strategy"]["matrix"]["include"]
    assert {REPO_ROOT / target["dockerfile"] for target in targets} == expected
    assert len({target["component"] for target in targets}) == len(targets)
    for target in targets:
        assert (REPO_ROOT / target.get("context", ".")).is_dir()
        if target["component"] == "control-plane-ui":
            assert target["context"] == "control-plane-ui"
    build = images["steps"][-1]["with"]
    assert build["platforms"] == "linux/amd64,linux/arm64"
    assert build["push"] is True
    assert build["tags"] == (
        "ghcr.io/${{ github.repository }}-${{ matrix.component }}:${{ needs.package.outputs.version }}"
    )


@pytest.mark.parametrize(
    ("version", "tag", "valid"),
    [
        ("0.7.0", "v0.7.0", True),
        ("0.7.0rc1", "v0.7.0rc1", False),
        ("1.12.3", "v1.12.3", True),
        ("0.7.0", "v0.6.0", False),
        ("0.7.0", "0.7.0", False),
        ("0.7.0", "v0.7.0; touch injected", False),
        ("0.7.0.dev1", "v0.7.0.dev1", False),
        ("0.7.0+local", "v0.7.0+local", False),
    ],
)
def test_release_version_guard(release_workflow, tmp_path, version, tag, valid):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "sage-run"\nversion = "{version}"\n')
    output = tmp_path / "output"
    step = next(step for step in release_workflow["jobs"]["package"]["steps"] if step.get("id") == "version")
    result = subprocess.run(  # noqa: S603 - executes the checked-in workflow step, not event data
        ["/bin/bash", "-eu", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "RELEASE_TAG": tag, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == valid, result.stderr
    if valid:
        assert output.read_text() == f"version={version}\n"
    else:
        assert not output.exists()
    assert not (tmp_path / "injected").exists()
