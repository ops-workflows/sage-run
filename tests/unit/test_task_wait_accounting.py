"""Human-wait accounting excluded from the runtime timeout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from shared.lib.task_queue import active_runtime_sec, wait_finished_updates, wait_started_updates

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _task(*, wait_started=None, waited_sec=0.0):
    return SimpleNamespace(wait_started=wait_started, waited_sec=waited_sec)


def test_wait_start_keeps_an_open_wait():
    assert wait_started_updates(_task(), NOW) == {"wait_started": NOW}
    assert wait_started_updates(None, NOW) == {"wait_started": NOW}
    assert wait_started_updates(_task(wait_started=NOW - timedelta(minutes=5)), NOW) == {}


def test_wait_finish_accumulates_and_closes():
    task = _task(wait_started=NOW - timedelta(minutes=30), waited_sec=60)
    assert wait_finished_updates(task, NOW) == {"wait_started": None, "waited_sec": 1860.0}
    assert wait_finished_updates(_task(), NOW) == {}
    assert wait_finished_updates(None, NOW) == {}


def test_active_runtime_excludes_closed_and_open_waits():
    started = NOW - timedelta(hours=3)
    assert active_runtime_sec(_task(waited_sec=3 * 3600 - 120), started, NOW) == 120
    open_wait = _task(wait_started=NOW - timedelta(hours=1), waited_sec=3600)
    assert active_runtime_sec(open_wait, started, NOW) == 3600
    assert active_runtime_sec(_task(waited_sec=99999), started, NOW) == 0
