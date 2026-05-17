"""In-memory registry of external harness processes.

Each registration owns a small FIFO command queue. UI lifecycle requests
(`play`, `stop`, future `load_state:<name>`) enqueue here; the agent process
dequeues either by polling `/api/harness/<id>/poll` (HTTP) or by reading the
`/api/harness/<id>/control` WebSocket (preferred — see env/app.py).
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque


class HarnessRegistry:
    def __init__(self, max_commands: int = 20) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._commands: dict[str, Deque[str]] = {}
        self._max_commands = max_commands

    def register(self, name: str) -> str:
        hid = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat()
        self._records[hid] = {
            "id": hid,
            "name": name,
            "status": "idle",
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        self._commands[hid] = deque(maxlen=self._max_commands)
        return hid

    def list(self) -> list[dict[str, Any]]:
        return [record.copy() for record in self._records.values()]

    def require(self, harness_id: str) -> None:
        if harness_id not in self._records:
            raise KeyError(harness_id)

    def has(self, harness_id: str) -> bool:
        return harness_id in self._records

    def update(self, harness_id: str, **updates: Any) -> None:
        self.require(harness_id)
        self._records[harness_id].update(updates)
        self._records[harness_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def enqueue(self, harness_id: str, command: str) -> None:
        self.require(harness_id)
        self._commands[harness_id].append(command)

    def poll(self, harness_id: str) -> str | None:
        self.require(harness_id)
        queue = self._commands[harness_id]
        if not queue:
            return None
        return queue.popleft()

    def unregister(self, harness_id: str) -> None:
        self._records.pop(harness_id, None)
        self._commands.pop(harness_id, None)
