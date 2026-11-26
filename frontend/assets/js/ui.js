// Shared UI helpers: icons, escaping, formatting, toasts, modals/drawers, face overlays, meters.

const ICONS = {
  scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="11" r="3"/><path d="M7 18a5 5 0 0 1 10 0"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  camera: '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  compare: '<rect x="2" y="4" width="8" height="16" rx="2"/><rect x="14" y="4" width="8" height="16" rx="2"/><path d="M10 12h4"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
  sun: '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>',
  menu: '<path d="M3 12h18M3 6h18M3 18h18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  trash: '<path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/>',
  xCircle: '<circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
  help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01"/>',
  play: '<polygon points="5 3 19 12 5 21 5 3"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  aperture: '<circle cx="12" cy="12" r="10"/><path d="M14.31 8l5.74 9.94M9.69 8h11.48M7.38 12l5.74-9.94M9.69 16L3.95 6.06M14.31 16H2.83M16.62 12l-5.74 9.94"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  refresh: '<path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  edit: '<path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  layers: '<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>',
  key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M17 6l3 3M14 9l2 2"/>',
  userX: '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M18 8l5 5M23 8l-5 5"/>',
  userCheck: '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M17 11l2 2 4-4"/>',
};

export const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;

export function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((el) => { if (!el.firstChild) el.innerHTML = icon(el.dataset.icon); });
}

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

export const initials = (name) => String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('') || '?';

export function avatar(person, size = '', thumbUrl) {
  const url = thumbUrl || (person?.cover_sample_id ? `/api/v1/samples/${person.cover_sample_id}/thumb` : null);
  return url
    ? `<span class="avatar ${size}"><img src="${url}" alt="" loading="lazy" /></span>`
    : `<span class="avatar ${size}" aria-hidden="true">${esc(initials(person?.name))}</span>`;
}

export const fmtNum = (n) => new Intl.NumberFormat().format(n ?? 0);
export const fmtScore = (s) => (s === null || s === undefined ? '—' : Number(s).toFixed(3));

export function fmtTime(iso, withDate = false) {
  if (!iso) return '—';
  const d = new Date(iso);
  const opts = withDate ? { dateStyle: 'medium', timeStyle: 'short' } : { timeStyle: 'short' };
  return new Intl.DateTimeFormat(undefined, opts).format(d);
}

export function timeAgo(iso) {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return fmtTime(iso, true);
}

export const MODEL_LABEL = { arcface: 'ArcFace', adaface: 'AdaFace', fusion: 'Fusion', strict: 'Strict', scrfd: 'SCRFD' };
export const MODEL_COLOR = { arcface: 'var(--arcface)', adaface: 'var(--adaface)', fusion: 'var(--fusion)', strict: 'var(--fusion)' };

export const STATUS = {
  match: { label: 'Recognised', cls: 'success', color: '#12b76a' },
  uncertain: { label: 'Uncertain', cls: 'warning', color: '#f59e0b' },
  unknown: { label: 'Unknown', cls: 'danger', color: '#ef4444' },
};
export const statusBadge = (s) => `<span class="badge ${STATUS[s]?.cls || ''}">${STATUS[s]?.label || esc(s)}</span>`;

/** Score meter on a −0.2…1 scale with a visible threshold tick. */
export function meter(label, score, threshold, color) {
  const lo = -0.2, hi = 1;
  const pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const pass = score >= threshold;
  return `<div class="meter">
    <div class="meter-head"><span>${esc(label)}</span><span class="mono">${fmtScore(score)} <span class="muted">/ ${fmtScore(threshold)}</span> ${pass ? '✓' : '✗'}</span></div>
    <div class="meter-track" role="meter" aria-label="${esc(label)} similarity" aria-valuemin="-1" aria-valuemax="1" aria-valuenow="${score}">
      <div class="meter-fill" style="width:${pct(score)}%;background:${color}"></div>
      <div class="meter-threshold" style="left:${pct(threshold)}%" title="Threshold ${fmtScore(threshold)}"></div>
    </div></div>`;
}

// ---------------------------------------------------------------- toasts
export function toast(message, type = 'info', ms = 3800) {
  const host = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.setAttribute('role', type === 'error' ? 'alert' : 'status');
  const ic = { success: 'checkCircle', error: 'xCircle', warning: 'alert' }[type] || 'help';
  el.innerHTML = `${icon(ic)}<div>${esc(message)}</div>`;
  host.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// ---------------------------------------------------------------- overlays
function overlay(kind, html, onClose) {
  const root = document.getElementById('modal-root');
  const ov = document.createElement('div');
  ov.className = `overlay ${kind === 'modal' ? 'center' : ''}`;
  ov.innerHTML = html;
  const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); onClose?.(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  ov.addEventListener('mousedown', (e) => { if (e.target === ov) close(); });
  ov.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', close));
  document.addEventListener('keydown', onKey);
  root.appendChild(ov);
  hydrateIcons(ov);
  ov.querySelector('input, button:not([data-close]), [tabindex]')?.focus();
  return { el: ov, close };
}
export const openModal = (html, onClose) => overlay('modal', `<div class="modal" role="dialog" aria-modal="true">${html}</div>`, onClose);
export const openDrawer = (html, onClose) => overlay('drawer', `<div class="drawer" role="dialog" aria-modal="true">${html}</div>`, onClose);

export function confirmDialog({ title, body, confirm = 'Confirm', danger = false }) {
  return new Promise((resolve) => {
    let result = false;
    const m = openModal(`
      <div class="modal-head"><h2>${esc(title)}</h2></div>
      <div class="modal-body"><p class="muted">${esc(body)}</p></div>
      <div class="modal-foot"><button class="btn" data-close>Cancel</button>
      <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-ok>${esc(confirm)}</button></div>`, () => resolve(result));
    m.el.querySelector('[data-ok]').addEventListener('click', () => { result = true; m.close(); });
  });
}

// ---------------------------------------------------------------- face overlays
/** Draw boxes + labels for API faces onto a canvas sized to the source image. */
export function drawFaces(canvas, srcW, srcH, faces, { mirror = false } = {}) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  if (!faces?.length || !srcW) return;
  // object-fit: contain mapping
  const scale = Math.min(rect.width / srcW, rect.height / srcH);
  const ox = (rect.width - srcW * scale) / 2, oy = (rect.height - srcH * scale) / 2;
  ctx.font = '600 13px ui-sans-serif, system-ui, sans-serif';
  for (const f of faces) {
    const [x1, y1, x2, y2] = f.bbox;
    const x = ox + x1 * scale, y = oy + y1 * scale, w = (x2 - x1) * scale, h = (y2 - y1) * scale;
    const st = STATUS[f.status] || { color: '#818cf8', label: 'Face' };
    ctx.strokeStyle = st.color; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x, y, w, h, 8) : ctx.rect(x, y, w, h); ctx.stroke();
    const name = f.status === 'match' ? f.person?.name : f.status ? (f.status === 'uncertain' ? `${f.person?.name ?? ''}?` : 'Unknown') : `${Math.round(f.det_score * 100)}%`;
    const label = f.status ? `${name}  ${Number(f.score).toFixed(2)}` : name;
    // Text is drawn un-mirrored even when the video is mirrored by CSS.
    ctx.save();
    if (mirror) { ctx.translate(rect.width, 0); ctx.scale(-1, 1); }
    const lx = mirror ? rect.width - x - w : x;
    const tw = ctx.measureText(label).width + 12;
    const ly = y - 24 < 0 ? y + h + 2 : y - 24;
    ctx.fillStyle = st.color; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(lx, ly, tw, 22, 6) : ctx.rect(lx, ly, tw, 22); ctx.fill();
    ctx.fillStyle = '#fff'; ctx.fillText(label, lx + 6, ly + 15);
    ctx.restore();
  }
}

export function emptyState(ic, title, body = '', action = '') {
  return `<div class="empty">${icon(ic)}<h3>${esc(title)}</h3><p>${body}</p>${action ? `<div style="margin-top:14px">${action}</div>` : ''}</div>`;
}

/** Wire a dropzone element to a hidden file input; calls onFiles(File[]). */
export function bindDropzone(zone, input, onFiles) {
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault(); zone.classList.remove('drag');
    const files = [...e.dataTransfer.files].filter((f) => f.type.startsWith('image/'));
    if (files.length) onFiles(files);
  });
  input.addEventListener('change', () => { if (input.files.length) onFiles([...input.files]); input.value = ''; });
}

export const loadingRow = (h = 64) => `<div class="skeleton" style="height:${h}px"></div>`;
