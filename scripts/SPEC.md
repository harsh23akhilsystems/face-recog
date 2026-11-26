# Spec — `scripts/` (model download and conversion)

One-off tools run from the project root. Not imported by the server.

## Files
| File | Make target | Responsibility |
|---|---|---|
| `download_models.py` | `make models` | Fetch SCRFD + ArcFace |
| `export_adaface_onnx.py` | `make adaface` | Convert an AdaFace PyTorch checkpoint to ONNX |

## `download_models.py`
- Downloads InsightFace `buffalo_l.zip` (~280 MB) to a temp folder and extracts only `det_10g.onnx` and
  `w600k_r50.onnx` into `models/` (`--out` to change).
- Skips the download if both files exist (`--force` to re-download).
- Fails if the archive lacks either file.
- Licence: research-only weights — see `SECURITY.md`.

## `export_adaface_onnx.py`
Input: an official AdaFace checkpoint (https://github.com/mk-minchul/AdaFace#pretrained-models).

1. Rebuilds the IR backbone (`BasicBlockIR`, `IRBackbone`) with **the same module names** as AdaFace's `net.py`.
   Supported `--arch`: `ir_18`, `ir_34`, `ir_50`, `ir_101`.
2. Loads `state_dict` keys prefixed `model.` with `strict=True` — a wrong `--arch` fails loudly instead of
   silently producing bad embeddings. Head weights are ignored.
3. Exports ONNX (opset 17, input `input` `[batch, 3, 112, 112]`, output `embedding` `[batch, 512]`, dynamic batch).
   The raw 512-d vector is exported; FaceGate L2-normalises at runtime.
4. Parity check: runs ONNX Runtime and PyTorch on the same input; aborts if `max|torch − onnx| ≥ 1e-3`.

`--random-init` exports untrained weights for smoke tests only (verified: IR-101 = 65.2 M params, parity 1.3e-6).

Requires the `export` extra (`make install-export`: torch CPU + onnx). Torch is never a runtime dependency.

```bash
make install-export
make adaface ADAFACE_CKPT=~/Downloads/adaface_ir101_webface12m.ckpt ADAFACE_ARCH=ir_101
# or directly:
.venv/bin/python scripts/export_adaface_onnx.py --ckpt X.ckpt --arch ir_50 --out models/adaface_ir50.onnx
```
After exporting a new model: set `recognizers.adaface.file` if the name differs, restart, run `facegate reembed`.
