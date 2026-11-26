"""Detect → align → embed with every enabled recognizer.

The pipeline is the only object that owns ONNX sessions. It degrades gracefully: a missing
recognizer file disables that model (reported by ``status()``) rather than crashing the API,
so the console can tell an operator exactly which file to add.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Protocol

import cv2
import numpy as np

from facegate.config import Settings
from facegate.vision.align import face_sharpness, norm_crop, sharpness
from facegate.vision.types import Face

log = logging.getLogger(__name__)


class Detector(Protocol):
    def detect(self, img_bgr: np.ndarray, max_side: int | None = None) -> list[Face]: ...


class Recognizer(Protocol):
    name: str

    def embed(self, crops_bgr: list[np.ndarray]) -> np.ndarray: ...


@dataclass
class ModelStatus:
    name: str
    role: str  # detector | recognizer
    file: str
    loaded: bool
    enabled: bool
    error: str | None = None
    providers: list[str] = field(default_factory=list)


class FacePipeline:
    def __init__(self, detector: Detector | None, recognizers: dict[str, Recognizer], status: list[ModelStatus]):
        self.detector = detector
        self.recognizers = recognizers
        self._status = status
        # ONNX Runtime sessions are thread-safe, but we serialise to keep CPU latency predictable
        # under concurrent webcam streams instead of oversubscribing cores.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_settings(cls, settings: Settings) -> FacePipeline:
        from facegate.vision.detector import SCRFDDetector
        from facegate.vision.recognizer import RECOGNIZER_TYPES

        status: list[ModelStatus] = []
        providers, threads = settings.runtime.providers, settings.runtime.intra_op_threads
        det_cfg = settings.detector
        detector = None
        try:
            detector = SCRFDDetector(
                settings.models_dir / det_cfg.file,
                providers,
                input_size=det_cfg.input_size,
                score_threshold=det_cfg.score_threshold,
                nms_threshold=det_cfg.nms_threshold,
                max_faces=det_cfg.max_faces,
                intra_op_threads=threads,
            )
            status.append(ModelStatus("scrfd", "detector", det_cfg.file, True, True, providers=detector.providers))
        except Exception as exc:  # noqa: BLE001 - surface any load failure to the console
            log.warning("Detector unavailable: %s", exc)
            status.append(ModelStatus("scrfd", "detector", det_cfg.file, False, True, error=str(exc)))

        recognizers: dict[str, Recognizer] = {}
        for name, cfg in settings.recognizers.items():
            if not cfg.enabled:
                status.append(ModelStatus(name, "recognizer", cfg.file, False, False))
                continue
            klass = RECOGNIZER_TYPES.get(name)
            if klass is None:
                status.append(ModelStatus(name, "recognizer", cfg.file, False, True, error="Unknown recognizer type"))
                continue
            try:
                rec = klass(name, settings.models_dir / cfg.file, providers, cfg.channel_order, threads)
                recognizers[name] = rec
                status.append(ModelStatus(name, "recognizer", cfg.file, True, True, providers=rec.providers))
            except Exception as exc:  # noqa: BLE001
                log.warning("Recognizer %s unavailable: %s", name, exc)
                status.append(ModelStatus(name, "recognizer", cfg.file, False, True, error=str(exc)))
        return cls(detector, recognizers, status)

    # ------------------------------------------------------------------ introspection
    def status(self) -> list[ModelStatus]:
        return list(self._status)

    @property
    def ready(self) -> bool:
        return self.detector is not None and bool(self.recognizers)

    @property
    def model_names(self) -> list[str]:
        return list(self.recognizers)

    # ------------------------------------------------------------------ inference
    def detect(self, img_bgr: np.ndarray, quality: bool = False, max_side: int | None = None) -> list[Face]:
        """Detect faces; with ``quality`` also attach the aligned crop and its sharpness (cheap, no embeddings).
        ``max_side`` runs the detector at a smaller input (faster, for close-up faces such as guided capture)."""
        if self.detector is None:
            raise RuntimeError("Face detector is not loaded")
        with self._lock:
            faces = self.detector.detect(img_bgr, max_side) if max_side else self.detector.detect(img_bgr)
        if quality:
            for face in faces:
                face.crop = norm_crop(img_bgr, face.kps)
                face.sharpness = sharpness(face.crop)
                face.face_sharpness = face_sharpness(img_bgr, face.kps)
        return faces

    def analyze(self, img_bgr: np.ndarray, max_faces: int | None = None) -> list[Face]:
        """Detect faces and attach aligned crops, sharpness and one embedding per recognizer."""
        if not self.ready:
            raise RuntimeError("Pipeline is not ready: detector and at least one recognizer are required")
        with self._lock:
            faces = self.detector.detect(img_bgr)  # type: ignore[union-attr]
            if max_faces is not None:
                faces = faces[:max_faces]
            if not faces:
                return []
            crops = [norm_crop(img_bgr, f.kps) for f in faces]
            for face, crop in zip(faces, crops, strict=True):
                face.crop = crop
                face.sharpness = sharpness(crop)
            for name, rec in self.recognizers.items():
                embs = rec.embed(crops)
                for face, emb in zip(faces, embs, strict=True):
                    face.embeddings[name] = emb
        return faces


def decode_image(data: bytes) -> np.ndarray:
    """Decode uploaded bytes (JPEG/PNG/WebP/BMP) to BGR, honouring nothing but pixels."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image; upload a JPEG, PNG, WebP or BMP file")
    return img


def encode_jpeg(img_bgr: np.ndarray, quality: int = 90) -> bytes:
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()
