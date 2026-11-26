// Guide styles for the face scan — five interchangeable on-screen guides, selectable live in the scan modal so the
// team can compare them on real people. They are *display only*: every style receives the same per-frame state from
// guided.js and capture behaviour is identical, so the comparison is fair. Once one is chosen the others can be
// deleted from STYLES (and their CSS block in styles.css) without touching guided.js.
//
// Coordinates: SVG viewBox 0..100 over the capture ring; the circular video spans 7.5..92.5 (radius 42.5) and is
// mirrored, so screen-left = the person's own left.

export const STYLES = [
  { id: 'dot', label: 'Dot', help: 'Point your nose at the dot' },
  { id: 'hold', label: 'Hold ring', help: 'Reach the dot, then hold still until its ring fills' },
  { id: 'faceid', label: 'Face ID', help: 'Turn until every part of the ring lights up' },
  { id: 'avatar', label: 'Avatar', help: 'Copy the little head and follow the arrow' },
  { id: 'points', label: 'Face points', help: 'Turn toward the glowing edge' },
];

const DEG = Math.PI / 180;
const HINT_ANGLE = { right: 0, down: 90, left: 180, up: -90 }; // screen angle (SVG y points down) of each direction
const angDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);
const fmt = (v) => v.toFixed(2);
const tr = (el, x, y, rot = 0) => { el.style.transform = `translate(${fmt(x)}px, ${fmt(y)}px)${rot ? ` rotate(${rot.toFixed(0)}deg)` : ''}`; };
/** Point on a circle around the centre at `deg` (screen angle). */
const polar = (r, deg) => [50 + r * Math.cos(deg * DEG), 50 + r * Math.sin(deg * DEG)];
/** Direction (deg) and length of the move still needed: from the live head position toward the target. */
function moveDir(s) {
  const from = s.you || { x: 50, y: 50 };
  const dx = s.target.x - from.x, dy = s.target.y - from.y;
  return { deg: Math.atan2(dy, dx) / DEG, len: Math.hypot(dx, dy) };
}

const CHEVRONS = '<path d="M-7,-2.6 L-4.4,0 L-7,2.6"/><path d="M-1.3,-2.6 L1.3,0 L-1.3,2.6"/><path d="M4.4,-2.6 L7,0 L4.4,2.6"/>';
const TARGET = '<circle class="gd-pulse" r="4.5"/><circle class="gd-dot" r="4"/><path class="gd-tick" d="M-1.9,0.1 L-0.5,1.5 L2.1,-1.4"/>';

// ---------------------------------------------------------------- 1 + 2: dot / hold ring
function dotGuide(svg, withHold) {
  const HOLD_C = 2 * Math.PI * 7;
  svg.innerHTML = `<line class="gd-line" id="gd-line"/>
    <g class="gd-chev" id="gd-chev">${CHEVRONS}</g>
    <g id="gd-target">${TARGET}${withHold ? `<circle class="gd-hold" r="7" stroke-dasharray="0 ${HOLD_C.toFixed(2)}"/>` : ''}</g>
    <g class="gd-you" id="gd-you"><circle r="2.4"/></g>`;
  const $ = (id) => svg.querySelector(id);
  const target = $('#gd-target'), you = $('#gd-you'), line = $('#gd-line'), chev = $('#gd-chev'), hold = $('.gd-hold');
  return (s) => {
    tr(target, s.target.x, s.target.y);
    const show = !!s.you && !s.hit && Math.hypot(s.target.x - s.you.x, s.target.y - s.you.y) > 9;
    if (s.you) {
      tr(you, s.you.x, s.you.y);
      line.setAttribute('x1', fmt(s.you.x)); line.setAttribute('y1', fmt(s.you.y));
      line.setAttribute('x2', fmt(s.target.x)); line.setAttribute('y2', fmt(s.target.y));
      tr(chev, (s.you.x + s.target.x) / 2, (s.you.y + s.target.y) / 2, moveDir(s).deg);
    }
    you.classList.toggle('hidden', !s.you);
    line.classList.toggle('hidden', !show);
    chev.classList.toggle('hidden', !show);
    target.classList.toggle('hit', s.hit);
    target.classList.toggle('over', s.over);
    if (hold) hold.setAttribute('stroke-dasharray', `${fmt(HOLD_C * (s.hit ? s.holdFrac : 0))} ${fmt(HOLD_C)}`);
  };
}

// ---------------------------------------------------------------- 3: Face ID tick ring
function faceIdGuide(svg) {
  const N = 60;
  svg.innerHTML = Array.from({ length: N }, (_, i) => {
    const deg = i * (360 / N), [x1, y1] = polar(36.5, deg), [x2, y2] = polar(41.5, deg);
    return `<line class="gd-ftick" data-deg="${deg}" x1="${fmt(x1)}" y1="${fmt(y1)}" x2="${fmt(x2)}" y2="${fmt(y2)}"/>`;
  }).join('');
  const ticks = [...svg.querySelectorAll('.gd-ftick')].map((el) => ({ el, deg: Number(el.dataset.deg) }));
  return (s) => {
    const live = s.you ? { deg: Math.atan2(s.you.y - 50, s.you.x - 50) / DEG, mag: Math.hypot(s.you.x - 50, s.you.y - 50) / 34 } : null;
    const tHint = s.hint !== 'center' ? HINT_ANGLE[s.hint] : null;
    svg.classList.toggle('gd-center', s.hint === 'center' && !s.hit);
    for (const t of ticks) {
      // Captured directions stay green; their sector widens as more of that direction's angles are captured.
      const done = Object.entries(s.captured).some(([h, frac]) => h !== 'center' && frac > 0 && angDiff(t.deg, HINT_ANGLE[h]) <= 32 * frac);
      t.el.classList.toggle('done', done);
      t.el.classList.toggle('target', !done && tHint !== null && angDiff(t.deg, tHint) <= 30);
      t.el.classList.toggle('lit', !!live && live.mag > 0.12 && angDiff(t.deg, live.deg) <= 10 + 12 * Math.min(1, live.mag));
      t.el.classList.toggle('over', s.over && tHint !== null && angDiff(t.deg, tHint) <= 30);
    }
  };
}

// ---------------------------------------------------------------- 4: mirror avatar + arrow
function avatarGuide(svg) {
  svg.innerHTML = `<g class="gd-avatar" transform="translate(11 11)">
      <circle class="gd-av-bg" r="10"/>
      <ellipse class="gd-av-face" rx="6.2" ry="7.6"/>
      <g id="gd-av-feat"><circle cx="-2.3" cy="-1.6" r=".9"/><circle cx="2.3" cy="-1.6" r=".9"/>
        <path d="M0,-.4 L0,1.6 L-.7,1.9"/><path d="M-1.8,3.6 L0,4.3 L1.8,3.6"/></g>
    </g>
    <g class="gd-arrow" id="gd-arrow"><path class="gd-arrow-shape" d="M-5,-6 L3,0 L-5,6"/><path class="gd-arrow-shape gd-arrow-2" d="M-11,-6 L-3,0 L-11,6"/></g>
    <g class="gd-ok hidden" id="gd-ok"><circle r="5.5"/><path d="M-2.6,.2 L-.7,2.1 L2.8,-1.9"/></g>`;
  const feat = svg.querySelector('#gd-av-feat'), arrow = svg.querySelector('#gd-arrow'), ok = svg.querySelector('#gd-ok');
  return (s) => {
    // Live copy of the head: features slide the way the face turns (same mirrored mapping as the video).
    const fx = s.you ? ((s.you.x - 50) / 34) * 3.4 : 0, fy = s.you ? ((s.you.y - 50) / 30) * 2.6 : 0;
    feat.setAttribute('transform', `translate(${fmt(fx)} ${fmt(fy)})`);
    const { deg, len } = moveDir(s);
    const needMove = !s.hit && len > 6;
    const [ax, ay] = polar(33, deg);
    tr(arrow, ax, ay, deg);
    arrow.classList.toggle('hidden', !needMove);
    arrow.classList.toggle('over', s.over);
    tr(ok, s.target.x, s.target.y);
    ok.classList.toggle('hidden', !s.hit || s.hint === 'center');
  };
}

// ---------------------------------------------------------------- 5: face points + scan line + edge glow
function pointsGuide(svg) {
  const EDGES = [[0, 1], [0, 2], [1, 2], [2, 3], [2, 4], [3, 4]];
  svg.innerHTML = `<defs><clipPath id="gd-clip"><circle cx="50" cy="50" r="42.5"/></clipPath></defs>
    <g clip-path="url(#gd-clip)"><rect class="gd-scan" x="7.5" y="0" width="85" height="1.4"/></g>
    <path class="gd-glow" id="gd-glow"/>
    <g class="gd-mesh">${EDGES.map(() => '<line/>').join('')}${Array.from({ length: 5 }, () => '<circle r="1.2"/>').join('')}</g>`;
  const lines = [...svg.querySelectorAll('.gd-mesh line')], dots = [...svg.querySelectorAll('.gd-mesh circle')];
  const glow = svg.querySelector('#gd-glow'), mesh = svg.querySelector('.gd-mesh');
  return (s) => {
    mesh.classList.toggle('hidden', !s.landmarks);
    if (s.landmarks) {
      s.landmarks.forEach(([x, y], i) => { dots[i].setAttribute('cx', fmt(x)); dots[i].setAttribute('cy', fmt(y)); });
      EDGES.forEach(([a, b], i) => {
        lines[i].setAttribute('x1', fmt(s.landmarks[a][0])); lines[i].setAttribute('y1', fmt(s.landmarks[a][1]));
        lines[i].setAttribute('x2', fmt(s.landmarks[b][0])); lines[i].setAttribute('y2', fmt(s.landmarks[b][1]));
      });
    }
    mesh.classList.toggle('hit', s.hit);
    // Edge glow: a bright arc on the side of the circle the person should turn toward (green once there).
    const { deg, len } = moveDir(s);
    const centre = s.hint === 'center';
    const show = centre || s.hit || len > 6;
    const at = s.hit && !centre ? HINT_ANGLE[s.hint] : deg;
    if (centre) {
      glow.setAttribute('d', 'M50,8.5 A41.5,41.5 0 1 1 49.99,8.5');
    } else {
      const [x1, y1] = polar(41.5, at - 28), [x2, y2] = polar(41.5, at + 28);
      glow.setAttribute('d', `M${fmt(x1)},${fmt(y1)} A41.5,41.5 0 0 1 ${fmt(x2)},${fmt(y2)}`);
    }
    glow.classList.toggle('hidden', !show);
    glow.classList.toggle('hit', s.hit);
    glow.classList.toggle('over', s.over);
    glow.classList.toggle('soft', centre && !s.hit);
  };
}

const BUILDERS = { dot: (svg) => dotGuide(svg, false), hold: (svg) => dotGuide(svg, true), faceid: faceIdGuide, avatar: avatarGuide, points: pointsGuide };

/** Render `style` into the guide <svg>; returns update(state). Unknown ids fall back to the first style. */
export function createGuide(style, svg) {
  const id = BUILDERS[style] ? style : STYLES[0].id;
  svg.setAttribute('data-style', id);
  svg.classList.remove('gd-center');
  const update = BUILDERS[id](svg);
  return { id, update };
}

