// Overview: KPIs, model health, today's activity by hour, and the latest recognitions.

import { api } from '../api.js';
import { avatar, emptyState, esc, fmtNum, fmtScore, icon, loadingRow, MODEL_COLOR, MODEL_LABEL, statusBadge, timeAgo } from '../ui.js';

export const title = 'Overview';
export const subtitle = 'System health and today’s recognition activity';

export function render() {
  return `
  <div class="grid grid-4" id="kpis">${loadingRow(92).repeat(4)}</div>
  <div class="grid grid-main-side" style="margin-top:16px">
    <div class="stack">
      <section class="card">
        <div class="card-head"><h2>Activity today</h2><span class="muted small">Events per hour (UTC)</span></div>
        <div class="card-body" id="hourly">${loadingRow(120)}</div>
      </section>
      <section class="card">
        <div class="card-head"><h2>Recent recognitions</h2><a class="btn btn-sm" href="#/activity">View all</a></div>
        <div class="list" id="recent">${loadingRow(160)}</div>
      </section>
    </div>
    <div class="stack">
      <section class="card">
        <div class="card-head"><h2>Models</h2><span id="mode-badge"></span></div>
        <div id="models">${loadingRow(140)}</div>
      </section>
      <section class="card card-pad stack">
        <h2>Quick actions</h2>
        <a class="btn btn-primary" href="#/live">${icon('camera')}Start live recognition</a>
        <a class="btn" href="#/people">${icon('plus')}Enroll a person</a>
        <a class="btn" href="#/verify">${icon('compare')}Compare two photos</a>
      </section>
    </div>
  </div>`;
}

const kpi = (ic, cls, label, value, sub) => `
  <div class="card kpi"><div class="kpi-icon ${cls}">${icon(ic)}</div>
  <div><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-sub">${sub}</div></div></div>`;

export async function mounted(root, state) {
  const [stats, events] = await Promise.all([api.stats(), api.events({ limit: 8 })]).catch(() => [null, []]);
  const h = state.health;

  if (stats) {
    const ev = stats.events_today || {};
    root.querySelector('#kpis').innerHTML =
      kpi('users', '', 'Enrolled people', fmtNum(stats.active_people), `${fmtNum(stats.people)} total · ${fmtNum(stats.people_without_samples)} without photos`) +
      kpi('layers', '', 'Face samples', fmtNum(stats.samples), stats.people ? `${(stats.samples / Math.max(1, stats.people)).toFixed(1)} per person` : 'Add people to begin') +
      kpi('userCheck', 'success', 'Recognised today', fmtNum(stats.recognised_today), `${fmtNum(ev.match || 0)} match events`) +
      kpi('userX', 'danger', 'Unknown today', fmtNum(ev.unknown || 0), `${fmtNum(ev.uncertain || 0)} uncertain`);

    const hours = Array.from({ length: 24 }, (_, i) => stats.hourly_today?.[i] || 0);
    const max = Math.max(1, ...hours);
    root.querySelector('#hourly').innerHTML = hours.some(Boolean)
      ? `<div class="hour-chart" role="img" aria-label="Events per hour today">${hours.map((n, i) =>
          `<div class="bar ${n ? '' : 'zero'}" style="height:${(n / max) * 100}%" title="${String(i).padStart(2, '0')}:00 — ${n} event${n === 1 ? '' : 's'}"></div>`).join('')}</div>
         <div class="hour-axis">${hours.map((_, i) => `<span>${i % 3 === 0 ? String(i).padStart(2, '0') : ''}</span>`).join('')}</div>`
      : emptyState('clock', 'No activity yet today', 'Events appear here as people are recognised.');
  }

  root.querySelector('#recent').innerHTML = events.length
    ? events.map((e) => `<div class="list-item">
        ${e.has_thumb ? avatar(e, 'sm', api.eventThumb(e.id)) : avatar(e, 'sm')}
        <div class="meta"><div class="title">${esc(e.name || (e.status === 'unknown' ? 'Unknown person' : 'Uncertain match'))}</div>
        <div class="small muted">${timeAgo(e.ts)} · ${esc(e.source)} · score ${fmtScore(e.score)}</div></div>
        ${statusBadge(e.status)}</div>`).join('')
    : emptyState('list', 'No recognitions yet', 'Open Live recognition to start.');

  if (h) {
    root.querySelector('#mode-badge').innerHTML = `<span class="badge info plain">Mode: ${esc(MODEL_LABEL[h.mode] || h.mode)}</span>`;
    root.querySelector('#models').innerHTML = h.models.map((m) => {
      const st = !m.enabled ? '<span class="badge">Disabled</span>'
        : m.loaded ? '<span class="badge success">Loaded</span>' : '<span class="badge danger">Missing</span>';
      const role = { detector: 'Face detector · 5-point landmarks', liveness: 'Liveness · anti-spoof for face sign-in (optional)' }[m.role] || 'Recognizer · 512-d embedding';
      const prov = m.providers?.[0]?.replace('ExecutionProvider', '') || '';
      return `<div class="model-row"><span class="model-swatch" style="background:${MODEL_COLOR[m.name] || 'var(--text-muted)'}"></span>
        <div style="flex:1;min-width:0"><div class="row" style="gap:8px"><strong>${esc(MODEL_LABEL[m.name] || m.name)}</strong>${prov ? `<span class="badge plain">${esc(prov)}</span>` : ''}</div>
        <div class="small muted">${role}</div><div class="small mono muted">${esc(m.file)}</div>
        ${m.error && m.enabled ? `<div class="err">${esc(m.error)}</div>` : ''}</div>${st}</div>`;
    }).join('');
  }
}
