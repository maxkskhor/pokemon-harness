from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

from harness.client import PokemonEnvClient


class Harness:
    """
    Base class for a Pokemon agent harness.

    Subclass this, set `name`, and override `run()`.
    Call `.serve()` to register with the backend and wait for Play/Stop from the UI.
    """

    name: str = "My Harness"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        run_id: str | None = None,
        load_state: str | None = "bedroom",
    ) -> None:
        self._base_url = base_url
        self._run_id = run_id or f"harness-{uuid.uuid4().hex[:6]}"
        self._load_state = load_state
        self._client = PokemonEnvClient(base_url)
        self._stop_event = threading.Event()
        self._harness_id: str | None = None

    # ── public API your run() calls ───────────────────────────────────

    def screenshot_bytes(self) -> bytes:
        """Return the current game frame as raw PNG bytes."""
        resp = self._client.client.get("/api/screenshot.png")
        resp.raise_for_status()
        return resp.content

    def screenshot(self, path: Path) -> Path:
        """Save the current frame to path and return it."""
        return self._client.get_screenshot(path)

    def state(self) -> dict[str, Any]:
        """Return the current game state (frame, position, party, etc.)."""
        return self._client.get_state()

    def press(self, button: str, frames: int = 8) -> None:
        """Press a GameBoy button."""
        self._client.press_button(button, frames)

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> None:
        """Emit a harness event visible in the UI trace panel."""
        self._client.emit(event_type, payload, turn_id=turn_id)

    def should_stop(self) -> bool:
        """Return True if the UI sent a Stop signal — check this in your loop."""
        return self._stop_event.is_set()

    # ── override this ─────────────────────────────────────────────────

    def run(self) -> None:
        """
        Main agent loop — override in your subclass.

        Check `self.should_stop()` periodically and return early when it's True.
        """
        raise NotImplementedError

    # ── lifecycle ─────────────────────────────────────────────────────

    def serve(self) -> None:
        """
        Register with the backend and block, waiting for Play/Stop from the UI.
        Press Ctrl-C to exit cleanly.
        """
        print(f"Connecting to {self._base_url} ...")
        self._client.wait_for_server()

        resp = self._client._post("/api/harness/register", {"name": self.name})
        self._harness_id = resp["id"]
        print(f"Registered '{self.name}' (id={self._harness_id})")
        print("Open the UI, select this harness from the dropdown, and click Play.")

        try:
            self._control_loop()
        except KeyboardInterrupt:
            pass
        finally:
            if self._harness_id:
                try:
                    self._client._post(f"/api/harness/{self._harness_id}/unregister", {})
                except Exception:
                    pass
            self._client.close()
            print("Disconnected.")

    # ── internals ─────────────────────────────────────────────────────

    def _control_loop(self) -> None:
        run_thread: threading.Thread | None = None
        while True:
            try:
                resp = self._client._get(f"/api/harness/{self._harness_id}/poll")
                cmd = resp.get("command")
            except Exception:
                time.sleep(1)
                continue

            if cmd == "play" and (run_thread is None or not run_thread.is_alive()):
                self._stop_event.clear()
                try:
                    self._client.start_run(self._run_id)
                except Exception as exc:
                    self._set_error(f"start_run failed: {exc}")
                    continue
                if self._load_state:
                    try:
                        self._client.load_state(self._load_state)
                    except Exception as exc:
                        self._client.emit(
                            "warning",
                            {"message": f"Could not load save state '{self._load_state}': {exc}. Starting from ROM beginning."},
                        )
                self._client.set_speed("1x")
                run_thread = threading.Thread(target=self._run_wrapped, daemon=True)
                run_thread.start()

            elif cmd == "stop":
                self._stop_event.set()
                if run_thread and run_thread.is_alive():
                    run_thread.join(timeout=10)
                run_thread = None
                self._set_status("idle")

            time.sleep(0.5)

    def _run_wrapped(self) -> None:
        try:
            self.run()
        except Exception as exc:
            self._set_error(str(exc))
            print(f"run() raised: {exc}")
        finally:
            self._set_status("idle")

    def _set_status(self, status: str) -> None:
        try:
            self._client._post(f"/api/harness/{self._harness_id}/status", {"status": status})
        except Exception:
            pass

    def _set_error(self, message: str) -> None:
        print(f"Harness error: {message}")
        try:
            self._client._post(f"/api/harness/{self._harness_id}/error", {"message": message})
        except Exception:
            pass
