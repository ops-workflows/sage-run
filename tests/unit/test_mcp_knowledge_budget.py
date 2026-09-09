"""Knowledge MCP request-budget tests."""

from __future__ import annotations

import pytest

from shared.lib.task_call_budget import TaskCallBudget

pytestmark = pytest.mark.unit


def test_task_call_budget_allows_limit_then_fails_fast() -> None:
    budget = TaskCallBudget(limit=2, max_tasks=10)

    assert budget.consume("task-a") == 1

    assert budget.consume("task-a") == 2
    with pytest.raises(PermissionError, match="budget exhausted.*Do not retry"):
        budget.consume("task-a")


def test_task_call_budget_evicts_oldest_task() -> None:
    budget = TaskCallBudget(limit=2, max_tasks=2)

    budget.consume("task-a")
    budget.consume("task-b")
    budget.consume("task-c")

    assert budget.consume("task-a") == 1


def test_task_call_budget_tracks_tasks_independently() -> None:
    budget = TaskCallBudget(limit=1, max_tasks=10)

    assert budget.consume("task-a") == 1
    assert budget.consume("task-b") == 1


def test_task_call_budget_uses_resource_specific_error() -> None:
    budget = TaskCallBudget(
        limit=1,
        max_tasks=10,
        resource_name="Splunk MCP",
        exhausted_instruction="Return provider evidence; do not retry.",
    )
    budget.consume("task-a")

    with pytest.raises(PermissionError, match="Splunk MCP.*Return provider evidence"):
        budget.consume("task-a")
