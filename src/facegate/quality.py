"""Live-camera quality checks for face sign-in, with a plain-language fix for every failure.

Ported from the Augastam face service (which used OpenCV YuNet) onto FaceGate's SCRFD detections, so
sign-in and recognition share one detector. The login page calls this every ~600 ms to guide the user
("move closer", "too dark", …) and only sends a recognition attempt once a frame passes, which keeps
bad frames from counting as failed sign-ins. Thresholds live in ``auth.quality`` in ``config.yaml``;
they are heuristics for a 640×480 webcam — tune them on your own cameras.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from facegate.config import QualityCfg
from facegate.vision.types import Face

ADVICE = {
    "no_face": "No face found — face the camera and make sure your face is in the frame.",
    "multiple_faces": "More than one face — only the person signing in should be in the frame.",
    "face_too_small": "Face is too small — move closer to the camera.",
    "face_too_large": "Face is too close — move back a little.",
    "off_center": "Face is off-centre — move into the middle of the frame.",
    "blurry": "Image is blurry — hold still and make sure the lens is clean.",
    "too_dark": "Too dark — add light in front of your face.",
    "too_bright": "Too bright — avoid strong light or glare on your face.",
    "turned_away": "Head is turned — look straight at the camera.",
    "tilted": "Head is tilted — keep your head level.",
    "unclear_face": "Face is unclear — remove masks/sunglasses and improve lighting.",
}


def _check(name: str, ok: bool, value: float | None, issue: str) -> dict[str, Any]:
    ok = bool(ok)  # numpy bools are not JSON-serialisable
    return {
        "name": name,
        "ok": ok,
        "value": None if value is None else round(float(value), 3),
        "issue": None if ok else issue,
        "advice": None if ok else ADVICE[issue],
    }


def analyze(img: np.ndarray, faces: list[Face], cfg: QualityCfg) -> dict[str, Any]:
    """``{ok, issues, advice, checks, face, faces_found, image_size}``; ``face.box`` is relative x, y, w, h."""
    h, w = img.shape[:2]
    faces = [f for f in faces if f.score >= cfg.min_det_score]
    checks = [_check("one_face", len(faces) == 1, len(faces), "no_face" if not faces else "multiple_faces")]
    face_info = None
    if len(faces) == 1:
        f = faces[0]
        x1, y1, x2, y2 = (float(v) for v in f.bbox)
        fw, fh = x2 - x1, y2 - y1
        frac = fw / w
        too_small = frac < cfg.min_face_frac or fw < cfg.min_face_px
        checks.append(
            _check(
                "face_size",
                cfg.min_face_frac <= frac <= cfg.max_face_frac and fw >= cfg.min_face_px,
                frac,
                "face_too_small" if too_small else "face_too_large",
            )
        )
        offset = max(abs((x1 + fw / 2) / w - 0.5), abs((y1 + fh / 2) / h - 0.5))
        checks.append(_check("centered", offset <= cfg.max_center_offset, offset, "off_center"))

        xa, ya, xb, yb = max(int(x1), 0), max(int(y1), 0), min(int(x2), w), min(int(y2), h)
        if xb > xa and yb > ya:
            grey = cv2.cvtColor(img[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(grey, cv2.CV_64F).var())
            bright = float(grey.mean())
            checks.append(_check("sharpness", sharp >= cfg.min_sharpness, sharp, "blurry"))
            checks.append(
                _check(
                    "brightness",
                    cfg.min_brightness <= bright <= cfg.max_brightness,
                    bright,
                    "too_dark" if bright < cfg.min_brightness else "too_bright",
                )
            )

        # SCRFD landmarks: left eye, right eye, nose, left mouth, right mouth (image left/right).
        (lex, ley), (rex, rey), (nx, _) = f.kps[0], f.kps[1], f.kps[2]
        eye_dist = float(np.hypot(rex - lex, rey - ley))
        if eye_dist > 1:
            yaw = abs(nx - (lex + rex) / 2) / eye_dist
            roll = abs(np.degrees(np.arctan2(rey - ley, rex - lex)))
            roll = min(roll, 180 - roll)
            checks.append(_check("frontal", yaw <= cfg.max_yaw, yaw, "turned_away"))
            checks.append(_check("level", roll <= cfg.max_roll_deg, roll, "tilted"))

        checks.append(_check("detector_confidence", f.score >= cfg.good_det_score, f.score, "unclear_face"))
        face_info = {
            "box": [round(x1 / w, 4), round(y1 / h, 4), round(fw / w, 4), round(fh / h, 4)],
            "score": round(float(f.score), 3),
        }

    issues = [c["issue"] for c in checks if not c["ok"]]
    return {
        "ok": not issues,
        "issues": issues,
        "advice": [ADVICE[i] for i in issues],
        "checks": checks,
        "face": face_info,
        "faces_found": len(faces),
        "image_size": [w, h],
    }
