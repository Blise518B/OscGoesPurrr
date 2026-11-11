// The demo window's Suits page (src/ui/views/suits.py, body_view.py,
// suits_cards.py): her front and back with every bHaptics dot and OWO patch
// where the app puts them, the card that opens beside her for what you click
// (with its line to it), the chips under her, the contact check, each suit's
// own frame, and the zone routes. Its
// sidebar entry shows while Settings -> Features has a suit switched on, as in
// the app, and each suit switched on has its row on Home (home_devices.py),
// which this file keeps up to date.
//
// There is no suit behind it. The demo's PC has a bHaptics TactSuit Pro vest
// connected and switched on, as it has toys and a shocker hub; OWO is
// switched off in Features (a new install has both off), with My OWO
// connected for when you switch it on. The avatar it wears has the bHaptics
// vest and head contacts and OWO's four front ones -- so the contact check has
// something to say. Nothing on that avatar touches the suits, so the body
// stays quiet except where you press: a held dot, and a part's Feel it, reach
// the Right now line as the app's do (suits_router's test holds, on the parts
// that are connected). An OWO Feel it shows nowhere on the page, in the app
// either.
//
// #demo=suits switches both suits on and opens the page.

import { el, hslider, segmented, toggle } from "./remote-ui.js";

const D = window.OGPDemo;

// ---- body_map.py ---------------------------------------------------------------
const POSITIONS = [["Head", 6], ["VestFront", 20], ["VestBack", 20], ["ForearmL", 6], ["ForearmR", 6],
                   ["HandL", 3], ["HandR", 3], ["FootL", 3], ["FootR", 3]];
const NODE_COUNTS = Object.fromEntries(POSITIONS);
const PART_GROUPS = [["vest", "Vest", ["VestFront", "VestBack"]], ["arms", "Sleeves", ["ForearmL", "ForearmR"]],
                     ["hands", "Hands", ["HandL", "HandR"]], ["feet", "Feet", ["FootL", "FootR"]],
                     ["head", "Head", ["Head"]]];
const GROUP_OF = Object.fromEntries(PART_GROUPS.flatMap(([key, , ps]) => ps.map((p) => [p, key])));
const MUSCLES = ["Pectoral_R", "Pectoral_L", "Abdominal_R", "Abdominal_L", "Arm_R", "Arm_L",
                 "Dorsal_R", "Dorsal_L", "Lumbar_R", "Lumbar_L"];
const range = (n) => Array.from({ length: n }, (_v, i) => i);
const cells = (rows, cols) => rows.flatMap((r) => cols.map((c) => r * 4 + c));
const UPPER = [0, 1], LOWER = [2, 3, 4];
// each vest panel numbered as seen from outside it: her right on the front's
// columns 0-1, on the back's 2-3
const OWO_REGIONS = {
  Pectoral_R: ["VestFront", cells(UPPER, [0, 1])], Pectoral_L: ["VestFront", cells(UPPER, [2, 3])],
  Abdominal_R: ["VestFront", cells(LOWER, [0, 1])], Abdominal_L: ["VestFront", cells(LOWER, [2, 3])],
  Arm_R: ["ForearmR", range(6)], Arm_L: ["ForearmL", range(6)],
  Dorsal_R: ["VestBack", cells(UPPER, [2, 3])], Dorsal_L: ["VestBack", cells(UPPER, [0, 1])],
  Lumbar_R: ["VestBack", cells(LOWER, [2, 3])], Lumbar_L: ["VestBack", cells(LOWER, [0, 1])],
};
const NAMES = {
  Head: "Head", VestFront: "Vest front", VestBack: "Vest back", ForearmL: "Left arm", ForearmR: "Right arm",
  HandL: "Left hand", HandR: "Right hand", FootL: "Left foot", FootR: "Right foot",
  Pectoral_R: "Right chest", Pectoral_L: "Left chest", Abdominal_R: "Right belly", Abdominal_L: "Left belly",
  Arm_R: "Right arm", Arm_L: "Left arm", Dorsal_R: "Right upper back", Dorsal_L: "Left upper back",
  Lumbar_R: "Right lower back", Lumbar_L: "Left lower back",
};
const positionsOf = (groups) => POSITIONS.map(([p]) => p).filter((p) => groups.has(GROUP_OF[p]));
const MUSCLE_OF = {};
for (const [m, [pos, idx]] of Object.entries(OWO_REGIONS)) for (const i of idx) MUSCLE_OF[`${pos}:${i}`] = m;
const muscleAt = (pos, i) => MUSCLE_OF[`${pos}:${i}`] || null;

// ---- body_view.py: where everything sits on her, in the drawing's pixels ---------
const FIG = { x: 255, y: 20, w: 535, h: 1480 };   // what's shown of the 1024 x 1536 drawing
const DOT_R = 10, DOT_MIN_PX = 4.5, ZONE_PAD = 7, HEIGHT = 700, CAPTION_H = 24, VIEW_GAP = 28;
const FIGURE_ALPHA = 0.5, FRONT = 0, BACK = 1;
const rad = (d) => (d * Math.PI) / 180;

function grid([ox, oy], angle, stepC, stepR, cols, rows) {
  const a = rad(angle), ux = Math.cos(a), uy = Math.sin(a), vx = -Math.sin(a), vy = Math.cos(a);
  const out = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) out.push([ox + c * stepC * ux + r * stepR * vx, oy + c * stepC * uy + r * stepR * vy]);
  }
  return out;
}
const along = ([sx, sy], angle, steps) => steps.map((d) => [sx - d * Math.sin(rad(angle)), sy + d * Math.cos(rad(angle))]);
const mirror = (pts) => pts.map(([x, y]) => [1024 - x, y]);

// her right forearm's arm warmer, elbow band to wrist band; the left one mirrors it
const ELBOW = [356, 590], WRIST = [316, 738];
const ARM_ANGLE = (Math.atan2(ELBOW[0] - WRIST[0], WRIST[1] - ELBOW[1]) * 180) / Math.PI;

/** position -> [view, the angle its grid is turned by, dot centres] */
const PLACES = (() => {
  const a = ARM_ANGLE;
  const first = along(ELBOW, a, [0.15 * Math.hypot(WRIST[0] - ELBOW[0], WRIST[1] - ELBOW[1])])[0];
  const across = 21;
  const arm = grid([first[0] - (across / 2) * Math.cos(rad(a)), first[1] - (across / 2) * Math.sin(rad(a))],
                   a, across, 41, 2, 3);
  const hand = along(WRIST, a, [26, 50, 74]);
  const foot = [[446, 1433], [465, 1428], [484, 1433]];
  const head = [-62.5, -37.5, -12.5, 12.5, 37.5, 62.5].map((k) => [516 + k, 150 + 6 * (k / 62.5) ** 2]);
  return {
    Head: [FRONT, 0, head],
    VestFront: [FRONT, 0, grid([452, 372], 0, 40, 63, 4, 5)],
    VestBack: [BACK, 0, grid([452, 368], 0, 40, 63, 4, 5)],
    ForearmR: [FRONT, a, arm],
    ForearmL: [FRONT, -a, mirror(arm)],
    HandR: [FRONT, a, hand],
    HandL: [FRONT, -a, mirror(hand)],
    FootR: [FRONT, 0, foot],
    FootL: [FRONT, 0, mirror(foot)],
  };
})();
const SIDE_MARKS = [[268, 440], [756, 440]];       // where the R / L letters go

// ---- what the demo's PC and avatar have --------------------------------------------
const SUIT = { label: "TactSuit Pro", battery: 87, positions: ["VestFront", "VestBack"] };
const AVATAR = {          // the worn avatar's suit contacts (VRChat's list of its parameters)
  contacts: { VestFront: range(20), VestBack: range(20), Head: range(6) },
  owo: new Set(["Abdominal_L", "Abdominal_R", "Pectoral_L", "Pectoral_R"]),
};
const TEST_DOT_MS = 600;  // suits_facade.TEST_HOLD_S: a part's Feel it
const HOLD_DOT_MS = 5000; // .. bhaptics_hold_dot: a pressed dot, at most
const OWO_TEST = 10;      // suits_cards.TEST_PERCENT
const REACT = ["Everyone", "Others only", "Me only"];
const INSPECTOR_W = 250, COLUMN_TOP = 24;

const SU = {
  bh: {
    link: "connected",                  // or "released" (Let go)
    paused: false,                      // Home's On / Off (bhaptics_stop_all)
    have: new Set(["vest"]), auto: true, react: 0, follow: true,
    devices: Object.fromEntries(POSITIONS.map(([p]) => [p, { on: true, strength: 100 }])),
  },
  owo: {
    connected: true, paused: false, auto: false, react: 0, follow: true, ceiling: 60, freq: 50,
    muscles: Object.fromEntries(MUSCLES.map((m) => [m, { on: true, top: 100 }])),
  },
  pick: { part: null, muscle: null },
  held: null,               // [position, index] pressed on her
  holds: new Map(),         // "pos:i" -> until (ms): the test dots the engine is sent
  routes: [],
};
// what refresh() worked out, for painting and picking (the BodyView's state)
const V = { bhOn: false, owoOn: false, shown: new Set(), dots: false, missDots: {}, missMuscles: new Set(),
            contacts: AVATAR.contacts };
const W = {};

// ---- small pieces in the app's look ----------------------------------------------
function hued(node, hue) {
  node.style.setProperty("--hue", `var(--${hue})`);
  node.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
  node.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
  return node;
}
const muted = (text, cls = "") => el(`p.pg-note${cls}`, {}, text);
function pill(text = "", tone = "") {
  const p = el("span.pg-pill", {}, text);
  p.set = (t, tn) => { p.textContent = t; p.className = `pg-pill${tn ? " " + tn : ""}`; p.hidden = !t; };
  p.set(text, tone);
  return p;
}
/** A value as the app's ValueSlider: its name, the number written out, the slider. */
function valueRow(label, { min, max, value, hue, fmt, onInput }) {
  const val = el("b.pg-val", {}, fmt(value));
  const input = hslider({ min, max, value, hue, onInput: (x) => { val.textContent = fmt(x); onInput && onInput(x); } });
  const row = el("div.pg-vrow", {}, el("div.pg-vhead", {}, el("span", {}, label), val), input);
  row.set = (v) => { if (!input.busy) input.setQuiet(v); val.textContent = fmt(Number(input.value)); };
  row.enable = (on) => { input.disabled = !on; row.classList.toggle("off", !on); };
  return row;
}
const btn = (text, cls, onclick, title) => el(`button.pg-btn${cls}`, { type: "button", onclick, title }, text);
/** The page's chip rows (suits_cards.ChipRow): every part or muscle with its setting. */
function chipRow(names, hue, onPick, labels = NAMES) {
  const box = hued(el("div.su-chips"), hue);
  const chips = {};
  for (const n of names) {
    chips[n] = el("button.su-chip", { type: "button", onclick: () => onPick(n) }, labels[n]);
    box.append(chips[n]);
  }
  return {
    box, chips,
    values(get) { for (const n of names) { const [on, pct] = get(n); chips[n].textContent = on ? `${labels[n]}  ${pct} %` : `${labels[n]}  off`; } },
    picked(name) { for (const n of names) chips[n].classList.toggle("on", n === name); },
    checked(set) { for (const n of names) chips[n].classList.toggle("on", set.has(n)); },
    shown(set) { for (const n of names) chips[n].hidden = !set.has(n); },
  };
}
/** The legend's marks, drawn as the body draws them (suits_cards.Swatch). */
function swatch(hue, shape) {
  const s = el("span.su-swatch");
  const v = `var(--${hue})`, mid = `var(--${hue}-mid)`, tint = `var(--${hue}-tint)`;
  s.innerHTML = '<svg viewBox="0 0 16 16" width="16" height="16">' + (
    shape === "patch" ? `<rect x="2.5" y="2.5" width="11" height="11" rx="3" style="fill:${tint};stroke:${mid};stroke-width:1.3"/>`
    : shape === "missing" ? `<circle cx="8" cy="8" r="7" style="fill:none;stroke:${v};stroke-width:1.3;stroke-dasharray:5.2 2.6"/>`
    : `<circle cx="8" cy="8" r="5.5" style="fill:var(--well);stroke:${v};stroke-width:1.4"/>`) + "</svg>";
  return s;
}

// ---- the body: geometry (BodyView) -------------------------------------------------
const G = { w: 0, h: 0, s: 0 };
function layoutBody() {
  const w = W.body.clientWidth;
  if (!w) return false;
  const byW = (w - VIEW_GAP) / 2 / FIG.w;
  const h = Math.floor(Math.min(HEIGHT, CAPTION_H + FIG.h * byW + 2));
  G.w = w; G.h = h;
  G.s = Math.max(0.05, Math.min((h - CAPTION_H) / FIG.h, byW));
  W.body.style.height = `${h}px`;
  W.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  W.svg.setAttribute("width", w);
  W.svg.setAttribute("height", h);
  return true;
}
function viewRect(view) {
  const s = G.s, w = FIG.w * s, h = FIG.h * s;
  const x0 = (G.w - (2 * w + VIEW_GAP)) / 2;
  return { x: x0 + view * (w + VIEW_GAP), y: CAPTION_H, w, h };
}
function toW(view, [x, y]) {
  const r = viewRect(view);
  return [r.x + (x - FIG.x) * G.s, r.y + (y - FIG.y) * G.s];
}
const dotR = () => Math.max(DOT_MIN_PX, DOT_R * G.s);
const dotAt = (pos, i) => toW(PLACES[pos][0], PLACES[pos][2][i]);

/** A muscle's patch: a rounded box around its dots, turned with the limb they
 *  sit on -- {view, angle, x, y, w, h, r} in the turned drawing's pixels. */
function zone(muscle, grow = 0) {
  const [pos, idx] = OWO_REGIONS[muscle];
  const [view, angle, points] = PLACES[pos];
  const a = rad(angle), ca = Math.cos(a), sa = Math.sin(a);
  const local = idx.map((i) => points[i]).map(([x, y]) => [x * ca + y * sa, -x * sa + y * ca]);
  const pad = dotR() / G.s + ZONE_PAD + grow / G.s;
  const xs = local.map((p) => p[0]), ys = local.map((p) => p[1]);
  const x = Math.min(...xs) - pad, y = Math.min(...ys) - pad;
  return { view, angle, x, y, w: Math.max(...xs) - Math.min(...xs) + 2 * pad,
           h: Math.max(...ys) - Math.min(...ys) + 2 * pad, r: pad };
}
/** A point of the turned drawing, in the widget. */
function zoneToW(z, [lx, ly]) {
  const a = rad(z.angle), ca = Math.cos(a), sa = Math.sin(a);
  return toW(z.view, [lx * ca - ly * sa, lx * sa + ly * ca]);
}
function zonePath(z) {
  const { x, y, w, h, r } = z, R = r * G.s;
  const P = (px, py) => zoneToW(z, [px, py]).map((v) => v.toFixed(2)).join(" ");
  return `M${P(x + r, y)}L${P(x + w - r, y)}A${R} ${R} 0 0 1 ${P(x + w, y + r)}` +
         `L${P(x + w, y + h - r)}A${R} ${R} 0 0 1 ${P(x + w - r, y + h)}` +
         `L${P(x + r, y + h)}A${R} ${R} 0 0 1 ${P(x, y + h - r)}` +
         `L${P(x, y + r)}A${R} ${R} 0 0 1 ${P(x + r, y)}Z`;
}
function zoneBox(z) {           // the patch's bounding box in the widget
  const { x, y, w, h, r } = z;
  const pts = [[x + r, y + r], [x + w - r, y + r], [x + w - r, y + h - r], [x + r, y + h - r]].map((p) => zoneToW(z, p));
  const R = r * G.s, xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return { l: Math.min(...xs) - R, r: Math.max(...xs) + R, t: Math.min(...ys) - R, b: Math.max(...ys) + R };
}
function inZone(z, px, py) {
  const rr = viewRect(z.view);
  const dx = (px - rr.x) / G.s + FIG.x, dy = (py - rr.y) / G.s + FIG.y;
  const a = rad(z.angle), ca = Math.cos(a), sa = Math.sin(a);
  const lx = dx * ca + dy * sa, ly = -dx * sa + dy * ca;
  if (lx < z.x || lx > z.x + z.w || ly < z.y || ly > z.y + z.h) return false;
  const cx = Math.min(Math.max(lx, z.x + z.r), z.x + z.w - z.r), cy = Math.min(Math.max(ly, z.y + z.r), z.y + z.h - z.r);
  return (lx - cx) ** 2 + (ly - cy) ** 2 <= z.r ** 2;
}
/** Where the line to its card starts: the right edge of a part's dots or a
 *  patch, at its middle. null for something not on her right now. */
function anchor(kind, name) {
  if (kind === "part" && V.bhOn && V.shown.has(name)) {
    const pts = PLACES[name][2].map((_p, i) => dotAt(name, i));
    const ys = pts.map((p) => p[1]);
    return [Math.max(...pts.map((p) => p[0])) + dotR() + 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  }
  if (kind === "muscle" && V.owoOn && OWO_REGIONS[name]) {
    const b = zoneBox(zone(name));
    return [b.r + 1, (b.t + b.b) / 2];
  }
  return null;
}
function hitDot(px, py) {
  if (!V.bhOn) return null;
  let best = null, bestD = (dotR() + 4) ** 2;
  for (const [pos, [, , points]] of Object.entries(PLACES)) {
    if (!V.shown.has(pos)) continue;
    points.forEach((_p, i) => {
      const [cx, cy] = dotAt(pos, i), d = (cx - px) ** 2 + (cy - py) ** 2;
      if (d <= bestD) { best = [pos, i]; bestD = d; }
    });
  }
  return best;
}
const hitMuscle = (px, py) => (V.owoOn ? MUSCLES.find((m) => inZone(zone(m), px, py)) || null : null);

// ---- the body: painting --------------------------------------------------------------
const C = (hue) => [`var(--${hue})`, `var(--${hue}-mid)`, `var(--${hue}-tint)`];
const blend = (hue, t) => `color-mix(in srgb, var(--${hue}) ${(Math.max(0, Math.min(1, t)) * 100).toFixed(1)}%, var(--${hue}-tint))`;
const dash = (w) => `stroke-dasharray:${4 * w} ${2 * w}`;
const WARN = `fill:none;stroke:var(--amber);stroke-width:1.3;${dash(1.3)}`;

function paintBody() {
  if (!G.w && !layoutBody()) return;
  const out = ['<defs><filter id="su-tint" color-interpolation-filters="sRGB">' +
               '<feFlood style="flood-color:var(--accent)"/><feComposite in2="SourceGraphic" operator="in"/></filter></defs>'];
  for (const [view, caption, sides, img] of [[FRONT, "FRONT", ["R", "L"], "front"], [BACK, "BACK", ["L", "R"], "back"]]) {
    const r = viewRect(view);
    out.push(`<text class="su-cap" x="${r.x + r.w / 2}" y="${CAPTION_H / 2}">${caption}</text>`,
             `<image href="assets/demo/suit-${img}.png" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" ` +
             `preserveAspectRatio="none" filter="url(#su-tint)" opacity="${FIGURE_ALPHA}"/>`);
    // her right and left as she stands, beside her chest: on the front her right is on our left
    SIDE_MARKS.forEach((p, k) => {
      const [x, y] = toW(view, p);
      out.push(`<text class="su-side" x="${x}" y="${y}">${sides[k]}</text>`);
    });
  }
  if (V.owoOn) {
    const [vib, mid, tint] = C("purple");
    for (const m of MUSCLES) {
      const z = zone(m), off = !SU.owo.muscles[m].on, picked = m === SU.pick.muscle;
      const fill = `fill:${tint};fill-opacity:${off ? 0 : 0.6}`;   // nothing on her plays it
      const w = picked ? 2.2 : 1.3;
      out.push(`<path d="${zonePath(z)}" style="${fill};stroke:${off ? "var(--dim)" : picked ? vib : mid};` +
               `stroke-width:${w};${off ? dash(w) : ""}"/>`);
      if (V.missMuscles.has(m) && !off) out.push(`<path d="${zonePath(zone(m, 3))}" style="${WARN}"/>`);
    }
  }
  if (V.bhOn) {
    const [vib, , tint] = C("orange"), r = dotR();
    for (const [pos, [, , points]] of Object.entries(PLACES)) {
      if (!V.shown.has(pos)) continue;
      const off = !SU.bh.devices[pos].on, picked = pos === SU.pick.part, missing = V.missDots[pos] || new Set();
      points.forEach((_p, i) => {
        const held = SU.held && SU.held[0] === pos && SU.held[1] === i;
        const fill = held ? blend("orange", 0.3 + 0.7 * 0.5) : picked && !off ? tint : "var(--well)";
        const [x, y] = dotAt(pos, i);
        out.push(`<circle cx="${x}" cy="${y}" r="${r}" style="fill:${fill};stroke:${off ? "var(--dim)" : vib};` +
                 `stroke-width:${picked ? 2 : 1.3}"/>`);
        if (missing.has(i) && !off) out.push(`<circle cx="${x}" cy="${y}" r="${r + 2.5}" style="${WARN}"/>`);
      });
    }
  }
  W.svg.innerHTML = out.join("");
}

// ---- the inspector: the cards beside her -----------------------------------------------
function cardHead(hue, tag) {
  const title = el("b.su-title");
  const head = el("div.su-head", {}, title, hued(el("span.su-tag", {}, tag), hue));
  return { head, title };
}
function partCard() {
  const { head, title } = cardHead("orange", "bHaptics");
  const check = pill();
  const on = toggle("On", true, (v) => { SU.bh.devices[W.part.part].on = v; refresh(); });
  const strength = valueRow("Strength", { min: 0, max: 100, value: 100, hue: "orange", fmt: (v) => `${v} %`,
    onInput: (v) => { SU.bh.devices[W.part.part].strength = v; W.partChips.values(partValue); } });
  strength.title = "How strong this part gets at a full touch, before the sidebar's strength.";
  const test = btn("Feel it", ".su-test", () => feelPart(W.part.part), "A gentle buzz on every motor of this part.");
  const hint = el("p.su-hint");
  const card = hued(el("div.su-card", {}, head, check, on, strength, test, hint), "orange");
  W.part = { card, title, check, on, strength, test, hint, part: "VestFront" };
  return card;
}
function showPart(part) {
  const P = W.part, cfg = SU.bh.devices[part], n = NODE_COUNTS[part];
  P.part = part;
  P.title.textContent = NAMES[part];
  P.on.set(cfg.on);
  P.strength.set(cfg.strength);
  P.strength.enable(cfg.on);
  P.test.disabled = !cfg.on;
  P.hint.textContent = cfg.on ? `${n} motors. Press and hold a dot to feel just that one.`
    : "Off: this part never buzzes, whatever touches it.";
  const found = (V.contacts[part] || []).length;
  if (found >= n) P.check.set(`On your avatar: all ${n} contacts`, "ok");
  else if (found) P.check.set(`On your avatar: ${found} of ${n} contacts`, "warn");
  else P.check.set("Not on your avatar", "err");
}
function muscleCard() {
  const { head, title } = cardHead("purple", "OWO");
  const check = pill();
  const on = toggle("On", true, (v) => { SU.owo.muscles[W.muscle.muscle].on = v; refresh(); });
  const top = valueRow("Top", { min: 0, max: 100, value: 100, hue: "purple", fmt: (v) => `${v} %`,
    onInput: (v) => { SU.owo.muscles[W.muscle.muscle].top = v; W.muscleChips.values(muscleValue); } });
  top.title = "A full touch on this muscle goes this high -- still under the ceiling.";
  const ceiling = el("p.su-hint");
  const test = btn(`Feel it (${OWO_TEST} %)`, ".su-test", () => {},
    `One short, gentle sensation on this muscle (${OWO_TEST} %, or its top if that's lower).`);
  const hint = el("p.su-hint");
  const card = hued(el("div.su-card", {}, head, check, on, top, ceiling, test, hint), "purple");
  W.muscle = { card, title, check, on, top, ceiling, test, hint, muscle: "Pectoral_R" };
  return card;
}
function showMuscle(muscle) {
  const M = W.muscle, cfg = SU.owo.muscles[muscle], [pos, idx] = OWO_REGIONS[muscle];
  const follows = SU.owo.follow, dotsShown = V.dots && V.shown.has(pos);
  M.muscle = muscle;
  M.title.textContent = NAMES[muscle];
  M.on.set(cfg.on);
  M.top.set(cfg.top);
  M.top.enable(cfg.on);
  M.test.disabled = !cfg.on;
  M.ceiling.textContent = `Never above the ceiling (${SU.owo.ceiling} %).`;
  M.hint.textContent = !cfg.on ? "Off: this muscle never plays."
    : !follows ? "Plays from your avatar's OWO contacts and zone routes."
    : dotsShown ? `Any touch on the ${idx.length} bHaptics dots inside it plays it too; each dot still buzzes on its own on the bHaptics suit.`
    : "Plays from your avatar's OWO contacts, zone routes, and any bHaptics contact your avatar has inside it.";
  const via = follows ? idx.filter((i) => (V.contacts[pos] || []).includes(i)).length : 0;
  if (AVATAR.owo.has(muscle)) M.check.set("On your avatar: its OWO contact", "ok");
  else if (via) M.check.set(`Played by ${via} bHaptics contacts`, "ok");
  else M.check.set("No contact for it on your avatar", "err");
}

/** Open a card for each thing picked (on her or in the chips); nothing picked
 *  shows the hint. A part you no longer have is dropped from the pick. */
function fillInspector() {
  let { part, muscle } = SU.pick;
  if (!(V.dots && V.shown.has(part))) part = null;
  if (!V.owoOn) muscle = null;
  SU.pick = { part, muscle };
  if (part) showPart(part);
  if (muscle) showMuscle(muscle);
  W.part.card.hidden = !part;
  W.muscle.card.hidden = !muscle;
  W.hint.hidden = Boolean(part || muscle);
  W.partChips.picked(part);
  W.muscleChips.picked(muscle);
  paintBody();
  alignColumn();
  drawLeaders();
}
/** The open cards move down so the first sits level with what it is for, as
 *  far as they all still fit beside her. */
function alignColumn() {
  const picks = [[W.part.card, "part", SU.pick.part], [W.muscle.card, "muscle", SU.pick.muscle]]
    .filter(([, , name]) => name).map(([card, kind, name]) => [card, anchor(kind, name)]);
  let pad = COLUMN_TOP;
  if (picks.length && picks[0][1]) {
    const used = picks.reduce((sum, [card]) => sum + card.offsetHeight + 10, 0);
    pad = Math.floor(Math.max(COLUMN_TOP, Math.min(picks[0][1][1] - 22, G.h - used)));
  }
  W.colPad.style.height = `${pad}px`;
}
/** The lines from each picked thing on her to the top of its card. */
function drawLeaders() {
  const lines = [];
  for (const [kind, name, card, hue] of [["part", SU.pick.part, W.part.card, "orange"],
                                         ["muscle", SU.pick.muscle, W.muscle.card, "purple"]]) {
    if (!name || card.hidden) continue;
    const a = anchor(kind, name);
    if (!a) continue;
    const sx = W.body.offsetLeft + a[0], sy = W.body.offsetTop + a[1];
    const ex = card.offsetLeft, ey = card.offsetTop + 15, c = `var(--${hue})`;
    lines.push(`<polyline points="${sx},${sy} ${sx + 12},${sy} ${ex},${ey}" style="fill:none;stroke:${c};stroke-width:1.5"/>`,
               `<circle cx="${sx}" cy="${sy}" r="2.5" style="fill:${c}"/><circle cx="${ex}" cy="${ey}" r="3" style="fill:${c}"/>`);
  }
  W.leaders.innerHTML = lines.join("");
}
function pick(part, muscle) { SU.pick = { part, muscle }; fillInspector(); }

// ---- pressing on her, and the tests ----------------------------------------------------
const outputOff = () => D.state.off || D.state.strength <= 0;
const bhLinked = () => V.bhOn && SU.bh.link === "connected" && !SU.bh.paused;
function hold(pos, i, ms) {
  if (ms === null) SU.holds.delete(`${pos}:${i}`);
  else SU.holds.set(`${pos}:${i}`, performance.now() + ms);
}
function feelPart(part) {
  if (!bhLinked() || outputOff()) return;              // the app logs why and does nothing
  for (let i = 0; i < NODE_COUNTS[part]; i++) hold(part, i, TEST_DOT_MS);
  live();
}
function bodyDown(e) {
  if (e.button !== 0) return;
  const rect = W.svg.getBoundingClientRect();
  const x = (e.clientX - rect.left) * (G.w / rect.width), y = (e.clientY - rect.top) * (G.h / rect.height);
  const dot = hitDot(x, y);
  if (dot) {
    SU.held = dot;
    hold(dot[0], dot[1], HOLD_DOT_MS);
    pick(dot[0], muscleAt(dot[0], dot[1]));
  } else {
    pick(null, hitMuscle(x, y));     // a patch between dots: just its muscle; empty space: close the cards
  }
  live();
}
function bodyUp() {
  if (!SU.held) return;
  hold(SU.held[0], SU.held[1], null);
  SU.held = null;
  paintBody();
  live();
}

/** The Right now line: what each suit is sent this moment (the engine's dots). */
function live() {
  const now = performance.now();
  let buzzing = 0;
  for (const [key, until] of SU.holds) {
    if (until <= now) { SU.holds.delete(key); continue; }
    if (bhLinked() && !outputOff() && SUIT.positions.includes(key.split(":")[0])) buzzing++;
  }
  const text = `Right now: ${buzzing ? `bHaptics: ${buzzing} ${buzzing === 1 ? "motor" : "motors"}` : "all quiet"}`;
  if (W.now.textContent !== text) W.now.textContent = text;
}

// ---- the page ----------------------------------------------------------------------
const partValue = (p) => [SU.bh.devices[p].on, SU.bh.devices[p].strength];
const muscleValue = (m) => [SU.owo.muscles[m].on, SU.owo.muscles[m].top];

function bodyCard() {
  W.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  W.svg.classList.add("su-svg");
  W.body = el("div.su-body", { title: "Click a part of her and its settings open beside her. Orange dots are bHaptics "
    + "motors, purple patches OWO's muscles; each lights up as it plays. Press and hold a dot to feel it. A dashed "
    + "amber ring: your avatar has no contact there. Front and back are drawn as seen from outside." }, W.svg);
  W.svg.addEventListener("pointerdown", bodyDown);
  window.addEventListener("pointerup", bodyUp);
  window.addEventListener("pointercancel", bodyUp);
  W.hint = el("p.pg-note.su-pickhint", {}, "Click a part of her to set it up. Press and hold a dot to feel it.");
  W.colPad = el("div", { style: { height: `${COLUMN_TOP}px` } });
  W.leaders = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  W.leaders.classList.add("su-leaders");
  const stage = el("div.su-stage", {}, W.body, el("div.su-col", {}, W.colPad, W.hint, partCard(), muscleCard()), W.leaders);

  const legend = el("div.su-legend");
  W.legend = {};
  for (const [key, hue, shape, text] of [["bh", "orange", "dot", "bHaptics motor — press and hold to feel it"],
                                         ["owo", "purple", "patch", "OWO muscle — the dots inside it play it too"],
                                         ["missing", "amber", "missing", "not on your avatar"]]) {
    W.legend[key] = [swatch(hue, shape), el("span", {}, text)];
    legend.append(...W.legend[key]);
  }
  W.partsLbl = muted("bHaptics parts you have");
  W.partChips = chipRow(POSITIONS.map(([p]) => p), "orange", (p) => pick(p, null));
  W.partChips.box.title = "Every part of the bHaptics suit you have, with its strength. Click one to set it up beside her.";
  W.musclesLbl = muted("OWO muscles");
  W.muscleChips = chipRow(MUSCLES, "purple", (m) => pick(null, m));
  W.muscleChips.box.title = "Every OWO muscle with its top. Click one to set it up beside her.";
  W.checkPills = el("div.su-chips");
  W.checkNote = el("p.su-hint");
  W.now = el("p.su-now", {}, "Right now: all quiet");
  return el("div.o-card.su-card-body", {},
    el("div.o-sect", {}, "Body"), stage, legend, W.partsLbl, W.partChips.box, W.musclesLbl, W.muscleChips.box,
    muted("Your avatar's contacts"),
    el("div.su-check", { title: "Whether the avatar you're wearing has the contacts for what you have: the bHaptics "
      + "avatar package's for each part, OWO's for each muscle. Read from VRChat's list of the avatar's parameters, so "
      + "nothing needs touching first." }, W.checkPills, W.checkNote),
    W.now);
}

/** A small card in a suit's frame (Avatar Remote's): a title, then rows. */
const smallCard = (title, ...kids) => el("div.su-small", {}, el("b.su-small-t", {}, title), ...kids);
function react(hue, state) {
  return el("div.su-react", {}, el("span.pg-muted", {}, "Feel touches from"),
    segmented(REACT, hue, (i) => { state.react = i; }, state.react));
}
function category(title, hue, body) {
  return hued(el(`div.pg-cat.su-cat.${hue}`, {}, el("div.pg-bar", {}, el("i.pg-ic", { innerHTML: D.icons.suits || "" }),
    el("span", {}, title)), body), hue);
}

function bhapticsFrame() {
  const bh = SU.bh;
  W.have = chipRow(PART_GROUPS.map(([k]) => k), "orange", (k) => {
    if (bh.have.has(k)) bh.have.delete(k); else bh.have.add(k);
    refresh();
  }, Object.fromEntries(PART_GROUPS.map(([k, name]) => [k, name])));
  W.bhPill = pill();
  W.bhInfo = el("p.pg-note");
  W.bhRelease = btn("Let go", "", () => { bh.link = "released"; SU.holds.clear(); refresh(); },
    "Disconnect and stop reconnecting, so the bHaptics Player or a game can use the suit. Connect takes it back.");
  const have = smallCard("You have", W.have.box, muted("Only these show on her. A part that connects is added by itself."));
  have.title = "The bHaptics parts you own: only their dots show on the body and in the lists. A part that connects is added by itself.";
  const link = smallCard("Link",
    el("div.pg-row.tight", {}, W.bhPill, el("span.grow"),
      btn("Connect", ".primary", () => { bh.link = "connected"; refresh(); },
        "Look for your bHaptics suit, sleeves and head over Bluetooth and connect them. Switch them on first, and "
        + "close the bHaptics Player: a suit takes one connection at a time. No pairing in Windows needed."),
      W.bhRelease),
    W.bhInfo,
    toggle("Connect when the app starts", bh.auto, (v) => { bh.auto = v; }));
  W.bhFollow = toggle("Also feel OWO's contacts", bh.follow, (v) => { bh.follow = v; homeRows(); });
  const touches = smallCard("Touches", react("orange", bh), W.bhFollow);
  return category("BHAPTICS", "orange", el("div.su-grid", {}, el("div.su-stack", {}, have, touches), link));
}

function owoFrame() {
  const o = SU.owo;
  W.owoPill = pill();
  W.owoInfo = el("p.pg-note");
  W.owoConnect = btn("Disconnect", ".primary", () => { o.connected = !o.connected; refresh(); },
    "Find the My OWO app — on this PC first, then on your network (the phone app works too) — and connect, the way a game does.");
  W.owoStop = btn("Stop all", ".danger", () => { o.paused = !o.paused; refresh(); },
    "Ends every sensation now and keeps the suit quiet until you press Resume - even after a restart.");
  const link = smallCard("Link",
    el("div.pg-row.tight", {}, W.owoPill, el("span.grow"), W.owoConnect, W.owoStop),
    W.owoInfo,
    toggle("Connect when the app starts", o.auto, (v) => { o.auto = v; }),
    el("div.pg-row.tight", {}, el("span.pg-muted", {}, "My OWO at"),
      el("input.su-input", { type: "text", placeholder: "this PC, then the network", tabIndex: -1 })));
  const strength = smallCard("Strength",
    valueRow("Ceiling", { min: 0, max: 100, value: o.ceiling, hue: "purple", fmt: (v) => `${v} %`,
      onInput: (v) => { o.ceiling = v; if (SU.pick.muscle) showMuscle(SU.pick.muscle); } }),
    valueRow("Frequency", { min: 1, max: 100, value: o.freq, hue: "purple", fmt: (v) => `${v} Hz`, onInput: (v) => { o.freq = v; } }),
    muted("100 % is the top of your own calibration in My OWO. Nothing goes above the ceiling — whatever a contact, a "
      + "setting or a test asks for."));
  W.owoFollow = toggle("Also feel bHaptics' contacts", o.follow, (v) => { o.follow = v; refresh(); });
  const touches = smallCard("Touches", react("purple", o), W.owoFollow);
  return category("OWO", "purple", el("div.su-grid", {}, el("div.su-stack.wide", {}, link, touches), strength));
}

const ZONE_TYPES = ["Orf", "Pen", "Touch"];
const FILTERS = [["TouchOthers", "Touch · others"], ["TouchSelf", "Touch · me"], ["PenOthers", "Pen · others"], ["PenSelf", "Pen · me"]];
function routeRow(r) {
  const row = el("div.su-route", {},
    el("div.pg-row", {},
      toggle("On", r.enabled, (v) => { r.enabled = v; }),
      el("input.su-input.zone", { type: "text", placeholder: "Zone or source", value: r.zone, tabIndex: -1,
                                  oninput: (e) => { r.zone = e.target.value; } }),
      el("span.o-in.combo.su-type", { onclick: (e) => { r.type = ZONE_TYPES[(ZONE_TYPES.indexOf(r.type) + 1) % 3]; e.currentTarget.textContent = r.type; } }, r.type),
      el("span", {}, "→"),
      el("span.o-in.combo.su-region", {}, NAMES[r.region]),
      el("div.su-gain", {}, valueRow("Gain", { min: 0, max: 400, value: r.gain, hue: "orange", fmt: (v) => `${v} %`, onInput: (v) => { r.gain = v; } })),
      btn("Delete", ".ghost", () => { SU.routes.splice(SU.routes.indexOf(r), 1); drawRoutes(); })),
    el("div.pg-row", {}, FILTERS.map(([key, label]) => el("label.su-box", {},
      el("input", { type: "checkbox", checked: r.filters.includes(key), tabIndex: -1 }), label))));
  return row;
}
function drawRoutes() {
  W.routes.replaceChildren(...(SU.routes.length ? SU.routes.map(routeRow) : [muted("None yet.")]));
}
function routesCard() {
  W.routes = el("div.su-routes");
  drawRoutes();
  return el("div.o-card.su-card-body", {},
    el("div.su-sect", {}, el("div.o-sect", {}, "Zone routes"),
      btn("+ Add route", "", () => {
        SU.routes.push({ enabled: true, zone: "", type: "Orf", filters: ["TouchOthers"], region: "VestFront", gain: 100 });
        drawRoutes();
      }, "Send an OGB / SPS zone, or one of your custom sources, to a part of the body. Both suits feel it.")),
    muted("For avatars without a suit package: pick a zone and where it should land — a muscle's patch or a whole part."),
    W.routes);
}

function build(root) {
  root.classList.add("su-page");
  root.append(
    el("div.o-viewtitle", {}, "Suits"),
    el("p.pg-intro", {}, "Your bHaptics suit and your OWO suit, both from the same contacts on your avatar. Click a part "
      + "of her to set it up."),
    bodyCard(),
    W.bhCat = bhapticsFrame(),
    W.owoCat = owoFrame(),
    routesCard());
}

// ---- refresh (suits.py refresh_suits_status) ---------------------------------------------
function refresh() {
  const f = D.state.features, bhOn = Boolean(f.bhaptics), owoOn = Boolean(f.owo);
  const shown = positionsOf(SU.bh.have);
  V.bhOn = bhOn; V.owoOn = owoOn; V.shown = new Set(shown); V.dots = bhOn && shown.length > 0;
  W.bhCat.hidden = !bhOn;
  W.owoCat.hidden = !owoOn;
  for (const n of [W.partsLbl, W.partChips.box, ...W.legend.bh]) n.hidden = !V.dots;
  for (const n of [W.musclesLbl, W.muscleChips.box, ...W.legend.owo]) n.hidden = !owoOn;
  W.legend.owo[1].textContent = V.dots ? "OWO muscle — the dots inside it play it too" : "OWO muscle — fills as it plays";

  const linked = SU.bh.link === "connected";
  if (linked) W.bhPill.set("Connected · 1 part", "ok");
  else W.bhPill.set("Let go", "idle");
  W.bhInfo.textContent = linked ? `Connected: ${SUIT.label} · ${SUIT.battery} %` : "Switch the suit on and press Connect.";
  W.bhRelease.disabled = !linked;

  const o = SU.owo;
  if (o.paused) W.owoPill.set("Stopped", "warn");
  else if (o.connected) W.owoPill.set("Connected · My OWO on this PC", "ok");
  else W.owoPill.set("Not connected", "warn");
  W.owoConnect.textContent = o.connected ? "Disconnect" : "Connect";
  W.owoStop.textContent = o.paused ? "Resume" : "Stop all";
  W.owoInfo.textContent = o.connected ? "" : "Open My OWO with the suit connected there, then press Connect.";
  W.owoInfo.hidden = !W.owoInfo.textContent;
  W.bhFollow.set(SU.bh.follow);
  W.owoFollow.set(o.follow);
  homeRows();

  W.have.checked(SU.bh.have);
  W.partChips.values(partValue);
  W.partChips.shown(V.shown);
  W.muscleChips.values(muscleValue);
  showCheck();
  fillInspector();
}

/** The contact check: does the avatar you're wearing have the contacts for
 *  what you have? Pills under her, amber rings on her. */
function showCheck() {
  const parts = V.dots ? V.shown : new Set(), items = [];
  const contacts = AVATAR.contacts, tone = (found, total) => (found >= total ? "ok" : found ? "warn" : "err");
  V.missDots = {};
  V.missMuscles = new Set();
  for (const [, name, positions] of PART_GROUPS) {
    const mine = positions.filter((p) => parts.has(p));
    if (!mine.length) continue;
    const found = mine.reduce((n, p) => n + (contacts[p] || []).length, 0);
    const total = mine.reduce((n, p) => n + NODE_COUNTS[p], 0);
    items.push([`${name}  ${found} / ${total}`, tone(found, total)]);
    for (const p of mine) {
      const gone = range(NODE_COUNTS[p]).filter((i) => !(contacts[p] || []).includes(i));
      if (gone.length) V.missDots[p] = new Set(gone);
    }
  }
  if (V.owoOn) {
    for (const [m, [pos, idx]] of Object.entries(OWO_REGIONS)) {
      const via = SU.owo.follow && idx.some((i) => (contacts[pos] || []).includes(i));
      if (!AVATAR.owo.has(m) && !via) V.missMuscles.add(m);
    }
    const found = MUSCLES.length - V.missMuscles.size;
    items.push([`OWO  ${found} / ${MUSCLES.length}`, tone(found, MUSCLES.length)]);
  }
  for (const n of W.legend.missing) n.hidden = !(Object.keys(V.missDots).length || V.missMuscles.size);
  W.checkPills.replaceChildren(...items.map(([text, tn]) => pill(text, tn)));
  W.checkPills.hidden = !items.length;
  W.checkNote.textContent = "Checked against every parameter of the avatar you're wearing.";
}

// ---- Home's rows (home_devices.py bhaptics_row / owo_row) -------------------------
/** Each suit's row in Home's toy list: what it says, its pill, its sharing
 *  switch (shown while the other suit is on too) and its On / Off. */
function homeRows() {
  const f = D.state.features, bh = SU.bh, o = SU.owo;
  const linked = bh.link === "connected";
  paintRow("bhaptics", linked, !bh.paused,
    linked ? `${SUIT.label} · 🔋 ${SUIT.battery} %` : "Let go - the bHaptics Player can have it",
    f.owo ? bh.follow : null);
  paintRow("owo", o.connected, !o.paused, o.connected ? "Connected through My OWO" : "My OWO not connected",
    f.bhaptics ? o.follow : null);
}
function paintRow(dev, connected, enabled, summary, share) {
  const row = document.querySelector(`.o-dev[data-dev="${dev}"]`);
  if (!row) return;
  row.querySelector(".js-sum").textContent = summary;
  row.querySelector(".js-pill").style.display = connected ? "none" : "";
  for (const q of [".js-share", ".js-sharel"]) row.querySelector(q).style.display = share === null ? "none" : "";
  row.querySelector(".js-share").classList.toggle("on", Boolean(share));
  row.querySelector(".js-devon").classList.toggle("on", enabled);
  row.querySelector(".js-devonl").textContent = enabled ? "On" : "Off";
  row.classList.toggle("down", !(connected && enabled));
}
function wireRows() {
  const click = (dev, q, fn) => document.querySelector(`.o-dev[data-dev="${dev}"] ${q}`)
    .addEventListener("click", () => { fn(); refresh(); live(); });
  click("bhaptics", ".js-share", () => { SU.bh.follow = !SU.bh.follow; });
  click("bhaptics", ".js-devon", () => { SU.bh.paused = !SU.bh.paused; if (SU.bh.paused) SU.holds.clear(); });
  click("owo", ".js-share", () => { SU.owo.follow = !SU.owo.follow; });
  click("owo", ".js-devon", () => { SU.owo.paused = !SU.owo.paused; });
}

build(D.page("Suits"));
wireRows();
refresh();
D.on("features", refresh);
D.on("page", (S) => { if (S.page === "Suits" && layoutBody()) fillInspector(); });
setInterval(() => { if (D.state.page === "Suits") live(); }, 150);
if (/demo=suits/.test(location.hash)) {
  D.setFeature("bhaptics", true);
  D.setFeature("owo", true);
  D.go("Suits");
}
