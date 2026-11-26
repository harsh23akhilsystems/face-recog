"""Request bodies for the JSON endpoints (multipart endpoints use FastAPI ``File``/``Form``)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from facegate.config import MatchMode


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    employee_id: str | None = Field(default=None, max_length=64)
    department: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    employee_id: str | None = Field(default=None, max_length=64)
    department: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    active: bool | None = None
    profile_sample_id: str | None = Field(default=None, max_length=64)  # null = automatic (most frontal photo)


class RuntimeSettingsPatch(BaseModel):
    mode: MatchMode | None = None
    fusion_threshold: float | None = Field(default=None, ge=-1, le=1)
    margin: float | None = Field(default=None, ge=0, le=1)
    thresholds: dict[str, float] | None = None
    log_recognitions: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
