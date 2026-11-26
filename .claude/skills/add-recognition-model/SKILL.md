---
name: add-recognition-model
description: Add a new face recognition (embedding) model — e.g. a commercially licensed ArcFace, MagFace, ElasticFace, TransFace, or an AdaFace variant — to the pipeline, matcher, settings and console. Use when the user wants to plug in, benchmark or replace a recognizer.
---

# Add a recognition model

Contract: input = 112×112 face aligned by `vision/align.py` (ArcFace template), output = one vector per face.
FaceGate L2-normalises and uses cosine similarity.

1. **Get an ONNX file** into `models/`. From PyTorch, copy the pattern of `scripts/export_adaface_onnx.py`
   (rebuild backbone with identical module names → `strict=True` load → dynamic-batch export → parity check).
2. **Recognizer class** in `src/facegate/vision/recognizer.py`:
   ```python
   class MagFaceRecognizer(OnnxRecognizer):
       default_channel_order = "rgb"   # what the model was trained on
       # override _detect_normalisation() if mean/std differ from 127.5/127.5
   RECOGNIZER_TYPES["magface"] = MagFaceRecognizer
   ```
3. **Config** `configs/config.yaml` → `recognizers.magface: {enabled: true, file: …, channel_order: auto, threshold: 0.3}`.
4. **Fusion with 3+ models** already works (`fusion` = mean over loaded models; `strict` = all must agree).
   `effective_mode` treats `fusion`/`strict` as needing ≥ 2 models. If adding a single-model mode, extend `MatchMode`
   in `config.py`, the `mode` check in `api/main.py::recognize`, and `MODES` in `pages/live.js` + `pages/settings.js`.
5. **UI colours/labels**: add to `MODEL_LABEL` / `MODEL_COLOR` in `frontend/assets/js/ui.js` and a `--<name>` token
   (light + dark) in `styles.css`.
6. **Re-embed** stored samples: `facegate reembed`.
7. **Benchmark**: `make evaluate DATA=…` — keep the model only if it improves fusion AUC/TAR@FAR.
8. **Tests**: extend `tests/conftest.py::FakePipeline` models tuple if logic changes; `make test lint`.
9. **Docs**: add a column to the recognizer table in `src/facegate/vision/SPEC.md` and a row to the licence table in `SECURITY.md`.
