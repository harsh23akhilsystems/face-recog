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
| `#/live` | `live.js` | Camera/Photo toggle · camera picker · Start/Stop · Log-activity and Mirror switches · stage with box + label overlay and LIVE/fps HUD · matching-mode control (modes needing a missing model are disabled) · "In frame" panel with per-model meters |
| `#/people` | `people.js` | Search · Add person (modal → person drawer) · card grid · **drawer**: Upload or Webcam capture, per-photo results, samples grid with delete, details form, Active switch, Delete with confirmation |
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
