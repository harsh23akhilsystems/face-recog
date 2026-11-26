// People: searchable gallery, add/edit/delete people, and enroll face samples by upload or webcam.
// Enrollment results show per-photo accept/reject reasons so HR staff can fix bad photos immediately.
// Admins (password session) can also give a person a sign-in account: username + password, linked to the person,
// so they can sign in with that password or — once photos are enrolled — with their face.

import { api, canManageUsers } from '../api.js';
import { Camera } from '../camera.js';
import { guidedCapture } from '../guided.js';
import {
  avatar, bindDropzone, confirmDialog, emptyState, esc, fmtTime, icon, loadingRow, openDrawer, openModal, toast,
} from '../ui.js';

export const title = 'People';
export const subtitle = 'Enrolled staff, their face samples and sign-in accounts';

let appState = {};
let usersByPerson = new Map(); // person_id -> user (admins only)
let unlinkedUsers = []; // logins not linked to any person (e.g. created with the CLI) — can be linked from a drawer
const isAdmin = () => canManageUsers(appState.me);

async function loadUsers() {
  usersByPerson = new Map();
  unlinkedUsers = [];
  if (!isAdmin()) return;
  try {
    for (const u of await api.users()) {
      if (u.person_id) usersByPerson.set(u.person_id, u);
      else unlinkedUsers.push(u);
    }
  } catch { /* not fatal */ }
}

export function render(root, state, actions) {
  actions.innerHTML = `
    <div class="search">${icon('search')}<input class="input" id="q" type="search" placeholder="Search name, ID or department" aria-label="Search people" /></div>
    <button class="btn btn-primary" id="add-person" type="button">${icon('plus')}Add person</button>`;
  return `<div id="people">${loadingRow(80)}</div>`;
}

const personCard = (p) => `
  <button class="card person-card" data-id="${esc(p.id)}" type="button">
    ${avatar(p)}
    <div class="meta">
      <div class="name">${esc(p.name)}</div>
      <div class="small muted">${[p.employee_id, p.department].filter(Boolean).map(esc).join(' · ') || '&nbsp;'}</div>
      <div class="row" style="gap:6px;margin-top:6px">
        ${p.sample_count ? `<span class="badge info plain">${p.sample_count} photo${p.sample_count === 1 ? '' : 's'}</span>` : '<span class="badge warning">No photos</span>'}
        ${p.active ? '' : '<span class="badge">Inactive</span>'}
        ${usersByPerson.has(p.id) ? `<span class="badge success plain" title="Sign-in username">${icon('key')} ${esc(usersByPerson.get(p.id).username)}</span>` : ''}
      </div>
    </div>
  </button>`;

export async function mounted(root, state, actions) {
  appState = state;
  const list = root.querySelector('#people');
  let timer;

  const load = async () => {
    const q = actions.querySelector('#q').value.trim();
    try {
      const [people] = await Promise.all([api.people(q), loadUsers()]);
      list.innerHTML = people.length
        ? `<div class="people-grid">${people.map(personCard).join('')}</div>`
        : q ? emptyState('search', 'No matches', `Nobody matches “${esc(q)}”.`)
          : emptyState('users', 'No one enrolled yet', 'Add a person, then upload 3–5 clear photos of their face.',
            `<button class="btn btn-primary" id="empty-add">${icon('plus')}Add your first person</button>`);
      list.querySelector('#empty-add')?.addEventListener('click', () => addPerson(load));
    } catch (e) { list.innerHTML = emptyState('alert', 'Could not load people', esc(e.message)); }
  };

  actions.querySelector('#q').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 200); });
  actions.querySelector('#add-person').addEventListener('click', () => addPerson(load));
  list.addEventListener('click', (e) => { const c = e.target.closest('.person-card'); if (c) openPerson(c.dataset.id, load); });
  await load();
  if (location.hash.includes('new=1')) addPerson(load);
}

// ---------------------------------------------------------------- add / edit
function personForm(p = {}) {
  return `
    <div class="field"><label for="f-name">Full name *</label><input class="input" id="f-name" required maxlength="120" value="${esc(p.name || '')}" /></div>
    <div class="grid grid-2">
      <div class="field"><label for="f-emp">Employee ID</label><input class="input" id="f-emp" maxlength="64" value="${esc(p.employee_id || '')}" /></div>
      <div class="field"><label for="f-dept">Department</label><input class="input" id="f-dept" maxlength="120" value="${esc(p.department || '')}" /></div>
    </div>
    <div class="field"><label for="f-notes">Notes</label><textarea class="input" id="f-notes" maxlength="1000">${esc(p.notes || '')}</textarea></div>`;
}
const readForm = (el) => ({
  name: el.querySelector('#f-name').value.trim(),
  employee_id: el.querySelector('#f-emp').value.trim() || null,
  department: el.querySelector('#f-dept').value.trim() || null,
  notes: el.querySelector('#f-notes').value.trim() || null,
});

function loginFields(suggested = '') {
  return `
    <div class="grid grid-2">
      <div class="field"><label for="u-name">Username</label><input class="input" id="u-name" maxlength="120" autocomplete="off" value="${esc(suggested)}" /></div>
      <div class="field"><label for="u-pass">Password</label><input class="input" id="u-pass" type="password" minlength="8" maxlength="256" autocomplete="new-password" /></div>
    </div>
    <div class="field"><label for="u-role">Role</label>
      <select class="select" id="u-role"><option value="staff">Staff — uses the console</option><option value="admin">Admin — can also manage logins</option></select></div>`;
}
const readLogin = (el) => ({
  username: el.querySelector('#u-name').value.trim(),
  password: el.querySelector('#u-pass').value,
  role: el.querySelector('#u-role').value,
});

function addPerson(onDone) {
  const admin = isAdmin();
  const m = openModal(`
    <form id="person-form">
      <div class="modal-head"><h2>Add person</h2><p class="small muted">You will add face photos in the next step.</p></div>
      <div class="modal-body">${personForm()}
        ${admin ? `<fieldset class="fieldset"><legend>Login <span class="muted small">(optional)</span></legend>
          <p class="small muted" style="margin:0 0 8px">Lets this person sign in with this password, and with their face once photos are added.</p>
          ${loginFields()}</fieldset>` : ''}</div>
      <div class="modal-foot"><button class="btn" type="button" data-close>Cancel</button>
      <button class="btn btn-primary" type="submit">Continue</button></div>
    </form>`);
  m.el.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = readForm(m.el);
    if (!body.name) return;
    const login = admin ? readLogin(m.el) : null;
    if (login && (login.username || login.password) && !(login.username && login.password.length >= 8)) {
      toast('For a login, enter a username and a password of at least 8 characters — or leave both empty.', 'warning');
      return;
    }
    try {
      const p = await api.createPerson(body);
      if (login?.username) {
        try {
          await api.createUser({ ...login, display_name: p.name, person_id: p.id });
          toast(`${p.name} added with login “${login.username}”`, 'success');
        } catch (err) { toast(`${p.name} added, but the login was not created: ${err.message}`, 'warning'); }
      } else toast(`${p.name} added`, 'success');
      m.close();
      await onDone(); openPerson(p.id, onDone, { guided: true });
    } catch (err) { toast(err.message, 'error'); }
  });
}

// ---------------------------------------------------------------- detail drawer
async function openPerson(id, onChange, { guided = false } = {}) {
  let person;
  try { person = await api.person(id); } catch (e) { toast(e.message, 'error'); return; }
  let cam = null;
  const d = openDrawer(`
    <div class="drawer-head">
      <span id="d-avatar">${avatar(person, 'lg')}</span>
      <div style="flex:1;min-width:0"><h2 id="d-name" style="font-size:18px">${esc(person.name)}</h2>
        <div class="small muted" id="d-sub"></div></div>
      <button class="btn btn-ghost btn-icon" data-close aria-label="Close">${icon('x')}</button>
    </div>
    <div class="drawer-body">
      <section class="card">
        <div class="card-head"><h3>Add face photos</h3><span class="small muted">Guided capture takes every angle automatically</span></div>
        <div class="card-body stack">
          <div class="row"><button class="btn btn-primary" id="guided" type="button">${icon('scan')}Guided capture</button>
            <span class="small muted">Camera opens in a circle and photographs the face from every angle, then saves.</span></div>
          <div class="segmented" role="group" aria-label="Photo source" id="src-seg">
            <button type="button" data-src="upload" aria-pressed="true">${icon('upload')} Upload</button>
            <button type="button" data-src="camera" aria-pressed="false">${icon('camera')} Webcam</button>
          </div>
          <div id="src-upload">
            <div class="dropzone" id="drop" tabindex="0" role="button" aria-label="Upload face photos">${icon('upload')}
              <div><strong>Drop photos here</strong> or click to browse</div><div class="small">One person per photo · face at least 80 px · good light</div></div>
            <input type="file" id="file" accept="image/*" multiple hidden />
          </div>
          <div id="src-camera" class="hidden stack">
            <div class="stage mirror" style="aspect-ratio:4/3"><video id="d-video" playsinline muted></video>
              <div class="placeholder" id="d-ph"><div>${icon('camera')}<div class="small">Starting camera…</div></div></div></div>
            <select class="select" id="d-cam" aria-label="Camera"><option value="">Default camera</option></select>
            <div class="row"><button class="btn btn-primary" id="snap" type="button">${icon('aperture')}Capture photo</button>
              <span class="small muted">Ask the person to look at the camera, then turn slightly between captures.</span></div>
          </div>
          <div class="result-list" id="results"></div>
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h3>Face samples <span class="muted" id="s-count"></span></h3></div>
        <div class="card-body" id="samples"></div>
      </section>
      ${isAdmin() ? `<section class="card">
        <div class="card-head"><h3>Sign-in account</h3><span class="small muted">password and face sign-in</span></div>
        <div class="card-body stack" id="account"></div>
      </section>` : ''}
      <section class="card">
        <div class="card-head"><h3>Details</h3></div>
        <form class="card-body stack" id="edit-form">${personForm(person)}
          <label class="switch"><input type="checkbox" id="f-active" ${person.active ? 'checked' : ''}/> Active — inactive people are never matched</label>
          <div class="row"><button class="btn btn-primary" type="submit">Save changes</button><span class="spacer"></span>
            <button class="btn btn-danger" type="button" id="delete">${icon('trash')}Delete person</button></div>
          <div class="small muted">Added ${fmtTime(person.created_at, true)} · ID <span class="mono">${esc(person.id.slice(0, 8))}</span></div>
        </form>
      </section>
    </div>`, () => { cam?.stop(); onChange(); });
  const $ = (s) => d.el.querySelector(s);

  const paintHeader = () => {
    $('#d-name').textContent = person.name;
    $('#d-sub').textContent = [person.employee_id, person.department].filter(Boolean).join(' · ') || 'No employee ID';
    $('#d-avatar').innerHTML = avatar(person, 'lg');
  };
  const paintSamples = () => {
    const s = person.samples || [];
    $('#s-count').textContent = `(${s.length})`;
    $('#samples').innerHTML = s.length
      ? `<div class="samples-grid">${s.map((x) => {
          const isProfile = x.id === person.cover_sample_id;
          return `<div class="sample ${isProfile ? 'is-profile' : ''}">
          ${x.has_thumb ? `<img src="${api.sampleThumb(x.id)}" alt="Face sample" loading="lazy"/>` : `<div class="empty">${icon('image')}</div>`}
          ${isProfile ? '<span class="badge success profile-badge">★ Profile</span>' : ''}
          <span class="q" title="Detection score · sharpness">${Math.round(x.det_score * 100)}% · ${Math.round(x.sharpness)}</span>
          ${isProfile || !x.has_thumb ? '' : `<button class="btn btn-sm btn-icon set-profile" data-profile="${esc(x.id)}" title="Set as profile photo" aria-label="Set as profile photo">★</button>`}
          <button class="btn btn-sm btn-icon btn-danger" data-sid="${esc(x.id)}" aria-label="Delete sample">${icon('trash')}</button></div>`;
        }).join('')}</div>
        <p class="small muted" style="margin-top:8px">${person.profile_sample_id ? 'Profile photo chosen manually.' : 'Profile photo is picked automatically (the most front-facing photo).'} Click ★ on a photo to use it instead.</p>`
      : emptyState('image', 'No face samples', 'This person cannot be recognised until at least one photo is added.');
  };
  const paintAccount = () => {
    const box = $('#account');
    if (!box) return;
    const u = usersByPerson.get(id);
    const hasPhotos = (person.samples || []).length > 0;
    if (!u) {
      box.innerHTML = `
        <p class="small muted" style="margin:0">No login yet. Create one so ${esc(person.name)} can sign in with a password${hasPhotos ? ' or their face' : ', and with their face once photos are added'}.</p>
        <form class="stack" id="acc-create">${loginFields(person.employee_id || '')}
          <div class="row"><button class="btn btn-primary" type="submit">${icon('key')}Create login</button></div></form>
        ${unlinkedUsers.length ? `<form class="row" id="acc-link" style="align-items:flex-end;flex-wrap:wrap;border-top:1px solid var(--border);padding-top:12px">
          <div class="field" style="flex:1;min-width:180px;margin:0"><label for="acc-user">…or link an existing login</label>
            <select class="select" id="acc-user">${unlinkedUsers.map((u) => `<option value="${u.id}">${esc(u.username)} — ${esc(u.display_name)}</option>`).join('')}</select></div>
          <button class="btn" type="submit">Link login</button></form>` : ''}`;
      return;
    }
    box.innerHTML = `
      <div class="row" style="gap:8px;flex-wrap:wrap">
        <span class="badge success plain">${icon('key')} ${esc(u.username)}</span>
        <span class="badge plain">${u.role === 'admin' ? 'Admin' : 'Staff'}</span>
        ${hasPhotos ? `<span class="badge success plain">${icon('checkCircle')} Face sign-in ready</span>`
          : '<span class="badge warning">Face sign-in needs photos — add some above</span>'}
      </div>
      <form class="row" id="acc-pass" style="align-items:flex-end;flex-wrap:wrap">
        <div class="field" style="flex:1;min-width:180px;margin:0"><label for="acc-new">New password</label>
          <input class="input" id="acc-new" type="password" minlength="8" maxlength="256" autocomplete="new-password" /></div>
        <button class="btn" type="submit">Reset password</button>
      </form>
      <div class="row"><span class="small muted">Removing the login keeps the person and their photos.</span><span class="spacer"></span>
        <button class="btn btn-danger btn-sm" type="button" id="acc-remove">${icon('trash')}Remove login</button></div>`;
  };
  const accountEvents = () => {
    const box = $('#account');
    if (!box) return;
    box.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        if (e.target.id === 'acc-create') {
          const login = readLogin(box);
          if (!login.username || login.password.length < 8) { toast('Enter a username and a password of at least 8 characters.', 'warning'); return; }
          const u = await api.createUser({ ...login, display_name: person.name, person_id: id });
          usersByPerson.set(id, u); toast(`Login “${u.username}” created`, 'success');
        } else if (e.target.id === 'acc-link') {
          const uid = Number(box.querySelector('#acc-user').value);
          const u = await api.updateUser(uid, { person_id: id });
          usersByPerson.set(id, u);
          unlinkedUsers = unlinkedUsers.filter((x) => x.id !== uid);
          toast(`Login “${u.username}” linked — ${person.name} can now sign in with their face`, 'success');
        } else if (e.target.id === 'acc-pass') {
          const pw = box.querySelector('#acc-new').value;
          if (pw.length < 8) { toast('Password must be at least 8 characters.', 'warning'); return; }
          await api.updateUser(usersByPerson.get(id).id, { password: pw });
          toast('Password changed; their open sessions were signed out', 'success');
        }
        paintAccount();
      } catch (err) {
        toast(/already taken/.test(err.message) && unlinkedUsers.length
          ? `${err.message}. If that login belongs to ${person.name}, use “Link login” below instead.` : err.message, 'error');
      }
    });
    box.addEventListener('click', async (e) => {
      if (!e.target.closest('#acc-remove')) return;
      const u = usersByPerson.get(id);
      if (!(await confirmDialog({ title: `Remove login “${u.username}”?`, body: `${person.name} will no longer be able to sign in with a password or their face. Their photos stay.`, confirm: 'Remove login', danger: true }))) return;
      try { await api.deleteUser(u.id); usersByPerson.delete(id); paintAccount(); toast('Login removed', 'success'); } catch (err) { toast(err.message, 'error'); }
    });
  };
  const reload = async () => { person = await api.person(id); paintHeader(); paintSamples(); paintAccount(); };
  paintHeader(); paintSamples(); paintAccount(); accountEvents();

  // A face that already belongs to someone else: say who (name + employee ID) and offer the obvious next steps.
  const showDuplicate = (dup) => {
    const isEmpty = !(person.samples || []).length;
    const pm = openModal(`
      <div class="modal-head"><h2>${icon('alert')} Person already enrolled</h2>
        <p class="small muted">This face is already saved in the gallery.</p></div>
      <div class="modal-body">
        <div class="row" style="gap:14px">${avatar(dup, 'lg')}
          <div style="min-width:0"><div style="font-size:16px;font-weight:600">${esc(dup.name)}</div>
            <div>Employee ID: <strong class="mono" style="font-size:14px">${esc(dup.employee_id || 'not set')}</strong></div>
            ${dup.department ? `<div class="small muted">${esc(dup.department)}</div>` : ''}
            <div class="small muted">Similarity ${Number(dup.score).toFixed(2)}</div></div></div>
        <p class="small muted">${isEmpty
          ? `No photos were saved for “${esc(person.name)}”. If this is the same person, delete this new entry and use the existing profile.`
          : `The photo was not added to “${esc(person.name)}”. Check that the right person is in front of the camera.`}</p>
      </div>
      <div class="modal-foot">
        <button class="btn" type="button" data-close>Close</button><span class="spacer"></span>
        ${isEmpty ? `<button class="btn btn-danger" type="button" id="dup-del">${icon('trash')}Delete new entry</button>` : ''}
        <button class="btn btn-primary" type="button" id="dup-open">${icon('user')}Open ${esc(dup.name)}</button>
      </div>`);
    pm.el.querySelector('#dup-open').addEventListener('click', () => { pm.close(); d.close(); openPerson(dup.id, onChange); });
    pm.el.querySelector('#dup-del')?.addEventListener('click', async () => {
      try { await api.deletePerson(id); toast(`New entry “${person.name}” deleted`, 'success'); pm.close(); d.close(); } catch (err) { toast(err.message, 'error'); }
    });
  };

  const enroll = async (files) => {
    $('#results').innerHTML = `<div class="result"><span class="spinner"></span> Processing ${files.length} photo${files.length === 1 ? '' : 's'}…</div>`;
    try {
      const r = await api.enroll(id, files);
      $('#results').innerHTML = r.results.map((x) => `<div class="result ${x.accepted ? 'ok' : 'bad'}">
        ${icon(x.accepted ? 'checkCircle' : 'xCircle')}<div><strong>${esc(x.filename)}</strong> — ${x.accepted ? 'Added' : esc(x.reason)}
        ${x.warnings?.length ? `<div class="small muted">${x.warnings.map(esc).join('; ')}</div>` : ''}</div></div>`).join('');
      toast(`${r.accepted} of ${r.results.length} photo${r.results.length === 1 ? '' : 's'} added`, r.accepted ? 'success' : 'warning');
      await reload();
      const dup = r.results.find((x) => x.duplicate_of)?.duplicate_of;
      if (dup) showDuplicate(dup);
    } catch (e) { $('#results').innerHTML = ''; toast(e.message, 'error'); }
  };
  bindDropzone($('#drop'), $('#file'), enroll);

  // webcam capture
  $('#src-seg').addEventListener('click', async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    $('#src-seg').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    const camMode = b.dataset.src === 'camera';
    $('#src-upload').classList.toggle('hidden', camMode);
    $('#src-camera').classList.toggle('hidden', !camMode);
    if (camMode) startCam(); else cam?.stop();
  });
  const startCam = async (deviceId) => {
    cam = cam || new Camera($('#d-video'));
    $('#d-ph').innerHTML = `<div>${icon('camera')}<div class="small">Starting camera…</div></div>`;
    $('#d-ph').classList.remove('hidden');
    try {
      const active = await cam.start(deviceId);
      $('#d-ph').classList.add('hidden');
      const devs = await Camera.devices();
      $('#d-cam').innerHTML = devs.map((x, i) => `<option value="${esc(x.deviceId)}" ${x.deviceId === active ? 'selected' : ''}>${esc(x.label || `Camera ${i + 1}`)}</option>`).join('')
        || '<option value="">Default camera</option>';
    } catch (err) { $('#d-ph').innerHTML = `<div class="small">${esc(err.message)}</div>`; }
  };
  $('#d-cam').addEventListener('change', (e) => startCam(e.target.value || undefined));
  let shot = 0;
  $('#snap').addEventListener('click', async () => {
    const f = await cam?.grab(1280, 0.92);
    if (!f) return;
    enroll([new File([f.blob], `webcam-${++shot}.jpg`, { type: 'image/jpeg' })]);
  });

  const runGuided = async () => {
    cam?.stop();
    $('#src-seg').querySelector('[data-src="upload"]').click();
    const { accepted, duplicate } = await guidedCapture({
      name: person.name, existing: (person.samples || []).length,
      enroll: (files) => api.enroll(id, files), checkDuplicate: (blob) => api.duplicateCheck(id, blob),
      checkSamples: (files) => api.checkSamples(id, files),
    });
    if (accepted) await reload();
    if (duplicate) showDuplicate(duplicate);
  };
  $('#guided').addEventListener('click', runGuided);
  if (guided) {
    api.enrollmentGuide().then((g) => { if (g.auto_start_for_new_person && d.el.isConnected) runGuided(); }).catch(() => {});
  }

  $('#samples').addEventListener('click', async (e) => {
    const pb = e.target.closest('[data-profile]');
    if (pb) {
      try {
        person = { ...person, ...(await api.updatePerson(id, { profile_sample_id: pb.dataset.profile })) };
        paintHeader(); paintSamples(); toast('Profile photo updated', 'success');
      } catch (err) { toast(err.message, 'error'); }
      return;
    }
    const b = e.target.closest('[data-sid]'); if (!b) return;
    if (!(await confirmDialog({ title: 'Delete this sample?', body: 'The face photo and its embeddings are removed permanently.', confirm: 'Delete', danger: true }))) return;
    try { await api.deleteSample(id, b.dataset.sid); await reload(); toast('Sample deleted', 'success'); } catch (err) { toast(err.message, 'error'); }
  });

  $('#edit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      person = { ...person, ...(await api.updatePerson(id, { ...readForm(d.el), active: $('#f-active').checked })) };
      paintHeader(); toast('Saved', 'success');
    } catch (err) { toast(err.message, 'error'); }
  });
  $('#delete').addEventListener('click', async () => {
    if (!(await confirmDialog({ title: `Delete ${person.name}?`, body: `Their profile, all face samples and embeddings are deleted permanently. Activity log entries are kept but unlinked.${usersByPerson.has(id) ? ' Their login is removed too.' : ''}`, confirm: 'Delete person', danger: true }))) return;
    try {
      const u = usersByPerson.get(id);
      if (u) await api.deleteUser(u.id);
      await api.deletePerson(id); toast(`${person.name} deleted`, 'success'); d.close();
    } catch (err) { toast(err.message, 'error'); }
  });
}
