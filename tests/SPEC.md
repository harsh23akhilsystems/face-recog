# Spec — `tests/` (test strategy)

Run with `make test`. No model weights or network are needed, and `data/` is never touched.

## Files
| File | Tests |
|---|---|
| `conftest.py` | Fixtures: temp config + DB via `FG_CONFIG` / `FG_ROOT`; `FakeDetector`, `FakeRecognizer`, `FakePipeline`; `face_image()`, `prototype()` |
| `test_vision.py` | Alignment maths, SCRFD decoders, NMS, `l2_normalize`; real-model smoke test |
| `test_service.py` | Enrollment rules, identification, all modes, margin, inactive people, cooldown, verify, settings persistence, cascade delete, ROC maths |
| `test_api.py` | Every endpoint and error code (404, 409, 413/422, 503) through FastAPI's TestClient |

## How the fakes work
Synthetic images encode identity in pixel `[0, 0]` = `(identity, variant, n_faces)`; identity 0 means "no face".
`FakePipeline.analyze` returns faces whose embeddings are the identity's random-but-fixed prototype plus small
noise per variant, so same-identity photos score ≈ 0.95 and different identities ≈ 0. The second face in a
multi-face image is a different identity. Use **PNG** in API tests — JPEG would blur the encoding pixel.

## Real-model smoke test
`test_real_models_smoke` runs only when `models/det_10g.onnx` exists: a blank image yields no faces, and every loaded
recognizer returns unit-norm 512-d vectors. It checks wiring, not accuracy — accuracy is measured with
`make evaluate` (see `src/facegate/SPEC.md`).

## Rules
- Keep tests independent of real weights; add fake behaviour to `conftest.py` instead.
- Every new business rule in `service.py` or `matcher.py` gets a test in `test_service.py`; every new endpoint
  gets one in `test_api.py`.
- `make test` and `make lint` must pass before finishing a change.
