from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx


class PokemonEnvClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def wait_for_server(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = self.client.get("/api/health")
                if response.status_code == 200:
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(0.25)
        raise RuntimeError(f"Environment server did not become healthy: {last_error}")

    def start_run(self, run_id: str, rom_path: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"run_id": run_id}
        if rom_path:
            payload["rom_path"] = rom_path
        return self._post("/api/run/start", payload)

    def stop_run(self) -> dict[str, Any]:
        return self._post("/api/run/stop", None)

    def get_state(self) -> dict[str, Any]:
        return self._get("/api/state")

    def get_screenshot(self, path: Path) -> Path:
        response = self.client.get("/api/screenshot.png")
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return path

    def press_button(self, button: str, frames: int = 8) -> dict[str, Any]:
        return self._post("/api/action/press", {"button": button, "frames": frames})

    def press_sequence(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        return self._post("/api/action/sequence", {"steps": steps})

    def wait(self, frames: int) -> dict[str, Any]:
        return self._post("/api/step", {"frames": frames})

    def set_speed(self, mode: str) -> dict[str, Any]:
        return self._post("/api/speed", {"mode": mode})

    def save_state(self, name: str) -> dict[str, Any]:
        return self._post("/api/save-state", {"name": name})

    def load_state(self, name: str) -> dict[str, Any]:
        return self._post("/api/load-state", {"name": name})

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
        frame: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"type": event_type, "payload": payload}
        if turn_id is not None:
            body["turn_id"] = turn_id
        if frame is not None:
            body["frame"] = frame
        return self._post("/api/harness/event", body)

    def _get(self, path: str) -> dict[str, Any]:
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()


def press(button: str, frames: int = 8) -> dict[str, Any]:
    return {"type": "press", "button": button, "frames": frames}


def wait(frames: int) -> dict[str, Any]:
    return {"type": "wait", "frames": frames}

