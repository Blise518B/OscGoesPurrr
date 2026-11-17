// The demo window's My Avatar Remote page (src/ui/views/params.py,
// param_cards.py): the board of controls for the avatar you wear -- its
// categories and cards, the live parameter list beside it.
//
// The cards are the friend board's own (remote-board.js Board), so the page
// and a friend's view of it read the same; this page adds what only the
// owner has: the ⠿ handles, the ⋯ menus, a category's lock, and the avatar
// menu's slot circle with its radial picker (param_slots.py). AVATAR is the
// worn avatar's state: the Friends page's "you" panel shows the same board,
// as a friend would see it (locked categories look-only there).

import { el, hslider } from "./remote-ui.js";
import { Board } from "./remote-board.js";

const D = window.OGPDemo;
const P = window.OGPRemoteProto;

const CATS = [
  { id: "outfit", name: "Outfit", color: "purple", locked: false },
  { id: "toggles", name: "Toggles", color: "cyan", locked: false },
  { id: "fun", name: "Fun", color: "amber", locked: true },
];
const CONTROLS = [
  { id: "hoodie", cat: "outfit", label: "Hoodie", param: "Outfit", ptype: "Int", kind: "toggle", on: 1, off: 0 },
  { id: "kimono", cat: "outfit", label: "Kimono", param: "Outfit", ptype: "Int", kind: "toggle", on: 2, off: 0 },
  { id: "swimsuit", cat: "outfit", label: "Swimsuit", param: "Outfit", ptype: "Int", kind: "toggle", on: 3, off: 0 },
  { id: "glasses", cat: "toggles", label: "Glasses", param: "Glasses", ptype: "Bool", kind: "toggle" },
  { id: "tailwag", cat: "toggles", label: "Tail wag", param: "TailWag", ptype: "Bool", kind: "toggle" },
  { id: "earsdown", cat: "toggles", label: "Ears down", param: "EarsDown", ptype: "Bool", kind: "toggle" },
  { id: "blush", cat: "toggles", label: "Blush", param: "Blush", ptype: "Float", kind: "slider", min: 0, max: 1 },
  { id: "wave", cat: "fun", label: "Wave", param: "Emote", ptype: "Int", kind: "button", on: 3, off: 0 },
  { id: "hueshift", cat: "fun", label: "Hue shift", param: "HueShift", ptype: "Float", kind: "slider", min: 0, max: 1 },
  { id: "particles", cat: "fun", label: "Particles", param: "Particles", ptype: "Int", kind: "int", min: 0, max: 10 },
];
const TYPES = [["Blush", "Float"], ["EarsDown", "Bool"], ["Emote", "Int"], ["FaceShy", "Float"], ["Glasses", "Bool"],
  ["HueShift", "Float"], ["OGP/Friend/Level", "Float"], ["OGP/Strength", "Float"], ["Outfit", "Int"], ["Particles", "Int"], ["ScaleFactor", "Float"],
  ["TailWag", "Bool"], ["TongueOut", "Bool"]];

// VRChat's /avatar/eyeheight and the Height box's settings (avatar_height.py:
// on for friends, the lock, lowest / highest -- VRChat's own menu's 0.2-5 m
// out of the box -- and Grow's seconds per doubling)
const HEIGHT = { on: true, locked: false, lo: 0.2, hi: 5.0, double_s: 4, now: 1.42, own: 1.42, target: null };
const clampH = (h) => Math.max(HEIGHT.lo, Math.min(HEIGHT.hi, h));
let glideTimer = null;
/** One step of Grow: doubling (or halving) every double_s seconds, never
 *  past the target (avatar_height.glide_step), ten writes a second. */
function glide() {
  const step = (Math.log(2) * 0.1) / Math.max(1, HEIGHT.double_s);
  const a = Math.log(HEIGHT.now), b = Math.log(HEIGHT.target);
  HEIGHT.now = Math.abs(b - a) <= step ? HEIGHT.target : Math.exp(a + (b > a ? step : -step));
  if (HEIGHT.now === HEIGHT.target) { clearInterval(glideTimer); glideTimer = null; HEIGHT.target = null; }
  AVATAR.listeners.forEach((fn) => fn());
}

export const AVATAR = {
  name: "Kitsune",
  id: "avtr_6a1f3c2e-4b7d-4e19-9c55-518c0ffee518",
  values: { "OGP/Friend/Level": 0, Blush: 0.45, EarsDown: false, Emote: 0, FaceShy: 0, Glasses: true, HueShift: 0.62, Outfit: 2,
            Particles: 3, ScaleFactor: 1, TailWag: true, TongueOut: false },
  board: { ver: "kitsune-1", name: "Kitsune", avatar: "", categories: CATS, controls: CONTROLS, keys: [], all: null },
  heightBox: HEIGHT,
  listeners: [],
  onChange(fn) { this.listeners.push(fn); },
  /** The board as a friend sees it: the Height box only while it's on for friends. */
  friendBoard() {
    return { ...this.board, height: HEIGHT.on ? { lo: HEIGHT.lo, hi: HEIGHT.hi, allowed: true, locked: HEIGHT.locked } : null };
  },
  heightNow() { return HEIGHT.now; },
  /** Grow (glide), now (a jump) or reset (back to your own height). */
  height(mode, h) {
    if (glideTimer) { clearInterval(glideTimer); glideTimer = null; }
    if (mode === "reset") HEIGHT.now = HEIGHT.own;
    else if (mode === "now") HEIGHT.now = clampH(h);
    else { HEIGHT.target = clampH(h); glideTimer = setInterval(glide, 100); }
    this.listeners.forEach((fn) => fn());
  },
  /** What setting a control does to its parameter (param_board.send_value). */
  set(id, v) {
    const c = CONTROLS.find((x) => x.id === id);
    if (!c) return;
    let out;
    if (c.ptype === "Bool") out = Boolean(v);
    else if (P.isIntSwitch(c)) { const [on, off] = P.intSwitchValues(c); out = v ? on : off; }
    else if (c.ptype === "Int") out = Math.max(c.min ?? 0, Math.min(c.max ?? 255, Math.round(Number(v))));
    else out = Math.max(c.min ?? -1, Math.min(c.max ?? 1, Number(v)));
    this.values[c.param] = out;
    this.listeners.forEach((fn) => fn());
  },
  hold(id, held) { this.set(id, held); },
};
// The avatar menu's slots (param_board SLOT_*): Avatar Remote ▸ Toggles 1-7 and
// Radials 1-7, each taken by a control ("c:<id>") or a whole category ("g:<id>")
const SLOTS = { toggle: ["c:glasses", "c:tailwag", null, null, null, null, null],
                radial: ["c:blush", null, null, null, null, null, null] };
const SLOT_KINDS = { toggle: ["toggle", "button"], radial: ["slider", "int"] };
const SLOT_NAMES = { toggle: ["Toggle", "Toggles"], radial: ["Radial", "Radials"] };
const slotsOf = (key) => ["toggle", "radial"].flatMap((m) => SLOTS[m].map((k, i) => (k === key ? [m, i] : null)).filter(Boolean));
function slotLabel(key) {
  if (!key) return "";
  if (key === "h:height") return "Height";                 // param_board.HEIGHT_SLOT, Radials only
  const [kind, id] = [key[0], key.slice(2)];
  if (kind === "g") return (CATS.find((c) => c.id === id) || {}).name || "";
  return (CONTROLS.find((c) => c.id === id) || {}).label || "";
}

// OGP/Strength is the app's own: your strength slider, as the avatar sees it
const valuesNow = () => ({ ...AVATAR.values, "OGP/Strength": D.state.strength });

// ---- the page ----------------------------------------------------------------

const W = { board: null, rows: {}, filter: "", dock: null, locks: {}, root: null, pick: null };

// ---- the slot circle and its radial (param_slots.py) ------------------------------

function slotDot(key, menus) {
  const dot = el("button.pg-slot", { type: "button" });
  dot.dataset.key = key;
  dot.dataset.menus = menus.join(" ");
  dot.onclick = (ev) => { ev.stopPropagation(); openSlots(dot); };
  return dot;
}

function paintDots() {
  for (const dot of W.board.root.querySelectorAll(".pg-slot")) {
    const menus = dot.dataset.menus.split(" ");
    const taken = slotsOf(dot.dataset.key).filter(([m]) => menus.includes(m));
    dot.textContent = taken.map(([m, i]) => (menus.length > 1 ? m[0].toUpperCase() : "") + (i + 1)).join("·");
    dot.classList.toggle("set", taken.length > 0);
    dot.title = taken.length
      ? `In your avatar menu: Avatar Remote ▸ ${taken.map(([m, i]) => `${SLOT_NAMES[m][0]} ${i + 1}`).join(", ")} - click to change`
      : "Put this in your avatar menu: click, then pick one of Avatar Remote ▸'s seven slots";
  }
  if (W.pick) W.pick.draw();
}

function closeSlots() {
  if (!W.pick) return;
  W.pick.box.remove();
  document.removeEventListener("pointerdown", W.pick.outside, true);
  document.removeEventListener("keydown", W.pick.esc, true);
  W.pick = null;
}

/** VRChat's radial: Back at the top, 1-7 clockwise, each saying what has it. */
function openSlots(dot) {
  const key = dot.dataset.key;
  const again = W.pick && W.pick.key === key;
  closeSlots();
  if (again) return;                                  // its own circle again: closed
  const menus = dot.dataset.menus.split(" ");
  const NS = "http://www.w3.org/2000/svg";
  const R1 = 100, R0 = 38, C = 108;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 216 216");
  svg.setAttribute("width", "216");
  svg.setAttribute("height", "216");
  const cap = el("div.pg-slotcap");
  const box = el("div.pg-slotpick", {}, cap, svg);
  const pt = (r, deg) => [C + r * Math.cos((deg * Math.PI) / 180), C + r * Math.sin((deg * Math.PI) / 180)];
  const wedge = (k) => {
    const a0 = -90 + 45 * k - 21.5, a1 = a0 + 43;
    const [x0, y0] = pt(R1, a0), [x1, y1] = pt(R1, a1), [x2, y2] = pt(R0, a1), [x3, y3] = pt(R0, a0);
    return `M${x0} ${y0}A${R1} ${R1} 0 0 1 ${x1} ${y1}L${x2} ${y2}A${R0} ${R0} 0 0 0 ${x3} ${y3}Z`;
  };
  const node = (tag, attrs, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    svg.append(n);
    return n;
  };
  const pick = { key, menu: menus.includes(slotsOf(key)[0]?.[0]) ? slotsOf(key)[0][0] : menus[0], box };
  pick.draw = () => {
    svg.replaceChildren();
    const name = slotLabel(key) + (key[0] === "g" ? " (whole category)" : "");
    cap.replaceChildren(el("b", {}, name), el("span", {}, `Avatar Remote ▸ ${SLOT_NAMES[pick.menu][1]}`));
    for (let k = 0; k < 8; k++) {
      const owner = k ? SLOTS[pick.menu][k - 1] : null;
      const mine = owner === key;
      const w = node("path", { d: wedge(k), class: `pg-wedge${mine ? " mine" : ""}` });
      const [x, y] = pt((R0 + R1) / 2, -90 + 45 * k);
      if (!k) {
        node("text", { x, y: y + 4, class: "pg-wlabel" }, "Back");
        w.onclick = closeSlots;
        continue;
      }
      node("text", { x, y: owner ? y - 1 : y + 5, class: `pg-wnum${mine ? " mine" : ""}` }, String(k));
      if (owner) node("text", { x, y: y + 13, class: `pg-wlabel${mine ? " mine" : ""}` }, slotLabel(owner).slice(0, 9));
      w.onclick = () => {
        SLOTS[pick.menu][k - 1] = mine ? null : key;
        paintDots();
      };
    }
    node("circle", { cx: C, cy: C, r: R0 - 4, class: "pg-hub" });
    if (menus.length > 1) {
      menus.forEach((m, i) => {
        const t = node("text", { x: C, y: C - 3 + i * 15, class: `pg-hubtext${m === pick.menu ? " on" : ""}` }, SLOT_NAMES[m][1]);
        t.onclick = () => { pick.menu = m; pick.draw(); };
      });
    } else {
      node("text", { x: C, y: C + 4, class: "pg-hubtext" }, SLOT_NAMES[pick.menu][0]);
    }
  };
  pick.outside = (ev) => { if (!box.contains(ev.target) && ev.target !== dot) closeSlots(); };
  pick.esc = (ev) => { if (ev.key === "Escape") closeSlots(); };
  document.addEventListener("pointerdown", pick.outside, true);
  document.addEventListener("keydown", pick.esc, true);
  W.pick = pick;
  pick.draw();
  W.root.append(box);
  const host = W.root.getBoundingClientRect(), at = dot.getBoundingClientRect();
  const x = Math.max(4, Math.min(at.left - host.left + at.width / 2 - 116, host.width - 236));
  box.style.left = `${x}px`;
  box.style.top = `${at.bottom - host.top + 4 + W.root.scrollTop}px`;
}

function ownBoard() {
  // the owner uses every category; the lock is what friends get (look-only);
  // the Height box is always there for you (its switch is for friends)
  return { ...AVATAR.board, categories: CATS.map((c) => ({ ...c, locked: false })),
           height: { lo: HEIGHT.lo, hi: HEIGHT.hi, allowed: true, locked: false } };
}

const MIME_CONTROL = "text/x-ogp-control", MIME_CATEGORY = "text/x-ogp-category";
function lockButton(get, set) {
  const lock = el("button.pg-lock", { type: "button" });
  const show = () => {
    lock.textContent = get() ? "🔒" : "🔓";
    lock.title = get() ? "Locked: friends can only look at it. Click to unlock."
      : "Friends may use it. Click to lock it (look-only for friends).";
  };
  lock.onclick = () => { set(!get()); show(); AVATAR.listeners.forEach((fn) => fn()); };
  show();
  return lock;
}

/** The owner's extras on the friend board's cards: ⠿ (drag it back to the
 *  list to remove it), ⋯, the lock -- and the Height box's own (param_height). */
function decorate(root) {
  for (const head of root.querySelectorAll(".cat:not(.hbox) > .cat-head:not(.own)")) {
    head.classList.add("own");
    const cat = CATS.find((c) => c.name === head.querySelector(".cat-name").textContent);
    if (!cat) continue;
    const grip = el("span.pg-grip.light", { draggable: "true", title: "Drag to move the category - or onto the parameter list to remove it" }, "⠿");
    grip.addEventListener("dragstart", (e) => { e.dataTransfer.setData(MIME_CATEGORY, cat.id); e.dataTransfer.effectAllowed = "move"; dragging(MIME_CATEGORY); });
    grip.addEventListener("dragend", () => dragging(null));
    head.prepend(grip);
    head.append(slotDot(`g:${cat.id}`, ["toggle", "radial"]), lockButton(() => cat.locked, (v) => { cat.locked = v; }),
      el("span.pg-more", { title: "Rename, colour, delete…" }, "⋯"));
  }
  for (const head of root.querySelectorAll(".pc-head:not(.own)")) {
    head.classList.add("own");
    const label = head.querySelector(".pc-label").textContent;
    const c = CONTROLS.find((x) => (x.label || x.param) === label);
    const grip = el("span.pg-grip.hue", { draggable: "true", title: "Drag to move the control - or back to the parameter list to remove it" }, "⠿");
    if (c) {
      grip.addEventListener("dragstart", (e) => { e.dataTransfer.setData(MIME_CONTROL, c.id); e.dataTransfer.effectAllowed = "move"; dragging(MIME_CONTROL); });
      grip.addEventListener("dragend", () => dragging(null));
    }
    head.prepend(grip);
    if (c) head.append(slotDot(`c:${c.id}`, [SLOT_KINDS.toggle.includes(c.kind) ? "toggle" : "radial"]));
    head.append(el("span.pg-more", { title: "Edit, duplicate, delete…" }, "⋯"));
  }
  const hbox = root.querySelector(".hbox");
  const hhead = hbox && hbox.querySelector(".cat-head:not(.own)");
  if (hhead) {
    hhead.classList.add("own");
    const sw = el("label.sw.pg-hsw", { title: "Height for friends: whether friends you allow see this box and can change your height. "
      + "Off, they don't see it and nothing they send changes it; your own box and avatar menu still work." },
      el("input", { type: "checkbox", checked: HEIGHT.on, onchange: (e) => { HEIGHT.on = e.target.checked; AVATAR.listeners.forEach((fn) => fn()); } }),
      el("span.knob"));
    const opts = heightOptions();
    const more = el("span.pg-more", { title: "Height settings: your lowest and highest height, and how fast Grow glides. Nobody can take "
      + "you past them, friends included." }, "⋯");
    more.onclick = () => { opts.hidden = !opts.hidden; };
    hhead.append(slotDot("h:height", ["radial"]), lockButton(() => HEIGHT.locked, (v) => { HEIGHT.locked = v; }), more, sw);
    hbox.querySelector(".hbody").before(opts);
    hbox.title = "Height: your height in VRChat, from here, from your avatar menu and from friends you allow. It stays where it was put "
      + "until someone changes it.";
  }
}

/** What ⋯ folds out inside the Height box: Lowest, Highest, Grow speed. */
function heightOptions() {
  const fmtM = (h) => P.fmtHeight(h);
  const lo = hslider({ max: 1000, hue: "green", value: Math.round(P.heightToSlider(HEIGHT.lo, 0.1, 100) * 1000),
    onInput: (x) => { HEIGHT.lo = Math.min(P.sliderToHeight(x / 1000, 0.1, 100), HEIGHT.hi / 1.1); loV.textContent = fmtM(HEIGHT.lo); } });
  const hi = hslider({ max: 1000, hue: "green", value: Math.round(P.heightToSlider(HEIGHT.hi, 0.1, 100) * 1000),
    onInput: (x) => { HEIGHT.hi = Math.max(P.sliderToHeight(x / 1000, 0.1, 100), HEIGHT.lo * 1.1); hiV.textContent = fmtM(HEIGHT.hi); } });
  // faster to the right: fewer seconds per doubling
  const speed = hslider({ max: 29, hue: "green", value: 30 - HEIGHT.double_s,
    onInput: (x) => { HEIGHT.double_s = 30 - x; spV.textContent = `×2 in ${HEIGHT.double_s} s`; } });
  const loV = el("span.pval", {}, fmtM(HEIGHT.lo)), hiV = el("span.pval", {}, fmtM(HEIGHT.hi));
  const spV = el("span.pval", {}, `×2 in ${HEIGHT.double_s} s`);
  const row = (name, s, v, title) => el("div.row", { title }, el("span.small.pg-hopt", {}, name), s, v);
  return el("div.pg-hopts", { hidden: true },
    row("Lowest", lo, loV, "The smallest anyone can make you, you included. VRChat's own menu stops at 0.2 m, and VRChat doesn't support under 0.1 m."),
    row("Highest", hi, hiV, "The tallest anyone can make you, you included. VRChat's own menu stops at 5 m, and VRChat doesn't support over 100 m."),
    row("Grow speed", speed, spV, "How long Grow takes to double or halve your height. Slower is gentler on VRChat's view, which can jitter while the height glides."));
}

// ---- dragged back to the list: removed (params.py, param_remove.py) ----------

const UNDO_S = 8;
function dragging(mime) {
  if (!W.drop) return;
  W.drop.hidden = !mime;
  W.drop.lastChild.textContent = mime === MIME_CATEGORY ? "The whole category and its controls. Asks first." : "Undo brings it back.";
}
/** A control goes at once, its menu slots with it; Undo puts it back. */
function takeControl(id) {
  const at = CONTROLS.findIndex((c) => c.id === id);
  if (at < 0) return;
  const c = CONTROLS[at], key = `c:${id}`;
  const slots = ["toggle", "radial"].flatMap((m) => SLOTS[m].map((k, i) => (k === key ? [m, i] : null)).filter(Boolean));
  CONTROLS.splice(at, 1);
  slots.forEach(([m, i]) => { SLOTS[m][i] = null; });
  AVATAR.listeners.forEach((fn) => fn());
  offerUndo(`Removed “${c.label}”.`, () => {
    CONTROLS.splice(at, 0, c);
    slots.forEach(([m, i]) => { if (!SLOTS[m][i]) SLOTS[m][i] = key; });
    AVATAR.listeners.forEach((fn) => fn());
  });
}
/** A whole category: asked first, in the window. */
function askTakeCategory(id) {
  const cat = CATS.find((c) => c.id === id);
  if (!cat) return;
  const n = CONTROLS.filter((c) => c.cat === id).length;
  const controls = `${n} control${n === 1 ? "" : "s"}`;
  strip("ask", n ? `Remove the category “${cat.name}” and its ${controls}?` : `Remove the empty category “${cat.name}”?`, () => {
    const ci = CATS.indexOf(cat), gone = CONTROLS.map((c, i) => [c, i]).filter(([c]) => c.cat === id);
    CATS.splice(ci, 1);
    for (const [c] of gone.slice().reverse()) CONTROLS.splice(CONTROLS.indexOf(c), 1);
    AVATAR.listeners.forEach((fn) => fn());
    offerUndo(`Removed “${cat.name}”.`, () => {
      CATS.splice(ci, 0, cat);
      for (const [c, i] of gone) CONTROLS.splice(i, 0, c);
      AVATAR.listeners.forEach((fn) => fn());
    });
  });
}
function offerUndo(text, undo) { strip("undo", text, undo); }
/** The strip above the list: Undo for UNDO_S seconds, or a question that waits. */
function strip(mode, text, then) {
  const s = W.strip;
  clearTimeout(s.timer);
  s.text.textContent = text;
  s.undo.hidden = mode !== "undo";
  s.yes.hidden = s.no.hidden = mode !== "ask";
  s.root.classList.toggle("ask", mode === "ask");
  s.then = then;
  s.root.hidden = false;
  if (mode === "undo") s.timer = setTimeout(() => { s.root.hidden = true; }, UNDO_S * 1000);
}
function removeStrip() {
  const text = el("span.grow");
  const go = () => { W.strip.root.hidden = true; const t = W.strip.then; W.strip.then = null; if (t) t(); };
  const undo = el("button.pg-btn", { type: "button", onclick: go, title: "Puts back what you just dragged to the list, where it was and "
    + "in the same avatar menu slots. Offered for a few seconds." }, "Undo");
  const yes = el("button.pg-btn.danger", { type: "button", onclick: go, title: "Removes the category and every control in it. Undo is "
    + "offered for a few seconds after." }, "Remove");
  const no = el("button.pg-btn", { type: "button", onclick: () => { W.strip.root.hidden = true; }, title: "Leaves the category on the board as it is." }, "Keep");
  const root = el("div.pg-rmstrip", { hidden: true }, text, undo, yes, no);
  return { root, text, undo, yes, no, timer: null, then: null };
}

function paramDock() {
  const filt = el("input.pg-filter", { type: "search", placeholder: "Filter parameters…" });
  const body = el("div.pg-ptbody");
  for (const [name, type] of TYPES) {
    const v = el("span.pv");
    const row = el("div.pg-prow", {}, el("span", {}, name), el("span", {}, type), v);
    W.rows[name] = { row, v, type };
    body.append(row);
  }
  filt.addEventListener("input", () => {
    W.filter = filt.value.trim().toLowerCase();
    for (const [name, r] of Object.entries(W.rows)) r.row.hidden = Boolean(W.filter) && !name.toLowerCase().includes(W.filter);
  });
  W.strip = removeStrip();
  // the list takes a control or a category dragged back to it: "Drop to remove"
  W.drop = el("div.pg-rmdrop", { hidden: true }, el("b", {}, "Drop to remove"), el("span"));
  const table = el("div.pg-ptable", {}, el("div.pg-prow.th", {}, el("span", {}, "Parameter"), el("span", {}, "Type"), el("span", {}, "Value")), body, W.drop);
  table.addEventListener("dragover", (e) => {
    const t = e.dataTransfer.types;
    if (t.includes(MIME_CONTROL) || t.includes(MIME_CATEGORY)) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }
  });
  table.addEventListener("drop", (e) => {
    const t = e.dataTransfer.types;
    dragging(null);
    if (t.includes(MIME_CONTROL)) { e.preventDefault(); takeControl(e.dataTransfer.getData(MIME_CONTROL)); }
    else if (t.includes(MIME_CATEGORY)) { e.preventDefault(); askTakeCategory(e.dataTransfer.getData(MIME_CATEGORY)); }
  });
  return el("div.pg-dock", {},
    el("div.pg-row.tight", {}, el("span.pg-chip.wide", {}, "Avatar parameters"),
      el("button.pg-btn", { type: "button", title: "Ask VRChat for every value again" }, "⟳  Resync")),
    filt, W.strip.root, table,
    el("p.pg-note", {}, "Double-click a parameter, or drag it into a category, to make a control. Drag a control back here to remove it."),
    el("p.pg-note", {}, "Values update live from VRChat."));
}

function fmt(type, v) {
  if (type === "Float") return Number(v).toFixed(3);
  if (type === "Bool") return v ? "true" : "false";
  return String(Math.round(Number(v)));
}

function refresh() {
  const values = valuesNow();
  W.board.update({ ver: AVATAR.board.ver, stop: false, yolo: false }, ownBoard(), values, false, HEIGHT.now);
  decorate(W.board.root);
  paintDots();
  for (const [name, r] of Object.entries(W.rows)) {
    const text = fmt(r.type, values[name]);
    if (r.v.textContent !== text) r.v.textContent = text;
  }
}

function build(root) {
  const friends = el("button.pg-btn", { type: "button", onclick: () => D.go("Friends") }, "Friends ▸");
  W.board = new Board({ onSet: (id, v) => AVATAR.set(id, v), onHold: (id, held) => AVATAR.hold(id, held), onSetAny() {},
                        onHeight: (mode, h) => AVATAR.height(mode, h) });
  W.dock = paramDock();
  const dockBtn = el("button.pg-link", { type: "button" }, "Avatar parameters ◂");
  const cols = el("div.pg-avcols", {}, el("div.pg-avboard", {}, W.board.root), W.dock);
  dockBtn.onclick = () => {
    const open = W.dock.hidden;
    W.dock.hidden = !open;
    cols.classList.toggle("wide", !open);
    dockBtn.textContent = open ? "Avatar parameters ◂" : "Avatar parameters ▸";
  };
  root.append(
    el("div.o-viewtitle", {}, "My Avatar Remote"),
    el("div.pg-introrow", {},
      el("p.pg-intro", {}, "The remote for your own avatar: build a board of controls for its parameters - toggles, hold "
        + "buttons, sliders, steppers - per avatar. Friends you allow (Friends page, the third box) see the board of the "
        + "avatar you're wearing and can use it; everything they do is logged there. A friend's avatar you use from "
        + "Friends, in their panel."), friends),
    el("div.o-card.pg-card.pg-avhead", {},
      el("div.pg-avname", {}, el("b", {}, AVATAR.name), el("span.pg-avid", {}, AVATAR.id)),
      el("div.pg-row", {}, el("button.pg-btn.icon", { type: "button", title: "Another avatar's board" }, "▾"),
        el("span.pg-pill.ok", {}, "● LIVE")),
      el("span.grow"),
      el("div.pg-avpreset", {},
        el("div.pg-row", {}, el("span.o-in.combo.pg-combo.short", {}, "Default"), el("button.pg-btn.icon", { type: "button" }, "···")),
        el("span.pg-pill.run", { title: "Friends who have your board open right now" }, "LOOKING: Mika"))),
    el("div.pg-row.pg-avtools", {},
      el("button.pg-btn", { type: "button" }, "+  Category"),
      el("button.pg-btn.yolo", { type: "button", title: "Lets friends set every parameter of the avatar - asks first" }, "⚡ YOLO"),
      el("span.grow"),
      el("button.pg-link", { type: "button" }, "Import from VRC Parameter Relay…"), dockBtn),
    cols);
  W.root = root;
  // (the page scroller is absolutely placed already: the slot picker sits in it)
  refresh();
}

build(D.page("My Avatar Remote"));
AVATAR.onChange(refresh);
D.on("strength", refresh);
