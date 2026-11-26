# Spec — `api/` (REST API and console hosting)

## Files
| File | Responsibility |
|---|---|
| `main.py` | `create_app()`, `/api/v1` endpoints, `require_ready`, `/login` page, console at `/` (redirects to `/login` when signed out), asset revalidation; creates `AuthService` + first-start admin in `lifespan` |
| `auth_routes.py` | `/auth/*`: password + face sign-in, quality check, logout, `me`, face status, user admin, login events |
| `deps.py` | Shared dependencies: `get_service`, `get_auth`, `read_image`, `client_id`, `current_session`, `admin_session` |
| `schemas.py` | JSON bodies: `PersonCreate`, `PersonUpdate`, `RuntimeSettingsPatch` |

## Rules
- Base path `/api/v1`. Interactive docs at `/docs`.
- **Every `/api/v1` route except `/health` needs a session** (HttpOnly `fg_session` cookie, SameSite=Lax) → 401
  otherwise. `/health` is public but, signed out, returns only `{status, ready, version, app, signed_in: false}`.
- The API never runs inference directly — it calls `FaceService`. Inference handlers are sync `def` so FastAPI runs
  them in its threadpool.
- Images are `multipart/form-data` (JPEG/PNG/WebP/BMP, ≤ `api.max_upload_mb`).
- Errors: `{"detail": "<human-readable message>"}` — the console shows it verbatim.
- `/assets/*` is served with `Cache-Control: no-cache` (no build step / hashed names).

| Status | Meaning |
|---|---|
| 401 | not signed in; bad credentials; face not recognised / liveness failed |
| 403 | admin-only route; admin route from a face session; face sign-in turned off |
| 404 | person / sample / thumbnail / user not found |
| 409 | duplicate `employee_id` |
| 413 | upload too large |
| 422 | invalid body, undecodable image, no face (verify), unknown mode, face sign-in framing problem (advice in `detail`), invalid user data |
| 429 | sign-in locked: ≥ `max_failed_per_user` password failures for the username, or ≥ `max_failed_face_per_client` face failures from the IP, within `lock_window_minutes` |
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

## Sign-in (`/auth`, no `/api/v1` prefix)
| Method | Path | Access | Body | Notes |
|---|---|---|---|---|
| POST | `/auth/login` | public | `{username, password}` | sets the session cookie → `{user, method: "password"}` |
| POST | `/auth/face` | public | multipart `image` | quality → liveness → match in `auth.face_mode` → linked active user → `{user, method: "face", score}` |
| POST | `/auth/quality` | public | multipart `image` | `{ok, issues[], advice[], checks[], face:{box:[x,y,w,h] relative, score}, faces_found, image_size}`; nothing stored |
| GET | `/auth/face/status` | public | | `{available, any_enrolled, liveness}` — no user data |
| POST | `/auth/logout` | any | | ends the session, clears the cookie |
| GET | `/auth/me` | session | | `{user, method, face}` |
| GET | `/auth/events?limit=` | admin | | login audit log, newest first |
| GET / POST | `/auth/users` | admin | `{username, password, display_name?, role?, person_id?}` | 201; 422 on duplicate username, short password, unknown or already-linked person |
| PATCH | `/auth/users/{id}` | admin | any of `display_name, role, person_id ("" unlinks), password` | password change ends that user's sessions; 409 demoting the last admin |
| DELETE | `/auth/users/{id}` | admin | | 204; soft delete (audit trail kept), sessions ended; 409 on yourself |

`user` = `{id, username, display_name, role, person_id, face_login, created_at}` (`GET /auth/users` adds `person_name`).
The People page uses these routes to create a person's login at registration time. "admin" = role `admin` **and** a
password session. Face-sign-in framing failures (422) are logged as `rejected` and do not count towards lockout.
