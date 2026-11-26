"""Geometry and decoding helpers that real-model accuracy depends on."""

from __future__ import annotations

import numpy as np
import pytest

from facegate.config import load_settings
from facegate.vision.align import ARCFACE_TEMPLATE, estimate_norm, norm_crop, sharpness
from facegate.vision.detector import distance2bbox, distance2kps, nms
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
