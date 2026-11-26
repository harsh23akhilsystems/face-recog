# Spec — `src/facegate/` (service, config, CLI, evaluation)

Sub-folders have their own specs: `vision/SPEC.md`, `gallery/SPEC.md`, `api/SPEC.md`.

## Files at this level
| File | Responsibility |
|---|---|
| `service.py` | `FaceService` — the only façade the API and CLI call: recognize, enroll, verify, detect, events, runtime settings, health, reembed |
| `auth.py` | `AuthService` — users (PBKDF2), sessions (hashed tokens), login audit + lockout, password and face sign-in, first-start admin |
| `quality.py` | Live-camera checks for face sign-in on SCRFD detections, each with a plain-language fix |
| `config.py` | Typed settings from `configs/config.yaml` (pydantic); `load_settings`, cached `get_settings`; `FG_CONFIG` / `FG_ROOT` overrides |
| `cli.py` | `facegate` command: `status`, `enroll-dir`, `identify`, `verify`, `evaluate`, `reembed`, `user …` |
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
6. Not a duplicate: rejected if it matches a **different** person at ≥ `duplicate_threshold` (0.55). The reason names
   them ("Already enrolled as X, employee ID Y") and the outcome carries `duplicate_of` for the console popup.
   `check_duplicate(img, person_id)` runs the same check without enrolling (guided capture's first photo).
   `enroll(..., dry_run=True)` applies all gates (photo limit counted across the batch) without storing anything.

Accepted → stores the aligned crop (if `store_thumbnails`) and one embedding per loaded model.
Raw uploaded photos are never stored.

### Guided capture (`FaceService.enrollment_guide`, `enrollment.guided`)
The console's guided capture calls `GET /enrollment/guide` for the pose `steps` plus the same gates as above
(`min_face_px`, `min_det_score`, `min_sharpness`, `max_samples_per_person`), polls `POST /detect` (which returns
`sharpness` and `pose {yaw, pitch}`) on the live video with a small detector input (`detect_size`) while a voice
walks the person through each direction (`phase_prompts`). Every frame that is centred (`max_center_offset`) and
passes the gates competes for each step whose yaw/pitch range it fits; the best frame per step is enrolled when the
scan ends — only once every step has a frame (`best_window_ms` after a direction's steps are found; unfinished
directions are re-announced every `remind_ms`, never skipped automatically).
All photos then go through `enroll` unchanged — guided capture adds no server-side bypass.
Each step: `key`, `prompt`, `hint` (center/left/right/up/down), `yaw` and `pitch` as `[min, max]` or `null`.
`yaw` ≈ sin(angle), + = person turned to *their* left; `pitch` is relative to that person's frontal capture,
− = chin up. Defaults: front, slight left, left, slight right, right, chin up, chin down (7 photos).

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

## Sign-in (`auth.py`)
Tables `users`, `sessions`, `login_events` live in the gallery database and share its connection and lock.
- **Password**: PBKDF2-SHA256 (`auth.password_iterations`), per-user salt; unknown usernames are hashed against a
  dummy so timing does not reveal which accounts exist.
- **Sessions**: `secrets.token_urlsafe(32)` in the cookie; only its SHA-256 is stored; `auth.session_hours`;
  expired rows are purged on startup. Changing a password or removing a user ends their sessions.
- **Face sign-in** (checked in order): `auth.face_login` on and models loaded (503) → not locked (429) →
  `pipeline.detect` at `auth.detect_size` + `quality.analyze` (422 with the first piece of advice and the quality
  result; not logged, not counted) → `pipeline.embed` on that one face only → liveness, when a model is loaded and mode `enforce` (401) → `matcher.identify(…, auth.face_mode)` must be `match`
  → the matched person must be linked to an active user (`users.person_id`, unique) → session with method `face`.
  There are no separate face templates: the People page's samples are the templates, and deleting the person
  unlinks the account (`ON DELETE SET NULL`).
- **Roles**: `admin` may manage users, only from a password session; `staff` uses the whole console.
- **First start**: with no users, creates `admin` with a random password in `data/initial_admin_credentials.txt`
  (mode 0600).

## Quality checks (`quality.py`, thresholds in `auth.quality`)
`one_face` · `face_size` (width fraction and px) · `centered` · `sharpness` · `brightness` · `frontal` (yaw from nose
vs eye midpoint) · `level` (eye-line roll) · `detector_confidence`. Heuristics for a 640×480 webcam — tune per camera.

## CLI — users
```bash
facegate user list
facegate user add <username> [--name] [--role admin|staff] [--person-id ID | --employee-id EMP] [--password]
facegate user link <username> (--person-id ID | --employee-id EMP | --unlink)
facegate user passwd <username> [--password]
facegate user remove <username>          # refuses to remove the last admin
```
Omit `--password` to be prompted (keeps it out of shell history). Needs only the database, not the models.
