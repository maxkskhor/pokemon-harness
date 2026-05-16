from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Button = Literal["A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT"]
SpeedMode = Literal["paused", "1x", "5x", "max"]


class StartRunRequest(BaseModel):
    run_id: str | None = Field(default=None, min_length=1, max_length=80)
    rom_path: str | None = None
    sym_path: str | None = None

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not all(char.isalnum() or char in ("-", "_") for char in value):
            raise ValueError("run_id may only contain letters, numbers, hyphen, and underscore")
        return value


class PressAction(BaseModel):
    button: Button
    frames: int = Field(default=8, ge=1, le=600)


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


class StepRequest(BaseModel):
    frames: int = Field(ge=1, le=3600)


class SpeedRequest(BaseModel):
    mode: SpeedMode


class SaveStateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not all(char.isalnum() or char in ("-", "_") for char in value):
            raise ValueError("state name may only contain letters, numbers, hyphen, and underscore")
        return value


class HarnessEventRequest(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    turn_id: str | None = Field(default=None, max_length=80)
    frame: int | None = Field(default=None, ge=0)


class HarnessRegisterRequest(BaseModel):
    name: str = Field(default="Harness", min_length=1, max_length=80)


class HarnessStatusRequest(BaseModel):
    status: Literal["idle", "starting", "running", "stopping", "error"] = Field(min_length=1, max_length=20)


class HarnessErrorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
