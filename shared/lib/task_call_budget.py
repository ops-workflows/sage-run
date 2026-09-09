"""Bounded in-memory call accounting for task-scoped MCP safeguards."""

from __future__ import annotations

import threading
from collections import OrderedDict


class TaskCallBudget:
    def __init__(
        self,
        *,
        limit: int,
        max_tasks: int,
        resource_name: str = "MCP",
        exhausted_instruction: str = "Do not retry.",
    ) -> None:
        self.limit = limit
        self.max_tasks = max_tasks
        self.resource_name = resource_name
        self.exhausted_instruction = exhausted_instruction
        self._counts: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def consume(self, task_id: str) -> int:
        with self._lock:
            used = self._counts.pop(task_id, 0)
            if used >= self.limit:
                self._counts[task_id] = used
                raise PermissionError(
                    f"{self.resource_name} task call budget exhausted ({self.limit} calls). "
                    f"{self.exhausted_instruction}"
                )
            current = used + 1
            self._counts[task_id] = current
            while len(self._counts) > self.max_tasks:
                self._counts.popitem(last=False)
            return current
