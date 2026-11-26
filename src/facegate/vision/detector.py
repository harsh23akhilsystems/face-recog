"""SCRFD face detector (ONNX).

SCRFD (Guo et al., 2021, "Sample and Computation Redistribution for Efficient Face Detection")
predicts, for each anchor on stride-8/16/32 feature maps, a face score, a box as distances
to the four sides, and five landmarks as offsets. We decode those here instead of depending
on the ``insightface`` package, which pulls in heavy optional deps and compiles C extensions.

The 5 landmarks are what make recognition accurate: ArcFace and AdaFace were trained on faces
warped to a canonical 5-point template (see ``align.py``).
"""

from __future__ import annotations

import cv2
import numpy as np

from facegate.vision.onnx_utils import create_session
from facegate.vision.types import Face


def distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        preds.append(points[:, i % 2] + distance[:, i])
        preds.append(points[:, i % 2 + 1] + distance[:, i + 1])
    return np.stack(preds, axis=-1)


def nms(dets: np.ndarray, threshold: float) -> list[int]:
    """Greedy non-maximum suppression over ``[x1, y1, x2, y2, score]`` rows."""
    x1, y1, x2, y2, scores = dets.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= threshold)[0] + 1]
    return keep


class SCRFDDetector:
    """Letterbox → SCRFD → anchor decode → NMS → rescale to the original image."""

    def __init__(
        self,
        model_path,
        providers: list[str],
        input_size: tuple[int, int] = (640, 640),
        score_threshold: float = 0.5,
        nms_threshold: float = 0.4,
        max_faces: int = 20,
        intra_op_threads: int = 0,
    ) -> None:
        self.session = create_session(model_path, providers, intra_op_threads)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.input_size = tuple(input_size)
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.max_faces = max_faces
        self.input_mean, self.input_std = 127.5, 128.0
        self._anchor_cache: dict[tuple[int, int, int], np.ndarray] = {}

        n_out = len(self.output_names)
        # 6 outputs: no landmarks; 9: with landmarks (3 strides); 10/15: 5 strides.
        layouts = {
            6: (3, [8, 16, 32], 2, False),
            9: (3, [8, 16, 32], 2, True),
            10: (5, [8, 16, 32, 64, 128], 1, False),
            15: (5, [8, 16, 32, 64, 128], 1, True),
        }
        if n_out not in layouts:
            raise ValueError(f"Unsupported SCRFD export with {n_out} outputs")
        self.fmc, self.strides, self.num_anchors, self.use_kps = layouts[n_out]
        if not self.use_kps:
            raise ValueError("This SCRFD model has no landmark head; use a *_kps / det_10g model for alignment.")

    @property
    def providers(self) -> list[str]:
        return self.session.get_providers()

    def _anchors(self, h: int, w: int, stride: int) -> np.ndarray:
        key = (h, w, stride)
        if key not in self._anchor_cache:
            centers = np.stack(np.mgrid[:h, :w][::-1], axis=-1).astype(np.float32)
            centers = (centers * stride).reshape(-1, 2)
            if self.num_anchors > 1:
                centers = np.stack([centers] * self.num_anchors, axis=1).reshape(-1, 2)
            self._anchor_cache[key] = centers
        return self._anchor_cache[key]

    def _letterbox(self, img: np.ndarray, max_side: int | None = None) -> tuple[np.ndarray, float]:
        """Fit the image inside ``input_size`` (optionally shrunk to ``max_side``) and pad only up to the next
        multiple of the largest stride, not to the full square: a 16:9 frame becomes 640×384 instead of 640×640,
        ~35% less compute with identical scale (the model has dynamic H/W)."""
        in_w, in_h = self.input_size
        if max_side and max_side < max(in_w, in_h):
            f = max_side / max(in_w, in_h)
            in_w, in_h = max(32, int(in_w * f)), max(32, int(in_h * f))
        im_ratio = img.shape[0] / img.shape[1]
        if im_ratio > in_h / in_w:
            new_h, new_w = in_h, max(1, int(in_h / im_ratio))
        else:
            new_w, new_h = in_w, max(1, int(in_w * im_ratio))
        scale = new_h / img.shape[0]
        m = self.strides[-1]
        canvas = np.zeros((-(-new_h // m) * m, -(-new_w // m) * m, 3), dtype=np.uint8)
        canvas[:new_h, :new_w] = cv2.resize(img, (new_w, new_h))
        return canvas, scale

    def detect(self, img_bgr: np.ndarray, max_side: int | None = None) -> list[Face]:
        canvas, scale = self._letterbox(img_bgr, max_side)
        size = (canvas.shape[1], canvas.shape[0])
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / self.input_std, size, (self.input_mean,) * 3, swapRB=True)
        outs = self.session.run(self.output_names, {self.input_name: blob})
        in_h, in_w = blob.shape[2:]

        scores_l, boxes_l, kps_l = [], [], []
        for idx, stride in enumerate(self.strides):
            scores = outs[idx]
            bbox_pred = outs[idx + self.fmc]
            kps_pred = outs[idx + self.fmc * 2]
            if scores.ndim == 3:  # batched export: (1, N, C)
                scores, bbox_pred, kps_pred = scores[0], bbox_pred[0], kps_pred[0]
            anchors = self._anchors(in_h // stride, in_w // stride, stride)
            pos = np.where(scores.reshape(-1) >= self.score_threshold)[0]
            if pos.size == 0:
                continue
            scores_l.append(scores.reshape(-1)[pos])
            boxes_l.append(distance2bbox(anchors, bbox_pred * stride)[pos])
            kps_l.append(distance2kps(anchors, kps_pred * stride).reshape(-1, 5, 2)[pos])

        if not scores_l:
            return []
        scores = np.concatenate(scores_l)
        boxes = np.concatenate(boxes_l) / scale
        kps = np.concatenate(kps_l) / scale
        dets = np.hstack([boxes, scores[:, None]]).astype(np.float32)
        keep = nms(dets, self.nms_threshold)[: self.max_faces]

        h, w = img_bgr.shape[:2]
        faces = []
        for i in keep:
            box = dets[i, :4].copy()
            box[[0, 2]] = box[[0, 2]].clip(0, w - 1)
            box[[1, 3]] = box[[1, 3]].clip(0, h - 1)
            faces.append(Face(bbox=box, score=float(dets[i, 4]), kps=kps[i].astype(np.float32)))
        faces.sort(key=lambda f: f.area, reverse=True)
        return faces
