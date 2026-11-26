# Spec — `vision/` (detection, alignment, recognition)

Turns an image into faces with embeddings. Only this folder touches ONNX Runtime.

## Files
| File | Responsibility |
|---|---|
| `detector.py` | `SCRFDDetector` — letterbox, run SCRFD, decode anchors, NMS; helpers `distance2bbox`, `distance2kps`, `nms` |
| `align.py` | `ARCFACE_TEMPLATE`, `estimate_norm`, `norm_crop` (112×112 warp), `sharpness` |
| `recognizer.py` | `OnnxRecognizer` base, `ArcFaceRecognizer`, `AdaFaceRecognizer`, `RECOGNIZER_TYPES`, `l2_normalize` |
| `pipeline.py` | `FacePipeline` — loads all models (incl. optional liveness, role `liveness` in `ModelStatus`), `analyze()` = detect → align → embed, `detect(img, input_size?)`, `embed(img, faces)`, `check_liveness()`, `warmup()` (one run per model at startup so the first request is not slow); `decode_image`, `encode_jpeg` |
| `liveness.py` | `MiniFASLiveness` — optional passive anti-spoof for face sign-in: 1.5× square crop, 128 px, RGB/255, score = real − spoof logit |
| `onnx_utils.py` | `create_session`, `available_providers` (CUDA → CPU) |
| `types.py` | `Face` dataclass (bbox, score, kps, embeddings, crop, sharpness) |

## Detector — SCRFD
| | |
|---|---|
| File | `det_10g.onnx` (SCRFD-10GF with keypoints, InsightFace `buffalo_l`) |
| Input | letterboxed to `detector.input_size` (640×640), top-left aligned, zero padding; RGB; `(x − 127.5) / 128` |
| Outputs | 9 tensors = 3 strides (8/16/32) × {score, bbox distances, 5-kps offsets}; 2 anchors per location |
| Decode | anchor centres × stride; `distance2bbox`, `distance2kps`; scale back by letterbox ratio |
| Post | score ≥ `score_threshold` (0.5) → NMS IoU `nms_threshold` (0.4) → top `max_faces` → sorted by area (largest first) |
| Also supported | exports with 6/10/15 outputs (layout detected from output count); models without kps are rejected |

## Alignment
Similarity transform (rotation, uniform scale, translation; `cv2.estimateAffinePartial2D`, LMEDS) from the 5 detected
landmarks to the ArcFace template, warped to 112×112:

```
(38.2946, 51.6963) (73.5318, 51.5014) (56.0252, 71.7366) (41.5493, 92.3655) (70.7299, 92.2041)
```
Both recognizers were trained on this exact warp — keep `align.py` the single source of the template.
Sharpness = variance of Laplacian on the aligned grey crop (used by the enrollment gate).

## Recognizers
| | ArcFace | AdaFace |
|---|---|---|
| File | `w600k_r50.onnx` | `adaface_ir101_webface12m.onnx` (exported, see `scripts/SPEC.md`) |
| Backbone | ResNet-50 (iresnet) | IR-101 (65.2 M params) |
| Training data | WebFace600K | WebFace12M |
| Loss | additive angular margin | quality-adaptive margin (feature-norm proxy) |
| Input | 112×112 **RGB**, `(x − 127.5) / 127.5` | 112×112 **BGR**, `(x/255 − 0.5)/0.5` ≡ `(x − 127.5) / 127.5` |
| Output | 512-d, L2-normalised by FaceGate | 512-d raw (BN1d output), L2-normalised by FaceGate |
| Strength | very high accuracy on clear frontal faces | robust to blur, low light, low resolution |

`channel_order: auto` uses the class default above. For ArcFace, if the ONNX graph's first nodes are named
`Sub…`/`_minus…` **and** `Mul…`/`_mul…` (normalisation baked in), raw 0–255 input is fed (same rule as InsightFace).
This check needs the optional `onnx` package and silently falls back to 127.5/127.5 without it.

## Pipeline behaviour
- Missing or broken model file → that model is skipped and reported in `status()` (never a crash).
- `ready` = detector loaded **and** ≥ 1 recognizer loaded.
- All recognizers embed all faces of a frame in one batch.
- One lock serialises inference to keep CPU latency predictable under several camera streams.

## Performance
Measured on the dev machine (8 logical CPUs, onnxruntime 1.32 CPU provider, 1280×886 photo, 6 faces batched):
SCRFD-10GF 640² ≈ 90 ms/frame · ArcFace R50 ≈ 85 ms/face · AdaFace IR-101 ≈ 80 ms/face.
So one frame with 3 faces and both recognizers ≈ 0.6 s on CPU. For faster live view use a CUDA GPU
(`onnxruntime-gpu`), `detector.input_size: [480, 480]`, or a single recognizer.
