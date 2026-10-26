"""Exact independent retention counts and backup failure safety."""

from __future__ import annotations

import json

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
