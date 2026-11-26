# models/

ONNX weights live here and are git-ignored. Expected files (names configurable in `configs/config.yaml`):

| File | Model | How to get it |
|---|---|---|
| `det_10g.onnx` | SCRFD-10GF detector + 5 landmarks | `make models` |
| `w600k_r50.onnx` | ArcFace ResNet-50 (WebFace600K) | `make models` |
| `adaface_ir101_webface12m.onnx` | AdaFace IR-101 (WebFace12M) | download the `.ckpt`, then `make install-export adaface ADAFACE_CKPT=…` |

See `src/facegate/vision/SPEC.md` for preprocessing details and `SECURITY.md` for licences.
