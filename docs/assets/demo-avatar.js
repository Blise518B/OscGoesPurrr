// The demo window's My Avatar Remote page (src/ui/views/params.py,
// param_cards.py): the board of controls for the avatar you wear -- its
// categories and cards, the live parameter list beside it.
//
// The cards are the friend board's own (remote-board.js Board), so the page
// and a friend's view of it read the same; this page adds what only the
// owner has: the ⠿ handles, the ⋯ menus, a category's lock. AVATAR is the
// worn avatar's state: the Friends page's "you" panel shows the same board,
// as a friend would see it (locked categories look-only there).

import { el } from "./remote-ui.js";
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
  ["HueShift", "Float"], ["OGP/Strength", "Float"], ["Outfit", "Int"], ["Particles", "Int"], ["ScaleFactor", "Float"],
  ["TailWag", "Bool"], ["TongueOut", "Bool"]];

export const AVATAR = {
  name: "Kitsune",
  id: "avtr_6a1f3c2e-4b7d-4e19-9c55-518c0ffee518",
  values: { Blush: 0.45, EarsDown: false, Emote: 0, FaceShy: 0, Glasses: true, HueShift: 0.62, Outfit: 2,
            Particles: 3, ScaleFactor: 1, TailWag: true, TongueOut: false },
  board: { ver: "kitsune-1", name: "Kitsune", avatar: "", categories: CATS, controls: CONTROLS, keys: [], all: null },
  listeners: [],
  onChange(fn) { this.listeners.push(fn); },
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
// OGP/Strength is the app's own: your strength slider, as the avatar sees it
const valuesNow = () => ({ ...AVATAR.values, "OGP/Strength": D.state.strength });

// ---- the page ----------------------------------------------------------------

const W = { board: null, rows: {}, filter: "", dock: null, locks: {} };

function ownBoard() {
  // the owner uses every category; the lock is what friends get (look-only)
  return { ...AVATAR.board, categories: CATS.map((c) => ({ ...c, locked: false })) };
}

/** The owner's extras on the friend board's cards: ⠿, ⋯, the lock. */
function decorate(root) {
  for (const head of root.querySelectorAll(".cat-head:not(.own)")) {
    head.classList.add("own");
    const cat = CATS.find((c) => c.name === head.querySelector(".cat-name").textContent);
    const lock = el("button.pg-lock", { type: "button" });
    const show = () => {
      lock.textContent = cat.locked ? "🔒" : "🔓";
      lock.title = cat.locked ? "Locked: friends can only look at it. Click to unlock."
        : "Friends may use it. Click to lock it (look-only for friends).";
    };
    lock.onclick = () => { cat.locked = !cat.locked; show(); AVATAR.listeners.forEach((fn) => fn()); };
    show();
    head.prepend(el("span.pg-grip.light", { title: "Drag to move the category" }, "⠿"));
    head.append(lock, el("span.pg-more", { title: "Rename, colour, delete…" }, "⋯"));
  }
  for (const head of root.querySelectorAll(".pc-head:not(.own)")) {
    head.classList.add("own");
    head.prepend(el("span.pg-grip.hue", { title: "Drag to move the control" }, "⠿"));
    head.append(el("span.pg-more", { title: "Edit, duplicate, delete…" }, "⋯"));
  }
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
  return el("div.pg-dock", {},
    el("div.pg-row.tight", {}, el("span.pg-chip.wide", {}, "Avatar parameters"),
      el("button.pg-btn", { type: "button", title: "Ask VRChat for every value again" }, "⟳  Resync")),
    filt,
    el("div.pg-ptable", {}, el("div.pg-prow.th", {}, el("span", {}, "Parameter"), el("span", {}, "Type"), el("span", {}, "Value")), body),
    el("p.pg-note", {}, "Double-click a parameter, or drag it into a category, to make a control."),
    el("p.pg-note", {}, "Values update live from VRChat."));
}

function fmt(type, v) {
  if (type === "Float") return Number(v).toFixed(3);
  if (type === "Bool") return v ? "true" : "false";
  return String(Math.round(Number(v)));
}

function refresh() {
  const values = valuesNow();
  W.board.update({ ver: AVATAR.board.ver, stop: false, yolo: false }, ownBoard(), values);
  decorate(W.board.root);
  for (const [name, r] of Object.entries(W.rows)) {
    const text = fmt(r.type, values[name]);
    if (r.v.textContent !== text) r.v.textContent = text;
  }
}

function build(root) {
  const friends = el("button.pg-btn", { type: "button", onclick: () => D.go("Friends") }, "Friends ▸");
  W.board = new Board({ onSet: (id, v) => AVATAR.set(id, v), onHold: (id, held) => AVATAR.hold(id, held), onSetAny() {} });
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
  refresh();
}

build(D.page("My Avatar Remote"));
AVATAR.onChange(refresh);
D.on("strength", refresh);
