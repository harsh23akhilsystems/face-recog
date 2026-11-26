# Spec — `frontend/` (web console)

## Files
| File | Responsibility |
|---|---|
| `index.html` | Shell: sidebar (brand, nav, status pill, signed-in user + Sign out, theme toggle), top bar, content, toast + modal roots |
| `login.html` | Sign-in page (Augastam design): animated backdrop, hero carousel, password form, face sign-in step, success step |
| `assets/css/login.css` | Sign-in styles (`lg-*`); card tokens for light + dark, brand-blue backdrop in both |
| `assets/js/login.js` | Sign-in behaviour: carousel, parallax, password sign-in, camera + quality loop + face sign-in |
| `assets/img/augastam_logo.svg` | Brand logo on the sign-in card |
| `assets/css/styles.css` | Design tokens (light + dark) and every component style |
| `assets/js/app.js` | Router (`ROUTES`), health pill (every 30 s), theme, "models missing" notice |
| `assets/js/api.js` | One function per backend endpoint; `ApiError` with the server's `detail`; any 401 → `/login`; `auth.me/logout` |
| `assets/js/ui.js` | Icons, `esc`, avatars, formatters, toasts, modal/drawer/confirm, `drawFaces`, `meter`, `bindDropzone` |
| `assets/js/camera.js` | `Camera`: start/stop/grab/devices with readable error messages |
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
The sidebar footer shows the signed-in user (initial, name, role and how they signed in) with a **Sign out** button.
Below 900 px the sidebar becomes an off-canvas drawer with a menu button.
Status pill: `Ready · N recognizers` (green), `Degraded · models missing` (amber), `Offline · server unreachable` (red).
Pages flagged `needsModels` show a notice listing missing model files and the command to fix it.

## Pages
| Route | File | Content |
|---|---|---|
| `#/overview` | `overview.js` | 4 KPI cards · hourly activity bars (UTC) · recent recognitions · model status (role, file, provider, Loaded/Missing/Disabled, error) · quick actions |
| `#/live` | `live.js` | Camera/Photo toggle · camera picker · Start/Stop · Log-activity and Mirror switches · stage with box + label overlay and LIVE/fps HUD · matching-mode control (modes needing a missing model are disabled) · "In frame" panel with per-model meters |
| `#/people` | `people.js` | Search · Add person (modal with optional **Login**: username, password, role → person drawer) · card grid (key badge = has a login) · **drawer**: Upload or Webcam capture, per-photo results, samples grid with delete, **Sign-in account** (create login / reset password / remove login; admins with a password session only), details form, Active switch, Delete (also removes the login) with confirmation |
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
- Webcams work only on `localhost` or HTTPS. Linux USB-camera failures: README → Troubleshooting → Camera.

## Page module contract
```js
export const title = '…'; export const subtitle = '…'; export const needsModels = true; // optional
export function render(root, state, actions) { return '<html>'; }    // actions = top-bar slot
export async function mounted(root, state, actions) { return cleanupFn; } // optional cleanup
```
To add a page: create `pages/<name>.js`, register it in `ROUTES` in `app.js`, add a nav link in `index.html`, and
update this spec.

## Sign-in page (`/login`)
- Served only when signed out (`/` redirects here; signed in, `/login` redirects to `/`). Success → `/`.
- **Password step**: show/hide toggle, inline error with the server's message (`role=alert`), spinner while signing in.
- **Face step** (button shown only when `/auth/face/status.available`; explains if no account is linked yet):
  mirrored camera in a 4:3 stage with an oval guide, scanning line + pulsing ring while the camera is live, face
  box (green = good, amber = fix), and a `role=status` line with the server's advice.
  Loop (built for speed): frames (≤ 640 px, JPEG 0.85) go **straight to `/auth/face`**, one request in flight, no
  fixed tick and no "hold still" frames — a well-framed user is signed in on the first frame. 422 → draw the
  returned face box + advice, next frame after 120 ms; 401 → retry up to 3 times with a 1 s pause; 429 → stop, no
  retry button. Success shows the tick for 300 ms, then opens the console. Leaving the step or the page releases
  the camera, and responses from a stopped loop are ignored.
- Branding: Augastam logo and hero copy from the original application, nothing added to the card header. No web fonts are fetched (intranet); the font stack falls back to system fonts.
- Theme: same `fg-theme` key as the console, applied before first paint. `prefers-reduced-motion` stops every
  animation and the parallax.
