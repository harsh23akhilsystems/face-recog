"""ONNX Runtime session helpers.

Why ONNX for every model: one runtime for SCRFD, ArcFace and AdaFace means no PyTorch at
serving time, identical behaviour on CPU and GPU, and a single place to choose providers.
"""

from __future__ import annotations

import logging
from pathlib import Path

import onnxruntime as ort

log = logging.getLogger(__name__)


def available_providers(preferred: list[str]) -> list[str]:
    """Keep the preferred providers that this onnxruntime build actually supports, in order."""
    have = set(ort.get_available_providers())
    chosen = [p for p in preferred if p in have]
    return chosen or ["CPUExecutionProvider"]


def create_session(model_path: Path, providers: list[str], intra_op_threads: int = 0) -> ort.InferenceSession:
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.log_severity_level = 3
    if intra_op_threads > 0:
        opts.intra_op_num_threads = intra_op_threads
    session = ort.InferenceSession(str(model_path), sess_options=opts, providers=available_providers(providers))
    log.info("Loaded %s with %s", model_path.name, session.get_providers())
    return session
