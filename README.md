# FaceGate

**Workplace face recognition** — SCRFD face detection with two recognition models, **ArcFace** and **AdaFace**,
fused for accuracy. Served by FastAPI, with a clean web console for live camera recognition, staff enrollment,
1:1 verification and an activity log.

```
camera / photo ─▶ SCRFD (boxes + 5 landmarks) ─▶ 5-point alignment (112×112)
                                                   ├─▶ ArcFace R50  ─▶ 512-d ┐
                                                   └─▶ AdaFace IR101 ─▶ 512-d ┴─▶ gallery match (fusion / strict) ─▶ name or "unknown"
```

| | |
|---|---|
| **Detection** | SCRFD-10GF (`det_10g.onnx`), 640×640 letterbox, 5-point landmarks |
| **Recognition** | ArcFace ResNet-50 (`w600k_r50.onnx`) + AdaFace IR-101 (`adaface_ir101_webface12m.onnx`) |
| **Matching** | Cosine similarity, 4 modes: `fusion` (default), `strict`, `arcface`, `adaface`; open-set with an uncertainty margin |
| **Runtime** | ONNX Runtime (CPU or CUDA) — no PyTorch at serving time |
| **Storage** | One SQLite file: people, aligned face thumbnails, embeddings, events. No raw photos are kept |
| **UI** | No-build vanilla JS console, light/dark, keyboard-accessible |

---

## Quick start

```bash
make install            # .venv (Python 3.12, via uv) + deps
make models             # SCRFD + ArcFace from InsightFace buffalo_l (~280 MB download, keeps 2 files)
# AdaFace: see "AdaFace" below (optional — the system runs on ArcFace alone)
make serve              # http://localhost:8100  ·  API docs at /docs
```

On first start the server creates the user **`admin`** and writes its random password to
`data/initial_admin_credentials.txt` (owner-only). Open http://localhost:8100 → you land on **/login** → sign in,
then delete that file and create real accounts with `facegate user add` (see **Sign-in** below).

Then in the console: **People → Add person → upload 3–5 photos**, and open **Live recognition**.

> Webcam access requires `http://localhost` or HTTPS. To use cameras on other machines, put FaceGate behind a
> TLS reverse proxy (see `SECURITY.md`).

### AdaFace

AdaFace publishes PyTorch checkpoints, not ONNX. Download one from the
[official repo](https://github.com/mk-minchul/AdaFace#pretrained-models) (recommended:
`adaface_ir101_webface12m.ckpt`), then:

```bash
make install-export                                   # adds torch (CPU) + onnx
make adaface ADAFACE_CKPT=~/Downloads/adaface_ir101_webface12m.ckpt ADAFACE_ARCH=ir_101
```

The exporter rebuilds the IR backbone, loads the weights with `strict=True` (so an architecture mismatch fails
loudly), exports ONNX and checks PyTorch/ONNX parity. For IR-50 checkpoints use `ADAFACE_ARCH=ir_50`.
If you already have your own AdaFace ONNX, drop it in `models/` and set `recognizers.adaface.file`.

If a model is missing the server still starts; the console shows exactly which file is needed, and matching
falls back to the available model.

---

## Using it

| Page | What it does |
|---|---|
| **Overview** | KPIs, model health, today's activity by hour, latest recognitions |
| **Live recognition** | Webcam stream (or photo upload) with boxes, names, and per-model score meters |
| **People** | Add/edit/deactivate/delete staff; enroll by upload or webcam with instant per-photo quality feedback |
| **Verify 1:1** | Are these two photos the same person? Both models' scores vs thresholds. Nothing is stored |
| **Activity log** | Every recognition (with cooldown), filter by status, CSV export |
| **Settings** | Matching mode, thresholds, uncertainty margin, logging — applied live, persisted to `data/settings.json` |

### Sign-in

The console and every `/api/v1` route (except `/health`) need a signed-in session. The login page (`/login`) offers:

- **Password** — an admin creates logins on the **People** page (Add person → *Login*, or a person's
  *Sign-in account* section), or with the CLI / admin API (`/auth/users`).
- **Face** — for users whose account is *linked* to their person in the gallery. It uses the same SCRFD + ArcFace /
  AdaFace models and the same enrolled photos as recognition, matched in `auth.face_mode` (`strict` by default). The
  camera view guides the user (scan animation, "move closer", "too dark", …) and only submits a frame once it passes
  the quality checks. An optional MiniFAS liveness model (`auth.liveness`) rejects photos and screens.

```bash
facegate user add alice --name "Alice Rao" --employee-id E104    # prompts for the password; links face sign-in
facegate user add ops-lead --role admin                          # admin = may manage users (password session only)
facegate user link bob --employee-id E221                        # enable face sign-in for an existing user
facegate user link bob --unlink
facegate user passwd alice                                       # also ends alice's sessions
facegate user list
facegate user remove bob
```

Settings live under `auth:` in `configs/config.yaml` (session length, lockout, `cookie_secure` for HTTPS, quality
thresholds, liveness). Behind HTTPS set `auth.cookie_secure: true`.

### CLI

```bash
.venv/bin/facegate status                         # models + gallery
.venv/bin/facegate enroll-dir staff_photos/       # staff_photos/<Full Name>[__EMPID]/*.jpg
.venv/bin/facegate identify photo.jpg --mode strict
.venv/bin/facegate verify a.jpg b.jpg
make evaluate DATA=path/to/labelled_faces         # threshold calibration report → reports/evaluation.json
```

### Choosing thresholds

Defaults (cosine 0.30) suit clear frontal photos. **Calibrate on your own people and cameras**: collect a
folder `root/<person>/*.jpg` (≥ 20 people, ≥ 3 images each, captured with the real camera) and run
`make evaluate DATA=root`. The report gives AUC, EER, TAR@FAR and a recommended threshold for ArcFace, AdaFace
and fusion. Details: `src/facegate/gallery/SPEC.md` and `src/facegate/SPEC.md` → Evaluation.

---

## Project layout

```
configs/config.yaml          every tunable (paths, thresholds, quality gates, providers)
src/facegate/
  config.py                  typed settings (pydantic) — FG_CONFIG / FG_ROOT overrides
  vision/                    detector.py (SCRFD) · align.py · recognizer.py (ArcFace/AdaFace) · pipeline.py
  gallery/                   store.py (SQLite) · matcher.py (1:N, fusion/strict, margin)
  service.py                 business rules: enrollment gates, duplicates, events, runtime settings
  evaluation.py              ROC / EER / TAR@FAR threshold calibration
  auth.py                    sign-in: users, sessions, audit log, password + face sign-in, lockout
  quality.py                 live-camera framing/lighting checks for face sign-in
  api/                       FastAPI app (REST under /api/v1, sign-in under /auth, login page at /login, console at /)
  cli.py                     facegate <command>
frontend/                    index.html (console) · login.html (sign-in) + assets/{css,js/pages,img} — no build
scripts/                     download_models.py · export_adaface_onnx.py
tests/                       fake-pipeline unit/API tests + real-model smoke test (auto-skips without weights)
.claude/skills/              task playbooks for Claude Code
ARCHITECTURE.md · PRODUCT_SPEC.md · SECURITY.md      project-wide docs
*/SPEC.md                    each code folder documents itself (see the spec map in PRODUCT_SPEC.md)
```

## Troubleshooting

### Camera: "could not be opened" / "in use by another application" (Linux laptops)
If no app is using the camera (`fuser -v /dev/video0` prints nothing) but it still fails, check whether the camera
keeps dropping off USB: `journalctl -k -b | grep -c "USB disconnect"`. Some integrated webcams (e.g. Luxvisions
30c9:0014 in ThinkPad L14) fail to wake from **USB autosuspend**. Turn autosuspend off for that camera:

```bash
lsusb | grep -i camera                       # note ID vvvv:pppp and find its port: grep -l pppp /sys/bus/usb/devices/*/idProduct
echo 'ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="30c9", ATTR{idProduct}=="0014", ATTR{power/control}="on"' \
  | sudo tee /etc/udev/rules.d/50-camera-no-autosuspend.rules
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=30c9
```

## Development

```bash
make dev      # auto-reload
make test     # pytest (no weights needed; real-model smoke test runs if models/ is populated)
make lint     # ruff
make format
```

Read `CLAUDE.md` for conventions and `ARCHITECTURE.md` for the design.

## Licences — read before deploying

FaceGate's code is yours. **The pretrained weights are not**: InsightFace's `buffalo_l` (SCRFD, ArcFace) is
released for **non-commercial research use**, and AdaFace weights are trained on datasets (WebFace4M/12M,
MS1MV2) with research-only terms. For commercial use, license the models or train on data you have rights to.
Face data is biometric personal data in most jurisdictions — see `SECURITY.md`.
