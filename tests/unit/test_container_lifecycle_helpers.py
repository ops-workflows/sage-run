"""Unit tests for container-lifecycle helpers.

Tests pure helper functions from ``session_manager.container_lifecycle``:
env merging, selector resolution, and workflow bundle selection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from session_manager.container_lifecycle import (
    _active_platform_config_file,
    _apply_runtime_env_overrides,
    _get_agent_env_vars,
    _get_platform_runtime_env,
    _get_session_model_selector,
    _lifecycle_cost_usd,
    _load_active_release,
    _resolve_workflow_bundle,
)

import shared.lib.object_store as object_store_mod
from shared.lib.config import settings

pytestmark = pytest.mark.unit


# ── env merging ──────────────────────────────────────────


def test_agent_env_vars_coerces_scalars_to_strings():
    cfg = {"env": {"A": 1, "B": True, "C": "value", "D": 3.14}}
    env = _get_agent_env_vars(cfg)
    assert env == {"A": "1", "B": "True", "C": "value", "D": "3.14"}


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"total_cost_usd": 0.00097425}, 0.00097425),
        ({"total_cost_usd": 0}, 0.0),
        ({}, None),
        ({"total_cost_usd": "0.1"}, None),
        ({"total_cost_usd": True}, None),
        ({"total_cost_usd": -1}, None),
    ],
)
def test_lifecycle_cost_usd(data, expected):
    assert _lifecycle_cost_usd(data) == expected


def test_agent_env_vars_skips_none_and_non_scalar():
    cfg = {"env": {"A": None, "B": {"nested": 1}, "C": [1, 2], "D": "ok"}}
    env = _get_agent_env_vars(cfg)
    assert env == {"D": "ok"}


def test_agent_env_vars_empty_on_missing_or_bad_section():
    assert _get_agent_env_vars({}) == {}
    assert _get_agent_env_vars({"env": "not-a-dict"}) == {}


def test_apply_runtime_env_overrides_null_removes_variable():
    env = {"ANTHROPIC_API_KEY": "secret", "KEEP_ME": "yes"}
    _apply_runtime_env_overrides(env, {"ANTHROPIC_API_KEY": None})
    assert "ANTHROPIC_API_KEY" not in env
    assert env["KEEP_ME"] == "yes"


def test_apply_runtime_env_overrides_scalar_sets_value():
    env = {"FOO": "old"}
    _apply_runtime_env_overrides(env, {"FOO": "new", "BAR": "added"})
    assert env == {"FOO": "new", "BAR": "added"}


def test_runtime_profile_resolves_platform_secret_without_process_env(tmp_path, monkeypatch):
    from unittest.mock import patch

    from session_manager.container_lifecycle import _get_platform_config_env

    monkeypatch.delenv("CUSTOM_LLM_API_KEY", raising=False)
    monkeypatch.setattr(settings, "age_identity", "test-identity")
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        """
secrets:
  CUSTOM_LLM_API_KEY:
    encrypted: ciphertext
model_profiles:
  custom:
    ANTHROPIC_AUTH_TOKEN: ${CUSTOM_LLM_API_KEY}
""".strip()
    )
    with patch("shared.lib.platform_secrets.decrypt_named_secrets", return_value={"CUSTOM_LLM_API_KEY": "profile-key"}):
        platform_env = _get_platform_config_env(platform_file=str(config))
    runtime_env = _get_platform_runtime_env(
        model_selector="custom", platform_file=str(config), environment=platform_env
    )

    assert runtime_env["ANTHROPIC_AUTH_TOKEN"] == "profile-key"  # noqa: S105 - test fixture.


# ── session model selector ──────────────────────────────────────────


def test_session_model_selector_returns_value():
    assert _get_session_model_selector({"session": {"model": "test"}}) == "test"


def test_session_model_selector_returns_none_for_missing():
    assert _get_session_model_selector({}) is None
    assert _get_session_model_selector({"session": {}}) is None
    assert _get_session_model_selector({"session": {"model": "   "}}) is None
    assert _get_session_model_selector({"session": "not-a-dict"}) is None


def test_active_platform_config_prefers_synced_snapshot(monkeypatch, tmp_path):
    mounted_config = tmp_path / "mounted-platform-config.yaml"
    mounted_config.write_text("default_model_profile: mounted\n", encoding="utf-8")
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    snapshot = bundle_root / "platform-config.yaml"
    snapshot.write_text("default_model_profile: synced\n", encoding="utf-8")
    monkeypatch.setattr(settings, "platform_config_file", str(mounted_config))
    monkeypatch.setattr(settings, "runtime_bundle_root", str(bundle_root))

    assert _active_platform_config_file() == str(snapshot)


def test_active_platform_config_falls_back_before_first_sync(monkeypatch, tmp_path):
    mounted_config = tmp_path / "mounted-platform-config.yaml"
    mounted_config.write_text("default_model_profile: mounted\n", encoding="utf-8")
    monkeypatch.setattr(settings, "platform_config_file", str(mounted_config))
    monkeypatch.setattr(settings, "runtime_bundle_root", str(tmp_path / "bundles"))

    assert _active_platform_config_file() == str(mounted_config)


def test_active_release_selects_matching_config_and_bundle(monkeypatch, tmp_path):
    manifest = {
        "release_id": "release-1",
        "platform_config_key": "releases/release-1/platform-config.yaml",
        "bundles": {
            "platform-test": {
                "key": "releases/release-1/bundles/platform-test.tar.gz",
                "checksum": "sha256:bundle-manifest",
            }
        },
    }
    objects = {
        "releases/active.json": json.dumps({"manifest_key": "releases/release-1/manifest.json"}).encode(),
        "releases/release-1/manifest.json": json.dumps(manifest).encode(),
        "releases/release-1/platform-config.yaml": b"default_model_profile: synced\n",
    }
    monkeypatch.setattr(settings, "runtime_bundle_object_store_bucket", "sage-run-bundles")
    monkeypatch.setattr(settings, "runtime_bundle_root", str(tmp_path))
    monkeypatch.setattr(object_store_mod, "download_bytes", lambda bucket, key: objects.get(key))
    monkeypatch.setattr(
        object_store_mod,
        "presigned_get_url",
        lambda bucket, key, *, expires_sec=3600: f"https://objects.test/{bucket}/{key}?exp={expires_sec}",
    )

    release = _load_active_release()
    assert release == manifest
    config_path = _active_platform_config_file(release)
    bundle_path, bundle_uri, checksum = _resolve_workflow_bundle("platform-test", release=release)

    assert Path(config_path).read_text(encoding="utf-8") == "default_model_profile: synced\n"
    assert bundle_path is None
    assert (
        bundle_uri == "https://objects.test/sage-run-bundles/releases/release-1/bundles/platform-test.tar.gz?exp=3600"
    )
    assert checksum == "sha256:bundle-manifest"


# ── stale container cleanup ──────────────────────────────────────────


def test_resolve_workflow_bundle_returns_configured_uri_without_local_root(monkeypatch):
    monkeypatch.setattr(settings, "runtime_bundle_root", "")
    monkeypatch.setattr(settings, "runtime_bundle_uri_template", "s3://bundles/{workflow}")

    bundle_path, bundle_uri, checksum = _resolve_workflow_bundle("platform-test")

    assert bundle_path is None
    assert bundle_uri == "s3://bundles/platform-test"
    assert checksum is None


def test_resolve_workflow_bundle_uses_existing_local_bundle(monkeypatch, tmp_path):
    bundle_dir = tmp_path / "platform-test"
    bundle_dir.mkdir()
    (bundle_dir / "manifest.yaml").write_text("bundle_version: 1\n", encoding="utf-8")
    monkeypatch.setattr(settings, "runtime_bundle_root", str(tmp_path))
    monkeypatch.setattr(settings, "runtime_bundle_uri_template", "")

    bundle_path, bundle_uri, checksum = _resolve_workflow_bundle("platform-test")

    assert bundle_path == str(bundle_dir)
    assert bundle_uri == f"file://{bundle_dir}"
    assert checksum.startswith("sha256:")


def test_resolve_workflow_bundle_uploads_to_object_store_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "runtime_bundle_uri_template", "")
    monkeypatch.setattr(settings, "runtime_bundle_object_store_bucket", "sage-run-bundles")
    monkeypatch.setattr(settings, "runtime_bundle_presigned_url_expires_sec", 900)

    fresh_root = tmp_path / "fresh-root"
    monkeypatch.setattr(settings, "runtime_bundle_root", str(fresh_root))

    def _fake_build(**kwargs):
        output_dir = kwargs["output_dir"]
        built_dir = output_dir / kwargs["workflow"]
        built_dir.mkdir(parents=True, exist_ok=True)
        (built_dir / "manifest.yaml").write_text("bundle_version: 1\n", encoding="utf-8")

    monkeypatch.setattr("session_manager.container_lifecycle.build_workflow_bundle", _fake_build)

    import shared.lib.object_store as object_store_mod
    import shared.lib.workflow_bundles as workflow_bundles_mod

    upload_calls: list[tuple] = []
    presign_calls: list[tuple] = []

    def _fake_upload(dir_arg, workflow_arg, *, bucket, key_prefix="bundles"):
        upload_calls.append((dir_arg, workflow_arg, bucket, key_prefix))
        return f"{key_prefix}/{workflow_arg}.tar.gz"

    def _fake_presign(bucket, key, *, expires_sec=3600):
        presign_calls.append((bucket, key, expires_sec))
        return f"https://fake/{bucket}/{key}?exp={expires_sec}"

    monkeypatch.setattr(workflow_bundles_mod, "upload_bundle_archive", _fake_upload)
    monkeypatch.setattr(object_store_mod, "presigned_get_url", _fake_presign)

    bundle_path, bundle_uri, checksum = _resolve_workflow_bundle("platform-test")

    expected_bundle_dir = fresh_root / "platform-test"
    assert bundle_path == str(expected_bundle_dir)
    assert bundle_uri == "https://fake/sage-run-bundles/bundles/platform-test.tar.gz?exp=900"
    assert checksum.startswith("sha256:")
    assert upload_calls == [(expected_bundle_dir, "platform-test", "sage-run-bundles", "bundles")]
    assert presign_calls == [("sage-run-bundles", "bundles/platform-test.tar.gz", 900)]


def test_resolve_workflow_bundle_reuses_object_store_key_without_reupload(monkeypatch, tmp_path):
    bundle_dir = tmp_path / "platform-test"
    bundle_dir.mkdir()
    (bundle_dir / "manifest.yaml").write_text("bundle_version: 1\n", encoding="utf-8")
    monkeypatch.setattr(settings, "runtime_bundle_root", str(tmp_path))
    monkeypatch.setattr(settings, "runtime_bundle_uri_template", "")
    monkeypatch.setattr(settings, "runtime_bundle_object_store_bucket", "sage-run-bundles")

    import shared.lib.object_store as object_store_mod
    import shared.lib.workflow_bundles as workflow_bundles_mod

    def _fail_upload(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("upload_bundle_archive should not run for an existing local bundle")

    presign_calls: list[tuple] = []

    def _fake_presign(bucket, key, *, expires_sec=3600):
        presign_calls.append((bucket, key, expires_sec))
        return f"https://fake/{bucket}/{key}"

    monkeypatch.setattr(workflow_bundles_mod, "upload_bundle_archive", _fail_upload)
    monkeypatch.setattr(object_store_mod, "presigned_get_url", _fake_presign)

    _, bundle_uri, _ = _resolve_workflow_bundle("platform-test")

    assert bundle_uri == "https://fake/sage-run-bundles/bundles/platform-test.tar.gz"
    assert presign_calls == [("sage-run-bundles", "bundles/platform-test.tar.gz", 3600)]
