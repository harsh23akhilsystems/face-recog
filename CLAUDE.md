# CLAUDE.md — working in this repo

FaceGate: workplace face recognition — SCRFD detection, ArcFace + AdaFace recognition (ONNX Runtime),
SQLite gallery, FastAPI backend, no-build web console. Read `README.md`, then `ARCHITECTURE.md`
and the `SPEC.md` inside the folder you are changing (map in `PRODUCT_SPEC.md`).

## Commands
- Python lives in `.venv` (3.12, created with `uv`). Always use `.venv/bin/python` / `make`.
- `make install` → `make models` → `make serve` (http://localhost:8100). `make test` and `make lint` before finishing.
- AdaFace needs `make install-export` + `make adaface ADAFACE_CKPT=…` (torch is export-only, never a runtime dep).

## Skills (`.claude/skills/`)
`setup-models` · `run-console` · `enroll-people` · `calibrate-thresholds` · `add-recognition-model` — load the matching one first.

## Conventions
- All tunables in `configs/config.yaml`; no magic numbers in code paths a user may want to change.
  Operator-adjustable values (mode, thresholds, margin, logging) are also in `RUNTIME_KEYS` in `service.py`.
- All inference goes through `FacePipeline`; only it owns ONNX sessions. API/CLI call `FaceService`, never the store directly
  for writes that need business rules (enrollment, events).
- Embeddings are always L2-normalised float32; similarity is a plain dot product.
- Alignment uses the single ArcFace 5-point template in `vision/align.py` — both recognizers depend on it.
- Preprocessing per model is part of the model contract (`src/facegate/vision/SPEC.md`): ArcFace RGB, AdaFace **BGR**.
  Changing it silently destroys accuracy — the real-model smoke test will not catch it; re-run `make evaluate`.
- Never store raw uploaded photos. Only the 112×112 aligned crop (if `store_thumbnails`) and vectors.
- Missing models must degrade (503 with a clear message / console notice), never crash startup.
- Frontend: vanilla ES modules, no build step. Pages export `title`, `render` (HTML) and `mounted` (wire-up; may
  return a cleanup fn). Use CSS tokens from `styles.css`; support both themes; status must carry text, not only colour.
  Escape all user data with `esc()`.
- Style: ruff (line length 120), type hints, module docstrings explaining *why*.
- Specs live next to the code: one `SPEC.md` per folder (`src/facegate/`, `vision/`, `gallery/`, `api/`, `frontend/`,
  `scripts/`, `tests/`) plus root `PRODUCT_SPEC.md` and `SECURITY.md`. When behaviour changes, update that folder's
  `SPEC.md` in the same change. Do not recreate a `docs/specs/` folder.

## Gotchas
- Tests use a temp config via `FG_CONFIG` / `FG_ROOT` and a `FakePipeline` (tests/conftest.py); they never touch `data/`.
  Use PNG (not JPEG) in API tests — fake identities are encoded in exact pixel values.
- `onnx` is only installed with the `export` extra; `_detect_normalisation` must work without it.
- `getUserMedia` only works on `localhost` or HTTPS.
- InsightFace / AdaFace pretrained weights are research-licensed — flag this whenever deployment comes up.
