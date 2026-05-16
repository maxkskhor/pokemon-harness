from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


Source = Literal["env", "harness"]
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_safe_name(value: str, label: str = "name") -> str:
    if not SAFE_NAME_RE.match(value):
        raise ValueError(f"{label} may only contain letters, numbers, hyphen, and underscore")
    return value


class TraceStore:
    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        safe_run_id = ensure_safe_name(run_id, "run_id")
        path = self.runs_dir / safe_run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def trace_path(self, run_id: str, source: Source) -> Path:
        return self.run_dir(run_id) / f"{source}.jsonl"

    def reset_run(self, run_id: str) -> None:
        for source in ("env", "harness"):
            path = self.trace_path(run_id, source)  # type: ignore[arg-type]
            if path.exists():
                path.unlink()

    def append(
        self,
        *,
        run_id: str,
        source: Source,
        event_type: str,
        payload: dict[str, Any],
        frame: int | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "run_id": run_id,
            "source": source,
            "type": event_type,
            "turn_id": turn_id,
            "frame": frame,
            "timestamp": now_iso(),
            "payload": payload,
        }
        path = self.trace_path(run_id, source)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def read(self, run_id: str, source: Source) -> list[dict[str, Any]]:
        path = self.trace_path(run_id, source)
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events
