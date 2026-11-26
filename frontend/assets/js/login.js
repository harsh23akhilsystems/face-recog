// Sign-in page: hero carousel + parallax, password sign-in, and face sign-in with the scan animation.
// Face flow: frames go straight to /auth/face, one request in flight. The server checks framing first and answers
// 422 + advice + face box for a bad frame (no recognition run), or signs in on a good one — so a well-framed user
// is signed in on the first frame the camera delivers, with no fixed ticks or "hold still" frames.

const $ = (id) => document.getElementById(id);
const MAX_ATTEMPTS = 3;
const FRAME_GAP_MS = 120; // pause between frames after a framing hint (keeps CPU use sane)
const RETRY_PAUSE_MS = 1000; // pause after "face not recognised" before trying again
const REDIRECT_MS = 300; // time the success tick is shown before opening the console

// ---------------------------------------------------------------- hero carousel (4 s per product)
const cards = [...document.querySelectorAll('.lg-pc')];
const dots = [...$('dots').children];
let active = 1;
let heroTimer = null;
function setActive(i) {
  active = i;
  cards.forEach((c, k) => {
    c.classList.toggle('is-active', k === i);
    c.setAttribute('aria-pressed', String(k === i));
    c.querySelector('.lg-pc-bar')?.remove();
    if (k === i) {
      const bar = document.createElement('i');
      bar.className = 'lg-pc-bar';
      bar.style.animationDuration = '4000ms';
      c.appendChild(bar);
    }
  });
  dots.forEach((d, k) => d.classList.toggle('is-active', k === i));
  clearTimeout(heroTimer);
  heroTimer = setTimeout(() => setActive((active + 1) % cards.length), 4000);
}
cards.forEach((c, k) => { c.onclick = () => setActive(k); });
setActive(1);

// ---------------------------------------------------------------- parallax
const page = $('page');
if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
  page.addEventListener('mousemove', (e) => {
    page.style.setProperty('--mx', (e.clientX / innerWidth - 0.5).toFixed(3));
    page.style.setProperty('--my', (e.clientY / innerHeight - 0.5).toFixed(3));
  });
}

// ---------------------------------------------------------------- steps
function show(step) {
  for (const s of ['stepPassword', 'stepFace', 'stepSuccess']) $(s).hidden = s !== step;
}

function success(user, how) {
  stopCamera();
  $('welcomeName').textContent = `Welcome, ${user.display_name}`;
  $('welcomeHow').textContent = how === 'face' ? 'Face recognised. Opening the console…' : 'Opening the console…';
  show('stepSuccess');
  setTimeout(() => location.replace('/'), REDIRECT_MS);
}

async function postJSON(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return { r, j: await r.json().catch(() => ({})) };
}

async function postImage(url, blob) {
  const form = new FormData();
  form.append('image', blob, 'frame.jpg');
  const r = await fetch(url, { method: 'POST', body: form });
  return { r, j: await r.json().catch(() => ({})) };
}

const detail = (j, fallback) => (typeof j.detail === 'string' ? j.detail : fallback);

// ---------------------------------------------------------------- password sign-in
const EYE = '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>';
const EYE_OFF = '<path d="M3 3l18 18M10.6 10.6a3 3 0 004.2 4.2M9.9 5.1A10 10 0 0112 5c6.4 0 10 7 10 7a17 17 0 01-3.2 4M6.6 6.6A17 17 0 002 12s3.6 7 10 7a9.8 9.8 0 005.4-1.6"/>';
$('togglePw').onclick = () => {
  const pw = $('password');
  const showing = pw.type === 'text';
  pw.type = showing ? 'password' : 'text';
  $('togglePw').setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
  $('eyeIcon').innerHTML = showing ? EYE : EYE_OFF;
};

function pwError(msg) {
  $('pwError').hidden = !msg;
  $('pwError').textContent = msg || '';
  for (const id of ['username', 'password']) $(id).classList.toggle('is-error', !!msg);
}
['username', 'password'].forEach((id) => $(id).addEventListener('input', () => pwError('')));

$('stepPassword').onsubmit = async (e) => {
  e.preventDefault();
  const username = $('username').value.trim();
  const password = $('password').value;
  if (!username || !password) return pwError('Please enter your username and password.');
  const btn = $('btnContinue');
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="lg-spinner" aria-hidden="true"></span><span>Signing in…</span>';
  try {
    const { r, j } = await postJSON('/auth/login', { username, password });
    if (!r.ok) return pwError(detail(j, 'Sign-in failed.'));
    success(j.user, 'password');
  } catch {
    pwError("Can't reach the server. Check your connection.");
  } finally {
    btn.disabled = false;
    btn.innerHTML = label;
  }
};

// ---------------------------------------------------------------- face sign-in
let faceInfo = { available: false, any_enrolled: false };
fetch('/auth/face/status').then((r) => r.json()).then((j) => {
  faceInfo = j;
  $('faceOption').hidden = !j.available;
}).catch(() => {});

const cam = $('cam');
const overlay = $('overlay');
let stream = null;
let running = false; // the frame loop is active
let attempts = 0;
let session = 0; // bumps on every start/stop so a late response from an old loop is ignored

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function status(kind, msg, spinner = false) {
  const el = $('faceStatus');
  el.className = `lg-face-status${kind ? ` is-${kind}` : ''}`;
  el.innerHTML = `${spinner ? '<span class="lg-spinner lg-spinner-dark" aria-hidden="true"></span>' : ''}<span></span>`;
  el.lastChild.textContent = msg;
}

function scanning(on) {
  $('scanLine').hidden = !on;
  $('scanRing').hidden = !on;
}

function frame(maxSide = 640) {
  const s = Math.min(1, maxSide / Math.max(cam.videoWidth, cam.videoHeight));
  const c = frame.canvas || (frame.canvas = document.createElement('canvas'));
  c.width = Math.round(cam.videoWidth * s);
  c.height = Math.round(cam.videoHeight * s);
  c.getContext('2d').drawImage(cam, 0, 0, c.width, c.height);
  return new Promise((res) => c.toBlob(res, 'image/jpeg', 0.85));
}

function drawBox(q) {
  overlay.width = cam.videoWidth || 640;
  overlay.height = cam.videoHeight || 480;
  const ctx = overlay.getContext('2d');
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  $('guide').classList.toggle('is-ok', !!q?.ok);
  if (!q?.face) return;
  const [x, y, w, h] = q.face.box;
  ctx.lineWidth = 3;
  ctx.strokeStyle = q.ok ? '#3ddc97' : '#f5a524';
  ctx.strokeRect(x * overlay.width, y * overlay.height, w * overlay.width, h * overlay.height);
}

async function startFace() {
  show('stepFace');
  attempts = 0;
  $('btnRetry').hidden = true;
  if (!faceInfo.any_enrolled) {
    status('warn', 'No account is linked to an enrolled face yet. Sign in with your password; an administrator can link your account to your face.');
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    status('invalid', 'Camera access needs HTTPS or http://localhost. Use your password instead.');
    return;
  }
  status(null, 'Starting camera… click “Allow” if your browser asks.', true);
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' }, audio: false });
    cam.srcObject = stream;
    await cam.play();
    scanning(true);
    status(null, 'Look at the camera…');
    run(++session);
  } catch (err) {
    const why = { NotAllowedError: 'camera access was blocked', NotFoundError: 'no camera found', NotReadableError: 'the camera is in use by another app' }[err.name] || err.message;
    status('invalid', `Camera unavailable: ${why}. Use your password instead.`);
    $('btnRetry').hidden = false;
  }
}

function stopCamera() {
  session++;
  running = false;
  scanning(false);
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
}

async function run(id) {
  running = true;
  while (running && id === session) {
    if (!cam.videoWidth) { await sleep(50); continue; }
    let r;
    let j;
    try {
      const form = new FormData();
      form.append('image', await frame(), 'frame.jpg');
      r = await fetch('/auth/face', { method: 'POST', body: form });
      j = await r.json().catch(() => ({}));
    } catch {
      if (id !== session) return;
      status('invalid', 'Connection problem — retrying…');
      await sleep(1000);
      continue;
    }
    if (id !== session) return; // stopped or restarted while the request was in flight
    if (r.ok) { drawBox({ ok: true }); success(j.user, 'face'); return; }
    if (r.status === 422) { // framing: show the hint and box, try the next frame
      drawBox(j.quality);
      status('warn', detail(j, 'Adjust your position.'));
      await sleep(FRAME_GAP_MS);
      continue;
    }
    if (r.status === 401 && ++attempts < MAX_ATTEMPTS) {
      drawBox(null);
      status('invalid', `${detail(j, 'Face not recognised.')} (${attempts}/${MAX_ATTEMPTS})`);
      await sleep(RETRY_PAUSE_MS);
      if (id === session) status(null, 'Trying again — look at the camera…');
      continue;
    }
    stopCamera();
    drawBox(null);
    status('invalid', r.status === 401 ? 'Face not recognised. Please sign in with your password.' : detail(j, 'Face sign-in failed.'));
    $('btnRetry').hidden = r.status === 429;
    return;
  }
}

$('btnFace').onclick = startFace;
$('btnRetry').onclick = startFace;
$('btnBack').onclick = () => { stopCamera(); drawBox(null); show('stepPassword'); };
addEventListener('pagehide', stopCamera);
