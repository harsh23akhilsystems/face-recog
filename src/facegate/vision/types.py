"""Plain data types shared by the vision pipeline, gallery and API.

Kept free of ONNX/OpenCV imports so that tests and the API layer can use them cheaply.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class Face:
    """One detected face in original-image pixel coordinates."""

    bbox: np.ndarray  # (4,) x1, y1, x2, y2
    score: float
    kps: np.ndarray  # (5, 2) left eye, right eye, nose, left mouth, right mouth
    embeddings: dict[str, np.ndarray] = field(default_factory=dict)  # model name -> L2-normalised (D,)
    sharpness: float = 0.0
    crop: np.ndarray | None = None  # aligned 112x112 BGR crop

    @property
    def width(self) -> float:
        return float(self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return float(self.bbox[3] - self.bbox[1])

    @property
    def min_side(self) -> float:
        return min(self.width, self.height)

    @property
    def area(self) -> float:
        return self.width * self.height
