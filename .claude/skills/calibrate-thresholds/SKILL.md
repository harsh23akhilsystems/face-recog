---
name: calibrate-thresholds
description: Measure recognition accuracy (ROC, EER, TAR@FAR) for ArcFace, AdaFace and fusion on the company's own labelled faces and pick thresholds / matching mode. Use when the user asks about accuracy, false accepts/rejects, thresholds, comparing ArcFace vs AdaFace, or which mode to use.
---

# Calibrate thresholds

## 1. Build an evaluation set
`root/<person>/*.jpg` — ≥ 20 people (more is better), ≥ 3 images each, from the **deployment camera and lighting**,
**not** the enrollment photos. Keep it in `data/` (git-ignored; it is biometric data).

## 2. Run
```bash
make evaluate DATA=data/eval_faces           # → reports/evaluation.json
.venv/bin/facegate evaluate data/eval_faces --target-far 1e-4   # stricter target
```

## 3. Read the report (per model and `fusion`)
- `auc` (→ 1.0), `eer` (→ 0): overall separability. Compare models; fusion should be ≥ the best single model.
- `genuine_mean` vs `impostor_max`: the gap is your safety margin.
- `tar_at_far`: `null` means too few impostor pairs to estimate that FAR — add more people.
- `recommended.threshold`: lowest threshold with FAR ≤ target. If `reliable: false`, there were too few impostor
  pairs and the EER point was used instead — treat it as a rough starting value and collect more people.

## 4. Apply
Settings page sliders (persist to `data/settings.json`), or `PUT /api/v1/settings`:
```bash
curl -s -X PUT -H 'Content-Type: application/json' localhost:8100/api/v1/settings \
  -d '{"thresholds":{"arcface":0.34,"adaface":0.31},"fusion_threshold":0.32}'
```
For permanent defaults edit `recognizers.*.threshold` / `matching.fusion_threshold` in `configs/config.yaml`.

## Choosing a mode
| Use case | Mode |
|---|---|
| Attendance, reception | `fusion` |
| Door assist / high-security (with second factor) | `strict` |
| Very low-quality CCTV | `adaface` or `fusion` |
| CPU-bound, clear frontal faces | `arcface` (disable AdaFace in config) |

Raise `matching.margin` if look-alikes get confused; check per-demographic-group metrics before production
(`SECURITY.md`).
