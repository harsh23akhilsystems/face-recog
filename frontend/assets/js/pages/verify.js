// Verify 1:1: are these two photos the same person? Shows each model's cosine vs its threshold.

import { api } from '../api.js';
import { bindDropzone, drawFaces, esc, icon, meter, MODEL_COLOR, MODEL_LABEL, toast } from '../ui.js';

export const title = 'Verify 1:1';
export const subtitle = 'Check whether two photos show the same person — nothing is saved';
export const needsModels = true;

const slot = (k, label) => `
  <section class="card"><div class="card-head"><h2>${label}</h2></div><div class="card-body" id="slot-${k}">
    <div class="dropzone" id="drop-${k}" tabindex="0" role="button" aria-label="Upload ${label}">${icon('upload')}
      <div><strong>Drop a photo</strong> or click to browse</div><div class="small">The largest face is used</div></div>
    <div class="drop-preview hidden" id="prev-${k}"><img alt="${label}" /><canvas></canvas>
      <button class="btn btn-sm" type="button" data-clear="${k}">${icon('x')}Change</button></div>
    <input type="file" id="file-${k}" accept="image/*" hidden />
  </div></section>`;

export function render() {
  return `
  <div class="grid grid-2">${slot('a', 'Photo A')}${slot('b', 'Photo B')}</div>
  <div class="row" style="margin:16px 0"><button class="btn btn-primary" id="compare" type="button" disabled>${icon('compare')}Compare faces</button>
    <span class="small muted" id="hint">Add both photos to compare.</span></div>
  <div id="result"></div>`;
}

export async function mounted(root) {
  const $ = (s) => root.querySelector(s);
  const files = { a: null, b: null };
  const sync = () => {
    $('#compare').disabled = !(files.a && files.b);
    $('#hint').textContent = files.a && files.b ? '' : 'Add both photos to compare.';
  };
  for (const k of ['a', 'b']) {
    bindDropzone($(`#drop-${k}`), $(`#file-${k}`), ([f]) => {
      files[k] = f;
      const p = $(`#prev-${k}`);
      p.querySelector('img').src = URL.createObjectURL(f);
      p.classList.remove('hidden'); $(`#drop-${k}`).classList.add('hidden');
      drawFaces(p.querySelector('canvas'), 0, 0, []);
      $('#result').innerHTML = '';
      sync();
    });
  }
  root.addEventListener('click', (e) => {
    const k = e.target.closest('[data-clear]')?.dataset.clear; if (!k) return;
    files[k] = null; $(`#prev-${k}`).classList.add('hidden'); $(`#drop-${k}`).classList.remove('hidden');
    $('#result').innerHTML = ''; sync();
  });

  $('#compare').addEventListener('click', async () => {
    const btn = $('#compare');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Comparing…';
    try {
      const r = await api.verify(files.a, files.b);
      for (const [k, face] of [['a', r.face_a], ['b', r.face_b]]) {
        const p = $(`#prev-${k}`), img = p.querySelector('img');
        await img.decode().catch(() => {});
        drawFaces(p.querySelector('canvas'), img.naturalWidth, img.naturalHeight, [{ ...face, status: r.match ? 'match' : 'unknown', person: { name: k.toUpperCase() }, score: r.fused_score }]);
      }
      const meters = Object.entries(r.per_model).map(([m, v]) => meter(MODEL_LABEL[m] || m, v.score, v.threshold, MODEL_COLOR[m])).join('');
      const fused = Object.keys(r.per_model).length > 1 ? meter('Fusion (mean)', r.fused_score, r.fusion_threshold, MODEL_COLOR.fusion) : '';
      $('#result').innerHTML = `<section class="card card-pad stack">
        <div class="verdict ${r.match ? 'match' : 'nomatch'}" role="status">${icon(r.match ? 'checkCircle' : 'xCircle')}
          <div><div class="big">${r.match ? 'Same person' : 'Different people'}</div>
          <div class="small">Decision mode: ${esc(MODEL_LABEL[r.mode] || r.mode)} · tick marks show the thresholds</div></div></div>
        <div class="stack">${meters}${fused}</div></section>`;
    } catch (e) { toast(e.message, 'error'); }
    btn.disabled = false; btn.innerHTML = `${icon('compare')}Compare faces`;
  });
}
