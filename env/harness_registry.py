"""In-memory registry of external harness processes.

Each registration owns a small FIFO command queue. UI lifecycle requests
(`play`, `stop`, future `load_state:<name>`) enqueue here; the agent process
dequeues either by polling `/api/harness/<id>/poll` (HTTP) or by reading the
`/api/harness/<id>/control` WebSocket (preferred — see env/app.py).
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque


LIVE_STATUSES = {"starting", "running", "stopping"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class HarnessRegistry:
    def __init__(self, max_commands: int = 20, storage_path: Path | None = None) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._commands: dict[str, Deque[str]] = {}
        self._max_commands = max_commands
        self._storage_path = storage_path
        self._hydrate()

    def register(
        self,
        name: str,
        *,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        hid = uuid.uuid4().hex[:8]
        now = _now()
        self._records[hid] = {
            "id": hid,
            "name": name,
            "model": model,
            "metadata": metadata or {},
            "status": "idle",
            "error": None,
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        }
        self._commands[hid] = deque(maxlen=self._max_commands)
        self._persist()
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
        now = _now()
        self._records[harness_id]["updated_at"] = now
        self._records[harness_id]["last_seen_at"] = now
        self._persist()

    def touch(self, harness_id: str) -> None:
        self.require(harness_id)
        self._records[harness_id]["last_seen_at"] = _now()
        self._persist()

    def enqueue(self, harness_id: str, command: str) -> None:
        self.require(harness_id)
        self._commands[harness_id].append(command)
        self._records[harness_id]["updated_at"] = _now()
        self._persist()

    def poll(self, harness_id: str) -> str | None:
        self.require(harness_id)
        self._records[harness_id]["last_seen_at"] = _now()
        queue = self._commands[harness_id]
        if not queue:
            self._persist()
            return None
        command = queue.popleft()
        self._persist()
        return command

    def unregister(self, harness_id: str) -> None:
        self._records.pop(harness_id, None)
        self._commands.pop(harness_id, None)
        self._persist()

    def prune_stale(self, *, disconnect_after_s: float = 30.0, prune_after_s: float = 300.0) -> None:
        now = datetime.now(timezone.utc)
        disconnect_after = timedelta(seconds=disconnect_after_s)
        prune_after = timedelta(seconds=prune_after_s)
        changed = False
        for harness_id, record in list(self._records.items()):
            last_seen = _parse_time(record.get("last_seen_at")) or _parse_time(record.get("updated_at")) or now
            age = now - last_seen
            if age > prune_after:
                self._records.pop(harness_id, None)
                self._commands.pop(harness_id, None)
                changed = True
                continue
            if age > disconnect_after and record.get("status") in LIVE_STATUSES:
                record["status"] = "disconnected"
                record["updated_at"] = _now()
                changed = True
        if changed:
            self._persist()

    def _hydrate(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except Exception:
            return
        records = data.get("records") if isinstance(data, dict) else None
        commands = data.get("commands") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return
        for raw in records:
            if not isinstance(raw, dict):
                continue
            harness_id = raw.get("id")
            if not isinstance(harness_id, str) or not harness_id:
                continue
            record = dict(raw)
            if record.get("status") in LIVE_STATUSES:
                record["status"] = "disconnected"
            now = _now()
            record.setdefault("name", "Harness")
            record.setdefault("model", None)
            record.setdefault("metadata", {})
            record.setdefault("error", None)
            record.setdefault("created_at", now)
            record.setdefault("updated_at", now)
            record.setdefault("last_seen_at", record["updated_at"])
            self._records[harness_id] = record
            queued = commands.get(harness_id, []) if isinstance(commands, dict) else []
            self._commands[harness_id] = deque(
                [cmd for cmd in queued if isinstance(cmd, str)],
                maxlen=self._max_commands,
            )
        self._persist()

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "records": list(self._records.values()),
            "commands": {hid: list(queue) for hid, queue in self._commands.items()},
        }
        self._storage_path.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
