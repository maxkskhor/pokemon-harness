from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from env.trace import ensure_safe_name


Button = Literal["A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT"]
SpeedMode = Literal["paused", "1x", "5x", "max"]


class StartRunRequest(BaseModel):
    run_id: str | None = Field(default=None, min_length=1, max_length=80)
    rom_path: str | None = None
    sym_path: str | None = None
    harness_id: str | None = Field(default=None, max_length=80)
    start_state: str | None = Field(default=None, max_length=80)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_safe_name(value, "run_id")


class PressAction(BaseModel):
    button: Button
    frames: int = Field(default=8, ge=1, le=600)
    turn_id: str | None = Field(default=None, max_length=80)


class SequenceStep(BaseModel):
    type: Literal["press", "wait"]
    button: Button | None = None
    frames: int = Field(default=8, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_button(self) -> "SequenceStep":
        if self.type == "press" and self.button is None:
            raise ValueError("press steps require a button")
        return self


class SequenceAction(BaseModel):
    steps: list[SequenceStep] = Field(min_length=1, max_length=500)
    turn_id: str | None = Field(default=None, max_length=80)


class StepRequest(BaseModel):
    frames: int = Field(ge=1, le=3600)
    turn_id: str | None = Field(default=None, max_length=80)


class SpeedRequest(BaseModel):
    mode: SpeedMode


class SaveStateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # Optional agent-side state (e.g. LLM message history) to persist alongside the
    # emulator snapshot. Stored as <name>.agent.json next to <name>.state and returned
    # by load_state so the agent can restore its own context on rewind.
    agent_state: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return ensure_safe_name(value, "state name")


class HarnessEventRequest(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    turn_id: str | None = Field(default=None, max_length=80)
    frame: int | None = Field(default=None, ge=0)
    harness_id: str | None = Field(default=None, max_length=80)


class HarnessRegisterRequest(BaseModel):
    name: str = Field(default="Harness", min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] | None = None


class HarnessStatusRequest(BaseModel):
    status: Literal["idle", "starting", "running", "stopping", "error", "disconnected"] = Field(min_length=1, max_length=20)


class HarnessErrorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class HarnessResumeRequest(BaseModel):
    source_run_id: str = Field(min_length=1, max_length=80)
    checkpoint_name: str = Field(default="_auto_resume", min_length=1, max_length=80)

    @field_validator("source_run_id")
    @classmethod
    def validate_source_run_id(cls, value: str) -> str:
        return ensure_safe_name(value, "source_run_id")

    @field_validator("checkpoint_name")
    @classmethod
    def validate_checkpoint_name(cls, value: str) -> str:
        return ensure_safe_name(value, "checkpoint_name")
