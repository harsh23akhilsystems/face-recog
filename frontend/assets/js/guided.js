// Guided enrollment as a *video scan*: the camera opens inside a circle, a voice walks the person through one
// smooth movement per direction ("look straight", "slowly turn left", "right", "chin up", "chin down"), and every
// analysed video frame competes for each pose step whose yaw/pitch range it falls in. The best frame per step
// (sharp, confident, centred, near the middle of the range) is kept; when the scan ends those frames are enrolled.
//
// Why a scan instead of "hold this pose": holding still on command is slow and irritating, and the first acceptable
// frame is rarely the best one. Watching continuously means the person just moves naturally (~10–15 s total) and we
// pick the best frames afterwards. No video file is recorded or uploaded — only the analysed frames (for detection)
// and the chosen photos (for enrollment, where only aligned crops + embeddings are stored).
// Poses, tolerances, prompts and quality gates come from `GET /enrollment/guide` (`enrollment.guided` in config.yaml).
//
// Guidance is a *follow-the-dot* overlay: a target dot sits where the person's nose should point for the next missing
// angle, a "you" dot tracks their live head pose (same yaw/pitch the scan measures), and pulsing chevrons point from one
// to the other. Reaching the target turns it green; overshooting makes it shake. Optional Lottie animations (vendored
// lottie-web light player, MIT; files in assets/anim/) show a "turn like this" intro and a success check.

import { api } from './api.js';
import { Camera } from './camera.js';
import { STYLES, createGuide } from './guide-styles.js';
import { esc, icon, openModal, toast } from './ui.js';

const ARROW = { left: '←', right: '→', up: '↑', down: '↓', center: '•' };
const STEP_LABEL = { center: 'Front', left: 'Left', right: 'Right', up: 'Up', down: 'Down' };
const PHASE_ORDER = ['center', 'left', 'right', 'up', 'down'];
const VOICE_KEY = 'fg-voice', STYLE_KEY = 'fg-guide-style', STRIP_KEY = 'fg-guide-strip';
const pref = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const setPref = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stepName = (s) => `${STEP_LABEL[s.hint] || s.key}${s.key.endsWith('slight') ? ' (slight)' : ''}`;

// Ring geometry (SVG viewBox 0..100). Segments sit just outside the circular video.
const R = 47, C = 2 * Math.PI * R, GAP = 2.2;
const PROG_R = 44.2, PROG_C = 2 * Math.PI * PROG_R;

function ringSvg(n) {
  const seg = C / n;
  const segs = Array.from({ length: n }, (_, i) =>
    `<circle class="seg" data-i="${i}" cx="50" cy="50" r="${R}" stroke-dasharray="${(seg - GAP).toFixed(2)} ${C.toFixed(2)}" stroke-dashoffset="${(-i * seg).toFixed(2)}"/>`).join('');
  return `<svg class="capture-segs" viewBox="0 0 100 100" aria-hidden="true">${segs}
    <circle class="hold" cx="50" cy="50" r="${PROG_R}" stroke-dasharray="0 ${PROG_C.toFixed(2)}"/>
    <circle class="sweep" cx="50" cy="50" r="${R}" stroke-dasharray="${C.toFixed(2)} ${C.toFixed(2)}" stroke-dashoffset="${C.toFixed(2)}"/></svg>`;
}

// Guide overlay (SVG viewBox 0..100, not mirrored); its content is drawn by the selected style in guide-styles.js.
// Pose → screen: the video is mirrored, so a person turning to *their* left (+yaw) moves left; chin down moves down.
const guideSvg = () => '<svg class="capture-guide hidden" id="g-guide" viewBox="0 0 100 100" aria-hidden="true"></svg>';
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const toXY = (yaw, pitch) => [50 - clamp(yaw / 0.6, -1.1, 1.1) * 34, 50 + clamp(pitch / 0.2, -1.1, 1.1) * 30];

// ---------------------------------------------------------------- free animations (Lottie) + sound
let lottieLoading = null;
function loadLottie() {
  if (window.lottie) return Promise.resolve(window.lottie);
  lottieLoading = lottieLoading || new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = '/assets/vendor/lottie/lottie_light.min.js';
    s.onload = () => res(window.lottie);
    s.onerror = () => { lottieLoading = null; rej(new Error('lottie player missing')); };
    document.head.appendChild(s);
  });
  return lottieLoading;
}
const reducedMotion = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
/** Play assets/<path> into `el`; resolves to the animation, or null if off/missing/reduced-motion (caller falls back). */
async function playLottie(el, path, loop) {
  if (!path || reducedMotion() || path.includes('..')) return null;
  try {
    const [lottie, data] = await Promise.all([
      loadLottie(), fetch(`/assets/${path}`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status)))),
    ]);
    el.innerHTML = '';
    return lottie.loadAnimation({ container: el, renderer: 'svg', loop, autoplay: true, animationData: data });
  } catch { return null; }
}
let audioCtx = null;
/** Short soft "click" when an angle is captured (Web Audio, no sound file). */
function beep(on) {
  if (!on) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const t = audioCtx.currentTime, o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.setValueAtTime(880, t); o.frequency.exponentialRampToValueAtTime(1320, t + 0.08);
    g.gain.setValueAtTime(0.07, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);
    o.connect(g).connect(audioCtx.destination); o.start(t); o.stop(t + 0.15);
  } catch { /* audio unavailable */ }
}

// ---------------------------------------------------------------- voice
const voiceWanted = (cfgDefault) => {
  try { const v = localStorage.getItem(VOICE_KEY); return v === null ? cfgDefault : v === '1'; } catch { return cfgDefault; }
};
const saveVoice = (on) => { try { localStorage.setItem(VOICE_KEY, on ? '1' : '0'); } catch { /* private mode */ } };
function say(text, on) {
  if (!on || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05;
  window.speechSynthesis.speak(u);
}

// ---------------------------------------------------------------- frame scoring
const area = (f) => (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]);

/** Framing/quality gates (same as server enrollment). Returns {face, centre} or {problem}. */
function judge(r, guide) {
  if (!r.faces?.length) return { problem: 'No face found — centre your face in the circle' };
  const f = r.faces.reduce((a, b) => (area(b) > area(a) ? b : a));
  const [x1, y1, x2, y2] = f.bbox;
  const cx = (x1 + x2) / 2 / r.width - 0.5, cy = (y1 + y2) / 2 / r.height - 0.5;
  const centre = Math.max(Math.abs(cx), Math.abs(cy));
  if (centre > guide.max_center_offset) return { problem: 'Centre your face in the circle' };
  if (Math.min(x2 - x1, y2 - y1) < guide.min_face_px) return { problem: 'Move a little closer to the camera' };
  if (f.det_score < guide.min_det_score) return { problem: 'Face the light and keep your face uncovered' };
  if (f.sharpness < guide.min_sharpness) return { problem: 'Move a little slower' };
  return { face: f, centre };
}

const inRange = (v, r) => !r || (v >= r[0] && v <= r[1]);
/** 0 at the middle of the range, 1 at its edges (open-ended ranges such as [-1, -0.05] use inner edge ± 0.25). */
function rangeDist(v, r) {
  if (!r) return 0;
  const lo = r[0] <= -0.99 ? r[1] - 0.25 : r[0], hi = r[1] >= 0.99 ? r[0] + 0.25 : r[1];
  const mid = (lo + hi) / 2, half = Math.max(1e-3, (hi - lo) / 2);
  return Math.min(1, Math.abs(v - mid) / half);
}
/** Middle of a range (open-ended ranges use inner edge ± 0.25, as in `rangeDist`); 0 when unchecked. */
function rangeMid(r) {
  if (!r) return 0;
  const lo = r[0] <= -0.99 ? r[1] - 0.25 : r[0], hi = r[1] >= 0.99 ? r[0] + 0.25 : r[1];
  return (lo + hi) / 2;
}
/**
 * Pose used to judge a step. Turns and tilts are measured from this person's own frontal frame (`baseline`), not from
 * the alignment template: a face that rests at yaw −0.12 (face shape, camera beside the screen) would otherwise reach
 * "slight right" by looking straight, and need a much deeper turn for "left" than for "right". Only the front step
 * itself uses absolute yaw — that is what "looking at the camera" means.
 */
function poseFor(face, step, baseline) {
  const yaw = face.pose?.yaw ?? 0, pitch = (face.pose?.pitch ?? 0) - (baseline?.pitch ?? 0);
  return { yaw: step.hint === 'center' ? yaw : yaw - (baseline?.yaw ?? 0), pitch };
}
/**
 * A step with its turn/tilt range relaxed: the inner edge (the one nearest straight-ahead) × `factor`. Used once a
 * direction has been unfinished for `relax_after_ms`, so a person who cannot turn as far still completes the scan.
 */
function relaxed(step, factor) {
  if (factor >= 1 || step.hint === 'center') return step;
  const key = step.hint === 'left' || step.hint === 'right' ? 'yaw' : 'pitch';
  const r = step[key];
  if (!r) return step;
  const inner = r[0] >= 0 ? [r[0] * factor, r[1]] : [r[0], r[1] * factor];
  return { ...step, [key]: inner };
}
/** How well a frame fits a step: 0 = middle of its pose range … 1 = edge; -1 = outside (or not measurable yet). */
function stepFit(j, step, baseline) {
  if (step.hint !== 'center' && baseline === null) return -1; // every turn is measured against the frontal frame
  const { yaw, pitch } = poseFor(j.face, step, baseline);
  if (!inRange(yaw, step.yaw) || !inRange(pitch, step.pitch)) return -1;
  // Once the frontal baseline exists, "front" must also be level — otherwise chin-up/down frames would win it too.
  if (step.hint === 'center' && baseline !== null && Math.abs(pitch) > 0.05) return -1;
  return Math.max(rangeDist(yaw, step.yaw), rangeDist(pitch, step.pitch));
}

/**
 * Candidate quality (higher is better). Sharpness is *relative to the sharpest frame seen in this scan*: absolute
 * Laplacian values depend on camera, light and face size (here 400–1000), so a fixed cap would rate every frame as
 * equally sharp. Squared, so a frame at 70% of the best sharpness scores only ~half. Motion is a penalty on top of
 * the hard `max_motion` gate.
 */
function quality(c, maxSharp, guide) {
  const sharp = Math.min(1, c.sharp / Math.max(1, maxSharp));
  const still = 1 / (1 + (c.diff / guide.still_diff) ** 2); // halves at still_diff, ~0.1 at 3× still_diff
  return c.det * sharp * sharp * still * (1 - 0.3 * c.fit) * (1 - c.centre);
}

// Image-based stillness: compare a 32×32 grey thumbnail of the face between consecutive frames. Unlike landmark
// motion (which jitters by ~0.02–0.03 even on a still head) this sees real movement — the thing that causes blur.
const tiny = document.createElement('canvas');
tiny.width = tiny.height = 32;
const tctx = tiny.getContext('2d', { willReadFrequently: true });
function faceThumb(src, bbox) {
  if (!src) return null;
  const [x1, y1, x2, y2] = bbox;
  tctx.drawImage(src, x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1), 0, 0, 32, 32);
  const d = tctx.getImageData(0, 0, 32, 32).data, g = new Float32Array(1024);
  let mean = 0;
  for (let i = 0; i < 1024; i++) { g[i] = 0.299 * d[4 * i] + 0.587 * d[4 * i + 1] + 0.114 * d[4 * i + 2]; mean += g[i]; }
  mean /= 1024;
  for (let i = 0; i < 1024; i++) g[i] -= mean; // ignore exposure drift
  return g;
}
/** Mean absolute difference (0..1) between two face thumbnails, scaled per 100 ms. */
function frameDiff(a, b, dt) {
  if (!a || !b) return Infinity;
  let s = 0;
  for (let i = 0; i < 1024; i++) s += Math.abs(a[i] - b[i]);
  return (s / 1024 / 255) * (100 / Math.max(40, dt));
}

/** Head movement per 100 ms (pose change, or box shift relative to face size) between two consecutive frames. */
function motionOf(face, prev, dt) {
  if (!prev) return Infinity;
  const [x1, y1, x2, y2] = face.bbox;
  const size = Math.max(1, x2 - x1);
  const shift = Math.hypot((x1 + x2) / 2 - prev.cx, (y1 + y2) / 2 - prev.cy) / size;
  const turn = Math.max(Math.abs((face.pose?.yaw ?? 0) - prev.yaw), 2 * Math.abs((face.pose?.pitch ?? 0) - prev.pitch));
  return Math.max(shift, turn) * (100 / Math.max(40, dt));
}

/**
 * Open the guided video-scan modal.
 * @param {{name: string, existing?: number, enroll: (files: File[]) => Promise<any>,
 *          checkDuplicate?: (blob: Blob) => Promise<{duplicate_of: object|null}>}} opts
 *   `enroll` receives the chosen photos and returns the `/people/{id}/samples` response.
 *   `checkDuplicate` runs in the background on the best frontal frame; if the face is already enrolled as someone
 *   else the scan stops and the result carries `duplicate`.
 *   `checkSamples` (`POST /people/{id}/samples/check`, a dry-run enroll) runs on the chosen photos when the scan ends;
 *   any angle it rejects is scanned again automatically before anything is saved.
 * @returns {Promise<{accepted: number, duplicate: object|null}>} resolves when the modal closes.
 */
export async function guidedCapture({ name, existing = 0, enroll, checkDuplicate, checkSamples }) {
  let guide;
  try { guide = await api.enrollmentGuide(); } catch (e) { toast(e.message, 'error'); return { accepted: 0, duplicate: null }; }
  const steps = guide.steps;
  const room = guide.max_samples_per_person - existing;
  const allPhases = PHASE_ORDER
    .map((hint) => ({
      hint,
      prompt: guide.phase_prompts?.[hint] || steps.find((s) => s.hint === hint)?.prompt,
      steps: steps.flatMap((s, i) => (s.hint === hint ? [i] : [])),
    }))
    .filter((p) => p.steps.length);

  return new Promise((resolve) => {
    let closed = false, running = false, ctrl = null, accepted = 0, loopGen = 0, duplicate = null, dupChecked = false;
    let voiceOn = voiceWanted(guide.voice);
    const cam = { current: null };
    const m = openModal(`
      <div class="modal-head row" style="justify-content:space-between;align-items:flex-start">
        <div><h2>Face scan · ${esc(name)}</h2>
          <p class="small muted" id="g-sub"></p></div>
        <button class="btn btn-ghost btn-sm" type="button" id="g-voice"></button>
      </div>
      <div class="capture-opts row">
        <label class="small muted" for="g-style">Guide style</label>
        <select class="select capture-style" id="g-style">${STYLES.map((s, i) => `<option value="${s.id}">${i + 1}. ${esc(s.label)}</option>`).join('')}</select>
        <label class="switch small"><input type="checkbox" id="g-strip"/> Photo strip</label>
      </div>
      <div class="modal-body">
        ${room < steps.length ? `<div class="result bad">${icon('alert')}<div>${esc(name)} already has ${existing} photo${existing === 1 ? '' : 's'}; only ${Math.max(0, room)} more fit (limit ${guide.max_samples_per_person}). Delete weak samples first or the extra photos will be rejected.</div></div>` : ''}
        <div class="capture-ring" id="g-ring">
          <div class="capture-video"><video id="g-video" playsinline muted></video></div>
          ${guideSvg()}
          ${ringSvg(steps.length)}
          <div class="capture-anim hidden" id="g-intro"></div>
          <div class="capture-ph" id="g-ph"><div><span class="spinner"></span><div class="small" style="margin-top:8px">Starting camera — click “Allow” if asked</div></div></div>
          <div class="capture-done hidden" id="g-done">${icon('check')}</div>
          <span class="badge capture-rec hidden" id="g-rec">SCANNING <span id="g-time">0s</span></span>
        </div>
        <div class="capture-prompt" role="status" aria-live="polite">
          <div class="capture-arrow" id="g-arrow" aria-hidden="true"></div>
          <strong id="g-prompt">Get ready…</strong>
          <div class="small muted" id="g-hint">&nbsp;</div>
        </div>
        <div class="capture-steps" id="g-steps"></div>
        <div class="capture-strip hidden" id="g-strip-row"></div>
        <div class="result-list" id="g-results"></div>
      </div>
      <div class="modal-foot">
        <button class="btn" type="button" data-close>Cancel</button><span class="spacer"></span>
        <button class="btn" type="button" id="g-skip" title="Move on to the next direction">Skip this angle</button>
      </div>`, () => {
      closed = true; running = false; ctrl?.abort(); cam.current?.stop();
      window.speechSynthesis?.cancel();
      best.forEach((v) => v.url && URL.revokeObjectURL(v.url));
      resolve({ accepted, duplicate });
    });
    m.el.querySelector('.modal').classList.add('modal-capture');
    const $ = (s) => m.el.querySelector(s);

    // step index -> {blob, q, pose, saved}. `saved` entries were enrolled already and are never re-sent.
    const best = new Map();
    let phases = allPhases, pi = 0, phase = null, phaseFilledAt = 0, lastRemind = 0, scanStart = 0, baseline = null;
    let phaseStart = 0;
    /** Step `k` as currently judged: relaxed once its direction has been unfinished for `relax_after_ms`. */
    const stepAt = (k) => {
      return lateNow() && phase?.steps.includes(k) ? relaxed(steps[k], guide.relax_factor ?? 1) : steps[k];
    };
    const lateNow = () => !!phase && performance.now() - phaseStart >= (guide.relax_after_ms ?? Infinity);
    /**
     * Too much movement for a sharp frame? Landmark-based motion gets noisy at deep turns (the far eye is guessed),
     * which can block "Hold still" forever; once a direction is late, only the image-based stillness is used.
     */
    const isMoving = (j) => (!lateNow() && j.motion > guide.max_motion) || j.diff > 3 * guide.still_diff;
    let skipped = false; // the scan only ends with angles missing if the operator pressed "Skip this angle"
    let prevFace = null, prevAt = 0, prevMotion = Infinity, prevThumb = null, maxSharp = 0; // motion tracking + sharpest frame seen (for relative sharpness)

    const paintVoice = () => {
      $('#g-voice').textContent = voiceOn ? '🔊 Sound on' : '🔇 Sound off';
      $('#g-voice').setAttribute('aria-pressed', String(voiceOn));
    };
    $('#g-voice').addEventListener('click', () => {
      voiceOn = !voiceOn; saveVoice(voiceOn); paintVoice();
      if (!voiceOn) window.speechSynthesis?.cancel(); else if (phase && running) say(phase.prompt, true);
    });
    paintVoice();

    // ---- guide style picker (compare five styles live; remembered per browser) + optional photo strip
    let guideView = null, holdStart = 0;
    const applyStyle = (id) => {
      guideView = createGuide(id, $('#g-guide'));
      $('#g-style').value = guideView.id;
      $('#g-sub').textContent = `${STYLES.find((s) => s.id === guideView.id).help} — move slowly; the sharpest photo for every angle is picked automatically.`;
      setPref(STYLE_KEY, guideView.id);
    };
    $('#g-style').addEventListener('change', (e) => applyStyle(e.target.value));
    applyStyle(pref(STYLE_KEY, guide.guide_style || STYLES[0].id));
    const stripOn = () => $('#g-strip').checked;
    $('#g-strip').checked = pref(STRIP_KEY, '1') === '1';
    const renderStrip = (popK = -1) => {
      $('#g-strip-row').classList.toggle('hidden', !stripOn());
      $('#g-steps').classList.toggle('hidden', stripOn());
      if (!stripOn()) return;
      $('#g-strip-row').innerHTML = steps.map((s, k) => {
        const b = best.get(k);
        return `<div class="strip-slot ${b ? 'done' : ''} ${k === popK ? 'pop' : ''}" title="${esc(stepName(s))}">
          <div class="strip-img">${b?.url ? `<img src="${b.url}" alt="${esc(stepName(s))} photo"/>` : `<span aria-hidden="true">${ARROW[s.hint]}</span>`}</div>
          <span class="strip-label">${b ? '✓ ' : ''}${esc(stepName(s))}</span></div>`;
      }).join('');
    };
    $('#g-strip').addEventListener('change', () => { setPref(STRIP_KEY, stripOn() ? '1' : '0'); renderStrip(); });

    const paint = (msg, hint = '') => {
      $('#g-prompt').textContent = msg || phase?.prompt || 'Get ready…';
      $('#g-hint').textContent = hint || ' ';
      $('#g-arrow').textContent = phase && running ? ARROW[phase.hint] : '';
      m.el.querySelectorAll('.seg').forEach((el) => {
        const k = Number(el.dataset.i);
        el.classList.toggle('done', best.has(k));
        el.classList.toggle('active', running && !best.has(k) && !!phase?.steps.includes(k));
      });
      $('#g-steps').innerHTML = steps.map((s, k) => {
        const done = best.has(k), active = running && !done && phase?.steps.includes(k);
        return `<span class="badge ${done ? 'success' : active ? 'info' : ''}">${done ? '✓ ' : active ? '● ' : ''}${esc(stepName(s))}</span>`;
      }).join('');
      const skip = $('#g-skip'); if (skip) skip.disabled = !running;
    };
    const setProgress = (frac) => {
      $('.capture-segs .hold').setAttribute('stroke-dasharray', `${(PROG_C * Math.max(0, Math.min(1, frac))).toFixed(2)} ${PROG_C.toFixed(2)}`);
    };
    const flash = () => { const r = $('#g-ring'); r.classList.remove('flash'); void r.offsetWidth; r.classList.add('flash'); };

    const startPhase = (i) => {
      // Directions whose angles were already caught on the way (e.g. while turning back) need no instruction.
      while (i < phases.length && phases[i].hint !== 'center' && phases[i].steps.every((k) => best.has(k))) i += 1;
      if (i >= phases.length) { phase = phases[phases.length - 1]; finishOrRevisit(); return; }
      pi = i; phase = phases[i]; phaseFilledAt = 0; lastRemind = phaseStart = performance.now();
      say(phase.prompt, voiceOn);
      paint();
    };
    /** After the last direction: if any angle is still missing (and nobody pressed Skip), go back for it. */
    const finishOrRevisit = () => {
      const back = skipped ? -1 : phases.findIndex((p) => p.steps.some((k) => !best.has(k)));
      if (back >= 0) startPhase(back); else finish();
    };
    const endPhase = () => {
      if (phase.hint === 'center') {
        const front = phase.steps.map((k) => best.get(k)).find(Boolean);
        if (front) {
          baseline = { yaw: front.pose?.yaw ?? 0, pitch: front.pose?.pitch ?? 0 };
          if (checkDuplicate && !dupChecked && !front.saved) {
            dupChecked = true;
            // Runs in the background so the scan does not pause; a hit stops everything.
            checkDuplicate(front.blob).then((r) => {
              if (r.duplicate_of && !closed) { duplicate = r.duplicate_of; m.close(); }
            }).catch(() => { /* enroll repeats the duplicate check */ });
          }
        } else if (baseline === null) {
          baseline = { yaw: 0, pitch: 0 }; // front was skipped: judge turns against the template so they can still complete
        }
      }
      if (pi + 1 < phases.length) startPhase(pi + 1); else finishOrRevisit();
    };

    /**
     * Offer one analysed frame to the single unsaved step it fits best (one frame never fills two angles), and keep
     * it if it beats that step's current best. Frames taken while the head is moving are not eligible (motion blur).
     */
    const offer = (j, blob) => {
      if (isMoving(j)) return; // moving → motion blur
      // An angle that has no photo yet wins over a better-fitting one that already has one: with overlapping
      // (relaxed) ranges, "slight right" would otherwise keep every frame and "right" would never fill.
      let k = -1, fit = 2, rank = 2;
      steps.forEach((_, i) => {
        if (best.get(i)?.saved) return;
        const d = stepFit(j, stepAt(i), baseline);
        const r = best.has(i) ? 1 : 0;
        if (d >= 0 && (r < rank || (r === rank && d < fit))) { k = i; fit = d; rank = r; }
      });
      if (k < 0) return;
      const cand = { blob, pose: j.face.pose, sharp: j.face.face_sharpness ?? j.face.sharpness, det: j.face.det_score, centre: j.centre, motion: j.motion, diff: j.diff, fit };
      const cur = best.get(k);
      if (cur && quality(cand, maxSharp, guide) <= quality(cur, maxSharp, guide)) return;
      if (!cur) { flash(); beep(voiceOn); }
      if (cur?.url) URL.revokeObjectURL(cur.url);
      if (stripOn()) cand.url = URL.createObjectURL(blob);
      best.set(k, cand);
      if (stripOn()) renderStrip(cur ? -1 : k);
    };

    /** Coaching text while the current direction's angles are not reached yet. */
    const coach = (j) => {
      const missing = phase.steps.filter((k) => !best.has(k)).map(stepAt);
      const moving = isMoving(j);
      if (!missing.length) return moving ? 'Hold still…' : 'Perfect — hold still';
      const s = missing[0];
      const { yaw, pitch } = poseFor(j.face, s, baseline);
      if (stepFit(j, s, baseline) >= 0) return 'Hold still for a moment'; // in position, but moving → blurry
      if (s.yaw && yaw < s.yaw[0]) return phase.hint === 'left' ? 'Keep turning to your left' : 'Turn back a little to your left';
      if (s.yaw && yaw > s.yaw[1]) return phase.hint === 'right' ? 'Keep turning to your right' : 'Turn back a little to your right';
      if (s.pitch && pitch < s.pitch[0]) return phase.hint === 'down' ? 'Chin a little lower' : 'Lower your chin a little';
      if (s.pitch && pitch > s.pitch[1]) return phase.hint === 'up' ? 'Chin a little higher' : 'Lift your chin a little';
      return '';
    };

    /** Map detector landmarks (frame px) onto the guide's viewBox: video is object-fit: cover in the circle, mirrored. */
    const mapLandmarks = (face, r) => {
      if (!face?.landmarks || !r?.width) return null;
      const s = 85 / Math.min(r.width, r.height), x0 = 50 - (r.width * s) / 2, y0 = 50 - (r.height * s) / 2;
      return face.landmarks.map(([x, y]) => [100 - x0 - x * s, y0 + y * s]);
    };

    /**
     * Build the per-frame guide state (identical for every style) and hand it to the selected style:
     * target = middle of the next missing angle, you = live head pose, hit/over, hold progress, captured share per
     * direction, face landmarks.
     */
    const guideUpdate = (j, r) => {
      const g = $('#g-guide');
      if (!running || !phase) { g.classList.add('hidden'); return; }
      g.classList.remove('hidden');
      const missingK = phase.steps.find((k) => !best.has(k));
      const step = stepAt(missingK ?? phase.steps[phase.steps.length - 1]);
      const [tx, ty] = toXY(rangeMid(step.yaw), rangeMid(step.pitch));
      let hit = missingK === undefined, over = false, you = null;
      if (j?.face) {
        const { yaw, pitch } = poseFor(j.face, step, baseline);
        const [ux, uy] = toXY(yaw, pitch);
        you = { x: ux, y: uy };
        hit = hit || (inRange(yaw, step.yaw) && inRange(pitch, step.pitch));
        over = !hit && ((step.hint === 'left' && step.yaw && yaw > step.yaw[1]) || (step.hint === 'right' && step.yaw && yaw < step.yaw[0])
          || (step.hint === 'up' && step.pitch && pitch < step.pitch[0]) || (step.hint === 'down' && step.pitch && pitch > step.pitch[1]));
      }
      // Hold progress: how long the head has been in position *and* still (the sharp-frame window).
      const now = performance.now();
      const still = hit && j?.face && !isMoving(j);
      if (!still) holdStart = 0; else if (!holdStart) holdStart = now;
      const holdFrac = holdStart ? Math.min(1, (now - holdStart) / Math.max(1, guide.best_window_ms)) : 0;
      const captured = {};
      allPhases.forEach((p) => { captured[p.hint] = p.steps.filter((k) => best.has(k)).length / p.steps.length; });
      guideView.update({ target: { x: tx, y: ty }, you, hit, over, holdFrac, captured, hint: phase.hint, landmarks: mapLandmarks(j?.face, r) });
    };

    async function loop() {
      const gen = ++loopGen; // a rescan starts a new loop; any older one must exit
      while (running && !closed && gen === loopGen) {
        const f = await cam.current.grab(guide.capture_max_side, 0.92);
        if (!f) { await sleep(80); continue; }
        ctrl = new AbortController();
        let r;
        try { r = await api.detect(f.blob, ctrl.signal, guide.detect_size); } catch (e) {
          if (e.name === 'AbortError' || closed) return;
          paint(e.message); await sleep(1000); continue;
        }
        if (!running || closed || gen !== loopGen) return;
        const now = performance.now();
        $('#g-time').textContent = `${Math.round((now - scanStart) / 1000)}s`;

        const j = judge(r, guide);
        if (j.face) {
          // Averaged over two frame-pairs: landmark jitter on a perfectly still head is ~0.02–0.03 per 100 ms with
          // single spikes to ~0.065 (measured), which would otherwise reject good frames at random.
          const raw = motionOf(j.face, prevFace, now - prevAt);
          j.motion = Number.isFinite(prevMotion) ? (raw + prevMotion) / 2 : raw;
          prevMotion = raw;
          const thumb = faceThumb(cam.current.frame, j.face.bbox);
          j.diff = frameDiff(thumb, prevThumb, now - prevAt);
          prevThumb = thumb;
          maxSharp = Math.max(maxSharp, j.face.face_sharpness ?? j.face.sharpness);
        }
        if (!j.face) { prevMotion = Infinity; prevThumb = null; }
        prevFace = j.face ? { cx: (j.face.bbox[0] + j.face.bbox[2]) / 2, cy: (j.face.bbox[1] + j.face.bbox[3]) / 2,
          yaw: j.face.pose?.yaw ?? 0, pitch: j.face.pose?.pitch ?? 0 } : null;
        prevAt = now;
        let tip;
        if (j.face) {
          offer(j, f.blob);
          if (!phaseFilledAt && phase.steps.every((k) => best.has(k))) phaseFilledAt = now;
          tip = coach(j);
        } else {
          tip = j.problem;
        }
        paint('', tip);
        guideUpdate(j, r);
        // Inner arc: share of this direction's angles captured.
        setProgress(phase.steps.filter((k) => best.has(k)).length / phase.steps.length);
        if (phaseFilledAt) {
          if (now - phaseFilledAt >= guide.best_window_ms) endPhase();
        } else if (now - lastRemind >= guide.remind_ms) {
          // Never give up on an angle: repeat the most specific instruction we have and keep the video running.
          lastRemind = now;
          say(tip && !tip.startsWith('Good') ? tip : phase.prompt, voiceOn);
        }
      }
    }

    let introShown = false, successAnim = null;
    /** Free Lottie intro ("turn your head like this") — once per browser session, never on a rescan. */
    async function intro() {
      let seen = introShown;
      try { seen = seen || sessionStorage.getItem('fg-intro') === '1'; } catch { /* private mode */ }
      if (seen || !guide.animations?.intro || !guide.intro_ms) return;
      introShown = true;
      try { sessionStorage.setItem('fg-intro', '1'); } catch { /* private mode */ }
      const el = $('#g-intro');
      const a = await playLottie(el, guide.animations.intro, true);
      if (!a || closed) return;
      el.classList.remove('hidden');
      paint('Turn your head slowly, like this', 'Then point your nose at the dot');
      say('Turn your head slowly, like this. Then point your nose at the dot.', voiceOn);
      await sleep(guide.intro_ms);
      el.classList.add('hidden'); a.destroy();
    }

    async function start() {
      $('#g-ring').classList.remove('complete');
      $('#g-done').classList.add('hidden');
      successAnim?.destroy(); successAnim = null;
      renderStrip();
      $('#g-done').innerHTML = icon('check');
      $('#g-ph').classList.remove('hidden');
      cam.current = cam.current || new Camera($('#g-video'));
      try {
        await cam.current.start();
      } catch (err) {
        $('#g-ph').innerHTML = `<div class="small">${esc(err.message)}<div style="margin-top:10px"><button class="btn btn-sm" id="g-retry" type="button">${icon('refresh')}Try again</button></div></div>`;
        $('#g-retry').addEventListener('click', start);
        return;
      }
      if (closed) { cam.current.stop(); return; }
      $('#g-ph').classList.add('hidden');
      await intro();
      if (closed) return;
      $('#g-rec').classList.remove('hidden');
      running = true; scanStart = performance.now();
      startPhase(0); loop();
    }

    // ---- automatic retakes: any angle that is missing or fails the server's checks is scanned again, same window
    const missingSteps = () => steps.flatMap((_, k) => (best.has(k) ? [] : [k]));
    const toFile = ([k, b]) => new File([b.blob], `${k + 1}-${steps[k].key}.jpg`, { type: 'image/jpeg' });
    const dropShot = (k) => { const b = best.get(k); if (b?.url) URL.revokeObjectURL(b.url); best.delete(k); };
    const attempts = new Map(); // step -> failed tries, to escalate the advice
    const RETRY_TIPS = [
      [/confidence/i, "Face the light, and don't turn quite so far."],
      [/blurry/i, 'Hold still for a moment at each angle.'],
      [/small/i, 'Come a little closer to the camera.'],
      [/No face/i, 'Keep your whole face inside the circle.'],
    ];
    const tipFor = (reason) => RETRY_TIPS.find(([re]) => re.test(reason || ''))?.[1] || '';
    /** A rejection that another photo cannot fix (photo limit) must not loop forever. */
    const unfixable = (reason) => /Limit of/i.test(reason || '');

    /** Keep the camera running and scan only the `missing` angles again; explain why by voice and on screen. */
    function resumeFor(missing, failures) {
      phases = allPhases.map((p) => ({ ...p, steps: p.steps.filter((k) => missing.includes(k)) })).filter((p) => p.steps.length);
      if (baseline === null && !phases.some((p) => p.hint === 'center')) phases.unshift(allPhases[0]);
      $('#g-ring').classList.remove('complete'); $('#g-done').classList.add('hidden');
      successAnim?.destroy(); successAnim = null; $('#g-done').innerHTML = icon('check');
      const stubborn = missing.filter((k) => (attempts.get(k) || 0) >= 3);
      $('#g-results').innerHTML = `<div class="result">${icon('refresh')}<div><strong>Retaking ${missing.length} angle${missing.length === 1 ? '' : 's'}:
        ${missing.map((k) => esc(stepName(steps[k]))).join(', ')}</strong>
        ${failures.map((f) => `<div class="small muted">${esc(stepName(steps[f.k]))} — ${esc(f.reason)}</div>`).join('')}
        ${stubborn.length ? `<div class="small">Still failing after ${attempts.get(stubborn[0])} tries — check the light, or press <strong>Skip this angle</strong> to save without it.</div>` : ''}</div></div>`;
      cam.current?.video.play().catch(() => {});
      $('#g-rec').classList.remove('hidden');
      running = true; skipped = false;
      startPhase(0);
      if (!running) return; // nothing left to scan (startPhase finished immediately)
      const tip = failures.length ? tipFor(failures[0].reason) : '';
      say(`${missing.length} angle${missing.length === 1 ? ' needs' : 's need'} another try. ${tip} ${phase.prompt}`, voiceOn);
      lastRemind = performance.now() + 3000; // let the explanation finish before the first reminder
      loop();
    }

    async function finish() {
      running = false; ctrl?.abort(); setProgress(0);
      $('#g-rec').classList.add('hidden');
      phase = null;
      guideUpdate(null);
      // 1. Run the server's real enrollment checks on the chosen photos *without saving* (the quick in-scan check
      //    uses a smaller detector input and can be more lenient), so a bad angle is retaken while the person is here.
      const fresh = [...best.entries()].filter(([, b]) => !b.saved && !b.verified);
      if (fresh.length && checkSamples) {
        paint('Checking photos…', 'Making sure every angle is clear');
        let r = null;
        try { r = await checkSamples(fresh.map(toFile)); } catch { r = null; } // check unavailable: enroll still gates
        if (closed) return;
        if (r) {
          const dupHit = r.results.find((x) => x.duplicate_of);
          if (dupHit) { duplicate = dupHit.duplicate_of; m.close(); return; }
          const failures = [];
          r.results.forEach((x, n) => {
            const k = fresh[n]?.[0];
            if (k === undefined) return;
            if (x.accepted) { best.get(k).verified = true; return; }
            if (unfixable(x.reason)) { skipped = true; return; } // keep it; enroll reports the limit
            dropShot(k); attempts.set(k, (attempts.get(k) || 0) + 1); failures.push({ k, reason: x.reason });
          });
          renderStrip();
          if (failures.length && !skipped) { resumeFor(missingSteps(), failures); return; }
        }
      }
      if (missingSteps().length && !skipped) { resumeFor(missingSteps(), []); return; }

      // 2. Everything checked: freeze the frame, celebrate, save.
      cam.current?.video.pause();
      const missing = missingSteps().length;
      const unsaved = [...best.values()].filter((v) => !v.saved).length;
      if (!missing) {
        $('#g-ring').classList.add('complete'); $('#g-done').classList.remove('hidden');
        playLottie($('#g-done'), guide.animations?.success, false).then((a) => { successAnim = a; }); // else static check
      }
      paint(best.size ? `${best.size} of ${steps.length} angles captured` : 'No usable frames — check light and distance', '');
      if (!unsaved) { say('No usable frames.', voiceOn); renderActions(); return; }
      say(missing ? `${best.size} angles captured. Saving.` : 'All angles captured. Saving.', voiceOn);
      if (guide.auto_submit) submit(); else renderActions(true);
    }

    async function submit() {
      const entries = [...best.entries()].filter(([, s]) => !s.saved);
      const files = entries.map(toFile);
      $('#g-results').innerHTML = `<div class="result"><span class="spinner"></span> Saving ${files.length} photo${files.length === 1 ? '' : 's'}…</div>`;
      $('#g-hint').textContent = 'Saving…';
      let r;
      try { r = await enroll(files); } catch (e) {
        $('#g-results').innerHTML = `<div class="result bad">${icon('xCircle')}<div>${esc(e.message)}</div></div>`;
        renderActions(true); return;
      }
      accepted += r.accepted;
      const dupHit = r.results.find((x) => x.duplicate_of);
      if (dupHit) duplicate = dupHit.duplicate_of; // shown as a popup by the caller once this modal closes
      if (dupHit && !r.accepted) { m.close(); return; }
      const rejected = [];
      r.results.forEach((x, n) => {
        const k = entries[n]?.[0];
        if (k === undefined) return;
        if (x.accepted) best.get(k).saved = true;
        else { dropShot(k); rejected.push({ k, x, step: steps[k] }); }
      });
      renderStrip();
      // Rare after the pre-check, but if the save itself rejects an angle, retake it automatically too.
      const fixable = rejected.filter((e) => !unfixable(e.x.reason));
      if (fixable.length && !skipped) {
        fixable.forEach((e) => attempts.set(e.k, (attempts.get(e.k) || 0) + 1));
        resumeFor(missingSteps(), fixable.map((e) => ({ k: e.k, reason: e.x.reason })));
        return;
      }
      const missingList = steps.filter((_, k) => !best.has(k));
      if (!missingList.length) {
        $('#g-results').innerHTML = `<div class="result ok">${icon('checkCircle')}<div><strong>${accepted} photos added</strong> — ${esc(name)} can now be recognised.</div></div>`;
        $('#g-hint').textContent = 'Done';
        say('Done. Thank you.', voiceOn);
        toast(`${accepted} photos added for ${name}`, 'success');
        setTimeout(() => { if (!closed) m.close(); }, 1600);
        return;
      }
      // Only reached when the operator skipped angles or hit the photo limit.
      $('#g-ring').classList.remove('complete');
      $('#g-done').classList.add('hidden');
      const notReached = missingList.filter((s) => !rejected.some((e) => e.step === s));
      $('#g-results').innerHTML = [
        accepted ? `<div class="result ok">${icon('checkCircle')}<div><strong>${accepted} photo${accepted === 1 ? '' : 's'} added</strong></div></div>` : '',
        ...rejected.map((e) => `<div class="result bad">${icon('xCircle')}<div><strong>${esc(stepName(e.step))}</strong> — ${esc(e.x.reason)}</div></div>`),
        notReached.length ? `<div class="result bad">${icon('alert')}<div><strong>Skipped:</strong> ${notReached.map((s) => esc(stepName(s))).join(', ')}</div></div>` : '',
      ].join('');
      paint(`${accepted} saved — ${missingList.length} angle${missingList.length === 1 ? '' : 's'} missing`, '');
      renderActions();
    }

    function renderActions(allowResubmit = false) {
      const missing = steps.flatMap((_, k) => (best.has(k) ? [] : [k]));
      const partial = missing.length && missing.length < steps.length;
      const unsaved = [...best.values()].filter((v) => !v.saved).length;
      $('.modal-foot').innerHTML = `<button class="btn" type="button" id="g-close">${accepted ? 'Done' : 'Close'}</button><span class="spacer"></span>
        ${allowResubmit && unsaved ? `<button class="btn" type="button" id="g-submit">${icon('upload')}Save ${unsaved} photos</button>` : ''}
        <button class="btn btn-primary" type="button" id="g-again">${icon('refresh')}${partial ? `Scan missing angles (${missing.length})` : 'Scan again'}</button>`;
      $('#g-close').addEventListener('click', () => m.close());
      $('#g-submit')?.addEventListener('click', submit);
      $('#g-again').addEventListener('click', () => {
        const retake = partial ? missing : steps.map((_, k) => k);
        if (!partial) [...best.keys()].forEach((k) => { const b = best.get(k); if (!b.saved) { if (b.url) URL.revokeObjectURL(b.url); best.delete(k); } });
        phases = allPhases.map((p) => ({ ...p, steps: p.steps.filter((k) => retake.includes(k)) })).filter((p) => p.steps.length);
        // Up/down are measured against a frontal frame; re-run the front direction if there is no baseline yet.
        if (baseline === null && !phases.some((p) => p.hint === 'center')) phases.unshift(allPhases[0]);
        $('#g-results').innerHTML = '';
        skipped = false;
        restoreFoot(); start();
      });
    }
    const footHtml = $('.modal-foot').innerHTML;
    function restoreFoot() {
      $('.modal-foot').innerHTML = footHtml;
      $('[data-close]').addEventListener('click', () => m.close());
      bindFoot();
    }
    function bindFoot() {
      $('#g-skip').addEventListener('click', () => { if (running) { skipped = true; endPhase(); } });
    }

    bindFoot();
    paint();
    start();
  });
}
