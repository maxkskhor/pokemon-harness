from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
import sys
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Generator

from harness.client import PokemonEnvClient, _current_turn_id

logger = logging.getLogger("pokemon_harness.agent")


class PokemonAgent:
    """
    Base class for a Pokemon agent.

    Subclass this, set `name`, and override `run()`.
    Call `.serve()` to register with the backend and wait for Play/Stop from the UI.
    """

    name: str = "My Pokemon Agent"
    model: str | None = None

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        run_id: str | None = None,
        load_state: str | None = "bedroom",
        client_factory: Callable[[str], PokemonEnvClient] | None = None,
    ) -> None:
        self._base_url = base_url
        self._run_id_prefix = run_id or "agent"
        self._run_id = self._new_run_id()
        self._load_state = load_state
        self._client = (client_factory or PokemonEnvClient)(base_url)
        self._stop_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._cmd_queue: Queue[str] = Queue()
        self._ws_thread: threading.Thread | None = None
        self._harness_id: str | None = None
        self._turn_counter: int = 0
        # When the agent itself calls load_state, the env also pushes a
        # load_state:<name> command back via the control WS. Track the most recent
        # local restore so we ignore that echo (dedup window: 5 s).
        self._last_local_load: tuple[str, float] | None = None

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
        """Press a GameBoy button.

        The env publishes the canonical `button_press` trace event (with frame deltas,
        screen hash, and before/after position) — the agent does not need to emit a
        duplicate event of its own.
        """
        self._client.press_button(button, frames)

    def save_state(self, name: str) -> dict[str, Any]:
        """Save the current emulator state under a run-local name.

        Also serializes the agent's own context (via `serialize_history()`) and stores
        it as a `<name>.agent.json` sidecar so a subsequent rewind can reset the LLM
        message history along with the emulator.
        """
        agent_state = self.serialize_history()
        return self._client.save_state(name, agent_state=agent_state or None)

    def load_state(self, name: str) -> dict[str, Any]:
        """Load a run-local or shared emulator state by name.

        Restores agent-side history synchronously (via `restore_history()`) from any
        sidecar included in the response, and records the load so the WebSocket-pushed
        echo (when the UI initiated this load) is dropped instead of restoring twice.
        """
        response = self._client.load_state(name)
        sidecar = response.get("agent_state") if isinstance(response, dict) else None
        if sidecar:
            self._apply_agent_state(name, sidecar)
        return response

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> None:
        """Emit an event visible in the UI trace panel."""
        if self._harness_id is None:
            self._client.emit(event_type, payload, turn_id=turn_id)
        else:
            self._client.emit(event_type, payload, turn_id=turn_id, harness_id=self._harness_id)

    def should_stop(self) -> bool:
        """Return True if the UI sent a Stop signal — check this in your loop."""
        return self._stop_event.is_set()

    @contextmanager
    def turn(
        self,
        goal: str | None = None,
        *,
        turn_id: str | None = None,
    ) -> Generator[str, None, None]:
        """Scoped turn context.

        Usage::

            with self.turn(goal="leave the bedroom") as turn_id:
                self.emit("decision", {"action": "RIGHT"})
                self.press("RIGHT")

        Emits `turn_started` on entry and `turn_finished` on exit.
        Nested turns raise RuntimeError — complete the outer turn first.
        """
        if _current_turn_id.get() is not None:
            raise RuntimeError(
                "Nested turn contexts are not supported. "
                "Complete the outer turn before starting a new one."
            )

        self._turn_counter += 1
        tid = turn_id or f"turn-{self._turn_counter:03d}"
        token = _current_turn_id.set(tid)

        frame: int | None = None
        try:
            frame = self.state().get("frame")
        except Exception:
            pass

        started_at = time.monotonic()
        start_payload: dict[str, Any] = {
            "turn_id": tid,
            "turn_index": self._turn_counter,
        }
        if goal is not None:
            start_payload["goal"] = goal
        if frame is not None:
            start_payload["frame"] = frame
        self._emit_safe("turn_started", start_payload, turn_id=tid)

        status = "ok"
        error_summary: str | None = None
        try:
            yield tid
        except Exception as exc:
            status = "error"
            error_summary = str(exc)
            raise
        finally:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            finish_payload: dict[str, Any] = {
                "turn_id": tid,
                "turn_index": self._turn_counter,
                "status": status,
                "elapsed_ms": elapsed_ms,
            }
            if error_summary is not None:
                finish_payload["error"] = error_summary
            if goal is not None:
                finish_payload["goal"] = goal
            try:
                finish_payload["frame"] = self.state().get("frame")
            except Exception:
                pass
            self._emit_safe("turn_finished", finish_payload, turn_id=tid)
            _current_turn_id.reset(token)

    # ── override these to make checkpoints carry agent context ───────

    def serialize_history(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the agent's own state.

        Default: empty dict. Override in subclasses to persist LLM message history,
        a running goal, planning scratchpad, etc. Whatever this returns is round-tripped
        verbatim into `restore_history()` when a checkpoint is reloaded.
        """
        return {}

    def restore_history(self, data: dict[str, Any]) -> None:
        """Restore agent state from a checkpoint sidecar.

        Default: no-op. Override in subclasses to apply whatever `serialize_history()`
        produced. Called from the control-loop thread, so use locks if your `run()` may
        be reading the same fields concurrently.
        """
        return None

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

        register_payload: dict[str, Any] = {"name": self.name}
        if self.model is not None:
            register_payload["model"] = self.model
        resp = self._client._post("/api/harness/register", register_payload)
        self._harness_id = resp["id"]
        print(f"Registered '{self.name}' (id={self._harness_id})")
        print("Open the UI, select this agent from the dropdown, and click Play.")

        # Start a daemon thread that holds a WebSocket open to the backend and pushes
        # commands ({"command": "play" | "stop" | ...}) onto self._cmd_queue.
        # Falls back to HTTP polling if the WS endpoint is unavailable (older backend).
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()

        try:
            self._control_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown_event.set()
            if self._harness_id:
                try:
                    self._client._post(f"/api/harness/{self._harness_id}/unregister", {})
                except Exception:
                    pass
            self._client.close()
            print("Disconnected.")

    # ── internals ─────────────────────────────────────────────────────

    def _ws_loop(self) -> None:
        """Holds a long-lived WebSocket to the backend and pushes commands onto _cmd_queue.

        On disconnect, reconnects with exponential backoff.
        """
        from websockets.sync.client import connect as ws_connect
        from websockets.exceptions import ConnectionClosed, InvalidStatus

        ws_base = self._base_url
        if ws_base.startswith("https://"):
            ws_base = "wss://" + ws_base[len("https://"):]
        elif ws_base.startswith("http://"):
            ws_base = "ws://" + ws_base[len("http://"):]
        url = f"{ws_base.rstrip('/')}/api/harness/{self._harness_id}/control"

        backoff = 0.5
        while not self._shutdown_event.is_set():
            try:
                with ws_connect(url, open_timeout=5, close_timeout=2) as ws:
                    backoff = 0.5
                    while not self._shutdown_event.is_set():
                        try:
                            message = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            logger.warning("malformed control message: %r", message)
                            continue
                        cmd = data.get("command")
                        if cmd:
                            self._cmd_queue.put(cmd)
            except ConnectionClosed:
                if self._shutdown_event.is_set():
                    return
            except InvalidStatus as exc:
                logger.warning("control WS rejected: %s", exc)
            except Exception as exc:
                logger.warning("control WS error: %s", exc)
            if self._shutdown_event.is_set():
                return
            time.sleep(min(backoff, 5.0))
            backoff = min(backoff * 2, 5.0)

    def _control_loop(self) -> None:
        run_thread: threading.Thread | None = None
        while not self._shutdown_event.is_set():
            try:
                # Block up to 1 s so KeyboardInterrupt is responsive even when idle.
                cmd = self._cmd_queue.get(timeout=1.0)
            except Empty:
                continue

            if cmd == "play" and (run_thread is None or not run_thread.is_alive()):
                self._stop_event.clear()
                self._set_status("starting")
                try:
                    self._prepare_run_for_play()
                except Exception as exc:
                    self._set_error(f"prepare run failed: {exc}")
                    continue
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
                try:
                    self._client.pause_run()
                except Exception:
                    pass
                self._set_status("idle")
                self._emit_safe("lifecycle", {"status": "idle"})

            elif cmd == "reset":
                self._stop_event.set()
                if run_thread and run_thread.is_alive():
                    run_thread.join(timeout=10)
                run_thread = None
                try:
                    self._client.stop_run()
                except Exception:
                    pass
                self._turn_counter = 0
                self._run_id = self._new_run_id()
                self._stop_event.clear()
                self._set_status("idle")
                self._emit_safe("lifecycle", {"status": "reset"})

            elif cmd.startswith("load_state:"):
                name = cmd[len("load_state:"):]
                if self._is_local_load_echo(name):
                    continue  # we already restored from our own load_state call
                # Sidecar lookup uses self._run_id because start_run(self._run_id) above
                # makes the env's session.run_id equal to the agent's run_id; if a future
                # change decouples them, this read must use the env's run_id instead.
                try:
                    sidecar = self._client.read_agent_state(self._run_id, name)
                except Exception as exc:
                    self._emit_safe("warning", {"message": f"load_state:{name} sidecar fetch failed: {exc}"})
                    continue
                if sidecar:
                    self._apply_agent_state(name, sidecar, source="ws")

    def _prepare_run_for_play(self) -> None:
        try:
            state = self._client.get_state()
        except Exception:
            self._run_id = self._new_run_id()
            self._client.start_run(
                self._run_id,
                harness_id=self._harness_id,
                start_state=self._load_state,
            )
            self._turn_counter = 0
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
            return

        active_run_id = state.get("run_id")
        if isinstance(active_run_id, str) and active_run_id:
            self._run_id = active_run_id
        self._turn_counter = self._count_existing_turns(self._run_id)
        try:
            self._client.resume_run()
        except Exception:
            pass
        self._emit_safe(
            "lifecycle",
            {
                "status": "run_resumed",
                "run_id": self._run_id,
                "frame": state.get("frame"),
            },
        )

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

    def _count_existing_turns(self, run_id: str) -> int:
        try:
            events: Any = self._client._get(f"/api/runs/{run_id}/harness-trace")
            if not isinstance(events, list):
                return 0
            return sum(
                1
                for event in events
                if isinstance(event, dict) and event.get("type") == "turn_finished"
            )
        except Exception:
            return 0

    def _new_run_id(self) -> str:
        return f"{self._run_id_prefix}-{uuid.uuid4().hex[:8]}"

    def _apply_agent_state(self, name: str, sidecar: dict[str, Any], source: str = "local") -> None:
        try:
            self.restore_history(sidecar)
        except Exception as exc:
            full_tb = traceback.format_exc()
            self._emit_safe("error", {"message": f"restore_history failed: {exc}", "traceback": full_tb})
            return
        self._last_local_load = (name, time.monotonic())
        self._emit_safe(
            "lifecycle",
            {"status": "history_restored", "name": name, "source": source},
        )

    def _is_local_load_echo(self, name: str) -> bool:
        last = self._last_local_load
        if last is None:
            return False
        last_name, last_at = last
        return last_name == name and (time.monotonic() - last_at) < 5.0
