"""Spawn and track agent processes defined in agents.yaml.

This lets the UI launch/stop agent processes directly, instead of requiring
every agent to be pre-spawned by scripts/dev.sh. Spawned processes are plain
`uv run python -m <module>` children; each one registers itself with the
harness registry over HTTP once it boots.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from env.paths import PROJECT_ROOT

LOGS_DIR = PROJECT_ROOT / "logs"


class AgentProcessManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or (PROJECT_ROOT / "agents.yaml")
        self._procs: dict[str, subprocess.Popen] = {}

    def definitions(self) -> list[dict[str, Any]]:
        if not self.config_path.exists():
            return []
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return []
        out = []
        for entry in data.get("agents", []):
            if isinstance(entry, dict) and entry.get("name") and entry.get("module"):
                out.append({
                    "name": str(entry["name"]),
                    "module": str(entry["module"]),
                    "description": entry.get("description"),
                })
        return out

    def list(self) -> list[dict[str, Any]]:
        out = []
        for definition in self.definitions():
            name = definition["name"]
            proc = self._procs.get(name)
            running = proc is not None and proc.poll() is None
            out.append({
                **definition,
                "running": running,
                "pid": proc.pid if running and proc else None,
                "log": f"logs/{name}.log",
            })
        return out

    def launch(self, name: str, *, model: str | None = None) -> dict[str, Any]:
        definition = next((d for d in self.definitions() if d["name"] == name), None)
        if definition is None:
            raise KeyError(name)
        proc = self._procs.get(name)
        if proc is not None and proc.poll() is None:
            return {"name": name, "pid": proc.pid, "already_running": True}

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = (LOGS_DIR / f"{name}.log").open("a", encoding="utf-8")
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "POKEMON_AGENT_KEY": name}
        if model:
            env["POKEMON_AGENT_MODEL"] = model
        # start_new_session so terminate() can signal the whole group (uv run
        # wraps the actual python process).
        proc = subprocess.Popen(
            [sys.executable, "-m", definition["module"]],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._procs[name] = proc
        return {"name": name, "pid": proc.pid, "already_running": False}

    def terminate(self, name: str) -> bool:
        proc = self._procs.get(name)
        if proc is None or proc.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return False
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        return True

    def shutdown(self) -> None:
        for name in list(self._procs):
            self.terminate(name)
