# Spec — `api/` (REST API and console hosting)

## Files
| File | Responsibility |
|---|---|
| `main.py` | `create_app()`, all endpoints, upload checks (`read_image`), `require_ready`, static console at `/`, asset revalidation |
| `schemas.py` | JSON bodies: `PersonCreate`, `PersonUpdate`, `RuntimeSettingsPatch` |

## Rules
- Base path `/api/v1`. Interactive docs at `/docs`.
- The API never runs inference directly — it calls `FaceService`. Inference handlers are sync `def` so FastAPI runs
  them in its threadpool.
- Images are `multipart/form-data` (JPEG/PNG/WebP/BMP, ≤ `api.max_upload_mb`).
- Errors: `{"detail": "<human-readable message>"}` — the console shows it verbatim.
- `/assets/*` is served with `Cache-Control: no-cache` (no build step / hashed names).

| Status | Meaning |
|---|---|
| 404 | person / sample / thumbnail not found |
| 409 | duplicate `employee_id` |
| 413 | upload too large |
| 422 | invalid body, undecodable image, no face (verify), unknown mode |
| 503 | required models not loaded — message lists the missing files |

## System
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `status` ok/degraded, `ready`, `models[]` {name, role, file, loaded, enabled, error, providers}, `mode`, counts, `app`, `organisation`, `version` |
| GET | `/stats` | people, active_people, samples, people_without_samples, events_today{status:n}, recognised_today, hourly_today{hour:n} (UTC) |
| GET | `/settings` | mode, effective_mode, fusion_threshold, margin, thresholds{model}, log_recognitions, cooldown_seconds, available_models |
| PUT | `/settings` | partial update of the same keys; persisted to `paths.runtime_settings` |
| POST | `/admin/reembed` | recompute all embeddings from stored crops → {samples, models} |

## Inference
| Method | Path | Form fields | Response |
|---|---|---|---|
| POST | `/detect` | `image` | `{width, height, faces:[{bbox, det_score, landmarks, sharpness}]}` |
| POST | `/recognize` | `image`, `mode?`, `source?` (≤ 32 chars, default `upload`), `log_events?` (bool; default from settings) | `{width, height, mode, elapsed_ms, faces:[…face, status, score, threshold, per_model, runner_up_score, person}]}` |
| POST | `/verify` | `image_a`, `image_b` | `{mode, match, fused_score, fusion_threshold, per_model:{m:{score, threshold, match}}, face_a, face_b}` |

`person` = `{id, name, employee_id, department, cover_sample_id}` or `null`. `status` ∈ `match | uncertain | unknown`.

## People
| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/people?q=` | | search name / employee_id / department; includes `sample_count`, `cover_sample_id` |
| POST | `/people` | `{name, employee_id?, department?, notes?}` | 201 |
| GET | `/people/{id}` | | + `samples[]` {id, det_score, sharpness, face_px, has_thumb, models[], created_at} |
| PATCH | `/people/{id}` | any of name, employee_id, department, notes, active | inactive people are never matched |
| DELETE | `/people/{id}` | | 204; cascades samples + embeddings; events kept with `person_id = NULL` |
| POST | `/people/{id}/samples` | `images` (repeatable) | `{accepted, results:[{filename, accepted, sample_id, reason, warnings, det_score, sharpness, face_px}], person}` |
| DELETE | `/people/{id}/samples/{sid}` | | 204 |
| GET | `/samples/{sid}/thumb` | | `image/jpeg` 112×112 aligned crop |

## Events
| Method | Path | Notes |
|---|---|---|
| GET | `/events?limit=50&status=&person_id=&since=` | newest first; `limit` ≤ 500; `since` ISO-8601 UTC |
| GET | `/events/{id}/thumb` | aligned crop at event time |

## Example
```bash
curl -s -F image=@door.jpg -F mode=strict -F source=door-1 localhost:8100/api/v1/recognize | jq '.faces[] | {status, name: .person.name, score}'
```
