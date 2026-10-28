// The demo window's Shockers page (src/ui/views/pishock.py, pishock_cards.py,
// pishock_rules.py): the hub, a card per shocker with its own limits, the
// timing every shocker shares, and the behaviours you drag shockers onto.
//
// There is no hub behind it. What a shocker would do shows on its card --
// a test is the app's own (level 10 for 0.5 s, capped by the shocker, a
// vibrate while shocks aren't armed, then the rest after it) -- and the
// Friends page's "you" panel fires the same shockers through `fire`.

import { el, hslider, segmented, toggle } from "./remote-ui.js";

const D = window.OGPDemo;
const TEST_LEVEL = 10;                  // pishock_facade.TEST_INTENSITY
const TEST_MS = 500;                    // .. TEST_DURATION_MS

export const SHOCK = {
  shockers: [
    { name: "Collar", id: 24325, shock: 25, vibrate: 60, pulse: 1.0, out: null, until: 0, restUntil: 0 },
    { name: "Thigh", id: 24326, shock: 40, vibrate: 80, pulse: 2.0, out: null, until: 0, restUntil: 0 },
  ],
  timing: { rest: 0.5, hold: 10, brk: 2.0 },
  stopped: false,
  listeners: [],
};

/** One pulse on shocker `i`, through the rules the engine keeps: Off and
 *  Stop all hold it back, a shock is a vibrate until armed, every level and
 *  length within the shocker's own caps. What it would do: [op, level, ms]. */
export function fire(i, op, level, ms) {
  const s = SHOCK.shockers[i], st = D.state.shock;
  const now = performance.now();
  if (!s || !st.on || SHOCK.stopped || now < s.restUntil) return null;
  if (op === "shock" && !st.armed) op = "vibrate";
  const cap = op === "vibrate" ? s.vibrate : s.shock;
  const lvl = op === "beep" ? 0 : Math.max(1, Math.min(cap, Math.round(level)));
  const len = Math.max(100, Math.min(ms, s.pulse * 1000));
  s.out = [op, lvl];
  s.until = now + len;
  s.restUntil = s.until + SHOCK.timing.rest * 1000;
  paint();
  return [op, lvl, len];
}

/** A held op let go: it ends now, and the rest after a pulse starts. */
export function release(i) {
  const s = SHOCK.shockers[i], now = performance.now();
  if (!s || !s.out || now >= s.until) return;
  s.until = now;
  s.restUntil = now + SHOCK.timing.rest * 1000;
  paint();
}

function stopAll() {
  SHOCK.stopped = !SHOCK.stopped;
  for (const s of SHOCK.shockers) { s.out = null; s.until = 0; s.restUntil = 0; }
  paint();
}

// ---- the page --------------------------------------------------------------

const W = { cards: [], stopBtn: null, armPill: null, armSw: null, behaviours: null };

function hued(node, hue) {
  node.style.setProperty("--hue", `var(--${hue})`);
  node.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
  node.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
  return node;
}
function icon(name, cls = "pg-ic") {
  const i = el(`i.${cls}`);
  i.innerHTML = D.icons[name] || "";
  return i;
}
/** A slider row: its name, the number written out, the slider (the app's:
 *  values are sliders, never spin boxes). */
function valueRow(label, { min, max, value, hue, fmt, onInput }) {
  const val = el("b.pg-val", {}, fmt(value));
  const s = hslider({ min, max, value, hue, onInput: (x) => { val.textContent = fmt(x); onInput && onInput(x); } });
  return el("div.pg-vrow", {}, el("div.pg-vhead", {}, el("span", {}, label), val), s);
}
const secs = (x) => `${(x / 10).toFixed(1)} s`;

function hubCard() {
  const st = D.state.shock;
  W.armPill = el("span.pg-pill.warn", {}, "ARMED · shocks are real");
  W.armSw = toggle("Arm shocks", st.armed, (on) => { st.armed = on; D.emit("shock"); });
  W.stopBtn = el("button.btn.danger.sm", { type: "button", onclick: stopAll }, "Stop all");
  return el("div.o-card.pg-card", {},
    el("div.pg-row", {},
      el("span.pg-chip", {}, "Hub"),
      el("span.pg-pill.ok", {}, "CONNECTED · COM7 · PiShock Next · fw 3.1.2"),
      el("span.o-in.combo.pg-combo", {}, "Find automatically"),
      el("button.pg-btn.icon", { type: "button", title: "Look for the hub again" }, "↻"),
      el("button.pg-btn.primary", { type: "button" }, "Disconnect")),
    el("div.pg-row", {},
      toggle("Connect when the app starts", true, () => {}),
      W.armSw, W.armPill, W.stopBtn));
}

function shockerCard(s, i) {
  const pill = el("span.pg-pill.ok", {}, "READY");
  const grip = el("span.pg-grip", { draggable: "true", title: "Drag onto a behaviour to drive it" }, "⠿");
  grip.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/ogp-shocker", String(i)); e.dataTransfer.effectAllowed = "copy"; });
  const test = (op) => el("button.pg-btn", { type: "button", onclick: () => fire(i, op, TEST_LEVEL, TEST_MS) },
    op[0].toUpperCase() + op.slice(1));
  const card = hued(el("div.pg-scard", {},
    el("div.pg-shead", {}, grip, el("b", {}, s.name)),
    el("div.pg-sid", {}, el("span", {}, `ID ${s.id}`), pill),
    valueRow("Max shock", { min: 1, max: 100, value: s.shock, hue: "yellow", fmt: String, onInput: (x) => { s.shock = x; } }),
    valueRow("Max vibrate", { min: 1, max: 100, value: s.vibrate, hue: "pink", fmt: String, onInput: (x) => { s.vibrate = x; } }),
    valueRow("Longest pulse", { min: 1, max: 150, value: Math.round(s.pulse * 10), hue: "yellow", fmt: secs,
                                onInput: (x) => { s.pulse = x / 10; } }),
    el("div.pg-tests", {}, test("beep"), test("vibrate"), test("shock"))), "yellow");
  W.cards.push({ s, pill });
  return card;
}

function everyCard() {
  const t = SHOCK.timing;
  return hued(el("div.pg-scard.every", {},
    el("b", {}, "Every shocker"),
    valueRow("Rest after a pulse", { min: 0, max: 50, value: t.rest * 10, hue: "yellow", fmt: secs, onInput: (x) => { t.rest = x / 10; } }),
    valueRow("Longest hold", { min: 1, max: 60, value: t.hold, hue: "yellow", fmt: (x) => `${x} s`, onInput: (x) => { t.hold = x; } }),
    valueRow("Then a break of", { min: 0, max: 100, value: t.brk * 10, hue: "yellow", fmt: secs, onInput: (x) => { t.brk = x / 10; } }),
    el("p.pg-note", {}, "Every shocker on the hub keeps to these, whoever drives it.")), "yellow");
}

/** The shockers a behaviour drives: chips with ×, the + to add, and a drop
 *  target for a shocker card's ⠿ (pishock_cards.ShockerChips). */
function chipBox(names) {
  const box = el("div.pg-chips");
  const plus = el("button.pg-plus", { type: "button", title: "Pick the shockers it drives" }, "+");
  const draw = () => {
    box.replaceChildren(...names.map((n) => el("span.pg-schip", {}, n,
      el("button.pg-x", { type: "button", title: `Take ${n} off`, onclick: () => { names.splice(names.indexOf(n), 1); draw(); } }, "×"))), plus);
  };
  const add = (n) => { if (!names.includes(n)) { names.push(n); draw(); } };
  plus.onclick = () => {
    const free = SHOCK.shockers.map((s) => s.name).filter((n) => !names.includes(n));
    if (!free.length) return;
    const menu = el("div.pg-menu", {}, free.map((n) => el("button", { type: "button", onclick: () => { menu.remove(); add(n); } }, n)));
    box.append(menu);
    setTimeout(() => document.addEventListener("pointerdown", function off(e) {
      if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("pointerdown", off); }
    }), 0);
  };
  box.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/ogp-shocker")) { e.preventDefault(); box.classList.add("over"); } });
  box.addEventListener("dragleave", () => box.classList.remove("over"));
  box.addEventListener("drop", (e) => {
    e.preventDefault(); box.classList.remove("over");
    const s = SHOCK.shockers[Number(e.dataTransfer.getData("text/ogp-shocker"))];
    if (s) add(s.name);
  });
  draw();
  return box;
}

function behaviourCard({ name, kind, zone, contact, op, mode, strength, length, contacts, shockers, on = true }) {
  const remove = el("button.pg-x.big", { type: "button", title: "Remove this behaviour" }, "×");
  const head = el("div.pg-bhead", {}, el("b", {}, name), el("span.grow"),
    el("span.pg-muted", {}, zone), el("span.pg-pill.run", {}, kind),
    toggle("", on, () => {}), remove);
  const ops = el("div.pg-segs", {},
    segmented(["Vibrate", "Shock", "Beep"], "yellow", () => {}, ["vibrate", "shock", "beep"].indexOf(op)),
    mode ? segmented(["Pulse once", "While touching"], "yellow", () => {}, mode === "hold" ? 1 : 0) : "");
  const card = hued(el("div.pg-bcard", {}, head), "cyan");
  if (contact !== undefined) {
    card.append(el("div.pg-row.tight", {}, el("span.o-in.pg-field", {}, contact), el("button.pg-btn", { type: "button" }, "Pick")));
  }
  card.append(ops,
    valueRow("Strength", { min: 1, max: 100, value: strength, hue: "yellow", fmt: String }));
  if (length !== undefined) {
    card.append(valueRow("Length", { min: 1, max: 100, value: length * 10, hue: "yellow", fmt: secs }));
  }
  if (contacts) {
    for (const [param, names] of contacts) {
      card.append(el("div.pg-row.tight", {}, el("span.o-in.pg-field.short", {}, param),
        el("button.pg-btn", { type: "button" }, "Pick"), chipBox(names), el("button.pg-x", { type: "button" }, "×")));
    }
    card.append(el("button.pg-btn.wide", { type: "button" }, "+  Add a contact"));
  } else {
    card.append(chipBox(shockers));
  }
  remove.onclick = () => card.remove();
  return card;
}

function build(root) {
  const st = D.state.shock;
  root.append(
    el("div.o-viewtitle", {}, "Shockers"),
    el("p.pg-intro", {}, "Your PiShock or OpenShock hub over its USB cable — no account, no internet, straight from your "
      + "avatar's contacts to the shockers. Connect the hub, set each shocker's limits, then drag the shockers onto the "
      + "behaviours below."),
    hubCard());
  const shockers = hued(el("div.pg-cat", {},
    el("div.pg-bar", {}, icon("shock"), el("span", {}, "SHOCKERS")),
    el("div.pg-sgrid", {}, ...SHOCK.shockers.map(shockerCard), everyCard())), "yellow");
  const add = el("button.pg-btn.onbar", { type: "button" }, "+  Add behaviour");
  W.behaviours = el("div.pg-bgrid", {},
    behaviourCard({ name: "Touch zones", kind: "TOUCH ZONES", zone: "Neck", op: "vibrate", mode: "once", strength: 25,
                    length: 0.6, contacts: [["Contact/Neck", ["Collar"]], ["Contact/ThighL", ["Thigh"]]] }),
    behaviourCard({ name: "Headpat", kind: "CONTACT", zone: "off", contact: "Headpat", op: "shock", mode: "once",
                    strength: 15, shockers: ["Collar", "Thigh"] }));
  add.onclick = () => W.behaviours.append(behaviourCard({ name: "Contact", kind: "CONTACT", zone: "off", contact: "",
                                                          op: "vibrate", mode: "once", strength: 10, shockers: [] }));
  const behaviours = hued(el("div.pg-cat", {},
    el("div.pg-bar", {}, el("span", {}, "BEHAVIOURS"), el("span.grow"), add),
    el("p.pg-note", {}, "What your avatar's contacts do. Drag a shocker card's ⠿ onto a behaviour (or press its  +) to "
      + "pick the shockers it drives; × takes one off. A new behaviour drives none until you do."),
    W.behaviours), "cyan");
  root.append(shockers, behaviours);
  void st;
}

/** Each card's state, the app's words (pishock.py _refresh_pishock_live). */
function paint() {
  const st = D.state.shock, now = performance.now();
  for (const { s, pill } of W.cards) {
    let text, tone;
    if (s.out && now < s.until) { text = `${s.out[0].toUpperCase()}${s.out[1] ? " " + s.out[1] : ""}`; tone = { shock: "shock", vibrate: "live" }[s.out[0]] || "info"; }
    else if (now < s.restUntil) { text = "BREAK"; tone = "warn"; }
    else if (!st.on || SHOCK.stopped) { text = "STOPPED"; tone = "idle"; }
    else { text = "READY"; tone = "ok"; s.out = null; }
    if (pill.textContent !== text) { pill.textContent = text; pill.className = `pg-pill ${tone}`; }
  }
  if (W.armPill) {
    W.armPill.hidden = !st.armed;
    W.stopBtn.textContent = SHOCK.stopped ? "Resume" : "Stop all";
    const sw = W.armSw.querySelector("input");
    if (sw.checked !== st.armed) sw.checked = st.armed;
  }
}

build(D.page("Shockers"));
D.on("shock", paint);
setInterval(paint, 100);
paint();
