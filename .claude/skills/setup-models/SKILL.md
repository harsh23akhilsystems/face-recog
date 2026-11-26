---
name: setup-models
description: Install, download, convert or swap the SCRFD detector and ArcFace / AdaFace recognition models (ONNX). Use when models are missing, the console says "Degraded", the user has an AdaFace .ckpt to convert, wants GPU inference, or wants a different model file.
---

# Set up models

## Default set
```bash
make install          # once
make models           # det_10g.onnx (SCRFD) + w600k_r50.onnx (ArcFace) into models/
make status           # each model: loaded / error
```

## AdaFace (.ckpt → ONNX)
1. User downloads a checkpoint from https://github.com/mk-minchul/AdaFace#pretrained-models
   (IR-101 WebFace12M recommended; IR-50 variants are smaller/faster).
2. ```bash
   make install-export
   make adaface ADAFACE_CKPT=/path/adaface_ir101_webface12m.ckpt ADAFACE_ARCH=ir_101
   ```
   For IR-50: `ADAFACE_ARCH=ir_50` and set `recognizers.adaface.file` in `configs/config.yaml` to the output name
   (or pass `--out` to the script directly).
3. Parity line must print `max |torch - onnx|` < 1e-3. `load_state_dict` errors = wrong `--arch`.
4. Restart the server; if people were enrolled before AdaFace existed: `facegate reembed`
   (or `POST /api/v1/admin/reembed`).

## GPU
`uv pip install --python .venv/bin/python onnxruntime-gpu` (and uninstall `onnxruntime`). `runtime.providers`
already lists CUDA first; `/health` shows the provider actually used per model.

## Swapping a model file
Change `detector.file` / `recognizers.<name>.file`. Recognizers must take 112×112 aligned crops and output a vector;
set `channel_order` correctly (ArcFace exports: `rgb`; AdaFace: `bgr`). **Changing the recognizer invalidates
stored embeddings** → run `reembed`, then recalibrate (`calibrate-thresholds` skill).

## Troubleshooting
| Symptom | Fix |
|---|---|
| `Model file not found` | File name in config ≠ file in `models/` |
| `Unsupported SCRFD export with N outputs` | Not an SCRFD export; use `det_10g.onnx` or `scrfd_*_kps.onnx` |
| `has no landmark head` | Use a `_kps` SCRFD variant — alignment needs landmarks |
| Scores all ~0.9 for everyone | Wrong channel order / normalisation, or random weights. Check `channel_order`, re-export |
| Licence questions | `SECURITY.md` — buffalo_l and AdaFace weights are research-only |
