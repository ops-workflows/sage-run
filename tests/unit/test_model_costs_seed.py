"""Unit tests for seeding Claude Code model costs into ~/.claude.json."""

from __future__ import annotations

import json
import os

os.environ.setdefault("TASK_ID", "test")
os.environ.setdefault("TASK_PROMPT", "test")

import pytest  # noqa: E402

from runtime.session_entrypoint import _seed_claude_model_costs  # noqa: E402

pytestmark = pytest.mark.unit


def test_seed_merges_costs_into_existing_global_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude.json").write_text(
        json.dumps({"numStartups": 3, "additionalModelCostsCache": {"other": {"inputTokens": 9}}})
    )
    monkeypatch.setenv("MODEL_COSTS_JSON", json.dumps({"qwen": {"input": 0.15, "output": 1.0, "cache_read": 0.05}}))

    _seed_claude_model_costs()

    config = json.loads((tmp_path / ".claude.json").read_text())
    assert config["numStartups"] == 3
    assert config["additionalModelCostsCache"] == {
        "other": {"inputTokens": 9},
        "qwen": {
            "inputTokens": 0.15,
            "outputTokens": 1.0,
            "promptCacheWriteTokens": 0.15,
            "promptCacheReadTokens": 0.05,
            "webSearchRequests": 0,
        },
    }


@pytest.mark.parametrize("raw", ["", "not-json", "[]", json.dumps({"qwen": {"input": 0.1}})])
def test_seed_skips_missing_or_invalid_costs(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MODEL_COSTS_JSON", raw)

    _seed_claude_model_costs()

    assert not (tmp_path / ".claude.json").exists()
