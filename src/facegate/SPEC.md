# Spec — `src/facegate/` (service, config, CLI, evaluation)

Sub-folders have their own specs: `vision/SPEC.md`, `gallery/SPEC.md`, `api/SPEC.md`.

## Files at this level
| File | Responsibility |
|---|---|
| `service.py` | `FaceService` — the only façade the API and CLI call: recognize, enroll, verify, detect, events, runtime settings, health, reembed |
| `config.py` | Typed settings from `configs/config.yaml` (pydantic); `load_settings`, cached `get_settings`; `FG_CONFIG` / `FG_ROOT` overrides |
| `cli.py` | `facegate` command: `status`, `enroll-dir`, `identify`, `verify`, `evaluate`, `reembed` |
| `evaluation.py` | Threshold calibration: `collect_embeddings`, `pair_scores`, `roc_metrics`, `evaluate` |
| `__init__.py` | version |

## Configuration (`config.py`)
- Every tunable lives in `configs/config.yaml`; unknown values fail validation at startup.
- Relative paths resolve against the project root (`FG_ROOT`), so tests can use a temp folder.
- Operator-adjustable keys (`RUNTIME_KEYS` in `service.py`): `mode`, `fusion_threshold`, `margin`, `thresholds`,
  `log_recognitions`, `cooldown_seconds`. They are overlaid from `data/settings.json` (written by the Settings page /
  `PUT /settings`). Delete that file to return to YAML defaults.

## Enrollment rules (`FaceService.enroll`)
Checked per photo, in order; the first failure becomes the user-visible `reason`:
1. Person has fewer than `max_samples_per_person` (20) samples.
2. At least one face detected — the **largest** is used; a warning is added if there are several.
3. Face shorter side ≥ `min_face_px` (80).
4. Detection score ≥ `min_det_score` (0.70).
5. Sharpness ≥ `min_sharpness` (40).
6. Not a duplicate: rejected if it matches a **different** person at ≥ `duplicate_threshold` (0.55).

Accepted → stores the aligned crop (if `store_thumbnails`) and one embedding per loaded model.
Raw uploaded photos are never stored.

## Recognition & events (`FaceService.recognize`)
- Uses `effective_mode` (falls back if a model is missing).
- Logs an event per face when `log_recognitions` (or the request's `log_events`) is on.
- **Cooldown:** a recognised person is logged at most once per `cooldown_seconds` (60); unknown/uncertain faces share
  one cooldown bucket per `source`, so a lingering visitor is not logged every frame. `log_unknown` can disable them.

## Verify (`FaceService.verify`)
Largest face from each image; per-model cosine vs threshold; decision follows the active mode. Nothing is stored.
No face in either image → `ValueError` → HTTP 422.

## CLI (`cli.py`)
```bash
facegate status                                  # model + gallery status (JSON)
facegate enroll-dir staff/ --department Ops      # staff/<Full Name>[__EMPID]/*.jpg; existing names get samples appended
facegate identify photo.jpg --mode strict
facegate verify a.jpg b.jpg
facegate evaluate eval_faces/ --target-far 1e-3 --out reports/evaluation.json
facegate reembed                                 # after adding or changing a recognizer
```

## Evaluation (`evaluation.py`)
Input `root/<person>/*.jpg` — ≥ 20 people, ≥ 3 images each, from the deployment camera, not the enrollment photos.
- Builds all genuine (same person) and impostor (different people) pairs.
- Reports per model and for `fusion`: AUC, EER (+ threshold placed midway into the score gap), genuine/impostor
  means, max impostor score, TAR at FAR 1e-2/1e-3/1e-4 (only when there are ≥ 1/FAR impostor pairs).
- `recommended`: lowest threshold with FAR ≤ `--target-far` and `reliable: true`; with too few impostor pairs it
  falls back to the EER point and marks `reliable: false`.
