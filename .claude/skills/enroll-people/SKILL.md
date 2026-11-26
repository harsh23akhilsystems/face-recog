---
name: enroll-people
description: Enroll staff into the FaceGate gallery — single person via console/API, or bulk from a folder of photos — and fix rejected photos or duplicate identities. Use when the user wants to add, import, update, deactivate or delete people or face samples.
---

# Enroll people

## Photo guidance (tell the user)
3–5 photos per person: frontal, slight left, slight right, with/without glasses; even light; face ≥ 80 px
(ideally ≥ 150 px); one person per photo; ideally captured with the deployment camera.

## Console
People → Add person → Continue opens **guided capture** (voice-guided video scan, best frame per angle auto-picked and saved; config
`enrollment.guided`). Drawer → Guided capture / Upload / Webcam for more. Each photo shows Added / reason.
If a pose never triggers on real faces, widen its `yaw`/`pitch` range in `configs/config.yaml`.

## Bulk
```bash
# staff_photos/<Full Name>[__EMPID]/*.jpg
.venv/bin/facegate enroll-dir staff_photos --department Engineering
```
Re-running appends samples to existing names (watch `max_samples_per_person`).

## API
```bash
PID=$(curl -s -H 'Content-Type: application/json' -d '{"name":"Asha Rao","employee_id":"EMP-001"}' localhost:8100/api/v1/people | jq -r .id)
curl -s -F images=@a.jpg -F images=@b.jpg localhost:8100/api/v1/people/$PID/samples | jq '.results[] | {filename, accepted, reason}'
```

## Rejection reasons → fix
| Reason | Fix |
|---|---|
| No face detected | Face cropped out, extreme angle, or tiny — retake |
| Face too small | Move closer / use the original-resolution photo |
| Low detection confidence | Frontal pose, remove occlusion (mask, hand), improve light |
| Image too blurry | Hold still / better light; threshold `enrollment.min_sharpness` |
| Looks like already-enrolled X | Either wrong photo, a duplicate profile (merge by deleting one), or genuinely similar people (twins) — raise `duplicate_threshold` only if verified |
| Limit of N samples reached | Delete weak samples (low % / sharpness in the grid) first |

## Leavers
Deactivate (keeps data, never matched) or Delete (removes samples + embeddings; events keep the name).
