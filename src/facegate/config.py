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


class GuidedStepCfg(BaseModel):
    """One pose in guided capture. Ranges are inclusive [min, max]; ``None`` means "not checked".

    yaw ≈ sin(angle), positive = person turned to *their* left. pitch is relative to the person's own
    frontal capture, negative = chin up (see ``vision.align.head_pose``).
    """

    key: str
    prompt: str
    hint: Literal["center", "left", "right", "up", "down"] = "center"
    yaw: tuple[float, float] | None = None
    pitch: tuple[float, float] | None = None


def _default_steps() -> list[GuidedStepCfg]:
    s = GuidedStepCfg
    return [
        s(key="front", prompt="Look straight at the camera", yaw=(-0.15, 0.15)),
        s(key="left_slight", prompt="Turn slightly to your left", hint="left", yaw=(0.12, 0.30), pitch=(-0.15, 0.15)),
        s(key="left", prompt="Keep turning to your left", hint="left", yaw=(0.30, 0.85), pitch=(-0.18, 0.18)),
        s(key="right_slight", prompt="Turn slightly to your right", hint="right", yaw=(-0.3, -0.12), pitch=(-.15, .15)),
        s(key="right", prompt="Keep turning to your right", hint="right", yaw=(-0.85, -0.30), pitch=(-0.18, 0.18)),
        s(key="up", prompt="Look straight, then tilt your chin up", hint="up", yaw=(-0.25, 0.25), pitch=(-1.0, -0.05)),
        s(key="down", prompt="Now tilt your chin down", hint="down", yaw=(-0.25, 0.25), pitch=(0.05, 1.0)),
    ]


def _default_phase_prompts() -> dict[str, str]:
    return {
        "center": "Look straight at the camera",
        "left": "Slowly turn your head to your left",
        "right": "Now slowly turn your head to your right",
        "up": "Look straight, and tilt your chin up",
        "down": "Now tilt your chin down",
    }


class GuidedCaptureCfg(BaseModel):
    """Video scan: the console watches the live video while a voice walks the person through one phase per
    direction (center, left, right, up, down). Every analysed frame competes for each pose step whose range it
    falls in; the best-quality frame per step is kept and enrolled at the end — nobody has to hold still."""

    auto_start_for_new_person: bool = True
    auto_submit: bool = True
    voice: bool = True  # spoken instructions (browser speech synthesis); the console has a mute toggle
    capture_max_side: int = Field(default=1280, ge=320)
    detect_size: int = Field(default=384, ge=96, le=1280)
    best_window_ms: int = Field(default=800, ge=0)  # keep looking for a sharper frame this long after a phase fills
    max_motion: float = Field(default=0.06, gt=0)  # head movement per 100 ms above which a frame is too blurry to use
    # Face-thumbnail change per 100 ms (32×32 grey, 0..1) at which a frame's score halves; > 3× is never used.
    # Measured: still head ≈ 0.008–0.010, slow drift ≈ 0.016, moving ≈ 0.04, turning ≈ 0.08.
    still_diff: float = Field(default=0.012, gt=0)
    remind_ms: int = Field(default=4000, ge=1000)  # repeat the spoken instruction while a direction is unfinished
    max_center_offset: float = Field(default=0.22, ge=0, le=0.5)
    phase_prompts: dict[str, str] = Field(default_factory=_default_phase_prompts)
    # Default on-screen guide (console lets each browser switch while the styles are being compared):
    # dot | hold | faceid | avatar | points — see frontend/assets/js/guide-styles.js
    guide_style: Literal["dot", "hold", "faceid", "avatar", "points"] = "dot"
    # Lottie JSON under frontend/assets/ (empty string = off). Missing files are skipped by the console.
    animations: dict[str, str] = Field(
        default_factory=lambda: {"intro": "anim/face-scan.json", "success": "anim/success.json"}
    )
    intro_ms: int = Field(default=2500, ge=0)  # how long the intro animation plays (once per browser session)
    steps: list[GuidedStepCfg] = Field(default_factory=_default_steps, min_length=1)


class EnrollmentCfg(BaseModel):
    min_face_px: int = 80
    min_det_score: float = 0.70
    min_sharpness: float = 40.0
    max_samples_per_person: int = 20
    duplicate_threshold: float = 0.55
    store_thumbnails: bool = True
    guided: GuidedCaptureCfg = Field(default_factory=GuidedCaptureCfg)


class EventsCfg(BaseModel):
    log_recognitions: bool = True
    cooldown_seconds: int = 60
    retention_days: int = 90
    log_unknown: bool = True


class ApiCfg(BaseModel):
    max_upload_mb: int = 8
    cors_origins: list[str] = Field(default_factory=list)


class QualityCfg(BaseModel):
    """Live-camera checks run before a face-login attempt (and by the login page every ~600 ms)."""

    min_det_score: float = 0.60  # SCRFD confidence to count a face at all
    good_det_score: float = 0.75  # below this the face is "unclear"
    min_face_frac: float = 0.18  # face width / image width
    max_face_frac: float = 0.80
    min_face_px: int = 80
    max_center_offset: float = 0.30  # face centre distance from image centre, as a fraction of the size
    min_sharpness: float = 40.0  # variance of Laplacian on the grey face box
    min_brightness: float = 60.0  # mean grey level on the face box (0-255)
    max_brightness: float = 210.0
    max_yaw: float = 0.25  # nose offset from the eye midpoint / eye distance
    max_roll_deg: float = 15.0  # eye-line tilt


class LivenessCfg(BaseModel):
    """Passive anti-spoof (MiniFAS ONNX). A missing file disables the check; it never blocks startup."""

    mode: Literal["enforce", "log", "off"] = "enforce"
    file: str = "face_antispoof_minifas_int8.onnx"
    threshold: float = 0.0  # minimum (real - spoof) logit difference; 0.0 = probability 0.5


class AuthCfg(BaseModel):
    session_hours: int = 8
    cookie_name: str = "fg_session"
    cookie_secure: bool = False  # set true behind HTTPS so the session cookie is never sent in clear text
    password_min_length: int = 8
    password_iterations: int = 600_000  # PBKDF2-SHA256
    max_failed_per_user: int = 5  # password failures per username ...
    max_failed_face_per_client: int = 10  # ... or face failures per client IP ...
    lock_window_minutes: int = 15  # ... within this window lock further attempts
    face_login: bool = True
    face_mode: MatchMode = "strict"  # matching mode for sign-in; strict = every loaded model must agree
    detect_size: tuple[int, int] = (640, 640)  # SCRFD input for sign-in frames; (320, 320) is ~4x faster
    quality: QualityCfg = Field(default_factory=QualityCfg)
    liveness: LivenessCfg = Field(default_factory=LivenessCfg)


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
    auth: AuthCfg = Field(default_factory=AuthCfg)

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
    def data_dir(self) -> Path:
        return self.path(self.paths.data_dir)

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
