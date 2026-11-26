"""5-point similarity alignment to the ArcFace 112x112 template.

Both ArcFace and AdaFace were trained on crops produced by exactly this warp, so feeding
them anything else (a plain bbox crop, a different template) silently costs several points
of accuracy. Keep this module the single source of the template.
"""

from __future__ import annotations

import cv2
import numpy as np

ARCFACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def estimate_norm(kps: np.ndarray, image_size: int = 112) -> np.ndarray:
    """Least-squares similarity transform (rotation + uniform scale + translation)."""
    if image_size % 112 == 0:
        ratio, diff_x = image_size / 112.0, 0.0
    else:
        ratio, diff_x = image_size / 128.0, 8.0 * image_size / 128.0
    dst = ARCFACE_TEMPLATE * ratio
    dst[:, 0] += diff_x
    matrix, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), dst, method=cv2.LMEDS)
    if matrix is None:  # degenerate landmarks; fall back to a pure least-squares fit
        matrix, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), dst, method=0)
    return matrix


def norm_crop(img_bgr: np.ndarray, kps: np.ndarray, image_size: int = 112) -> np.ndarray:
    matrix = estimate_norm(kps, image_size)
    return cv2.warpAffine(img_bgr, matrix, (image_size, image_size), borderValue=0.0)


def sharpness(crop_bgr: np.ndarray) -> float:
    """Variance of the Laplacian: a cheap blur score used to reject poor enrollment photos."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def face_sharpness(img_bgr: np.ndarray, kps: np.ndarray) -> float:
    """Blur score of the *face itself*: Laplacian variance of the inner face (brows → chin, cheek to cheek) on a
    224 px aligned crop.

    Why not ``sharpness``: on the 112 px crop the corners hold background — ceiling lights, hair against a bright
    wall — whose hard edges keep the score high even when the face is motion-blurred (measured: blurred faces
    scored 880–905, sharp ones 470–800). Restricting to the inner face at 2× resolution ranks them correctly
    (blurred ≈ 200–230, sharp ≈ 430–690). Used by guided capture to pick the clearest frame.
    """
    gray = cv2.cvtColor(norm_crop(img_bgr, kps, 224), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray[80:200, 56:168], cv2.CV_64F).var())


def _pose_ratios(kps: np.ndarray) -> tuple[float, float]:
    k = kps.astype(np.float64)
    left_eye, right_eye, nose = k[0], k[1], k[2]
    eye_mid, mouth_mid = (left_eye + right_eye) / 2, (k[3] + k[4]) / 2
    axis, down = right_eye - left_eye, mouth_mid - eye_mid
    a2, d2 = float(axis @ axis), float(down @ down)
    t = float((nose - left_eye) @ axis) / a2 if a2 > 1e-6 else 0.5
    s = float((nose - eye_mid) @ down) / d2 if d2 > 1e-6 else 0.5
    return t, s


_TEMPLATE_T, _TEMPLATE_S = _pose_ratios(ARCFACE_TEMPLATE)


def head_pose(kps: np.ndarray) -> tuple[float, float]:
    """Rough (yaw, pitch) from the 5 landmarks — used only to guide enrollment capture, never for matching.

    Why landmarks and not a pose model: SCRFD already returns them, so pose costs nothing extra per frame.

    * ``yaw`` — where the nose sits between the eyes, scaled to about [-1, 1] (≈ sin of the yaw angle).
      Positive = nose toward image right = the person turned to *their* left.
    * ``pitch`` — where the nose sits between the eye line and mouth line, relative to the alignment template.
      Negative = chin up, positive = chin down. It depends on face shape and camera height, so callers should
      compare it with the same person's frontal value rather than with zero.
    """
    t, s = _pose_ratios(kps)
    yaw = float(np.clip((t - _TEMPLATE_T) * 2, -1, 1))
    pitch = float(np.clip(s - _TEMPLATE_S, -1, 1))
    return yaw, pitch
