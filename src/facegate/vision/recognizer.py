"""Face embedding models: ArcFace and AdaFace, both served as ONNX.

Both networks take a 112x112 aligned crop and output a 512-d vector; identity is compared with
cosine similarity on L2-normalised vectors. What differs is training and preprocessing:

* **ArcFace** (Deng et al., 2019) — additive angular margin. InsightFace exports usually take
  RGB in ``(x - 127.5) / 127.5``; some exports bake normalisation into the graph, which we detect
  the same way InsightFace does (look for ``Sub``/``Mul`` nodes at the start of the graph).
* **AdaFace** (Kim et al., 2022) — margin adapts to image quality (feature norm), so it is
  noticeably more robust on low-quality frames (CCTV, motion blur, poor light). Official weights
  expect **BGR** in ``(x / 255 - 0.5) / 0.5``, which is numerically the same scaling.

Running both and fusing the scores (see ``gallery/matcher.py``) reduces false accepts because the
two models make partially independent errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from facegate.vision.onnx_utils import create_session

ChannelOrder = Literal["auto", "rgb", "bgr"]


def l2_normalize(x: np.ndarray, axis: int = -1) -> np.ndarray:
    norm = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / np.clip(norm, 1e-12, None)


class OnnxRecognizer:
    """Generic 112x112 → D-dim ONNX embedder with configurable channel order and normalisation."""

    default_channel_order: ChannelOrder = "rgb"

    def __init__(
        self,
        name: str,
        model_path: Path,
        providers: list[str],
        channel_order: ChannelOrder = "auto",
        intra_op_threads: int = 0,
    ) -> None:
        self.name = name
        self.model_path = Path(model_path)
        self.session = create_session(self.model_path, providers, intra_op_threads)
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.output_name = self.session.get_outputs()[0].name
        shape = inp.shape
        self.input_size = (int(shape[3]), int(shape[2])) if isinstance(shape[2], int) else (112, 112)
        self.batch_dynamic = not isinstance(shape[0], int)
        self.embedding_dim = int(self.session.get_outputs()[0].shape[-1] or 512)
        self.swap_rb = (channel_order if channel_order != "auto" else self.default_channel_order) == "rgb"
        self.input_mean, self.input_std = self._detect_normalisation()

    @property
    def providers(self) -> list[str]:
        return self.session.get_providers()

    def _detect_normalisation(self) -> tuple[float, float]:
        """If the graph already subtracts/multiplies at the input, feed raw 0..255 pixels."""
        try:
            import onnx  # optional; only present with the `export` extra

            graph = onnx.load(str(self.model_path), load_external_data=False).graph
            names = [n.name for n in graph.node[:8]]
            has_sub = any(n.startswith(("Sub", "_minus")) for n in names)
            has_mul = any(n.startswith(("Mul", "_mul")) for n in names)
            if has_sub and has_mul:
                return 0.0, 1.0
        except Exception:  # noqa: BLE001 - onnx missing or unreadable: fall back to the standard scaling
            pass
        return 127.5, 127.5

    def embed(self, crops_bgr: list[np.ndarray]) -> np.ndarray:
        """Embed aligned BGR crops; returns ``(N, D)`` L2-normalised float32."""
        if not crops_bgr:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        blob = cv2.dnn.blobFromImages(
            crops_bgr, 1.0 / self.input_std, self.input_size, (self.input_mean,) * 3, swapRB=self.swap_rb
        )
        if self.batch_dynamic:
            out = self.session.run([self.output_name], {self.input_name: blob})[0]
        else:  # fixed batch-1 export
            out = np.concatenate(
                [self.session.run([self.output_name], {self.input_name: blob[i : i + 1]})[0] for i in range(len(blob))]
            )
        out = out.reshape(len(crops_bgr), -1).astype(np.float32)
        return l2_normalize(out)


class ArcFaceRecognizer(OnnxRecognizer):
    default_channel_order = "rgb"


class AdaFaceRecognizer(OnnxRecognizer):
    default_channel_order = "bgr"

    def _detect_normalisation(self) -> tuple[float, float]:
        # (x/255 - 0.5)/0.5 == (x - 127.5)/127.5; our exporter never bakes normalisation into the graph.
        return 127.5, 127.5


RECOGNIZER_TYPES: dict[str, type[OnnxRecognizer]] = {
    "arcface": ArcFaceRecognizer,
    "adaface": AdaFaceRecognizer,
}
