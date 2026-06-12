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

from env.agent_manager import AgentProcessManager
from env.emulator import Emulator
from env.harness_registry import HarnessRegistry
from env.emulator import file_sha1, rom_title
from env.models import (
    AgentLaunchRequest,
    HarnessErrorRequest,
    HarnessEventRequest,
    HarnessPlayRequest,
    HarnessRegisterRequest,
    HarnessResumeRequest,
    HarnessStatusRequest,
    PressAction,
    SaveStateRequest,
    SequenceAction,
    SpeedRequest,
    StartRunRequest,
    StepRequest,
)
from env.paths import ROMS_DIR, default_rom_path, list_rom_files
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
    agent_manager = AgentProcessManager()

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
            agent_manager.shutdown()

    api = FastAPI(title="Pokemon Harness Environment", version="0.1.0", lifespan=lifespan)
    api.state.manager = manager
    api.state.harness_registry = harness_registry
    api.state.registry_prune_task = None

    api.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/api/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "active_run": manager.session.run_id if manager.session else None}

    @api.get("/api/roms")
    async def list_roms() -> list[dict[str, Any]]:
        default = default_rom_path()
        out: list[dict[str, Any]] = []
        for path in list_rom_files():
            out.append({
                "filename": path.name,
                "title": rom_title(path),
                "sha1": file_sha1(path),
                "kind": "gba" if path.suffix.lower() == ".gba" else "gb",
                "default": default is not None and path.name == default.name,
            })
        return out

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
                # The UI's Play request may have pinned a ROM for this harness.
                pending_rom = record.get("pending_rom")
                if request.rom_path is None and pending_rom:
                    candidate = ROMS_DIR / pending_rom
                    if candidate.exists():
                        request.rom_path = str(candidate)
        return await manager.start_run(request, agent_info=agent_info)

    @api.post("/api/run/stop")
    async def stop_run() -> dict[str, object]:
        return await manager.stop_run()

    @api.post("/api/run/pause")
    async def pause_run() -> dict[str, object]:
        return await manager.pause_run()

    @api.post("/api/run/resume")
    async def resume_run() -> dict[str, object]:
        return await manager.resume_run()

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
    async def harness_play(
        harness_id: str, request: HarnessPlayRequest = HarnessPlayRequest()
    ) -> dict[str, Any]:
        if request.rom is not None:
            rom_path = ROMS_DIR / request.rom
            if rom_path.parent != ROMS_DIR or not rom_path.exists():
                raise HTTPException(status_code=404, detail=f"ROM not found: {request.rom}")
        try:
            harness_registry.update(
                harness_id, status="running", error=None, pending_rom=request.rom
            )
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

    @api.post("/api/harness/{harness_id}/resume_run")
    async def harness_resume_run(
        harness_id: str, request: HarnessResumeRequest
    ) -> dict[str, Any]:
        # Resolve harness from registry.
        records = {r["id"]: r for r in harness_registry.list()}
        record = records.get(harness_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Harness not found")
        if record.get("status") == "running":
            raise HTTPException(
                status_code=409,
                detail="Harness is already running. Stop it before resuming a past run.",
            )

        # Validate source run's recorded agent matches this harness.
        source_meta = manager._load_meta(request.source_run_id)
        if source_meta is None:
            raise HTTPException(status_code=404, detail="source run not found")
        source_agent = (source_meta.get("agent") or {}) if isinstance(source_meta.get("agent"), dict) else {}
        source_agent_name = source_agent.get("name")
        if source_agent_name and source_agent_name != record.get("name"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Selected harness '{record.get('name')}' does not match the source run's "
                    f"agent '{source_agent_name}'. Connect the matching agent to resume."
                ),
            )

        agent_info = {
            "harness_id": harness_id,
            "name": record.get("name"),
            "model": record.get("model"),
            "metadata": record.get("metadata") or {},
        }
        # Mint a fresh branched run_id based on the harness name (mirrors PokemonAgent._new_run_id).
        import uuid as _uuid
        agent_name_for_id = (record.get("name") or "agent").lower().replace(" ", "-")
        new_run_id = f"{agent_name_for_id}-{_uuid.uuid4().hex[:8]}"

        result = await manager.resume_from_checkpoint(
            source_run_id=request.source_run_id,
            checkpoint_name=request.checkpoint_name,
            agent_info=agent_info,
            new_run_id=new_run_id,
        )
        # Wake the agent with a command carrying the new + source run + checkpoint name.
        harness_registry.update(harness_id, status="running", error=None)
        harness_registry.enqueue(
            harness_id,
            f"resume_run:{new_run_id}:{request.source_run_id}:{request.checkpoint_name}",
        )
        return {"ok": True, **result}

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

    @api.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        """agents.yaml definitions merged with live harness registrations."""
        # Newest-first so a freshly relaunched agent wins over a stale record
        # left behind by a killed process.
        harnesses = sorted(
            harness_registry.list(),
            key=lambda h: h.get("last_seen_at") or "",
            reverse=True,
        )
        out = []
        for entry in agent_manager.list():
            match = next(
                (h for h in harnesses if (h.get("metadata") or {}).get("agent_key") == entry["name"]),
                None,
            )
            out.append({**entry, "harness": match})
        return out

    @api.post("/api/agents/{name}/launch")
    async def launch_agent(name: str, request: AgentLaunchRequest = AgentLaunchRequest()) -> dict[str, Any]:
        try:
            return agent_manager.launch(name, model=request.model)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"No agent named '{name}' in agents.yaml")

    @api.post("/api/agents/{name}/terminate")
    async def terminate_agent(name: str) -> dict[str, Any]:
        return {"terminated": agent_manager.terminate(name)}

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
