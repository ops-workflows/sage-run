"""Exact independent retention counts and backup failure safety."""

from __future__ import annotations

import json
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage_run import backups

pytestmark = pytest.mark.unit


def _set(root, index, kind="deployment", namespace="corp", **extra):
    path = root / f"{kind}-{namespace}-{index:03d}"
    path.mkdir()
    manifest = {
        "format": backups.BACKUP_FORMAT,
        "namespace": namespace,
        "kind": kind,
        "complete": True,
        "completed_at": f"2020-01-01T00:00:{index:02d}+00:00",
        **extra,
    }
    (path / "manifest.json").write_text(json.dumps(manifest))
    return path


def test_counts_are_independent_and_not_based_on_age(tmp_path):
    for index in range(12):
        _set(tmp_path, index, "nightly")
        _set(tmp_path, index)
    backups.prune_backups(tmp_path, namespace="corp", kind="deployment")
    assert len(list(tmp_path.glob("deployment-*"))) == 3
    assert len(list(tmp_path.glob("nightly-*"))) == 12
    backups.prune_backups(tmp_path, namespace="corp", kind="nightly")
    assert len(list(tmp_path.glob("nightly-*"))) == 7
    assert len(list(tmp_path.glob("deployment-*"))) == 3


def test_rotation_preserves_unmanaged_foreign_protected_incomplete_and_symlink_sets(tmp_path):
    legacy = tmp_path / "20261026-pre-compose-cleanup"
    legacy.mkdir()
    incomplete = _set(tmp_path, 1, complete=False)
    protected = _set(tmp_path, 2, protected=True)
    foreign = _set(tmp_path, 3, namespace="other")
    for index in range(4, 10):
        _set(tmp_path, index)
    link = tmp_path / "link"
    link.symlink_to(foreign, target_is_directory=True)
    backups.prune_backups(tmp_path, namespace="corp", kind="deployment")
    assert all(path.exists() for path in (legacy, incomplete, protected, foreign, link))
    completed = [
        path
        for path in tmp_path.glob("deployment-corp-*")
        if json.loads((path / "manifest.json").read_text())["complete"]
        and not json.loads((path / "manifest.json").read_text()).get("protected")
    ]
    assert len(completed) == 3


def test_dump_failure_does_not_prune_previous_backups(tmp_path, monkeypatch):
    for index in range(5):
        _set(tmp_path, index)
    monkeypatch.setenv("SAGE_RUN_BACKUP_ROOT", str(tmp_path))
    monkeypatch.setattr(backups.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("dump failed")))
    with pytest.raises(OSError, match="dump failed"):
        backups.create_backup(namespace="corp", kind="deployment", checkout=tmp_path)
    assert len(list(tmp_path.glob("deployment-*"))) == 5
    assert len(list(tmp_path.glob("*/manifest.json"))) == 5


@pytest.mark.parametrize("validation_exit", [0, 23])
def test_dump_validation_drains_large_input_and_preserves_exit_status(tmp_path, monkeypatch, validation_exit):
    payload = b"archive" * 200_000
    reader = tmp_path / "pg_restore"
    reader.write_text(f"#!/bin/sh\nhead -c 1 >/dev/null\nexit {validation_exit}\n")
    reader.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("SAGE_RUN_BACKUP_ROOT", str(tmp_path / "backups"))
    real_run = subprocess.run

    def run(command, **kwargs):
        if "pg_dump" in command:
            kwargs["stdout"].write(payload)
            return SimpleNamespace(returncode=0)
        try:
            return real_run(command[command.index("--") + 1 :], **kwargs)
        finally:
            assert kwargs["stdin"].tell() == len(payload), "kubectl upload must be fully consumed"

    def stop_after_validation(_):
        raise RuntimeError("validation completed")

    monkeypatch.setattr(backups.subprocess, "run", run)
    monkeypatch.setattr(backups, "_export_objects", stop_after_validation)
    if validation_exit:
        with pytest.raises(subprocess.CalledProcessError) as error:
            backups.create_backup(namespace="corp", kind="deployment", checkout=tmp_path)
        assert error.value.returncode == validation_exit
    else:
        with pytest.raises(RuntimeError, match="validation completed"):
            backups.create_backup(namespace="corp", kind="deployment", checkout=tmp_path)
    assert not list((tmp_path / "backups").glob("*/manifest.json"))


@pytest.mark.parametrize("mounted", [False, True])
def test_enabled_hindsight_requires_mount_and_archives_files(tmp_path, monkeypatch, mounted):
    source = tmp_path / "hindsight"
    if mounted:
        source.mkdir()
        (source / "asset.bin").write_bytes(b"hindsight-asset")
    root = tmp_path / "backups"
    checkout = tmp_path / "repo"
    checkout.mkdir()
    monkeypatch.setenv("SAGE_RUN_BACKUP_ROOT", str(root))
    monkeypatch.setenv("SAGE_RUN_BACKUP_HINDSIGHT", "true")
    monkeypatch.setattr(
        backups, "Path", lambda path: source if path == "/var/lib/sage-run/backup-hindsight" else Path(path)
    )

    def run(command, **kwargs):
        if "pg_dump" in command:
            kwargs["stdout"].write(b"database")
        elif "bundle" in command and "create" in command:
            Path(command[command.index("create") + 1]).write_bytes(b"git-history")
        elif "helm" in Path(command[0]).name:
            kwargs["stdout"].write("{}")
        return SimpleNamespace(stdout="test-commit")

    def export_objects(path):
        path.mkdir()
        return {}

    monkeypatch.setattr(backups.subprocess, "run", run)
    monkeypatch.setattr(backups, "_export_objects", export_objects)
    if not mounted:
        with pytest.raises(ValueError, match="Hindsight data mount is missing"):
            backups.create_backup(namespace="corp", kind="deployment", checkout=checkout)
        assert not list(root.glob("*/manifest.json"))
        return
    target = backups.create_backup(namespace="corp", kind="deployment", checkout=checkout)
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["files"]["hindsight.tar.gz"] == backups.checksum(target / "hindsight.tar.gz")
    with tarfile.open(target / "hindsight.tar.gz") as archive:
        stream = archive.extractfile("hindsight/asset.bin")
        assert stream is not None
        assert stream.read() == b"hindsight-asset"
