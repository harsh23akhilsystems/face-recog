// Live recognition: webcam → /recognize loop (one request in flight at a time) with box overlay,
// plus an "upload a photo" mode for one-off checks. The right panel lists who is in frame.
// By default only enrolled people (status "match") get a box; unknown/uncertain faces are hidden unless
// "Show unknown" is on, so the view answers "who of our staff is here" without clutter from passers-by.

import { api } from '../api.js';
import { Camera } from '../camera.js';
import { avatar, bindDropzone, drawFaces, emptyState, esc, icon, meter, MODEL_COLOR, MODEL_LABEL, statusBadge, toast } from '../ui.js';

export const title = 'Live recognition';
export const subtitle = 'Point a camera at the entrance or upload a photo';
export const needsModels = true;

const MODES = ['fusion', 'strict', 'arcface', 'adaface'];

export function render(root, state, actions) {
  actions.innerHTML = `<div class="segmented" role="group" aria-label="Input source">
      <button type="button" data-src="camera" aria-pressed="true">${icon('camera')} Camera</button>
      <button type="button" data-src="upload" aria-pressed="false">${icon('image')} Photo</button></div>`;
  return `
  <div class="grid grid-main-side">
    <section class="card">
      <div class="card-head">
        <div class="row">
          <select class="select" id="cam-select" style="width:220px" aria-label="Camera"><option value="">Default camera</option></select>
          <button class="btn btn-primary" id="cam-toggle" type="button">${icon('play')}Start camera</button>
        </div>
        <div class="row">
          <label class="switch small" title="Write recognitions to the activity log"><input type="checkbox" id="log-toggle" checked /> Log activity</label>
          <label class="switch small" title="Also draw boxes for faces that are not enrolled or not certain"><input type="checkbox" id="unknown-toggle" /> Show unknown</label>
          <label class="switch small"><input type="checkbox" id="mirror-toggle" checked /> Mirror</label>
        </div>
      </div>
      <div class="card-body stack">
        <div class="stage mirror" id="stage">
          <video id="video" playsinline muted></video>
          <img class="preview hidden" id="preview" alt="Uploaded photo" />
          <canvas id="overlay"></canvas>
          <div class="stage-hud"><span class="badge hidden" id="hud-live">LIVE</span><span class="badge plain hidden" id="hud-fps"></span></div>
          <div class="placeholder" id="placeholder" aria-live="polite"></div>
        </div>
        <div id="upload-zone" class="hidden">
          <div class="dropzone" id="drop" tabindex="0" role="button" aria-label="Upload a photo">${icon('upload')}
            <div><strong>Drop a photo here</strong> or click to browse</div><div class="small">JPEG, PNG or WebP · every face in the photo is identified</div></div>
          <input type="file" id="file" accept="image/*" hidden />
        </div>
        <div class="row">
          <span class="small muted">Matching mode</span>
          <div class="segmented" id="mode-seg" role="radiogroup" aria-label="Matching mode">
            ${MODES.map((m) => `<button type="button" data-mode="${m}" aria-pressed="false">${MODEL_LABEL[m]}</button>`).join('')}
          </div>
        </div>
      </div>
    </section>
    <section class="card">
      <div class="card-head"><h2>In frame</h2><span class="small muted" id="frame-meta"></span></div>
      <div id="seen">${emptyState('users', 'Nobody in frame', 'Detected faces and their scores will appear here.')}</div>
    </section>
  </div>`;
}

function seenItem(f, thresholds) {
  const p = f.person;
  const name = f.status === 'match' ? p.name : f.status === 'uncertain' ? `Possibly ${p?.name ?? ''}` : 'Unknown person';
  const sub = f.status === 'match' ? [p.employee_id, p.department].filter(Boolean).map(esc).join(' · ') : 'Not in the gallery';
  const meters = Object.entries(f.per_model || {})
    .map(([m, s]) => meter(MODEL_LABEL[m] || m, s, thresholds[m] ?? 0.3, MODEL_COLOR[m])).join('');
  return `<div class="seen-item">${f.status === 'match' ? avatar(p) : avatar({ name: '?' })}
    <div style="flex:1;min-width:0">
      <div class="row" style="justify-content:space-between"><strong>${esc(name)}</strong>${statusBadge(f.status)}</div>
      <div class="small muted">${sub || '&nbsp;'}</div>
      <div class="seen-scores">${meters}</div>
    </div></div>`;
}

export async function mounted(root, state, actions) {
  const $ = (s) => root.querySelector(s);
  const video = $('#video'), canvas = $('#overlay'), stage = $('#stage'), preview = $('#preview');
  const cam = new Camera(video);
  const settings = await api.settings().catch(() => null);
  let mode = settings?.effective_mode || 'fusion';
  const thresholds = settings?.thresholds || {};
  const available = settings?.available_models || [];
  let running = false, inflight = null, lastFaces = [], lastSize = [0, 0], frames = 0, fpsT = performance.now();
  let source = 'camera';

  // --- mode selector
  const seg = $('#mode-seg');
  const paintMode = () => seg.querySelectorAll('button').forEach((b) => {
    const m = b.dataset.mode;
    b.disabled = (m === 'fusion' || m === 'strict') ? available.length < 2 : !available.includes(m);
    b.setAttribute('aria-pressed', String(m === mode));
  });
  seg.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && !b.disabled) { mode = b.dataset.mode; paintMode(); } });
  paintMode();

  const visible = (faces) => ($('#unknown-toggle').checked ? faces : faces.filter((f) => f.status === 'match'));
  let lastRes = null;
  const renderSeen = (res) => {
    lastRes = res;
    const list = $('#seen');
    const shown = res ? visible(res.faces) : [];
    const hidden = res ? res.faces.length - shown.length : 0;
    $('#frame-meta').textContent = res
      ? `${shown.length} recognised${hidden ? ` · ${hidden} unknown hidden` : ''} · ${res.elapsed_ms} ms` : '';
    if (!shown.length) { list.innerHTML = emptyState('users', 'No enrolled person in frame', 'Recognised staff and their scores will appear here.'); return; }
    list.innerHTML = shown.map((f) => seenItem(f, thresholds)).join('');
  };

  const redraw = () => {
    const showing = source === 'camera' ? cam.active : !preview.classList.contains('hidden');
    drawFaces(canvas, lastSize[0], lastSize[1], showing ? visible(lastFaces) : [], { mirror: stage.classList.contains('mirror') });
  };
  $('#unknown-toggle').addEventListener('change', () => { redraw(); if (lastRes) renderSeen(lastRes); });
  const ro = new ResizeObserver(redraw); ro.observe(stage);

  // --- camera loop
  const tick = async () => {
    if (!running) return;
    const frame = await cam.grab();
    if (frame) {
      inflight = new AbortController();
      try {
        const res = await api.recognize(frame.blob, { mode, source: 'camera', log: $('#log-toggle').checked }, inflight.signal);
        if (!running) return;
        lastFaces = res.faces; lastSize = [res.width, res.height];
        redraw(); renderSeen(res);
        frames++;
        const now = performance.now();
        if (now - fpsT > 1000) { $('#hud-fps').textContent = `${(frames * 1000 / (now - fpsT)).toFixed(1)} fps`; frames = 0; fpsT = now; }
      } catch (e) {
        if (e.name === 'AbortError') return;
        toast(e.message, 'error'); stopCam(); showPlaceholder('error', e.message); return;
      }
    }
    setTimeout(tick, 60);
  };

  // The stage placeholder is the main call-to-action and the place camera errors stay visible
  // (a toast alone is easy to miss, which left people staring at "Camera is off").
  const showPlaceholder = (state, detail = '') => {
    const ph = $('#placeholder');
    const views = {
      off: [icon('camera'), 'Camera is off', 'Click below to start. Your browser will ask for camera permission.',
        `<button class="btn btn-primary" type="button" data-ph-start>${icon('play')}Start camera</button>`],
      starting: ['<span class="spinner" style="width:28px;height:28px"></span>', 'Starting camera…',
        'If your browser shows a permission prompt, click “Allow”.', ''],
      error: [icon('alert'), 'Camera could not start', esc(detail),
        `<button class="btn btn-primary" type="button" data-ph-start>${icon('refresh')}Try again</button>`],
      photo: [icon('image'), 'No photo yet', 'Upload a photo below.', ''],
    };
    const [ic, title, body, action] = views[state];
    ph.innerHTML = `<div class="stack" style="align-items:center;gap:8px;max-width:440px">${ic}
      <strong style="color:#e8ebf2">${title}</strong><div class="small">${body}</div>${action}</div>`;
    ph.classList.remove('hidden');
    ph.querySelector('[data-ph-start]')?.addEventListener('click', () => startCam());
  };

  const camBtn = $('#cam-toggle');
  const paintCam = () => {
    camBtn.innerHTML = running ? `${icon('stop')}Stop camera` : `${icon('play')}Start camera`;
    camBtn.classList.toggle('btn-primary', !running);
    $('#placeholder').classList.toggle('hidden', running);
    $('#hud-live').classList.toggle('hidden', !running); $('#hud-live').classList.toggle('live', running);
    $('#hud-fps').classList.toggle('hidden', !running);
  };
  const startCam = async () => {
    showPlaceholder('starting');
    try {
      const id = await cam.start($('#cam-select').value || undefined);
      const devs = await Camera.devices();
      $('#cam-select').innerHTML = devs.map((d, i) => `<option value="${esc(d.deviceId)}" ${d.deviceId === id ? 'selected' : ''}>${esc(d.label || `Camera ${i + 1}`)}</option>`).join('') || '<option value="">Default camera</option>';
      running = true; paintCam(); tick();
    } catch (e) {
      running = false; paintCam(); showPlaceholder('error', e.message); toast(e.message, 'error', 6000);
    }
  };
  function stopCam() {
    running = false; inflight?.abort(); cam.stop(); lastFaces = []; redraw(); renderSeen(null); paintCam();
    if (source === 'camera') showPlaceholder('off');
  }
  camBtn.addEventListener('click', () => (running ? stopCam() : startCam()));
  $('#cam-select').addEventListener('change', () => { if (running) startCam(); });
  $('#mirror-toggle').addEventListener('change', (e) => { stage.classList.toggle('mirror', e.target.checked && source === 'camera'); redraw(); });

  // --- upload mode
  bindDropzone($('#drop'), $('#file'), async ([file]) => {
    preview.src = URL.createObjectURL(file);
    preview.classList.remove('hidden'); $('#placeholder').classList.add('hidden');
    $('#frame-meta').innerHTML = '<span class="spinner"></span>';
    try {
      const res = await api.recognize(file, { mode, source: 'upload', log: $('#log-toggle').checked });
      lastFaces = res.faces; lastSize = [res.width, res.height];
      await preview.decode().catch(() => {});
      redraw(); renderSeen(res);
      if (!res.faces.length) toast('No faces found in this photo', 'warning');
    } catch (e) { toast(e.message, 'error'); renderSeen(null); }
  });

  actions.querySelector('.segmented').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    source = b.dataset.src;
    actions.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    const isCam = source === 'camera';
    if (!isCam) stopCam();
    video.classList.toggle('hidden', !isCam);
    preview.classList.add('hidden');
    $('#upload-zone').classList.toggle('hidden', isCam);
    $('#cam-toggle').closest('.row').classList.toggle('hidden', !isCam);
    stage.classList.toggle('mirror', isCam && $('#mirror-toggle').checked);
    showPlaceholder(isCam ? 'off' : 'photo');
    lastFaces = []; redraw(); renderSeen(null);
  });

  // Auto-start when the user already granted camera access earlier (no prompt, no extra click).
  showPlaceholder('off');
  try {
    const perm = await navigator.permissions?.query({ name: 'camera' });
    if (perm?.state === 'granted' && source === 'camera') startCam();
  } catch { /* Permissions API not supported for camera (e.g. older Firefox): wait for a click */ }

  return () => { stopCam(); ro.disconnect(); };
}
