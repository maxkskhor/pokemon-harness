from __future__ import annotations

import threading
import time
import traceback
import uuid
import sys
from pathlib import Path
from typing import Any

from harness.client import PokemonEnvClient


class PokemonAgent:
    """
    Base class for a Pokemon agent.

    Subclass this, set `name`, and override `run()`.
    Call `.serve()` to register with the backend and wait for Play/Stop from the UI.
    """

    name: str = "My Pokemon Agent"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        run_id: str | None = None,
        load_state: str | None = "bedroom",
    ) -> None:
        self._base_url = base_url
        self._run_id_prefix = run_id or "agent"
        self._run_id = self._new_run_id()
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

    def wait(self, frames: int) -> dict[str, Any]:
        """Advance the emulator by game frames without pressing a button."""
        return self._client.wait(frames)

    def sequence(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Run a press/wait action sequence."""
        return self._client.press_sequence(steps)

    def press(self, button: str, frames: int = 8) -> None:
        """Press a GameBoy button."""
        before = self._safe_state()
        self._client.press_button(button, frames)
        after = self._safe_state()
        self.emit(
            "action",
            {
                "kind": "button_press",
                "button": button,
                "frames": frames,
                "before": self._position_payload(before),
                "after": self._position_payload(after),
            },
        )

    def save_state(self, name: str) -> dict[str, Any]:
        """Save the current emulator state under a run-local name."""
        return self._client.save_state(name)

    def load_state(self, name: str) -> dict[str, Any]:
        """Load a run-local or shared emulator state by name."""
        return self._client.load_state(name)

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> None:
        """Emit an event visible in the UI trace panel."""
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
        print("Open the UI, select this agent from the dropdown, and click Play.")

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
                self._set_status("starting")
                self._run_id = self._new_run_id()
                try:
                    self._client.start_run(self._run_id)
                except Exception as exc:
                    self._set_error(f"start_run failed: {exc}")
                    continue
                self._emit_safe("lifecycle", {"status": "run_started", "run_id": self._run_id})
                if self._load_state:
                    try:
                        self._client.load_state(self._load_state)
                        self._emit_safe("lifecycle", {"status": "state_loaded", "name": self._load_state})
                    except Exception as exc:
                        self._emit_safe(
                            "warning",
                            {"message": f"Could not load save state '{self._load_state}': {exc}. Starting from ROM beginning."},
                        )
                self._client.set_speed("1x")
                self._set_status("running")
                run_thread = threading.Thread(target=self._run_wrapped, daemon=True)
                run_thread.start()

            elif cmd == "stop":
                self._stop_event.set()
                self._emit_safe("lifecycle", {"status": "stop_requested"})
                if run_thread and run_thread.is_alive():
                    run_thread.join(timeout=10)
                run_thread = None
                self._set_status("idle")
                self._emit_safe("lifecycle", {"status": "idle"})

            time.sleep(0.5)

    def _run_wrapped(self) -> None:
        try:
            self._emit_safe("lifecycle", {"status": "agent_loop_started"})
            self.run()
            self._emit_safe("lifecycle", {"status": "agent_loop_finished"})
        except Exception as exc:
            full_tb = traceback.format_exc()
            self._set_error(str(exc))
            print(full_tb, end="", file=sys.stderr)
            self._emit_safe("error", {"message": str(exc), "traceback": full_tb})
        finally:
            self._set_status("idle")

    def _emit_safe(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> None:
        try:
            self.emit(event_type, payload, turn_id=turn_id)
        except Exception as exc:
            print(f"Could not emit event '{event_type}': {exc}")

    def _safe_state(self) -> dict[str, Any] | None:
        try:
            return self.state()
        except Exception:
            return None

    def _position_payload(self, state: dict[str, Any] | None) -> dict[str, Any] | None:
        if state is None:
            return None
        pokemon = state.get("pokemon", {})
        if not isinstance(pokemon, dict):
            return None
        return {
            "frame": state.get("frame"),
            "map_id": pokemon.get("map_id"),
            "x": pokemon.get("x"),
            "y": pokemon.get("y"),
        }

    def _set_status(self, status: str) -> None:
        try:
            self._client._post(f"/api/harness/{self._harness_id}/status", {"status": status})
        except Exception:
            pass

    def _set_error(self, message: str) -> None:
        print(f"Agent error: {message}")
        try:
            self._client._post(f"/api/harness/{self._harness_id}/error", {"message": message})
        except Exception:
            pass

    def _new_run_id(self) -> str:
        return f"{self._run_id_prefix}-{uuid.uuid4().hex[:8]}"
