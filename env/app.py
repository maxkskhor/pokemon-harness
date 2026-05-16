from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from env.emulator import Emulator
from env.models import (
    HarnessErrorRequest,
    HarnessEventRequest,
    HarnessRegisterRequest,
    HarnessStatusRequest,
    PressAction,
    SaveStateRequest,
    SequenceAction,
    SpeedRequest,
    StartRunRequest,
    StepRequest,
)
from env.runtime import RuntimeManager
from env.trace import TraceStore


def create_app(
    emulator_factory: Callable[[Path, Path | None], Emulator] | None = None,
    trace_store: TraceStore | None = None,
    states_dir: Path | None = None,
) -> FastAPI:
    manager_kwargs = {}
    if emulator_factory:
        manager_kwargs["emulator_factory"] = emulator_factory
    if trace_store:
        manager_kwargs["trace_store"] = trace_store
    if states_dir:
        manager_kwargs["states_dir"] = states_dir
    manager = RuntimeManager(**manager_kwargs)
    api = FastAPI(title="Pokemon Harness Environment", version="0.1.0")

    harness_registry: dict[str, dict[str, Any]] = {}
    harness_commands: dict[str, str | None] = {}
    api.state.manager = manager

    def touch_harness(harness_id: str, **updates: Any) -> None:
        harness_registry[harness_id].update(updates)
        harness_registry[harness_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    api.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/api/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "active_run": manager.session.run_id if manager.session else None}

    @api.post("/api/run/start")
    async def start_run(request: StartRunRequest = StartRunRequest()) -> dict[str, object]:
        return await manager.start_run(request)

    @api.post("/api/run/stop")
    async def stop_run() -> dict[str, object]:
        return await manager.stop_run()

    @api.get("/api/state")
    async def state() -> dict[str, object]:
        return await manager.state()

    @api.get("/api/screenshot.png")
    async def screenshot() -> Response:
        return Response(content=await manager.screenshot_png(), media_type="image/png")

    @api.post("/api/action/press")
    async def press(request: PressAction) -> dict[str, object]:
        return await manager.press(request)

    @api.post("/api/action/sequence")
    async def sequence(request: SequenceAction) -> dict[str, object]:
        return await manager.sequence(request)

    @api.post("/api/step")
    async def step(request: StepRequest) -> dict[str, object]:
        return await manager.step(request)

    @api.post("/api/speed")
    async def speed(request: SpeedRequest) -> dict[str, object]:
        return await manager.set_speed(request.mode)

    @api.post("/api/save-state")
    async def save_state(request: SaveStateRequest) -> dict[str, object]:
        return await manager.save_state(request)

    @api.post("/api/load-state")
    async def load_state(request: SaveStateRequest) -> dict[str, object]:
        return await manager.load_state(request)

    @api.post("/api/harness/register")
    async def harness_register(request: HarnessRegisterRequest) -> dict[str, Any]:
        hid = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat()
        harness_registry[hid] = {
            "id": hid,
            "name": request.name,
            "status": "idle",
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        harness_commands[hid] = None
        return {"id": hid}

    @api.get("/api/harness/list")
    async def harness_list() -> list[dict[str, Any]]:
        return list(harness_registry.values())

    @api.post("/api/harness/event")
    async def harness_event(request: HarnessEventRequest) -> dict[str, object]:
        return await manager.harness_event(request)

    @api.post("/api/harness/{harness_id}/play")
    async def harness_play(harness_id: str) -> dict[str, Any]:
        if harness_id not in harness_registry:
            raise HTTPException(status_code=404, detail="Harness not found")
        touch_harness(harness_id, status="running", error=None)
        harness_commands[harness_id] = "play"
        return {"ok": True}

    @api.post("/api/harness/{harness_id}/stop")
    async def harness_stop_cmd(harness_id: str) -> dict[str, Any]:
        if harness_id not in harness_registry:
            raise HTTPException(status_code=404, detail="Harness not found")
        touch_harness(harness_id, status="stopping")
        harness_commands[harness_id] = "stop"
        return {"ok": True}

    @api.get("/api/harness/{harness_id}/poll")
    async def harness_poll(harness_id: str) -> dict[str, Any]:
        if harness_id not in harness_registry:
            raise HTTPException(status_code=404, detail="Harness not found")
        cmd = harness_commands.get(harness_id)
        if cmd:
            harness_commands[harness_id] = None
        return {"command": cmd}

    @api.post("/api/harness/{harness_id}/status")
    async def harness_status_update(harness_id: str, request: HarnessStatusRequest) -> dict[str, Any]:
        if harness_id not in harness_registry:
            raise HTTPException(status_code=404, detail="Harness not found")
        touch_harness(harness_id, status=request.status)
        return {"ok": True}

    @api.post("/api/harness/{harness_id}/error")
    async def harness_error_update(harness_id: str, request: HarnessErrorRequest) -> dict[str, Any]:
        if harness_id not in harness_registry:
            raise HTTPException(status_code=404, detail="Harness not found")
        touch_harness(harness_id, error=request.message, status="error")
        return {"ok": True}

    @api.post("/api/harness/{harness_id}/unregister")
    async def harness_unregister(harness_id: str) -> dict[str, Any]:
        harness_registry.pop(harness_id, None)
        harness_commands.pop(harness_id, None)
        return {"ok": True}

    @api.get("/api/runs/{run_id}/env-trace")
    async def env_trace(run_id: str) -> list[dict[str, object]]:
        return manager.read_trace(run_id, "env")

    @api.get("/api/runs/{run_id}/harness-trace")
    async def harness_trace(run_id: str) -> list[dict[str, object]]:
        return manager.read_trace(run_id, "harness")

    @api.websocket("/ws/events")
    async def events(websocket: WebSocket) -> None:
        await manager.broker.connect(websocket)

    return api


app = create_app()
