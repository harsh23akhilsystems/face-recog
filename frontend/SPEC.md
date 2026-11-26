# Spec — `frontend/` (web console)

## Files
| File | Responsibility |
|---|---|
| `index.html` | Shell: sidebar (brand, nav, status pill, theme toggle), top bar, content, toast + modal roots |
| `assets/css/styles.css` | Design tokens (light + dark) and every component style |
| `assets/js/app.js` | Router (`ROUTES`), health pill (every 30 s), theme, "models missing" notice |
| `assets/js/api.js` | One function per backend endpoint; `ApiError` with the server's `detail` |
| `assets/js/ui.js` | Icons, `esc`, avatars, formatters, toasts, modal/drawer/confirm, `drawFaces`, `meter`, `bindDropzone` |
| `assets/js/camera.js` | `Camera`: start/stop/grab/devices with readable error messages |
| `assets/js/guided.js` | `guidedCapture({name, existing, enroll, checkDuplicate})`: voice-guided face-scan modal (below) |
| `assets/js/guide-styles.js` | Five display-only guide styles (`STYLES`, `createGuide(style, svg) → {update(state)}`) — being compared; delete the losers later |
| `assets/vendor/lottie/` | lottie-web 5.12.2 **light** player (MIT, LICENSE.md alongside; no expressions/`eval`), loaded on demand |
| `assets/anim/` | Lottie JSON played by the scan: `face-scan.json` (intro), `success.json` — original artwork; README explains swapping in free LottieFiles ones |
| `assets/js/pages/*.js` | One module per page (below) |

## Principles
- **Simple first**: one primary action per page; advanced controls (mode, thresholds) are visible but secondary.
- **Explain every rejection**: enrollment and errors show the server's reason verbatim.
- **Status carries text, not only colour**: badges read "Recognised / Uncertain / Unknown / Loaded / Missing"; meters show the number and ✓/✗.
- **Both themes**: all colours come from CSS tokens (`:root` light, dark via `[data-theme=dark]` or OS preference).
- **Accessible**: keyboard reachable (dropzones are `role=button` with Enter/Space), focus rings, `aria-pressed`, `role=status/alert` toasts, reduced motion respected.
- **Safe**: all user data passes through `esc()` before entering HTML.
- **No build, no CDN**: vanilla ES modules; works on an offline intranet.

## Shell
Below 900 px the sidebar becomes an off-canvas drawer with a menu button.
Status pill: `Ready · N recognizers` (green), `Degraded · models missing` (amber), `Offline · server unreachable` (red).
Pages flagged `needsModels` show a notice listing missing model files and the command to fix it.

## Pages
| Route | File | Content |
|---|---|---|
| `#/overview` | `overview.js` | 4 KPI cards · hourly activity bars (UTC) · recent recognitions · model status (role, file, provider, Loaded/Missing/Disabled, error) · quick actions |
| `#/live` | `live.js` | Camera/Photo toggle · camera picker · Start/Stop · Log-activity, **Show unknown** (off: only recognised staff get a box / list entry) and Mirror switches · stage with box + label overlay and LIVE/fps HUD · matching-mode control (modes needing a missing model are disabled) · "In frame" panel with per-model meters |
| `#/people` | `people.js` | Search · Add person (modal → person drawer) · card grid · **drawer**: Guided capture button, Upload or Webcam capture, samples grid with ★ Profile badge and hover ★ "Set as profile photo" (with camera picker), per-photo results, samples grid with delete, details form, Active switch, Delete with confirmation |
| `#/verify` | `verify.js` | Two dropzones with previews and face boxes · Compare · verdict banner · meters per model + fusion |
| `#/activity` | `activity.js` | Status filter · Refresh · Export CSV · events table; auto-refresh 15 s |
| `#/settings` | `settings.js` | Mode cards · threshold sliders (models, fusion, margin) · logging switch + cooldown · Save / Discard |

## Live camera
- **States** shown on the stage placeholder: off (big **Start camera** button) → starting (spinner + "click Allow") →
  live, or error (message stays on the stage with **Try again**, plus a toast).
- If camera permission was already granted (`navigator.permissions`), the camera starts automatically.
- Loop: one request in flight; frames downscaled to ≤ 960 px longer side, JPEG q 0.85; 60 ms pause between requests.
- Overlay mapped through `object-fit: contain`; labels drawn un-mirrored when the video is mirrored.
- Leaving the page or stopping aborts the in-flight request and releases the device.
- The last camera used (any page) is remembered in `localStorage` (`fg-camera`) and opened by default everywhere,
  so People → Webcam uses the same device as Live (e.g. a phone camera) instead of the OS default.
- Webcams work only on `localhost` or HTTPS. Linux USB-camera failures: README → Troubleshooting → Camera.

## Guided capture (`guided.js`)
- Opens automatically after **Add person → Continue** (if `enrollment.guided.auto_start_for_new_person`), or from the
  drawer's **Guided capture** button. Config comes from `GET /enrollment/guide`.
- Mirrored video inside a circle; one ring segment per pose. Active segment pulses, captured ones fill, a thin inner
  arc shows hold progress. A text prompt + arrow says what to do ("Turn a little more to your left", "Move a little
  closer", "Hold still…"); step chips below read ✓ / ● / pending so state never relies on colour alone.
- **Video scan, no holding still.** One phase per direction (center → left → right → up → down), each announced by
  voice (browser speech synthesis, `phase_prompts`; 🔊/🔇 toggle remembered in `localStorage` `fg-voice`) and on screen
  with an arrow, plus live coaching ("Keep turning to your left", "Move a little slower", "Move a little closer").
- Loop: grab a frame (≤ `capture_max_side`, JPEG q 0.92) → `POST /detect` with `size=detect_size` (~60 ms) → framing
  and quality gates (centre, `min_face_px`, `min_det_score`, `min_sharpness`) → **stillness gate**: head movement
  since the previous frame (pose change or box shift / face size, per 100 ms, averaged over 2 frame-pairs because
  still-head landmark jitter is ~0.02–0.03 with spikes to ~0.065) must be ≤ `max_motion` (0.06), else the
  frame is skipped and the person sees "Hold still for a moment" → the frame goes to the **one** unsaved step it fits
  best (closest to the range middle; "front" must also be level once the baseline exists, so tilted frames cannot
  win it) and replaces that step's frame if its quality is higher: det score × (sharpness ÷ sharpest frame seen)² ×
  closeness to range middle × centring × stillness. Relative sharpness matters: absolute Laplacian values vary
  400–1000 between cameras/faces, so a fixed cap would rate every frame equally sharp.
- **Clarity signals.** Sharpness = `face_sharpness` from `/detect` (Laplacian of the *inner face* on a 224 px aligned
  crop — background edges such as ceiling lights made blurred faces score high on the old whole-crop measure).
  Stillness = change of a 32×32 grey face thumbnail between consecutive frames (`Camera.frame` canvas), per 100 ms:
  quality × 1/(1+(diff/`still_diff`)²), and frames above 3×`still_diff` are not used ("Hold still for a moment").
  The camera asks for 30 fps (≈ 33 ms exposure cap) to limit motion blur.
- A phase ends only `best_window_ms` after all its steps have a frame (time to find a better one). There is **no
  timeout**: while a direction is unfinished the most specific coaching line is spoken again every `remind_ms`, and the
  video keeps running. Directions already completed on the way are skipped; after the last direction any phase with a
  missing angle is revisited. The scan ends — and auto-saves — only when every angle has a frame. The best frontal frame sets the pitch baseline for
  chin up/down. Inner arc = phase time; ring segment fills when a step gets its first frame. No video file is kept.
- **Skip this angle** ends the current phase and allows the scan to finish with that angle missing.
- **Automatic retakes.** When the scan ends, the chosen photos go to `POST /people/{id}/samples/check` (dry-run
  enroll — the in-scan check uses a smaller detector input and can be more lenient, e.g. side-angle confidence).
  Any rejected angle is dropped and **scanned again in the same window** (camera stays on, same guide style), with the
  reasons listed and a spoken tip ("Face the light, and don't turn quite so far"); then re-checked. Only when every
  angle passes are the photos frozen, celebrated and enrolled. If the save itself still rejects an angle, it is retaken
  the same way. After 3 failed tries for an angle the panel suggests checking the light or **Skip this angle**.
  Photo-limit rejections are not retaken (another photo cannot fix them).
- **Guide style picker** (under the title; remembered in `localStorage` `fg-guide-style`, default
  `enrollment.guided.guide_style`): five interchangeable, display-only styles in `guide-styles.js`, all fed the same
  per-frame state `{target, you, hit, over, holdFrac, captured{hint: share}, hint, landmarks}` so capture behaviour is
  identical: **1 Dot** (below) · **2 Hold ring** (dot + ring around the target that fills while in position and still,
  over `best_window_ms`) · **3 Face ID** (60 ticks inside the circle: target sector pulses, ticks light in the live face
  direction, captured directions turn green and widen with progress) · **4 Avatar** (mini head in the corner copying the
  live pose + big chevrons at the circle edge pointing from current pose to target, ✓ at the target when reached) ·
  **5 Face points** (the 5 detector landmarks mapped onto the mirrored cover-fit video and joined, a sweeping scan
  line, and a glowing edge arc toward the target; full soft ring during "look straight").
- **Photo strip** switch (`fg-guide-strip`, on by default): seven round slots replace the step chips; each captured
  angle's photo pops in (object URLs, revoked on replace/close), empty slots show the direction arrow.
- **Follow-the-dot guide** (style 1, SVG over the video): a target dot at the middle of the next missing angle's yaw/pitch range,
  a white "you" dot at the live head pose (mirrored: +yaw → screen left, +pitch → down; yaw/0.6 and pitch/0.2 map to
  the circle's edge), a dashed line and three pulsing chevrons pointing from you to the target. Target turns green with
  a ✓ when inside the range and shakes when overshot. A soft Web-Audio click plays per captured angle; the 🔊/🔇 toggle
  mutes voice and click together.
- **Animations** (`enrollment.guided.animations`, Lottie): `intro` loops over the circle for `intro_ms` once per
  browser session (sessionStorage `fg-intro`) with "Turn your head slowly, like this"; `success` plays in the circle
  when all angles are captured, with a green sweep around the ring. Missing files, a missing player or
  `prefers-reduced-motion` fall back to no intro / the static check mark.
- When every pose is done the ring and circle turn green with a check mark and (if `auto_submit`) all photos are
  enrolled in one request. All accepted → spoken "Done", success toast, modal closes. Rejections and unreached angles are
  listed and **Scan missing angles (N)** re-runs only those directions; already-saved frames are never re-sent.
- Warns up front if the person's existing samples + steps would exceed `max_samples_per_person`.
- Cancel / Escape stops the camera and discards un-saved photos.
- **Duplicate person**: when the front phase ends, its best frame is sent (in the background, the scan continues) to
  `POST /people/{id}/duplicate-check`; if the face is already enrolled as someone else, the scan stops and People shows an **Person already enrolled** popup with that person's avatar, name,
  **employee ID**, department and similarity, plus *Open <name>* and (when the new entry has no photos) *Delete new
  entry*. The same popup appears when an upload/webcam/guided enroll result carries `duplicate_of`.

## Page module contract
```js
export const title = '…'; export const subtitle = '…'; export const needsModels = true; // optional
export function render(root, state, actions) { return '<html>'; }    // actions = top-bar slot
export async function mounted(root, state, actions) { return cleanupFn; } // optional cleanup
```
To add a page: create `pages/<name>.js`, register it in `ROUTES` in `app.js`, add a nav link in `index.html`, and
update this spec.
