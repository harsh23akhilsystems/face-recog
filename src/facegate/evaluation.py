"""Threshold calibration on *your* faces.

Published thresholds come from benchmark datasets whose demographics, cameras and lighting are
not your office's. This module takes a labelled folder (``root/<person>/<image>``), embeds every
face, builds all genuine (same person) and impostor (different people) pairs, and reports for
ArcFace, AdaFace and their fusion:

* ROC AUC, equal error rate (EER)
* TAR at FAR = 1e-2, 1e-3, 1e-4 and the threshold achieving each
* a recommended threshold: the lowest one whose FAR ≤ ``target_far``

Use the recommendation to set ``recognizers.*.threshold`` / ``matching.fusion_threshold``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from facegate.vision.pipeline import FacePipeline

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def collect_embeddings(pipeline: FacePipeline, root: Path) -> tuple[dict[str, np.ndarray], np.ndarray, list[str]]:
    labels: list[int] = []
    per_model: dict[str, list[np.ndarray]] = {m: [] for m in pipeline.model_names}
    skipped: list[str] = []
    people = sorted(p for p in root.iterdir() if p.is_dir())
    for label, person_dir in enumerate(people):
        for img_path in sorted(person_dir.iterdir()):
            if img_path.suffix.lower() not in IMAGE_EXT:
                continue
            img = cv2.imread(str(img_path))
            faces = pipeline.analyze(img, max_faces=1) if img is not None else []
            if not faces:
                skipped.append(str(img_path))
                continue
            for m in per_model:
                per_model[m].append(faces[0].embeddings[m])
            labels.append(label)
    mats = {m: np.stack(v) if v else np.zeros((0, 512), np.float32) for m, v in per_model.items()}
    return mats, np.array(labels), skipped


def pair_scores(mat: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sims = mat @ mat.T
    iu = np.triu_indices(len(labels), k=1)
    same = labels[iu[0]] == labels[iu[1]]
    return sims[iu], same


def roc_metrics(scores: np.ndarray, same: np.ndarray, target_far: float = 1e-3) -> dict[str, Any]:
    genuine, impostor = scores[same], scores[~same]
    if genuine.size == 0 or impostor.size == 0:
        return {"error": "Need at least two people and two images of one person"}
    thresholds = np.unique(np.concatenate([genuine, impostor]))
    far = np.array([(impostor >= t).mean() for t in thresholds])
    frr = np.array([(genuine < t).mean() for t in thresholds])
    eer_i = int(np.argmin(np.abs(far - frr)))
    # Thresholds are observed scores; place the EER threshold midway into the gap below it so a cleanly
    # separable set yields a threshold between the impostor max and genuine min, not *at* a genuine score.
    eer_thr = float(thresholds[eer_i] + thresholds[eer_i - 1]) / 2 if eer_i > 0 else float(thresholds[eer_i])
    # AUC via the rank-sum statistic (probability a genuine pair outranks an impostor pair).
    order = np.argsort(np.concatenate([genuine, impostor]))
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, order.size + 1)
    auc = (ranks[: genuine.size].sum() - genuine.size * (genuine.size + 1) / 2) / (genuine.size * impostor.size)

    def at_far(f: float) -> dict[str, float] | None:
        ok = np.where(far <= f)[0]
        if ok.size == 0 or impostor.size < 1 / f:
            return None  # not enough impostor pairs to estimate this FAR honestly
        i = ok[0]
        return {"threshold": round(float(thresholds[i]), 4), "tar": round(1 - float(frr[i]), 4)}

    rec = at_far(target_far)
    if rec is None:
        rec = {
            "threshold": round(eer_thr, 4),
            "tar": round(float((genuine >= eer_thr).mean()), 4),
            "reliable": False,
            "note": f"Fewer than {int(1 / target_far)} impostor pairs: using the EER point. Add more people.",
        }
    else:
        rec["reliable"] = True
    return {
        "genuine_pairs": int(genuine.size),
        "impostor_pairs": int(impostor.size),
        "auc": round(float(auc), 5),
        "eer": round(float((far[eer_i] + frr[eer_i]) / 2), 4),
        "eer_threshold": round(eer_thr, 4),
        "genuine_mean": round(float(genuine.mean()), 4),
        "impostor_mean": round(float(impostor.mean()), 4),
        "impostor_max": round(float(impostor.max()), 4),
        "tar_at_far": {f"{f:g}": at_far(f) for f in (1e-2, 1e-3, 1e-4)},
        "recommended": rec | {"target_far": target_far},
    }


def evaluate(pipeline: FacePipeline, root: Path, target_far: float = 1e-3) -> dict[str, Any]:
    mats, labels, skipped = collect_embeddings(pipeline, root)
    report: dict[str, Any] = {
        "images": int(labels.size),
        "people": int(len(set(labels.tolist()))),
        "skipped": skipped,
        "models": {},
    }
    all_scores = {}
    for m, mat in mats.items():
        scores, same = pair_scores(mat, labels)
        all_scores[m] = scores
        report["models"][m] = roc_metrics(scores, same, target_far)
    if len(all_scores) > 1:
        fused = np.mean(np.stack(list(all_scores.values())), axis=0)
        report["models"]["fusion"] = roc_metrics(fused, same, target_far)
    return report
