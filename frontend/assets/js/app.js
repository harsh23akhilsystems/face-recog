// Router, shell state (health, theme, mobile menu) and page lifecycle.
// Each page module exports: title, subtitle, render(root, state) → HTML/DOM, mounted(root, state) → optional cleanup fn.

import { api, auth } from './api.js';
import { esc, hydrateIcons, icon } from './ui.js';
import * as overview from './pages/overview.js';
import * as live from './pages/live.js';
import * as people from './pages/people.js';
import * as verify from './pages/verify.js';
import * as activity from './pages/activity.js';
import * as settings from './pages/settings.js';

const ROUTES = { overview, live, people, verify, activity, settings };
const state = { health: null, me: null };
let cleanup = null;

async function refreshHealth() {
  const el = document.getElementById('system-status');
  try {
    state.health = await api.health();
    const h = state.health;
    const loaded = h.models.filter((m) => m.role === 'recognizer' && m.loaded).map((m) => m.name);
    el.className = `system-status ${h.ready ? 'ok' : 'degraded'}`;
    el.querySelector('.label').textContent = h.ready
      ? `Ready · ${loaded.length} recognizer${loaded.length === 1 ? '' : 's'}`
      : 'Degraded · models missing';
    document.getElementById('brand-name').textContent = h.app || 'FaceGate';
    document.getElementById('brand-org').textContent = h.organisation || 'Face recognition';
    document.title = `${h.app || 'FaceGate'} · ${h.organisation || ''}`;
  } catch {
    state.health = null;
    el.className = 'system-status down';
    el.querySelector('.label').textContent = 'Offline · server unreachable';
  }
  return state.health;
}

async function navigate() {
  const name = (location.hash.replace(/^#\/?/, '').split('?')[0] || 'overview');
  const page = ROUTES[name] || overview;
  cleanup?.(); cleanup = null;
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === name));
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('page-title').textContent = page.title;
  document.getElementById('page-subtitle').textContent = page.subtitle || '';
  const actions = document.getElementById('topbar-actions');
  actions.innerHTML = '';
  const view = document.getElementById('view');
  view.innerHTML = '';
  if (!state.health) await refreshHealth();
  if (state.health && !state.health.ready && page.needsModels) {
    view.insertAdjacentHTML('afterbegin', modelsNotice(state.health));
  }
  const html = await page.render(view, state, actions);
  if (typeof html === 'string') view.insertAdjacentHTML('beforeend', html);
  hydrateIcons(document);
  cleanup = (await page.mounted?.(view, state, actions)) || null;
  view.focus({ preventScroll: true });
}

function modelsNotice(h) {
  const missing = h.models.filter((m) => m.enabled && !m.loaded);
  return `<div class="notice" style="margin-bottom:16px">${icon('alert')}<div>
    <strong>Some models are not loaded.</strong> Recognition needs the SCRFD detector and at least one recognizer.
    <ul style="margin:6px 0 0;padding-left:18px">${missing.map((m) => `<li><code>models/${esc(m.file)}</code> — ${esc(m.name)}</li>`).join('')}</ul>
    <div class="small muted" style="margin-top:6px">Run <code>make models</code> for SCRFD + ArcFace, and see README → “AdaFace” to export AdaFace. Then restart the server.</div>
  </div></div>`;
}

function initTheme() {
  const btn = document.getElementById('theme-toggle');
  const current = () => document.documentElement.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const paint = () => {
    const dark = current() === 'dark';
    btn.innerHTML = `${icon(dark ? 'sun' : 'moon')}<span class="label">${dark ? 'Light mode' : 'Dark mode'}</span>`;
  };
  btn.addEventListener('click', () => {
    const next = current() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('fg-theme', next); } catch { /* private mode */ }
    paint();
    window.dispatchEvent(new Event('themechange'));
  });
  paint();
}

async function initUser() {
  const me = await auth.me();
  if (!me) { location.replace('/login'); return; }
  state.me = me;
  const u = me.user;
  document.getElementById('user-name').textContent = u.display_name;
  document.getElementById('user-how').textContent =
    `${u.role === 'admin' ? 'Admin' : 'Staff'} · signed in with ${me.method === 'face' ? 'face' : 'password'}`;
  document.getElementById('user-avatar').textContent = u.display_name.trim().slice(0, 1).toUpperCase();
  document.getElementById('user-chip').hidden = false;
  document.getElementById('logout-btn').addEventListener('click', async () => {
    try { await auth.logout(); } finally { location.replace('/login'); }
  });
}

document.getElementById('menu-btn').addEventListener('click', () => document.getElementById('sidebar').classList.toggle('open'));
window.addEventListener('hashchange', navigate);
window.addEventListener('fg:health', refreshHealth);
initTheme();
hydrateIcons(document);
initUser().then(refreshHealth).then(navigate);
setInterval(refreshHealth, 30000);
