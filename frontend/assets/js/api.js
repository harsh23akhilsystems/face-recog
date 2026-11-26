// Thin fetch wrapper around /api/v1. Errors surface the server's `detail` so the UI can show it verbatim.

const BASE = '/api/v1';

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function request(path, { method = 'GET', json, form, signal } = {}) {
  const opts = { method, signal, headers: {} };
  if (json !== undefined) { opts.body = JSON.stringify(json); opts.headers['Content-Type'] = 'application/json'; }
  if (form) opts.body = form;
  let res;
  try { res = await fetch(BASE + path, opts); } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError(0, 'Cannot reach the FaceGate server. Is it running?');
  }
  if (res.status === 401) {
    // Session expired or signed out in another tab: go to the sign-in page.
    location.replace('/login');
    throw new ApiError(401, 'Signed out');
  }
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return body;
}

const fd = (entries) => { const f = new FormData(); for (const [k, v] of entries) if (v !== undefined && v !== null) f.append(k, v); return f; };

export const auth = {
  me: () => fetch('/auth/me').then((r) => (r.ok ? r.json() : null)),
  logout: () => fetch('/auth/logout', { method: 'POST' }),
};

export const api = {
  health: () => request('/health'),
  stats: () => request('/stats'),
  settings: () => request('/settings'),
  saveSettings: (patch) => request('/settings', { method: 'PUT', json: patch }),

  people: (q) => request('/people' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  person: (id) => request(`/people/${id}`),
  createPerson: (body) => request('/people', { method: 'POST', json: body }),
  updatePerson: (id, body) => request(`/people/${id}`, { method: 'PATCH', json: body }),
  deletePerson: (id) => request(`/people/${id}`, { method: 'DELETE' }),
  enroll: (id, files) => request(`/people/${id}/samples`, { method: 'POST', form: fd(files.map((f) => ['images', f, f.name])) }),
  deleteSample: (pid, sid) => request(`/people/${pid}/samples/${sid}`, { method: 'DELETE' }),
  sampleThumb: (sid) => `${BASE}/samples/${sid}/thumb`,

  recognize: (blob, { mode, source = 'upload', log } = {}, signal) =>
    request('/recognize', { method: 'POST', signal, form: fd([['image', blob, 'frame.jpg'], ['mode', mode], ['source', source], ['log_events', log === undefined ? null : String(log)]]) }),
  verify: (a, b) => request('/verify', { method: 'POST', form: fd([['image_a', a], ['image_b', b]]) }),

  events: (params = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));
    return request('/events' + (qs.toString() ? `?${qs}` : ''));
  },
  eventThumb: (id) => `${BASE}/events/${id}/thumb`,
};
