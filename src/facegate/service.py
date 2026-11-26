"""Application service: the single façade the API and CLI call.

It owns the pipeline (ONNX sessions), the gallery store and the matcher, and implements the
business rules that do not belong to any one of them: enrollment quality gates, duplicate
detection, event cooldown, and operator-adjustable runtime settings (persisted to JSON so a
threshold tweak in the console survives a restart without editing ``config.yaml``).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from facegate.config import Settings
from facegate.gallery.matcher import Matcher, MatchResult, verify_scores
from facegate.gallery.store import GalleryStore
from facegate.vision.align import head_pose
from facegate.vision.pipeline import FacePipeline, encode_jpeg
from facegate.vision.types import Face

log = logging.getLogger(__name__)

RUNTIME_KEYS = ("mode", "fusion_threshold", "margin", "thresholds", "log_recognitions", "cooldown_seconds")


@dataclass
class EnrollOutcome:
    filename: str
    accepted: bool
    sample_id: str | None = None
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    det_score: float | None = None
    sharpness: float | None = None
    face_px: float | None = None
    duplicate_of: dict[str, Any] | None = None  # the already-enrolled person this face matches, if any


class FaceService:
    def __init__(self, settings: Settings, pipeline: FacePipeline, store: GalleryStore) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self.store = store
        self._apply_runtime_overrides()
        thresholds = {m: c.threshold for m, c in settings.recognizers.items()}
        thresholds.update(self._runtime.get("thresholds", {}))
        self.matcher = Matcher(store, thresholds, settings.matching)
        self._last_logged: dict[str, float] = {}
        self._log_lock = threading.Lock()
        purged = store.purge_events(settings.events.retention_days)
        if purged:
            log.info("Purged %d events older than %d days", purged, settings.events.retention_days)

    @classmethod
    def from_settings(cls, settings: Settings) -> FaceService:
        return cls(settings, FacePipeline.from_settings(settings), GalleryStore(settings.database_path))

    # ------------------------------------------------------------------ runtime settings
    def _apply_runtime_overrides(self) -> None:
        path = self.settings.runtime_settings_path
        self._runtime: dict[str, Any] = {}
        if path.exists():
            try:
                self._runtime = {k: v for k, v in json.loads(path.read_text()).items() if k in RUNTIME_KEYS}
            except json.JSONDecodeError:
                log.warning("Ignoring unreadable runtime settings at %s", path)
        m, e = self.settings.matching, self.settings.events
        m.mode = self._runtime.get("mode", m.mode)
        m.fusion_threshold = float(self._runtime.get("fusion_threshold", m.fusion_threshold))
        m.margin = float(self._runtime.get("margin", m.margin))
        e.log_recognitions = bool(self._runtime.get("log_recognitions", e.log_recognitions))
        e.cooldown_seconds = int(self._runtime.get("cooldown_seconds", e.cooldown_seconds))

    def get_runtime_settings(self) -> dict[str, Any]:
        m, e = self.settings.matching, self.settings.events
        return {
            "mode": m.mode,
            "effective_mode": self.matcher.effective_mode(self.pipeline.model_names),
            "fusion_threshold": m.fusion_threshold,
            "margin": m.margin,
            "thresholds": dict(self.matcher.model_thresholds),
            "log_recognitions": e.log_recognitions,
            "cooldown_seconds": e.cooldown_seconds,
            "available_models": self.pipeline.model_names,
        }

    def update_runtime_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        m, e = self.settings.matching, self.settings.events
        if "mode" in patch:
            m.mode = patch["mode"]
        if "fusion_threshold" in patch:
            m.fusion_threshold = float(patch["fusion_threshold"])
        if "margin" in patch:
            m.margin = float(patch["margin"])
        if "thresholds" in patch:
            for name, value in patch["thresholds"].items():
                if name in self.matcher.model_thresholds:
                    self.matcher.model_thresholds[name] = float(value)
        if "log_recognitions" in patch:
            e.log_recognitions = bool(patch["log_recognitions"])
        if "cooldown_seconds" in patch:
            e.cooldown_seconds = int(patch["cooldown_seconds"])
        current = self.get_runtime_settings()
        persisted = {k: current[k] for k in RUNTIME_KEYS}
        path = self.settings.runtime_settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(persisted, indent=2))
        return current

    # ------------------------------------------------------------------ status
    def health(self) -> dict[str, Any]:
        stats = self.store.stats()
        return {
            "status": "ok" if self.pipeline.ready else "degraded",
            "ready": self.pipeline.ready,
            "models": [asdict(s) for s in self.pipeline.status()],
            "mode": self.matcher.effective_mode(self.pipeline.model_names),
            "people": stats["people"],
            "samples": stats["samples"],
        }

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _face_box(face: Face) -> dict[str, Any]:
        x1, y1, x2, y2 = (round(float(v), 1) for v in face.bbox)
        return {
            "bbox": [x1, y1, x2, y2],
            "det_score": round(face.score, 4),
            "landmarks": face.kps.round(1).tolist(),
            "sharpness": round(face.sharpness, 1),
            "face_sharpness": round(face.face_sharpness, 1),
            "pose": dict(zip(("yaw", "pitch"), (round(v, 3) for v in head_pose(face.kps)), strict=True)),
        }

    def _person_lookup(self, person_id: str | None) -> dict[str, Any] | None:
        return self.store.get_person(person_id) if person_id else None

    # ------------------------------------------------------------------ detection / recognition
    def detect(self, img: np.ndarray, max_side: int | None = None) -> dict[str, Any]:
        faces = self.pipeline.detect(img, quality=True, max_side=max_side)
        return {"width": img.shape[1], "height": img.shape[0], "faces": [self._face_box(f) for f in faces]}

    def enrollment_guide(self) -> dict[str, Any]:
        """Everything the console's guided capture needs: the pose steps plus the same quality gates
        ``enroll`` applies, so a frame accepted on the client is accepted by the server too."""
        cfg = self.settings.enrollment
        return cfg.guided.model_dump() | {
            "min_face_px": cfg.min_face_px,
            "min_det_score": cfg.min_det_score,
            "min_sharpness": cfg.min_sharpness,
            "max_samples_per_person": cfg.max_samples_per_person,
        }

    def recognize(
        self, img: np.ndarray, mode: str | None = None, source: str = "api", log_events: bool | None = None
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        faces = self.pipeline.analyze(img)
        eff_mode = self.matcher.effective_mode(self.pipeline.model_names, mode)
        out = []
        for face in faces:
            res = self.matcher.identify(face.embeddings, eff_mode)
            person = self._person_lookup(res.person_id)
            item = self._face_box(face) | {
                "status": res.status,
                "score": round(res.score, 4),
                "threshold": res.threshold,
                "per_model": res.per_model,
                "runner_up_score": None if res.runner_up_score is None else round(res.runner_up_score, 4),
                "person": None
                if person is None
                else {k: person[k] for k in ("id", "name", "employee_id", "department", "cover_sample_id")},
            }
            out.append(item)
            should_log = self.settings.events.log_recognitions if log_events is None else log_events
            if should_log:
                self._maybe_log(face, res, person, eff_mode, source)
        return {
            "width": img.shape[1],
            "height": img.shape[0],
            "mode": eff_mode,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            "faces": out,
        }

    def _maybe_log(self, face: Face, res: MatchResult, person: dict[str, Any] | None, mode: str, source: str) -> None:
        if res.status != "match" and not self.settings.events.log_unknown:
            return
        # Unknown faces share one cooldown bucket per source so a lingering visitor isn't logged every frame.
        key = res.person_id if res.status == "match" else f"__{res.status}__{source}"
        now = time.monotonic()
        with self._log_lock:
            if now - self._last_logged.get(key, -1e9) < self.settings.events.cooldown_seconds:
                return
            self._last_logged[key] = now
        thumb = encode_jpeg(face.crop, 85) if face.crop is not None else None
        self.store.add_event(
            res.person_id if res.status == "match" else None,
            person["name"] if person and res.status == "match" else None,
            res.status,
            round(res.score, 4),
            mode,
            source,
            thumb,
        )

    def verify(self, img_a: np.ndarray, img_b: np.ndarray) -> dict[str, Any]:
        fa, fb = self.pipeline.analyze(img_a, max_faces=1), self.pipeline.analyze(img_b, max_faces=1)
        if not fa or not fb:
            missing = [n for n, f in (("A", fa), ("B", fb)) if not f]
            raise ValueError(f"No face found in image {' and '.join(missing)}")
        scores = verify_scores(fa[0].embeddings, fb[0].embeddings)
        thresholds = self.matcher.model_thresholds
        per_model = {
            m: {"score": round(s, 4), "threshold": thresholds.get(m, 0.3), "match": s >= thresholds.get(m, 0.3)}
            for m, s in scores.items()
        }
        fused = float(np.mean(list(scores.values())))
        mode = self.matcher.effective_mode(list(scores))
        if mode == "fusion":
            decision = fused >= self.settings.matching.fusion_threshold
        elif mode == "strict":
            decision = all(v["match"] for v in per_model.values())
        else:
            decision = per_model[mode]["match"]
        return {
            "mode": mode,
            "match": bool(decision),
            "fused_score": round(fused, 4),
            "fusion_threshold": self.settings.matching.fusion_threshold,
            "per_model": per_model,
            "face_a": self._face_box(fa[0]),
            "face_b": self._face_box(fb[0]),
        }

    # ------------------------------------------------------------------ enrollment
    def enroll(
        self, person_id: str, images: list[tuple[str, np.ndarray]], dry_run: bool = False
    ) -> list[EnrollOutcome]:
        """Apply every enrollment gate and store accepted samples. With ``dry_run`` nothing is stored: the outcomes say
        what *would* be accepted (guided capture uses this to retake an angle before the person walks away)."""
        cfg = self.settings.enrollment
        if self.store.get_person(person_id) is None:
            raise KeyError(person_id)
        outcomes: list[EnrollOutcome] = []
        would_add = 0
        for filename, img in images:
            if self.store.count_samples(person_id) + would_add >= cfg.max_samples_per_person:
                outcomes.append(
                    EnrollOutcome(
                        filename,
                        False,
                        reason=f"Limit of {cfg.max_samples_per_person} samples reached; delete old samples first",
                    )
                )
                continue
            faces = self.pipeline.analyze(img)
            if not faces:
                outcomes.append(EnrollOutcome(filename, False, reason="No face detected"))
                continue
            face = faces[0]  # largest
            oc = EnrollOutcome(
                filename,
                False,
                det_score=round(face.score, 3),
                sharpness=round(face.sharpness, 1),
                face_px=round(face.min_side, 1),
            )
            if len(faces) > 1:
                oc.warnings.append(f"{len(faces)} faces found; used the largest")
            if face.min_side < cfg.min_face_px:
                oc.reason = f"Face too small ({face.min_side:.0f}px < {cfg.min_face_px}px); move closer"
            elif face.score < cfg.min_det_score:
                oc.reason = f"Low detection confidence ({face.score:.2f}); face the camera, improve lighting"
            elif face.sharpness < cfg.min_sharpness:
                oc.reason = f"Image too blurry (sharpness {face.sharpness:.0f} < {cfg.min_sharpness:.0f})"
            if oc.reason:
                outcomes.append(oc)
                continue
            # Duplicate check: does this face look like a *different* enrolled person?
            dup = self._find_duplicate(face, person_id)
            if dup:
                emp = f", employee ID {dup['employee_id']}" if dup["employee_id"] else ""
                oc.reason = (
                    f"Already enrolled as {dup['name']}{emp} (similarity {dup['score']:.2f}); "
                    "check the photo belongs to this person"
                )
                oc.duplicate_of = dup
                outcomes.append(oc)
                continue
            if dry_run:
                oc.accepted = True
                would_add += 1
                outcomes.append(oc)
                continue
            thumb = encode_jpeg(face.crop, 92) if cfg.store_thumbnails and face.crop is not None else None
            oc.sample_id = self.store.add_sample(
                person_id, face.score, face.sharpness, face.min_side, face.embeddings, thumb, head_pose(face.kps)
            )
            oc.accepted = True
            outcomes.append(oc)
        return outcomes

    def _find_duplicate(self, face: Face, person_id: str | None) -> dict[str, Any] | None:
        """The *other* enrolled person this face matches at ≥ ``duplicate_threshold`` (fusion when available)."""
        res = self.matcher.identify(face.embeddings, "fusion" if len(face.embeddings) > 1 else None)
        if not res.person_id or res.person_id == person_id or res.score < self.settings.enrollment.duplicate_threshold:
            return None
        other = self.store.get_person(res.person_id)
        if other is None:
            return None
        keys = ("id", "name", "employee_id", "department", "cover_sample_id")
        return {k: other.get(k) for k in keys} | {"score": round(float(res.score), 3)}

    def check_duplicate(self, img: np.ndarray, person_id: str | None = None) -> dict[str, Any]:
        """Is the largest face in ``img`` already enrolled as someone other than ``person_id``? Used by guided
        capture right after the first photo, so HR learns about a duplicate before taking the other poses."""
        faces = self.pipeline.analyze(img, max_faces=1)
        if not faces:
            return {"face_found": False, "duplicate_of": None}
        return {"face_found": True, "duplicate_of": self._find_duplicate(faces[0], person_id)}

    def backfill_poses(self) -> int:
        """Give samples enrolled before pose was stored a yaw/pitch, so the profile photo can be the frontal one.

        The stored 112 px crop is a similarity warp of the original, and yaw/pitch are ratios of landmark positions,
        which such a warp preserves — so re-detecting landmarks on the crop recovers the capture pose.
        """
        import cv2

        if self.pipeline.detector is None:
            return 0
        done = 0
        for sid, thumb in self.store.iter_unposed_thumbs():
            crop = cv2.imdecode(np.frombuffer(thumb, np.uint8), cv2.IMREAD_COLOR)
            if crop is None:
                continue
            canvas = np.full((480, 480, 3), int(crop.mean()), np.uint8)  # detector needs context around the face
            canvas[110:370, 110:370] = cv2.resize(crop, (260, 260))
            faces = self.pipeline.detect(canvas)
            if faces:
                self.store.set_pose(sid, *head_pose(faces[0].kps))
                done += 1
        if done:
            log.info("Backfilled head pose for %d samples", done)
        return done

    def reembed(self) -> dict[str, int]:
        """Recompute every stored sample's embeddings from its thumbnail (after adding/upgrading a model)."""
        import cv2

        done = 0
        for sid, thumb in self.store.iter_thumbs():
            crop = cv2.imdecode(np.frombuffer(thumb, np.uint8), cv2.IMREAD_COLOR)
            for name, rec in self.pipeline.recognizers.items():
                self.store.set_embedding(sid, name, rec.embed([crop])[0])
            done += 1
        return {"samples": done, "models": len(self.pipeline.recognizers)}
