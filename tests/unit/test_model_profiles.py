"""Unit tests for model_profiles resolution in platform_secrets.py.

Validates that:
- The test profile sets ANTHROPIC_BASE_URL correctly
- The default_model_profile fallback works
- An unknown profile falls back to direct model override
- null runtime_env values produce None (removal markers)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from shared.lib.platform_secrets import load_platform_runtime_env

FIXTURE_PLATFORM_CONFIG = (
    Path(__file__).resolve().parents[1] / "fixtures" / "repo-root" / "shared" / "platform-config.yaml"
)

pytestmark = pytest.mark.unit


def test_test_profile_sets_anthropic_base_url():
    env = load_platform_runtime_env(str(FIXTURE_PLATFORM_CONFIG), model_selector="test")
    assert "ANTHROPIC_BASE_URL" in env
    assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:19999"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "test-token"  # noqa: S105 - test fixture value.
    assert env["ANTHROPIC_MODEL"] == "test-model"


def test_local_profile_sets_anthropic_base_url():
    env = load_platform_runtime_env(str(FIXTURE_PLATFORM_CONFIG), model_selector="local")
    assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:19999"


def test_default_profile_fallback():
    """When no selector is given, default_model_profile ('test') is used."""
    env = load_platform_runtime_env(str(FIXTURE_PLATFORM_CONFIG), model_selector=None)
    assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:19999"
    assert env["ANTHROPIC_MODEL"] == "test-model"


def test_unknown_profile_becomes_direct_model_name():
    env = load_platform_runtime_env(str(FIXTURE_PLATFORM_CONFIG), model_selector="claude-sonnet-4-20250514")
    assert env["ANTHROPIC_MODEL"] == "claude-sonnet-4-20250514"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-sonnet-4-20250514"
    # Should NOT contain ANTHROPIC_BASE_URL from a profile
    assert "ANTHROPIC_BASE_URL" not in env


def test_null_runtime_env_produces_none():
    env = load_platform_runtime_env(str(FIXTURE_PLATFORM_CONFIG), model_selector="test")
    # ANTHROPIC_API_KEY is set to null in runtime_env
    assert env.get("ANTHROPIC_API_KEY") is None
    assert "ANTHROPIC_API_KEY" in env  # key present with None value


def test_runtime_env_scalars_are_strings():
    env = load_platform_runtime_env(str(FIXTURE_PLATFORM_CONFIG), model_selector="test")
    assert env["DISABLE_TELEMETRY"] == "True"


def test_env_placeholders_expand_from_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_KEY", "omlx-test-token")
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        """
model_profiles:
  local:
    ANTHROPIC_BASE_URL: http://local-llm:8000
    ANTHROPIC_AUTH_TOKEN: ${LOCAL_LLM_KEY}
""".strip()
    )

    env = load_platform_runtime_env(str(config), model_selector="local")
    assert env["ANTHROPIC_BASE_URL"] == "http://local-llm:8000"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "omlx-test-token"  # noqa: S105 - test fixture value.


def test_profile_uses_decrypted_platform_env_without_mutating_process(tmp_path, monkeypatch):
    monkeypatch.delenv("CUSTOM_LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "existing-process-key")
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        """
runtime_env:
  FALLBACK_KEY: ${LLM_API_KEY}
model_profiles:
  custom:
    ANTHROPIC_AUTH_TOKEN: ${CUSTOM_LLM_API_KEY}
""".strip()
    )

    env = load_platform_runtime_env(
        str(config), model_selector="custom", environment={"CUSTOM_LLM_API_KEY": "decrypted-profile-key"}
    )

    assert env["ANTHROPIC_AUTH_TOKEN"] == "decrypted-profile-key"  # noqa: S105 - test fixture.
    assert env["FALLBACK_KEY"] == "existing-process-key"
    assert "CUSTOM_LLM_API_KEY" not in os.environ
    assert "CUSTOM_LLM_API_KEY" not in env


def test_profile_platform_env_takes_precedence_over_stale_process_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOM_LLM_API_KEY", "old-key")
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        """
model_profiles:
  custom:
    runtime_env:
      ANTHROPIC_AUTH_TOKEN: ${CUSTOM_LLM_API_KEY}
""".strip()
    )

    env = load_platform_runtime_env(str(config), model_selector="custom", environment={"CUSTOM_LLM_API_KEY": "new-key"})

    assert env["ANTHROPIC_AUTH_TOKEN"] == "new-key"  # noqa: S105 - test fixture.
    assert os.environ["CUSTOM_LLM_API_KEY"] == "old-key"


def test_model_costs_serialize_to_runtime_env(tmp_path):
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        """
model_profiles:
  local:
    ANTHROPIC_MODEL: qwen
    model_costs:
      qwen: {input: 0.15, output: 1, cache_read: 0.05}
      broken: {input: 0.15}
""".strip()
    )

    env = load_platform_runtime_env(str(config), model_selector="local")

    assert env["ANTHROPIC_MODEL"] == "qwen"
    assert "model_costs" not in env
    assert json.loads(env["MODEL_COSTS_JSON"]) == {"qwen": {"input": 0.15, "output": 1.0, "cache_read": 0.05}}


def test_profile_without_model_costs_sets_no_costs_env():
    env = load_platform_runtime_env(str(FIXTURE_PLATFORM_CONFIG), model_selector="test")
    assert "MODEL_COSTS_JSON" not in env
