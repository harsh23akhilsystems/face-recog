---
name: run-console
description: Start, verify and troubleshoot the FaceGate FastAPI server and web console. Use when the user wants to run the app, open the UI, call an API endpoint, use a webcam from another machine, or the console shows an error.
---

# Run the console

```bash
make serve                  # http://localhost:8100  ·  /docs (Swagger)
make dev                    # auto-reload
PORT=9000 make serve
```

## Smoke test
```bash
curl -s localhost:8100/api/v1/health | jq '{status, mode, models: [.models[] | {name, loaded}]}'
curl -s -F image=@photo.jpg localhost:8100/api/v1/recognize | jq '.faces[] | {status, name: .person.name, score}'
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| Pill says "Degraded · models missing" / API 503 | Load the `setup-models` skill |
| "Camera access needs HTTPS…" | Webcams only work on `localhost` or HTTPS. Use a TLS reverse proxy for remote machines |
| "Camera permission was denied" | Allow camera in the browser's address-bar site settings |
| Everyone shows as Unknown | Person has no samples / is inactive, or thresholds too high — check Settings and `calibrate-thresholds` |
| Wrong person matched | Raise threshold or use `strict` mode; check for mislabeled samples in People |
| Slow live view | CPU: lower `detector.input_size` to [480, 480], disable AdaFace, or use GPU (`setup-models`) |
| Port in use | `PORT=8101 make serve` |
| Stale UI after editing JS/CSS | Hard refresh (assets are served with `Cache-Control: no-cache`) |

## Frontend structure
`frontend/index.html` → `assets/js/app.js` (router, health pill, theme) → `pages/*.js` (`render` + `mounted`) →
`ui.js` (icons, esc, toasts, modals, drawFaces, meters) · `api.js` · `camera.js`. Tokens at the top of `assets/css/styles.css`.
To add a page: create `pages/<name>.js`, register in `ROUTES` in `app.js`, add a nav link, document in `frontend/SPEC.md`.
