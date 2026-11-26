# Architecture

## Components

```
            ┌──────────────────────────── browser ────────────────────────────┐
            │ frontend/ (vanilla ES modules)                                  │
            │  app.js router ─ pages/{overview,live,people,verify,activity,   │
            │                         settings}.js ─ api.js ─ camera.js       │
            └───────────────────────────────┬─────────────────────────────────┘
                                            │ HTTP (multipart frames, JSON)
┌───────────────────────────────────────────▼─────────────────────────────────────────────┐
│ api/main.py  FastAPI — /api/v1/*, static console at /                                    │
│   └─ FaceService (service.py) — enrollment gates · duplicate check · event cooldown ·    │
│        │                         runtime settings (data/settings.json)                  │
│        ├─ FacePipeline (vision/pipeline.py) — owns all ONNX sessions, serialised by lock │
│        │     ├─ SCRFDDetector (vision/detector.py)                                        │
│        │     ├─ norm_crop / sharpness (vision/align.py)                                   │
│        │     └─ ArcFaceRecognizer, AdaFaceRecognizer (vision/recognizer.py)               │
│        ├─ Matcher (gallery/matcher.py) — in-memory per-model index, rebuilt on change     │
│        └─ GalleryStore (gallery/store.py) — SQLite: people · samples · embeddings · events│
└──────────────────────────────────────────────────────────────────────────────────────────┘
CLI (cli.py) and evaluation.py use the same FaceService / FacePipeline.
```

## Request flow — `POST /api/v1/recognize`

1. `read_image` enforces the upload size limit and decodes to BGR (`decode_image`).
2. `FacePipeline.analyze`: SCRFD → per face: 5-point similarity warp to 112×112 → sharpness → each enabled
   recognizer embeds all crops in one batch.
3. `Matcher.identify` per face: per-model person scores (max over templates) → mode decision → margin check.
4. `FaceService._maybe_log` writes an event unless the same person (or "unknown" on that source) was logged
   within `events.cooldown_seconds`.
5. Response: boxes, landmarks, status (`match`/`uncertain`/`unknown`), decision score, per-model scores, person.

## Key decisions

| Decision | Why |
|---|---|
| ONNX Runtime for all three models | One dependency, CPU/GPU parity, no torch at runtime; the AdaFace exporter is the only torch user. |
| Re-implement SCRFD decoding instead of `insightface` package | The package compiles C extensions and pulls in heavy deps; decoding is ~80 lines and fully tested. |
| Two recognizers, fused | ArcFace and AdaFace make partially independent errors; averaging reduces false accepts, `strict` mode requires agreement for access control. AdaFace's quality-adaptive margin helps on CCTV-grade frames. |
| Store embeddings per sample *and* per model | Adding/upgrading a model = `facegate reembed` from stored crops; no re-photographing staff. |
| Store aligned 112×112 crops, not photos | Minimises retained biometric data while keeping re-embedding and a visual audit trail possible. |
| SQLite + in-memory matrix | Thousands of people × ~5 samples × 512-d is a few MB; a dot product over it is sub-millisecond. Switch to FAISS only beyond ~100k templates. |
| Open-set with margin | Workplace galleries are open-set (visitors). `uncertain` is safer than a wrong name. |
| Runtime settings JSON overlay | Operators tune thresholds in the console without editing YAML or restarting. |
| Pipeline lock | Predictable CPU latency under several concurrent camera streams; remove if serving on GPU with batching. |

## Extending

- **New recognizer**: subclass `OnnxRecognizer`, register in `RECOGNIZER_TYPES`, add to `config.yaml`, run `reembed`.
  See `.claude/skills/add-recognition-model/SKILL.md`.
- **Anti-spoofing / liveness**: add a stage in `FacePipeline.analyze` after detection; return a `live` flag and gate
  matches on it in `FaceService.recognize`. Not included — see `SECURITY.md`.
- **Multiple sites / cameras**: send a `source` per camera (already stored on events).
