"""Typed configuration loaded from ``configs/config.yaml``.

Why a typed layer: the YAML is edited by operators, so typos must fail loudly at startup
(pydantic validation) instead of surfacing as a ``KeyError`` mid-request. Tests point
``FG_CONFIG`` / ``FG_ROOT`` at temporary files so they never touch real data.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MatchMode = Literal["arcface", "adaface", "fusion", "strict"]


class AppCfg(BaseModel):
    name: str = "FaceGate"
    organisation: str = "Your Company"
    host: str = "0.0.0.0"
    port: int = 8100


class PathsCfg(BaseModel):
    models_dir: str = "models"
    data_dir: str = "data"
    database: str = "data/facegate.db"
    runtime_settings: str = "data/settings.json"


class RuntimeCfg(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["CPUExecutionProvider"])
    intra_op_threads: int = 0


class DetectorCfg(BaseModel):
    name: str = "scrfd"
    file: str = "det_10g.onnx"
    input_size: tuple[int, int] = (640, 640)
    score_threshold: float = 0.5
    nms_threshold: float = 0.4
    max_faces: int = 20


class RecognizerCfg(BaseModel):
    enabled: bool = True
    file: str
    channel_order: Literal["auto", "rgb", "bgr"] = "auto"
    threshold: float = 0.30


class MatchingCfg(BaseModel):
    mode: MatchMode = "fusion"
    fusion_threshold: float = 0.30
    margin: float = 0.05
    aggregate: Literal["max", "mean"] = "max"


class EnrollmentCfg(BaseModel):
    min_face_px: int = 80
    min_det_score: float = 0.70
    min_sharpness: float = 40.0
    max_samples_per_person: int = 20
    duplicate_threshold: float = 0.55
    store_thumbnails: bool = True


class EventsCfg(BaseModel):
    log_recognitions: bool = True
    cooldown_seconds: int = 60
    retention_days: int = 90
    log_unknown: bool = True


class ApiCfg(BaseModel):
    max_upload_mb: int = 8
    cors_origins: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    app: AppCfg = Field(default_factory=AppCfg)
    paths: PathsCfg = Field(default_factory=PathsCfg)
    runtime: RuntimeCfg = Field(default_factory=RuntimeCfg)
    detector: DetectorCfg = Field(default_factory=DetectorCfg)
    recognizers: dict[str, RecognizerCfg] = Field(default_factory=dict)
    matching: MatchingCfg = Field(default_factory=MatchingCfg)
    enrollment: EnrollmentCfg = Field(default_factory=EnrollmentCfg)
    events: EventsCfg = Field(default_factory=EventsCfg)
    api: ApiCfg = Field(default_factory=ApiCfg)

    # Resolved at load time, not read from YAML.
    root: Path = PROJECT_ROOT

    def path(self, rel: str) -> Path:
        """Resolve a config path relative to the project root (absolute paths pass through)."""
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    @property
    def models_dir(self) -> Path:
        return self.path(self.paths.models_dir)

    @property
    def database_path(self) -> Path:
        return self.path(self.paths.database)

    @property
    def runtime_settings_path(self) -> Path:
        return self.path(self.paths.runtime_settings)


def load_settings(config_path: str | Path | None = None) -> Settings:
    root = Path(os.environ.get("FG_ROOT", PROJECT_ROOT))
    path = Path(config_path or os.environ.get("FG_CONFIG", root / "configs" / "config.yaml"))
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    settings = Settings.model_validate(raw or {})
    settings.root = root
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
