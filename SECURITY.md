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
- All user-supplied text is HTML-escaped in the console.
- Model weights and the database are excluded from git (`.gitignore`).

## What the operator must do before production
1. **Lawful basis & consent** — written notice/consent from every enrolled person; signage where cameras run.
   Offer a non-biometric alternative for attendance where required.
2. **Authentication** — the API and console have **no login** in v1. Run on a trusted network segment only, behind
   a reverse proxy (nginx/Caddy/Traefik) with SSO or basic auth, and TLS (TLS is also needed for webcams on
   non-localhost machines).
3. **Encrypt at rest** — put `data/` on an encrypted volume; restrict file permissions to the service user.
4. **Access policy** — who can enroll, who can view the activity log, how long logs are kept.
5. **Data subject requests** — delete via People → Delete person (or `DELETE /api/v1/people/{id}`).
6. **Bias check** — run `make evaluate` on a demographically representative sample of your staff and check
   TAR/FAR per group before relying on the system.
7. **Human in the loop** — do not use `uncertain`/`unknown` results for automated adverse decisions.

## Spoofing
v1 has **no liveness detection**: a printed photo or a phone screen can be recognised. Do not use it as the sole
factor for physical access control. Use `strict` mode plus a second factor (badge/PIN), or add a liveness model
(see `ARCHITECTURE.md` → Extending).

## Model licences
| Model | Source | Licence of weights |
|---|---|---|
| SCRFD `det_10g`, ArcFace `w600k_r50` | InsightFace `buffalo_l` | **Non-commercial research only**; commercial licence available from InsightFace |
| AdaFace IR-101 / IR-50 | github.com/mk-minchul/AdaFace (code MIT) | Weights trained on WebFace4M/12M, MS1MV2 — datasets with **research-only** terms |

Using these weights in a commercial product without a licence is the operator's legal risk. Options: buy a
commercial licence, use commercially licensed models, or train on data you have rights to (the pipeline accepts
any 112×112 → 512-d ONNX recognizer and any SCRFD-format detector).
