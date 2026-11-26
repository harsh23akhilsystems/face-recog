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
