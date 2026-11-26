"""1:N identification and 1:1 verification over the enrolled gallery.

Decision logic (documented in ``gallery/SPEC.md``):

* Each person has several templates per model; a person's score is the ``max`` (or ``mean``)
  cosine over their templates.
* ``arcface`` / ``adaface`` — use one model and its own threshold.
* ``fusion`` — average the two models' per-person scores, compare with ``fusion_threshold``.
  Averaging two partially independent models lowers variance, cutting false accepts.
* ``strict`` — both models must independently clear their thresholds *and* agree on the same
  person. Best for access control where a false accept costs more than a retry.
* Open-set safety: if the best person beats the runner-up by less than ``margin`` the result is
  ``uncertain`` rather than a guess.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

from facegate.config import MatchingCfg
from facegate.gallery.store import GalleryStore


@dataclass
class MatchResult:
    status: str  # match | unknown | uncertain
    person_id: str | None
    score: float  # decision score in the active mode
    threshold: float
    per_model: dict[str, float] = field(default_factory=dict)  # best person's score under each model
    runner_up_score: float | None = None


@dataclass
class _ModelIndex:
    matrix: np.ndarray  # (N, D)
    row_person: np.ndarray  # (N,) int index into people
    people: list[str]


class Matcher:
    def __init__(self, store: GalleryStore, model_thresholds: dict[str, float], cfg: MatchingCfg) -> None:
        self.store = store
        self.model_thresholds = dict(model_thresholds)
        self.cfg = cfg
        self._indexes: dict[str, _ModelIndex] = {}
        self._version = -1
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ index
    def _ensure_index(self, models: list[str]) -> None:
        with self._lock:
            if self._version == self.store.version and all(m in self._indexes for m in models):
                return
            self._indexes = {}
            for m in models:
                mat, owners = self.store.load_embeddings(m)
                people = sorted(set(owners))
                pos = {p: i for i, p in enumerate(people)}
                self._indexes[m] = _ModelIndex(mat, np.array([pos[o] for o in owners], dtype=np.int64), people)
            self._version = self.store.version

    def person_scores(self, model: str, query: np.ndarray) -> dict[str, float]:
        """Aggregate cosine similarity of ``query`` against every enrolled person for one model."""
        self._ensure_index([model])
        idx = self._indexes[model]
        if idx.matrix.size == 0:
            return {}
        sims = idx.matrix @ query.astype(np.float32)
        n = len(idx.people)
        if self.cfg.aggregate == "mean":
            sums = np.bincount(idx.row_person, weights=sims, minlength=n)
            counts = np.bincount(idx.row_person, minlength=n)
            agg = sums / np.maximum(counts, 1)
        else:
            agg = np.full(n, -1.0, dtype=np.float64)
            np.maximum.at(agg, idx.row_person, sims)
        return dict(zip(idx.people, agg.tolist(), strict=True))

    # ------------------------------------------------------------------ decisions
    def effective_mode(self, available: list[str], mode: str | None = None) -> str:
        """Fall back gracefully when the requested mode needs a model that is not loaded."""
        mode = mode or self.cfg.mode
        if mode in ("fusion", "strict") and len(available) < 2:
            return available[0] if available else mode
        if mode in ("arcface", "adaface") and mode not in available:
            return available[0] if available else mode
        return mode

    def identify(self, embeddings: dict[str, np.ndarray], mode: str | None = None) -> MatchResult:
        available = [m for m in embeddings if m in self.model_thresholds]
        mode = self.effective_mode(available, mode)
        per_model = {m: self.person_scores(m, embeddings[m]) for m in available}

        if mode in ("arcface", "adaface"):
            return self._decide(per_model[mode], self.model_thresholds[mode], per_model)

        people = set().union(*(s.keys() for s in per_model.values())) if per_model else set()
        if mode == "fusion":
            fused = {p: float(np.mean([per_model[m].get(p, -1.0) for m in available])) for p in people}
            return self._decide(fused, self.cfg.fusion_threshold, per_model)

        # strict: each model must pick the same person above its own threshold.
        picks = {m: self._decide(per_model[m], self.model_thresholds[m], per_model) for m in available}
        ids = {r.person_id for r in picks.values()}
        fused = {p: float(np.mean([per_model[m].get(p, -1.0) for m in available])) for p in people}
        base = self._decide(fused, self.cfg.fusion_threshold, per_model)
        if all(r.status == "match" for r in picks.values()) and len(ids) == 1:
            return MatchResult("match", ids.pop(), base.score, base.threshold, base.per_model, base.runner_up_score)
        status = "uncertain" if any(r.status == "match" for r in picks.values()) else "unknown"
        return MatchResult(
            status,
            base.person_id if status == "uncertain" else None,
            base.score,
            base.threshold,
            base.per_model,
            base.runner_up_score,
        )

    def _decide(
        self, scores: dict[str, float], threshold: float, per_model: dict[str, dict[str, float]]
    ) -> MatchResult:
        if not scores:
            return MatchResult("unknown", None, 0.0, threshold, {})
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_id, best = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else None
        best_per_model = {m: round(float(s.get(best_id, -1.0)), 4) for m, s in per_model.items()}
        if best < threshold:
            return MatchResult("unknown", None, best, threshold, best_per_model, runner)
        if runner is not None and runner >= threshold and best - runner < self.cfg.margin:
            return MatchResult("uncertain", best_id, best, threshold, best_per_model, runner)
        return MatchResult("match", best_id, best, threshold, best_per_model, runner)


def verify_scores(a: dict[str, np.ndarray], b: dict[str, np.ndarray]) -> dict[str, float]:
    """Cosine similarity per model between two faces (1:1)."""
    return {m: float(np.dot(a[m], b[m])) for m in a if m in b}
