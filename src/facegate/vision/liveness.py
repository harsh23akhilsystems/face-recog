"""Passive liveness (anti-spoof) for face sign-in: a live face, or a photo / screen held up to the camera?

Model: MiniFAS INT8 ONNX (github.com/suriAI/face-antispoof-onnx, Apache-2.0, ~0.6 MB), ported from the
Augastam face service. Publisher's figure: 98.2 % on CelebA-Spoof — NOT measured on this deployment's
cameras. A single-frame passive check raises the bar against printed photos and phone screens; it is not a
guarantee against high-quality attacks (see SECURITY.md).

Owned by ``FacePipeline`` like every other ONNX session; a missing file disables it instead of failing startup.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from facegate.vision.onnx_utils import create_session

SIZE, EXPAND = 128, 1.5  # training-time input size and box enlargement


class MiniFASLiveness:
    def __init__(self, path: Path, providers: list[str], threshold: float, intra_op_threads: int = 0) -> None:
        self.session = create_session(path, providers, intra_op_threads)
        self.input_name = self.session.get_inputs()[0].name
        self.providers = self.session.get_providers()
        self.threshold = threshold

    @staticmethod
    def _crop(rgb: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        """Square crop of the face box enlarged ×1.5, reflect-padded at the edges (as in training)."""
        h, w = rgb.shape[:2]
        x1, y1, x2, y2 = (float(v) for v in bbox)
        m = max(x2 - x1, y2 - y1)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        s = max(1, int(m * EXPAND))
        x0, y0 = int(cx - m * EXPAND / 2), int(cy - m * EXPAND / 2)
        c = rgb[max(0, y0) : min(h, y0 + s), max(0, x0) : min(w, x0 + s)]
        return cv2.copyMakeBorder(
            c, max(0, -y0), max(0, y0 + s - h), max(0, -x0), max(0, x0 + s - w), cv2.BORDER_REFLECT_101
        )

    @staticmethod
    def _prep(img: np.ndarray) -> np.ndarray:
        r = SIZE / max(img.shape[:2])
        nh, nw = max(1, int(img.shape[0] * r)), max(1, int(img.shape[1] * r))
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LANCZOS4 if r > 1 else cv2.INTER_AREA)
        dh, dw = SIZE - nh, SIZE - nw
        img = cv2.copyMakeBorder(img, dh // 2, dh - dh // 2, dw // 2, dw - dw // 2, cv2.BORDER_REFLECT_101)
        return img.transpose(2, 0, 1).astype(np.float32)[None] / 255.0

    def score(self, img_bgr: np.ndarray, bbox: np.ndarray) -> dict:
        """``{score, real, threshold}`` — score is the (real − spoof) logit difference."""
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        logits = self.session.run(None, {self.input_name: self._prep(self._crop(rgb, bbox))})[0][0]
        s = float(logits[0] - logits[1])
        return {"score": round(s, 3), "real": s >= self.threshold, "threshold": self.threshold}
