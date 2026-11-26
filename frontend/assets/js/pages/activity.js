// Activity log: recognition events with filters and CSV export (for attendance reconciliation).

import { api } from '../api.js';
import { avatar, emptyState, esc, fmtScore, fmtTime, icon, loadingRow, MODEL_LABEL, statusBadge } from '../ui.js';

export const title = 'Activity log';
export const subtitle = 'Every recognition event, newest first';

const FILTERS = [['', 'All'], ['match', 'Recognised'], ['uncertain', 'Uncertain'], ['unknown', 'Unknown']];

export function render(root, state, actions) {
  actions.innerHTML = `
    <div class="segmented" id="filter" role="group" aria-label="Filter by status">
      ${FILTERS.map(([v, l], i) => `<button type="button" data-v="${v}" aria-pressed="${i === 0}">${l}</button>`).join('')}</div>
    <button class="btn" id="refresh" type="button">${icon('refresh')}Refresh</button>
    <button class="btn" id="export" type="button">${icon('upload')}Export CSV</button>`;
  return `<section class="card"><div class="table-wrap" id="table">${loadingRow(200)}</div></section>`;
}

export async function mounted(root, state, actions) {
  let status = '', rows = [];
  const load = async () => {
    try {
      rows = await api.events({ limit: 500, status });
      root.querySelector('#table').innerHTML = rows.length ? `<table class="table">
        <thead><tr><th>Person</th><th>Status</th><th>Score</th><th>Mode</th><th>Source</th><th>Time</th></tr></thead>
        <tbody>${rows.map((e) => `<tr>
          <td><div class="row" style="flex-wrap:nowrap">${e.has_thumb ? avatar(e, 'sm', api.eventThumb(e.id)) : avatar(e, 'sm')}
            <span>${esc(e.name || (e.status === 'unknown' ? 'Unknown person' : '—'))}</span></div></td>
          <td>${statusBadge(e.status)}</td>
          <td class="num mono">${fmtScore(e.score)}</td>
          <td>${esc(MODEL_LABEL[e.mode] || e.mode)}</td>
          <td>${esc(e.source)}</td>
          <td class="num">${fmtTime(e.ts, true)}</td></tr>`).join('')}</tbody></table>`
        : emptyState('list', 'No events', status ? 'Nothing matches this filter.' : 'Recognitions from the live camera and uploads appear here.');
    } catch (e) { root.querySelector('#table').innerHTML = emptyState('alert', 'Could not load events', esc(e.message)); }
  };
  actions.querySelector('#filter').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    status = b.dataset.v;
    actions.querySelectorAll('#filter button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    load();
  });
  actions.querySelector('#refresh').addEventListener('click', load);
  actions.querySelector('#export').addEventListener('click', () => {
    const head = ['timestamp_utc', 'person_id', 'name', 'status', 'score', 'mode', 'source'];
    const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [head.join(','), ...rows.map((r) => [r.ts, r.person_id, r.name, r.status, r.score, r.mode, r.source].map(q).join(','))].join('\n');
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob([csv], { type: 'text/csv' })), download: `facegate-activity-${new Date().toISOString().slice(0, 10)}.csv` });
    a.click(); URL.revokeObjectURL(a.href);
  });
  await load();
  const t = setInterval(load, 15000);
  return () => clearInterval(t);
}
