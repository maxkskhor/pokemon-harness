from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from env.emulator import Emulator
from env.models import (
    HarnessEventRequest,
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
    api.state.manager = manager

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

    @api.post("/api/harness/event")
    async def harness_event(request: HarnessEventRequest) -> dict[str, object]:
        return await manager.harness_event(request)

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
