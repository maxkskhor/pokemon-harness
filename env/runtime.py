from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from env.emulator import Emulator, PyBoyEmulator, file_sha1, png_sha256, rom_title
from env.models import (
    HarnessEventRequest,
    PressAction,
    SaveStateRequest,
    SequenceAction,
    SpeedMode,
    StartRunRequest,
    StepRequest,
)
from env.paths import RUNS_DIR, STATES_DIR, default_rom_path, default_symbol_path
from env.symbols import SymbolMap, parse_sym_file, read_pokemon_labels
from env.trace import TraceStore, now_iso


EmulatorFactory = Callable[[Path, Path | None], Emulator]
logger = logging.getLogger("pokemon_harness.runtime")


def _list_state_files(directory: Path, frames_by_name: dict[str, int]) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if path.suffix != ".state" or not path.is_file():
            continue
        stat = path.stat()
        entry: dict[str, Any] = {
            "name": path.stem,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
        frame = frames_by_name.get(path.stem)
        if frame is not None:
            entry["frame"] = frame
        out.append(entry)
    # Newest first — most useful for "rewind to the last checkpoint".
    out.sort(key=lambda entry: entry["modified_at"], reverse=True)
    return out


class EventBroker:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            self._clients.discard(websocket)

    async def publish(self, event: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in self._clients:
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self._clients.discard(websocket)


@dataclass
class Session:
    run_id: str
    rom_path: Path
    sym_path: Path | None
    symbols: SymbolMap
    emulator: Emulator
    trace_store: TraceStore
    broker: EventBroker
    speed_mode: SpeedMode = "paused"
    running: bool = True
    playback_task: asyncio.Task | None = None

    def __post_init__(self) -> None:
        self.lock = asyncio.Lock()
        self._screen_hash_frame: int | None = None
        self._screen_hash_value: str | None = None
        self._screen_png_bytes: bytes | None = None
        self.rom_metadata = {
            "path": str(self.rom_path),
            "filename": self.rom_path.name,
            "sha1": file_sha1(self.rom_path) if self.rom_path.exists() else None,
            "title": rom_title(self.rom_path) if self.rom_path.exists() else None,
            "sym_path": str(self.sym_path) if self.sym_path else None,
            "symbols_loaded": bool(self.symbols.labels),
        }

    async def emit_env(self, event_type: str, payload: dict[str, Any], trace: bool = True) -> dict[str, Any]:
        if trace:
            event = self.trace_store.append(
                run_id=self.run_id,
                source="env",
                event_type=event_type,
                payload=payload,
                frame=self.emulator.frame,
            )
            self._save_frame_thumbnail(event["frame"])
        else:
            event = {
                "run_id": self.run_id,
                "source": "env",
                "type": event_type,
                "turn_id": None,
                "frame": self.emulator.frame,
                "timestamp": now_iso(),
                "payload": payload,
            }
        await self.broker.publish(event)
        if trace:
            logger.info("env event run_id=%s type=%s frame=%s payload=%s", self.run_id, event_type, event["frame"], payload)
        return event

    async def emit_harness(self, event: HarnessEventRequest) -> dict[str, Any]:
        frame = event.frame if event.frame is not None else self.emulator.frame
        envelope = self.trace_store.append(
            run_id=self.run_id,
            source="harness",
            event_type=event.type,
            payload=event.payload,
            frame=frame,
            turn_id=event.turn_id,
        )
        self._save_frame_thumbnail(envelope["frame"])
        await self.broker.publish(envelope)
        logger.info(
            "harness event run_id=%s type=%s turn_id=%s frame=%s payload=%s",
            self.run_id,
            event.type,
            event.turn_id,
            envelope["frame"],
            event.payload,
        )
        return envelope

    def _save_frame_thumbnail(self, frame: int | None) -> None:
        """Persist a PNG for `frame` if one is not already on disk.

        Dedup-by-frame keeps disk usage proportional to unique game states, not
        to event volume. Synchronous because PyBoy's screenshot is cheap and
        keeping it on the same coroutine guarantees the recorded frame and the
        captured pixels stay in sync.
        """
        if frame is None:
            return
        target = self.trace_store.run_dir(self.run_id) / "frames" / f"{frame}.png"
        if target.exists():
            return
        try:
            png = self.cached_screen_png()
        except Exception:
            logger.exception("frame thumbnail render failed run_id=%s frame=%s", self.run_id, frame)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png)

    def state_payload(self) -> dict[str, Any]:
        pokemon = read_pokemon_labels(self.symbols, self.emulator.read_memory_byte)
        return {
            "run_id": self.run_id,
            "running": self.running,
            "frame": self.emulator.frame,
            "speed_mode": self.speed_mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rom": self.rom_metadata,
            "screen": {
                "width": 160,
                "height": 144,
                "sha256": self.screen_sha256(),
            },
            "pokemon": pokemon,
        }

    def position_snapshot(self) -> dict[str, Any]:
        """Cheap pokemon-label read used to annotate env action events with position diffs.

        Doesn't render a screenshot (unlike state_payload), so it's safe to call before
        a press completes.
        """
        pokemon = read_pokemon_labels(self.symbols, self.emulator.read_memory_byte)
        return {
            "frame": self.emulator.frame,
            "map_id": pokemon.get("map_id"),
            "x": pokemon.get("x"),
            "y": pokemon.get("y"),
        }

    def invalidate_screen_cache(self) -> None:
        self._screen_hash_frame = None
        self._screen_hash_value = None
        self._screen_png_bytes = None

    def cached_screen_png(self) -> bytes:
        if self._screen_hash_frame == self.emulator.frame and self._screen_png_bytes is not None:
            return self._screen_png_bytes
        png = self.emulator.screenshot_png()
        self._screen_hash_frame = self.emulator.frame
        self._screen_png_bytes = png
        self._screen_hash_value = png_sha256(png)
        return png

    def screen_sha256(self) -> str:
        if self._screen_hash_frame == self.emulator.frame and self._screen_hash_value is not None:
            return self._screen_hash_value
        self.cached_screen_png()
        assert self._screen_hash_value is not None
        return self._screen_hash_value


class RuntimeManager:
    def __init__(
        self,
        *,
        trace_store: TraceStore | None = None,
        states_dir: Path = STATES_DIR,
        emulator_factory: EmulatorFactory = PyBoyEmulator,
    ) -> None:
        self.trace_store = trace_store or TraceStore(RUNS_DIR)
        self.states_dir = states_dir
        self.emulator_factory = emulator_factory
        self.broker = EventBroker()
        self.session: Session | None = None

    async def start_run(self, request: StartRunRequest) -> dict[str, Any]:
        if self.session is not None:
            await self.stop_run()

        rom_path = Path(request.rom_path) if request.rom_path else default_rom_path()
        if rom_path is None or not rom_path.exists():
            raise HTTPException(
                status_code=400,
                detail="No ROM found. Run scripts/setup_pokered.sh after installing RGBDS with brew install rgbds.",
            )
        sym_path = Path(request.sym_path) if request.sym_path else default_symbol_path(rom_path)
        run_id = request.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
        self.trace_store.reset_run(run_id)
        symbols = parse_sym_file(sym_path)
        emulator = self.emulator_factory(rom_path, sym_path)
        session = Session(
            run_id=run_id,
            rom_path=rom_path,
            sym_path=sym_path,
            symbols=symbols,
            emulator=emulator,
            trace_store=self.trace_store,
            broker=self.broker,
        )
        self.session = session
        session.playback_task = asyncio.create_task(self._playback_loop(session))
        await session.emit_env("run_started", {"rom": session.rom_metadata})
        return session.state_payload()

    async def stop_run(self) -> dict[str, Any]:
        session = self._require_session()
        session.running = False
        if session.playback_task is not None:
            session.playback_task.cancel()
            try:
                await session.playback_task
            except asyncio.CancelledError:
                pass
        async with session.lock:
            session.emulator.stop()
        await session.emit_env("run_stopped", {})
        self.session = None
        return {"running": False, "run_id": session.run_id}

    async def state(self) -> dict[str, Any]:
        session = self._require_session()
        async with session.lock:
            return session.state_payload()

    async def screenshot_png(self) -> bytes:
        session = self._require_session()
        async with session.lock:
            return session.cached_screen_png()

    async def step(self, request: StepRequest) -> dict[str, Any]:
        session = self._require_session()
        async with session.lock:
            before = session.emulator.frame
            session.emulator.tick(request.frames)
            session.invalidate_screen_cache()
            state = session.state_payload()
        await session.emit_env("step", {"frames": request.frames, "before_frame": before, "after_frame": state["frame"]})
        return state

    async def press(self, request: PressAction) -> dict[str, Any]:
        session = self._require_session()
        async with session.lock:
            before = session.position_snapshot()
            session.emulator.press(request.button, request.frames)
            session.invalidate_screen_cache()
            state = session.state_payload()
            after = session.position_snapshot()
        await session.emit_env(
            "button_press",
            {
                "button": request.button,
                "frames": request.frames,
                "before_frame": before["frame"],
                "after_frame": state["frame"],
                "before": before,
                "after": after,
                "screen_sha256": state["screen"]["sha256"],
            },
        )
        return state

    async def sequence(self, request: SequenceAction) -> dict[str, Any]:
        session = self._require_session()
        executed: list[dict[str, Any]] = []
        async with session.lock:
            before = session.position_snapshot()
            for step in request.steps:
                if step.type == "press":
                    if step.button is None:
                        raise HTTPException(status_code=422, detail="press steps require a button")
                    session.emulator.press(step.button, step.frames)
                    session.invalidate_screen_cache()
                    executed.append({"type": "press", "button": step.button, "frames": step.frames})
                else:
                    session.emulator.tick(step.frames)
                    session.invalidate_screen_cache()
                    executed.append({"type": "wait", "frames": step.frames})
            state = session.state_payload()
            after = session.position_snapshot()
        await session.emit_env(
            "button_sequence",
            {
                "steps": executed,
                "before_frame": before["frame"],
                "after_frame": state["frame"],
                "before": before,
                "after": after,
                "screen_sha256": state["screen"]["sha256"],
            },
        )
        return state

    async def set_speed(self, mode: SpeedMode) -> dict[str, Any]:
        session = self._require_session()
        session.speed_mode = mode
        await session.emit_env("speed_changed", {"mode": mode})
        return {"run_id": session.run_id, "speed_mode": mode}

    async def save_state(self, request: SaveStateRequest) -> dict[str, Any]:
        session = self._require_session()
        path = self._state_path(session.run_id, request.name)
        async with session.lock:
            session.emulator.save_state(path)
            frame = session.emulator.frame
        sidecar_written = False
        if request.agent_state is not None:
            sidecar = self._agent_state_path(session.run_id, request.name)
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(request.agent_state), encoding="utf-8")
            sidecar_written = True
        await session.emit_env(
            "state_saved",
            {
                "name": request.name,
                "path": str(path),
                "frame": frame,
                "has_agent_state": sidecar_written,
            },
        )
        return {
            "run_id": session.run_id,
            "name": request.name,
            "path": str(path),
            "frame": frame,
            "has_agent_state": sidecar_written,
        }

    async def load_state(self, request: SaveStateRequest) -> dict[str, Any]:
        session = self._require_session()
        path = self._state_path(session.run_id, request.name)
        sidecar = self._agent_state_path(session.run_id, request.name)
        if not path.exists():
            shared_path = self.states_dir / "shared" / f"{request.name}.state"
            if shared_path.exists():
                path = shared_path
                sidecar = self.states_dir / "shared" / f"{request.name}.agent.json"
            else:
                raise HTTPException(status_code=404, detail=f"Save state not found: {request.name}")
        agent_state: dict[str, Any] | None = None
        if sidecar.exists():
            try:
                agent_state = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("malformed agent state sidecar at %s", sidecar)
                agent_state = None
        async with session.lock:
            session.emulator.load_state(path)
            session.invalidate_screen_cache()
            state = session.state_payload()
        await session.emit_env(
            "state_loaded",
            {
                "name": request.name,
                "path": str(path),
                "frame": state["frame"],
                "agent_state": agent_state,
            },
        )
        state["agent_state"] = agent_state
        return state

    async def harness_event(self, request: HarnessEventRequest) -> dict[str, Any]:
        session = self._require_session()
        return await session.emit_harness(request)

    def read_trace(self, run_id: str, source: str) -> list[dict[str, Any]]:
        if source not in ("env", "harness"):
            raise HTTPException(status_code=400, detail="source must be env or harness")
        return self.trace_store.read(run_id, source)  # type: ignore[arg-type]

    def frame_thumbnail_bytes(self, run_id: str, frame: int) -> bytes:
        if frame < 0:
            raise HTTPException(status_code=400, detail="frame must be non-negative")
        path = self.trace_store.run_dir(run_id) / "frames" / f"{frame}.png"
        if not path.exists():
            raise HTTPException(status_code=404, detail="frame thumbnail not found")
        return path.read_bytes()

    def list_run_states(self, run_id: str) -> list[dict[str, Any]]:
        run_states_dir = self.states_dir / run_id
        frames_by_name = self._frames_by_save_name(run_id)
        return _list_state_files(run_states_dir, frames_by_name)

    def list_shared_states(self) -> list[dict[str, Any]]:
        return _list_state_files(self.states_dir / "shared", {})

    def list_runs(self) -> list[dict[str, Any]]:
        runs_dir = self.trace_store.runs_dir
        if not runs_dir.exists():
            return []
        active_run_id = self.session.run_id if self.session else None
        out: list[dict[str, Any]] = []
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            env_path = run_dir / "env.jsonl"
            harness_path = run_dir / "harness.jsonl"
            if not env_path.exists() and not harness_path.exists():
                continue
            stat = run_dir.stat()
            out.append({
                "run_id": run_dir.name,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "has_env": env_path.exists(),
                "has_harness": harness_path.exists(),
                "active": run_dir.name == active_run_id,
            })
        out.sort(key=lambda entry: entry["modified_at"], reverse=True)
        return out

    def delete_state(self, run_id: str, name: str) -> None:
        # Reject names outside the safe alphabet up front so we cannot escape the run dir.
        if not all(char.isalnum() or char in ("-", "_") for char in name) or not name:
            raise HTTPException(status_code=422, detail="invalid state name")
        path = self._state_path(run_id, name)
        if not path.exists():
            raise HTTPException(status_code=404, detail="state not found")
        path.unlink()

    def _frames_by_save_name(self, run_id: str) -> dict[str, int]:
        """Best-effort lookup of the frame each save state was written at."""
        try:
            events = self.trace_store.read(run_id, "env")
        except Exception:
            return {}
        latest: dict[str, int] = {}
        for event in events:
            if event.get("type") != "state_saved":
                continue
            payload = event.get("payload") or {}
            name = payload.get("name")
            frame = payload.get("frame") if payload.get("frame") is not None else event.get("frame")
            if isinstance(name, str) and isinstance(frame, int):
                latest[name] = frame
        return latest

    async def _playback_loop(self, session: Session) -> None:
        tick_counts = {"paused": 0, "1x": 1, "5x": 5, "max": 30}
        delays = {"paused": 0.05, "1x": 1 / 60, "5x": 1 / 60, "max": 0.001}
        last_emit = 0.0
        while session.running:
            mode = session.speed_mode
            frames = tick_counts[mode]
            if frames:
                async with session.lock:
                    session.emulator.tick(frames)
                    session.invalidate_screen_cache()
                    frame = session.emulator.frame
                now = asyncio.get_event_loop().time()
                if now - last_emit >= 0.1:
                    await session.emit_env("playback_frame", {"mode": mode, "frame": frame}, trace=False)
                    last_emit = now
            await asyncio.sleep(delays[mode])

    def _state_path(self, run_id: str, name: str) -> Path:
        return self.states_dir / run_id / f"{name}.state"

    def _agent_state_path(self, run_id: str, name: str) -> Path:
        return self.states_dir / run_id / f"{name}.agent.json"

    def read_agent_state(self, run_id: str, name: str) -> dict[str, Any]:
        # Validation mirrors delete_state — keep traversal off-limits.
        if not all(char.isalnum() or char in ("-", "_") for char in name) or not name:
            raise HTTPException(status_code=422, detail="invalid state name")
        sidecar = self._agent_state_path(run_id, name)
        if not sidecar.exists():
            shared = self.states_dir / "shared" / f"{name}.agent.json"
            if not shared.exists():
                raise HTTPException(status_code=404, detail="agent state sidecar not found")
            sidecar = shared
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"malformed sidecar: {exc}")

    def _require_session(self) -> Session:
        if self.session is None:
            raise HTTPException(status_code=404, detail="No active run. Start one with POST /api/run/start.")
        return self.session
