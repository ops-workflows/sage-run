"""Unit tests for scoped Hindsight retention hooks."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path


def _load_hook_module():
    path = Path(__file__).resolve().parents[2] / "hooks" / "retain_incident_hook.py"
    spec = importlib.util.spec_from_file_location("retain_incident_hook_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_hook(monkeypatch, scope: str, hook_event: str):
    hook = _load_hook_module()
    monkeypatch.setenv("TASK_ID", "task-123")
    monkeypatch.setenv("TASK_WORKFLOW", "platform-test")
    monkeypatch.setenv("RETAIN_MEMORY_SCOPE", scope)
    monkeypatch.setattr(hook, "_fetch_session_detail", lambda _task_id: {"task": {"prompt": "Service alert"}})
    monkeypatch.setattr(hook, "resolve_bank_id", lambda _workflow, kind="business": f"{kind}-bank")
    retained = []
    emitted = []
    monkeypatch.setattr(hook, "_retain_memory", lambda **kwargs: retained.append(kwargs) or "operation-1")
    monkeypatch.setattr(hook, "emit_hook_event", lambda **kwargs: emitted.append(kwargs))
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": hook_event,
                    "agent_type": "online-alerts-coordinator",
                    "last_assistant_message": "## Online alert investigation\n\n**Status:** Verified",
                }
            )
        ),
    )
    with redirect_stdout(io.StringIO()):
        hook.main()
    return retained, emitted


def test_stop_hook_retains_only_final_business_rca(monkeypatch):
    retained, emitted = _run_hook(monkeypatch, "business", "Stop")

    assert [item["metadata"]["bank_kind"] for item in retained] == ["business"]
    assert emitted[0]["hook_event"] == "Stop"


def test_subagent_stop_hook_retains_only_learning_trace(monkeypatch):
    retained, emitted = _run_hook(monkeypatch, "learning", "SubagentStop")

    assert [item["metadata"]["bank_kind"] for item in retained] == ["learning"]
    assert retained[0]["document_id"] == "task-123:learning:online-alerts-coordinator"
    assert emitted[0]["hook_event"] == "SubagentStop"
