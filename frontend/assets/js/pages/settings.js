// Settings: matching mode, per-model thresholds, uncertainty margin and activity logging.
// Changes apply instantly on the server and persist to data/settings.json.

import { api } from '../api.js';
import { esc, icon, loadingRow, MODEL_COLOR, MODEL_LABEL, toast } from '../ui.js';

export const title = 'Settings';
export const subtitle = 'Tune how strictly faces are matched';

const MODES = [
  { id: 'fusion', name: 'Fusion', desc: 'Average of ArcFace and AdaFace scores. Best overall accuracy — recommended.', needs: 2 },
  { id: 'strict', name: 'Strict', desc: 'Both models must agree on the same person. Fewest false accepts; use for door access.', needs: 2 },
  { id: 'arcface', name: 'ArcFace only', desc: 'Fast and very accurate on clear, frontal, well-lit faces.', needs: 'arcface' },
  { id: 'adaface', name: 'AdaFace only', desc: 'More robust on low-quality frames: blur, low light, CCTV.', needs: 'adaface' },
];

const slider = (key, label, value, hint, color, min = 0, max = 0.8, step = 0.01) => `
  <div class="slider-row">
    <div><div style="font-weight:600;display:flex;gap:8px;align-items:center">${color ? `<span class="model-swatch" style="height:14px;width:6px;background:${color}"></span>` : ''}${label}</div>
      <div class="small muted">${hint}</div></div>
    <input type="range" min="${min}" max="${max}" step="${step}" value="${value}" data-key="${key}" aria-label="${esc(label)}" />
    <output>${Number(value).toFixed(2)}</output>
  </div>`;

export function render() { return `<div id="settings">${loadingRow(300)}</div>`; }

export async function mounted(root) {
  let s;
  try { s = await api.settings(); } catch (e) { root.querySelector('#settings').textContent = e.message; return; }
  const avail = s.available_models;
  const ok = (m) => (m.needs === 2 ? avail.length >= 2 : avail.includes(m.needs));

  root.querySelector('#settings').innerHTML = `
  <div class="stack" style="max-width:920px">
    <section class="card"><div class="card-head"><h2>Matching mode</h2>
      ${s.mode !== s.effective_mode ? `<span class="badge warning">Running as ${esc(MODEL_LABEL[s.effective_mode])} — a model is missing</span>` : ''}</div>
      <div class="card-body"><div class="mode-cards" role="radiogroup" aria-label="Matching mode">
        ${MODES.map((m) => `<button type="button" class="mode-card" role="radio" data-mode="${m.id}" aria-checked="${s.mode === m.id}" ${ok(m) ? '' : 'disabled'}>
          <span class="t">${s.mode === m.id ? icon('checkCircle') : ''}${m.name}</span><span class="small muted">${m.desc}</span>
          ${ok(m) ? '' : '<span class="small" style="color:var(--danger)">Needs a model that is not loaded</span>'}</button>`).join('')}
      </div></div></section>

    <section class="card"><div class="card-head"><h2>Thresholds</h2><span class="small muted">Higher = stricter (fewer false accepts, more “unknown”)</span></div>
      <div class="card-body" id="sliders">
        ${Object.entries(s.thresholds).map(([m, v]) => slider(`t:${m}`, `${MODEL_LABEL[m] || m} threshold`, v,
          avail.includes(m) ? 'Cosine similarity needed to accept a match' : 'Model not loaded', MODEL_COLOR[m])).join('')}
        ${slider('fusion_threshold', 'Fusion threshold', s.fusion_threshold, 'Applied to the mean of both models', MODEL_COLOR.fusion)}
        ${slider('margin', 'Uncertainty margin', s.margin, 'Best match must beat the runner-up by this much', null, 0, 0.3)}
      </div></section>

    <section class="card"><div class="card-head"><h2>Activity log</h2></div>
      <div class="card-body stack">
        <label class="switch"><input type="checkbox" id="log" ${s.log_recognitions ? 'checked' : ''}/> Record recognitions in the activity log</label>
        <div class="field" style="max-width:320px"><label for="cooldown">Cooldown per person (seconds)</label>
          <input class="input" id="cooldown" type="number" min="0" max="86400" value="${s.cooldown_seconds}" />
          <span class="hint">A person standing in front of the camera is logged once per this window.</span></div>
      </div></section>

    <div class="notice" style="background:var(--primary-soft)">${icon('help')}<div class="small">
      <strong>Calibrate on your own staff.</strong> Run <code>make evaluate DATA=path/to/labelled_faces</code> and use the
      recommended thresholds from the report. Defaults (≈0.30) suit clear, frontal photos.</div></div>

    <div class="row"><button class="btn btn-primary" id="save" type="button">${icon('check')}Save settings</button>
      <button class="btn" id="reset" type="button">Discard changes</button><span class="small muted" id="dirty"></span></div>
  </div>`;

  const $ = (q) => root.querySelector(q);
  let mode = s.mode;
  const markDirty = () => { $('#dirty').textContent = 'Unsaved changes'; };
  root.querySelectorAll('.mode-card').forEach((c) => c.addEventListener('click', () => {
    mode = c.dataset.mode;
    root.querySelectorAll('.mode-card').forEach((x) => {
      const on = x === c; x.setAttribute('aria-checked', String(on));
      x.querySelector('.t').innerHTML = `${on ? icon('checkCircle') : ''}${MODES.find((m) => m.id === x.dataset.mode).name}`;
    });
    markDirty();
  }));
  root.querySelectorAll('input[type=range]').forEach((r) => r.addEventListener('input', () => { r.nextElementSibling.textContent = Number(r.value).toFixed(2); markDirty(); }));
  $('#log').addEventListener('change', markDirty); $('#cooldown').addEventListener('input', markDirty);
  $('#reset').addEventListener('click', () => mounted(root));

  $('#save').addEventListener('click', async () => {
    const patch = { mode, thresholds: {}, log_recognitions: $('#log').checked, cooldown_seconds: Number($('#cooldown').value) };
    root.querySelectorAll('input[type=range]').forEach((r) => {
      const k = r.dataset.key;
      if (k.startsWith('t:')) patch.thresholds[k.slice(2)] = Number(r.value); else patch[k] = Number(r.value);
    });
    try {
      await api.saveSettings(patch);
      $('#dirty').textContent = ''; toast('Settings saved', 'success');
      window.dispatchEvent(new Event('fg:health'));
    } catch (e) { toast(e.message, 'error'); }
  });
}
