# Security, privacy & licensing spec — FaceGate

Face templates are **biometric personal data** (GDPR Art. 9, India DPDP Act 2023, BIPA in Illinois, and others).
Deploying FaceGate is a legal decision as much as a technical one. This spec lists what the software does and what
the operator must do.

## What the software does
- Stores no raw photos — only the 112×112 aligned crop (optional) and embeddings.
- Deleting a person deletes all their samples and embeddings (cascade); events keep only a denormalised name.
- Event retention purge (`events.retention_days`).
- Verify 1:1 stores nothing.
- Upload size limit; images decoded by OpenCV into pixel arrays only (no EXIF/metadata parsing).
- CORS closed by default (same-origin console).
- **Sign-in required** for the console and every `/api/v1` route except a reduced `/health`: PBKDF2-SHA256
  passwords, server-side sessions (only token hashes stored, HttpOnly + SameSite=Lax cookie, `Secure` via
  `auth.cookie_secure`), lockout after repeated failures (per username / per client IP), and a login audit log
  (`login_events`). User management needs an admin **password** session. First-start admin credentials are written
  owner-only (0600) — delete the file after first sign-in.
- Face sign-in frames are processed in memory and never stored; only the outcome and score are logged.
- All user-supplied text is HTML-escaped in the console.
- Model weights and the database are excluded from git (`.gitignore`).

## What the operator must do before production
1. **Lawful basis & consent** — written notice/consent from every enrolled person; signage where cameras run.
   Offer a non-biometric alternative for attendance where required.
2. **Authentication & transport** — the console has its own sign-in (above), but run it behind a TLS reverse proxy
   (nginx/Caddy/Traefik) and set `auth.cookie_secure: true`; without TLS passwords and session cookies cross the
   network in clear text (TLS is also needed for webcams on non-localhost machines). Lockout counts per client IP —
   behind a proxy every client may appear as the proxy's IP, so configure the proxy to forward the client address
   (uvicorn `--proxy-headers --forwarded-allow-ips`). There is no SSO or MFA yet.
3. **Encrypt at rest** — put `data/` on an encrypted volume; restrict file permissions to the service user.
4. **Access policy** — who can enroll, who can view the activity log, how long logs are kept.
5. **Data subject requests** — delete via People → Delete person (or `DELETE /api/v1/people/{id}`).
6. **Bias check** — run `make evaluate` on a demographically representative sample of your staff and check
   TAR/FAR per group before relying on the system.
7. **Human in the loop** — do not use `uncertain`/`unknown` results for automated adverse decisions.

## Spoofing
**Recognition** (Live page / `/recognize`) has no liveness check: a printed photo or a phone screen can be
recognised. Do not use it as the sole factor for physical access control; use `strict` mode plus a badge/PIN.

**Face sign-in** can use a passive single-frame liveness model (MiniFAS, `auth.liveness`). Put
`face_antispoof_minifas_int8.onnx` (github.com/suriAI/face-antispoof-onnx, Apache-2.0) in `models/`. **If the file
is missing, face sign-in still works without liveness** — the Overview page shows the model as missing and every
face sign-in is logged with `liveness unavailable`. Set `auth.liveness.mode: enforce` *and* install the model, or set
`auth.face_login: false`, before exposing face sign-in where photos of staff are easy to obtain. The publisher's
accuracy (98.2 % on CelebA-Spoof) has not been measured on your cameras; a passive check raises the bar against
photos and screens but not against high-quality attacks. Face sign-in also matches in `strict` mode by default
(every loaded recognizer must agree).

## Model licences
| Model | Source | Licence of weights |
|---|---|---|
| SCRFD `det_10g`, ArcFace `w600k_r50` | InsightFace `buffalo_l` | **Non-commercial research only**; commercial licence available from InsightFace |
| MiniFAS liveness (optional) | github.com/suriAI/face-antispoof-onnx | Apache-2.0 |
| AdaFace IR-101 / IR-50 | github.com/mk-minchul/AdaFace (code MIT) | Weights trained on WebFace4M/12M, MS1MV2 — datasets with **research-only** terms |

Using these weights in a commercial product without a licence is the operator's legal risk. Options: buy a
commercial licence, use commercially licensed models, or train on data you have rights to (the pipeline accepts
any 112×112 → 512-d ONNX recognizer and any SCRFD-format detector).
