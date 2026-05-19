from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.websockets import WebSocketDisconnect

from env.emulator import Emulator
from env.harness_registry import HarnessRegistry
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


__all__ = ["create_app", "app"]


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
    harness_registry = HarnessRegistry(storage_path=manager.trace_store.runs_dir / "registry.json")

    async def prune_harness_registry() -> None:
        while True:
            harness_registry.prune_stale(disconnect_after_s=30, prune_after_s=300)
            await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(api: FastAPI):
        task = asyncio.create_task(prune_harness_registry())
        api.state.registry_prune_task = task
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    api = FastAPI(title="Pokemon Harness Environment", version="0.1.0", lifespan=lifespan)
    api.state.manager = manager
    api.state.harness_registry = harness_registry
    api.state.registry_prune_task = None

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
        agent_info: dict[str, Any] | None = None
        if request.harness_id:
            records = {r["id"]: r for r in harness_registry.list()}
            record = records.get(request.harness_id)
            if record:
                agent_info = {
                    "harness_id": request.harness_id,
                    "name": record.get("name"),
                    "model": record.get("model"),
                    "metadata": record.get("metadata") or {},
                }
        return await manager.start_run(request, agent_info=agent_info)

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
        result = await manager.load_state(request)
        # Notify any running harnesses so they can restore their own agent-side state
        # (e.g. LLM message history) from the .agent.json sidecar via the GET endpoint
        # below. The triggering agent dedupes echoes inside PokemonAgent.load_state.
        if result.get("agent_state") is not None:
            for record in harness_registry.list():
                if record["status"] == "running":
                    try:
                        harness_registry.enqueue(record["id"], f"load_state:{request.name}")
                    except KeyError:
                        pass
        return result

    @api.get("/api/runs/{run_id}/states/{name}/agent")
    async def read_agent_state(run_id: str, name: str) -> dict[str, Any]:
        return manager.read_agent_state(run_id, name)

    @api.post("/api/harness/register")
    async def harness_register(request: HarnessRegisterRequest) -> dict[str, Any]:
        return {"id": harness_registry.register(request.name, model=request.model, metadata=request.metadata)}

    @api.get("/api/harness/list")
    async def harness_list() -> list[dict[str, Any]]:
        return harness_registry.list()

    @api.post("/api/harness/event")
    async def harness_event(request: HarnessEventRequest) -> dict[str, object]:
        if request.harness_id is not None:
            try:
                harness_registry.touch(request.harness_id)
            except KeyError:
                pass
        return await manager.harness_event(request)

    @api.post("/api/harness/{harness_id}/play")
    async def harness_play(harness_id: str) -> dict[str, Any]:
        try:
            harness_registry.update(harness_id, status="running", error=None)
            harness_registry.enqueue(harness_id, "play")
        except KeyError:
            raise HTTPException(status_code=404, detail="Harness not found")
        return {"ok": True}

    @api.post("/api/harness/{harness_id}/stop")
    async def harness_stop_cmd(harness_id: str) -> dict[str, Any]:
        try:
            harness_registry.update(harness_id, status="stopping")
            harness_registry.enqueue(harness_id, "stop")
        except KeyError:
            raise HTTPException(status_code=404, detail="Harness not found")
        return {"ok": True}

    @api.post("/api/harness/{harness_id}/reset")
    async def harness_reset_cmd(harness_id: str) -> dict[str, Any]:
        try:
            harness_registry.enqueue(harness_id, "reset")
        except KeyError:
            raise HTTPException(status_code=404, detail="Harness not found")
        return {"ok": True}

    @api.get("/api/harness/{harness_id}/poll")
    async def harness_poll(harness_id: str) -> dict[str, Any]:
        try:
            cmd = harness_registry.poll(harness_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Harness not found")
        return {"command": cmd}

    @api.post("/api/harness/{harness_id}/status")
    async def harness_status_update(harness_id: str, request: HarnessStatusRequest) -> dict[str, Any]:
        try:
            harness_registry.update(harness_id, status=request.status)
        except KeyError:
            raise HTTPException(status_code=404, detail="Harness not found")
        return {"ok": True}

    @api.post("/api/harness/{harness_id}/error")
    async def harness_error_update(harness_id: str, request: HarnessErrorRequest) -> dict[str, Any]:
        try:
            harness_registry.update(harness_id, error=request.message, status="error")
        except KeyError:
            raise HTTPException(status_code=404, detail="Harness not found")
        return {"ok": True}

    @api.post("/api/harness/{harness_id}/unregister")
    async def harness_unregister(harness_id: str) -> dict[str, Any]:
        harness_registry.unregister(harness_id)
        return {"ok": True}

    @api.get("/api/runs")
    async def list_runs() -> list[dict[str, Any]]:
        return manager.list_runs()

    @api.get("/api/runs/{run_id}/env-trace")
    async def env_trace(
        run_id: str,
        since_timestamp: str | None = None,
        limit: int | None = Query(default=None, ge=1, le=5000),
    ) -> list[dict[str, object]]:
        return manager.read_trace(run_id, "env", since_timestamp=since_timestamp, limit=limit)

    @api.get("/api/runs/{run_id}/harness-trace")
    async def harness_trace(
        run_id: str,
        since_timestamp: str | None = None,
        limit: int | None = Query(default=None, ge=1, le=5000),
    ) -> list[dict[str, object]]:
        return manager.read_trace(run_id, "harness", since_timestamp=since_timestamp, limit=limit)

    @api.get("/api/runs/{run_id}/frames")
    async def list_frames(run_id: str) -> list[int]:
        return manager.list_frames(run_id)

    @api.get("/api/runs/{run_id}/frames/{frame}.png")
    async def frame_thumbnail(run_id: str, frame: int) -> Response:
        return Response(content=manager.frame_thumbnail_bytes(run_id, frame), media_type="image/png")

    @api.get("/api/runs/{run_id}/states")
    async def list_run_states(run_id: str) -> list[dict[str, Any]]:
        return manager.list_run_states(run_id)

    @api.get("/api/states/shared")
    async def list_shared_states() -> list[dict[str, Any]]:
        return manager.list_shared_states()

    @api.delete("/api/runs/{run_id}/states/{name}")
    async def delete_state(run_id: str, name: str) -> dict[str, Any]:
        manager.delete_state(run_id, name)
        return {"ok": True}

    @api.websocket("/ws/events")
    async def events(websocket: WebSocket) -> None:
        await manager.broker.connect(websocket)

    @api.websocket("/api/harness/{harness_id}/control")
    async def harness_control(websocket: WebSocket, harness_id: str) -> None:
        """Push commands (play / stop / load_state:<name>) to an agent in real time.

        The HTTP `/poll` endpoint is kept for backwards compatibility; the WS uses the
        same FIFO queue as the backstop, so commands enqueued before the agent
        connects are delivered on connect.
        """
        try:
            harness_registry.require(harness_id)
        except KeyError:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        last_touch = asyncio.get_event_loop().time()
        try:
            while True:
                # Drain anything already queued and push it.
                cmd = harness_registry.poll(harness_id)
                if cmd is not None:
                    await websocket.send_json({"command": cmd})
                    continue
                # Nothing to send — re-check that the harness is still registered, then
                # yield. 50 ms keeps the loop cheap (no client traffic) and snappy.
                # A per-harness asyncio.Event signalled from enqueue() would drop push
                # latency to ~0 ms but requires cross-thread plumbing; not worth it yet.
                if not harness_registry.has(harness_id):
                    break
                now = asyncio.get_event_loop().time()
                if now - last_touch >= 5:
                    harness_registry.touch(harness_id)
                    last_touch = now
                await asyncio.sleep(0.05)
        except WebSocketDisconnect:
            pass
        except Exception:  # pragma: no cover — defensive
            logging.getLogger("pokemon_harness.control_ws").exception(
                "harness control websocket failed harness_id=%s", harness_id
            )

    return api


app = create_app()
