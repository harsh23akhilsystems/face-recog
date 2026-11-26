"""Geometry and decoding helpers that real-model accuracy depends on."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from facegate.config import load_settings
from facegate.vision.align import ARCFACE_TEMPLATE, estimate_norm, face_sharpness, head_pose, norm_crop, sharpness
from facegate.vision.detector import SCRFDDetector, distance2bbox, distance2kps, nms
from facegate.vision.recognizer import l2_normalize


def test_estimate_norm_is_identity_on_template():
    m = estimate_norm(ARCFACE_TEMPLATE.copy())
    np.testing.assert_allclose(m, [[1, 0, 0], [0, 1, 0]], atol=1e-3)


def test_estimate_norm_undoes_scale_and_shift():
    kps = ARCFACE_TEMPLATE * 2.0 + np.array([30, 40], dtype=np.float32)
    m = estimate_norm(kps)
    mapped = (m[:, :2] @ kps.T).T + m[:, 2]
    np.testing.assert_allclose(mapped, ARCFACE_TEMPLATE, atol=1e-2)


def test_norm_crop_shape_and_sharpness():
    img = np.random.default_rng(0).integers(0, 255, (300, 300, 3), dtype=np.uint8)
    crop = norm_crop(img, ARCFACE_TEMPLATE * 2)
    assert crop.shape == (112, 112, 3)
    assert sharpness(crop) > sharpness(np.full_like(crop, 128))


def test_head_pose_signs_and_scale_invariance():
    assert head_pose(ARCFACE_TEMPLATE) == pytest.approx((0.0, 0.0), abs=1e-6)
    turned = ARCFACE_TEMPLATE.copy()
    turned[2, 0] += 8  # nose toward image right = person turned to their left
    yaw, pitch = head_pose(turned)
    assert yaw > 0.3 and abs(pitch) < 0.02
    chin_up = ARCFACE_TEMPLATE.copy()
    chin_up[2, 1] -= 6  # nose closer to the eye line
    yaw, pitch = head_pose(chin_up)
    assert pitch < -0.1 and abs(yaw) < 0.02
    big = turned * 3 + np.array([200, 50], dtype=np.float32)
    assert head_pose(big) == pytest.approx(head_pose(turned), abs=1e-6)


def test_letterbox_pads_to_stride_not_square():
    det = object.__new__(SCRFDDetector)  # geometry only; no ONNX session needed
    det.input_size, det.strides = (640, 640), [8, 16, 32]
    canvas, scale = det._letterbox(np.zeros((720, 1280, 3), np.uint8))
    assert canvas.shape[:2] == (384, 640) and scale == pytest.approx(0.5)
    canvas, scale = det._letterbox(np.zeros((720, 1280, 3), np.uint8), max_side=384)
    assert canvas.shape[:2] == (224, 384) and scale == pytest.approx(0.3)
    canvas, _ = det._letterbox(np.zeros((1000, 500, 3), np.uint8))
    assert canvas.shape[:2] == (640, 320)


def test_face_sharpness_ignores_background_and_detects_blur():
    rng = np.random.default_rng(1)
    img = np.full((300, 300, 3), 128, np.uint8)
    face = (rng.random((120, 120)) * 255).astype(np.uint8)  # textured "face" around the template landmarks
    img[90:210, 90:210] = face[..., None]
    kps = ARCFACE_TEMPLATE * 1.5 + 66  # landmarks centred on the textured patch
    sharp = face_sharpness(img, kps)
    blurred = img.copy()
    blurred[90:210, 90:210] = cv2.blur(blurred[90:210, 90:210], (9, 1))
    assert face_sharpness(blurred, kps) < 0.5 * sharp  # horizontal motion blur is caught
    noisy_bg = img.copy()
    noisy_bg[:40] = 255 * (rng.random((40, 300, 3)) > 0.5)  # hard background edges outside the face
    assert face_sharpness(noisy_bg, kps) == pytest.approx(sharp, rel=0.05)


def test_distance_decoders():
    pts = np.array([[10.0, 20.0]])
    np.testing.assert_allclose(distance2bbox(pts, np.array([[1.0, 2.0, 3.0, 4.0]])), [[9, 18, 13, 24]])
    np.testing.assert_allclose(distance2kps(pts, np.array([[1.0, -1.0, 2.0, 2.0]])), [[11, 19, 12, 22]])


def test_nms_suppresses_overlaps():
    dets = np.array([[0, 0, 10, 10, 0.9], [1, 1, 11, 11, 0.8], [50, 50, 60, 60, 0.7]], dtype=np.float32)
    assert nms(dets, 0.4) == [0, 2]


def test_l2_normalize():
    v = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    np.testing.assert_allclose(v[0], [0.6, 0.8])
    assert np.isfinite(v).all()


@pytest.mark.skipif(
    not (load_settings().models_dir / "det_10g.onnx").exists(), reason="real ONNX models not downloaded"
)
def test_real_models_smoke():
    """With real weights present: blank image → no faces; recognizers emit unit-norm 512-d vectors."""
    from facegate.vision.pipeline import FacePipeline

    s = load_settings()
    p = FacePipeline.from_settings(s)
    assert p.detector is not None
    assert p.detect(np.zeros((480, 640, 3), np.uint8)) == []
    crop = np.random.default_rng(1).integers(0, 255, (112, 112, 3), dtype=np.uint8)
    for rec in p.recognizers.values():
        e = rec.embed([crop, crop])
        assert e.shape == (2, 512)
        np.testing.assert_allclose(np.linalg.norm(e, axis=1), 1.0, atol=1e-4)
