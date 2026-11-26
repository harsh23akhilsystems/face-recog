"""Test fixtures: a fake pipeline so service/API/matcher logic is tested without ONNX weights.

Synthetic "photos" encode identity in pixel values: ``face_image(identity, variant)`` produces an
image whose fake embedding is close to that identity's prototype (variant adds small noise).
Tests use a temp config/db via ``FG_CONFIG`` / ``FG_ROOT`` and never touch ``data/``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient

from facegate.config import load_settings
from facegate.gallery.store import GalleryStore
from facegate.service import FaceService
from facegate.vision.pipeline import FacePipeline, ModelStatus
from facegate.vision.recognizer import l2_normalize
from facegate.vision.types import Face

DIM = 64


def prototype(model: str, identity: int) -> np.ndarray:
    rng = np.random.default_rng(identity * 1000 + (0 if model == "arcface" else 1))
    return l2_normalize(rng.normal(size=DIM)).astype(np.float32)


def face_image(identity: int, variant: int = 0, faces: int = 1, size: int = 200) -> np.ndarray:
    """Encode (identity, variant, n_faces) in the top-left pixels; identity 0 means 'no face'."""
    img = np.full((size, size, 3), 128, dtype=np.uint8)
    img[0, 0] = (identity, variant, faces)
    return img


class FakeDetector:
    def detect(self, img: np.ndarray, input_size=None, max_side: int | None = None) -> list[Face]:
        identity, _, n = (int(v) for v in img[0, 0])
        if identity == 0:
            return []
        out = []
        for i in range(n):
            side = 150 - i * 20
            bbox = np.array([10, 10, 10 + side, 10 + side], dtype=np.float32)
            kps = np.array([[50, 60], [100, 60], [75, 90], [55, 120], [95, 120]], dtype=np.float32)
            out.append(Face(bbox=bbox, score=0.95, kps=kps))
        return out


class FakeRecognizer:
    def __init__(self, name: str) -> None:
        self.name = name

    def embed(self, crops):  # not used: FakePipeline.analyze fills embeddings directly
        return np.stack([prototype(self.name, 1) for _ in crops])


class FakePipeline(FacePipeline):
    def __init__(self, models=("arcface", "adaface")):
        recs = {m: FakeRecognizer(m) for m in models}
        status = [ModelStatus("scrfd", "detector", "fake.onnx", True, True)] + [
            ModelStatus(m, "recognizer", f"{m}.onnx", True, True) for m in models
        ]
        super().__init__(FakeDetector(), recs, status)

    def analyze(self, img, max_faces=None):
        return self.embed(img, self.detector.detect(img)[:max_faces])

    def embed(self, img, faces):
        identity, variant, _ = (int(v) for v in img[0, 0])
        rng = np.random.default_rng(identity * 7919 + variant)
        for i, f in enumerate(faces):
            # second face in a multi-face image is a *different* identity (identity + 100)
            who = identity if i == 0 else identity + 100
            f.crop = np.full((112, 112, 3), 100, np.uint8)
            f.sharpness = 120.0
            for m in self.recognizers:
                noise = rng.normal(scale=0.03, size=DIM) if variant else 0
                f.embeddings[m] = l2_normalize(prototype(m, who) + noise).astype(np.float32)
        return faces


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    cfg = {
        "paths": {
            "database": str(tmp_path / "test.db"),
            "runtime_settings": str(tmp_path / "settings.json"),
            "models_dir": str(tmp_path / "models"),
        },
        "recognizers": {
            "arcface": {"file": "a.onnx", "threshold": 0.3},
            "adaface": {"file": "b.onnx", "threshold": 0.3, "channel_order": "bgr"},
        },
        "matching": {"mode": "fusion", "fusion_threshold": 0.3, "margin": 0.05},
        "enrollment": {"min_face_px": 80, "min_det_score": 0.7, "min_sharpness": 40.0, "max_samples_per_person": 5},
        "events": {"cooldown_seconds": 60},
        # Cheap hashing for speed; synthetic images are flat grey, so sharpness can't be checked.
        "auth": {"password_iterations": 1000, "quality": {"min_sharpness": 0.0}},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("FG_CONFIG", str(path))
    monkeypatch.setenv("FG_ROOT", str(tmp_path))
    return load_settings(path)


@pytest.fixture()
def service(settings):
    svc = FaceService(settings, FakePipeline(), GalleryStore(settings.database_path))
    yield svc
    svc.store.close()


TEST_PASSWORD = "correct-horse-1"


@contextmanager
def signed_in_client(service: FaceService, username: str = "tester", role: str = "admin") -> Iterator[TestClient]:
    """TestClient over ``create_app(service)`` with a fresh user already signed in by password."""
    from facegate.api.main import create_app

    with TestClient(create_app(service)) as c:
        c.app.state.auth.create_user(username, TEST_PASSWORD, role=role)
        r = c.post("/auth/login", json={"username": username, "password": TEST_PASSWORD})
        assert r.status_code == 200, r.text
        yield c
