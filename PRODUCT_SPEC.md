# Product spec — FaceGate

> Where the other specs live: each code folder has its own `SPEC.md` (see the map at the bottom).

## Problem
The company needs to recognise enrolled staff from a camera or photo — for attendance, reception check-in or
access-assist — with an interface that non-technical staff (HR, reception, security) can operate.

## Users
| Role | Needs |
|---|---|
| **HR / admin** | Enroll new staff quickly, get clear feedback on bad photos, deactivate leavers, delete data on request |
| **Reception / security** | See who is at the camera, notice unknown visitors, review the day's log |
| **IT / ML owner** | Install, choose models, calibrate thresholds, monitor model health, integrate via API |

## Scope (v1)
- Face detection (SCRFD) with landmarks, any number of faces per frame (cap `detector.max_faces`).
- Recognition with ArcFace and AdaFace; four matching modes; open-set (`unknown`, `uncertain`).
- Enrollment by upload or webcam, quality gates, duplicate-identity check, ≤ `max_samples_per_person` samples.
- 1:1 verification of two photos (nothing stored).
- Activity log with cooldown, filters, CSV export, retention purge.
- Live-tunable settings; threshold calibration tool.
- REST API + CLI.
- Console sign-in: password or face (linked gallery person), sessions, lockout, login audit log, admin/staff roles,
  optional passive liveness for face sign-in.

## Out of scope (v1)
Active (challenge-response) liveness · user-management pages in the console (CLI/API only) · SSO · door-controller integration ·
multi-tenant · video file processing · face clustering of unknowns. See `ARCHITECTURE.md` → Extending.

## Success criteria
- On calibrated thresholds: TAR ≥ 99 % at FAR ≤ 0.1 % on a held-out set of the company's own staff photos
  (measured with `make evaluate`).
- Live view ≥ 1.5 fps on an 8-thread CPU with ≤ 3 faces and both recognizers (measured ≈ 0.6 s/frame — see
  `src/facegate/vision/SPEC.md` → Performance); ≥ 10 fps on a CUDA GPU.
- A new employee enrolled in < 1 minute from the console, with an actionable message for every rejected photo.
- Server starts and explains what is missing when any model file is absent.

## Spec map
| Spec | Covers |
|---|---|
| `PRODUCT_SPEC.md` (this file) | users, scope, goals |
| `SECURITY.md` | privacy, consent, authentication, spoofing, model licences |
| `ARCHITECTURE.md` | how the parts fit together and why |
| `src/facegate/SPEC.md` | service rules (enrollment, events, settings), config, CLI, evaluation |
| `src/facegate/vision/SPEC.md` | SCRFD, alignment, ArcFace, AdaFace, performance |
| `src/facegate/gallery/SPEC.md` | database schema, matching modes, thresholds |
| `src/facegate/api/SPEC.md` | REST endpoints |
| `frontend/SPEC.md` | web console pages and design rules |
| `scripts/SPEC.md` | model download and AdaFace export |
| `tests/SPEC.md` | test strategy |
