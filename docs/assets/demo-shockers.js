// The demo window's Shockers page (src/ui/views/pishock.py, pishock_cards.py,
// pishock_rules.py): the hub with Arm shocks and Share with friends, a card
// per shocker with what may reach it at all (Allowed) and its own limits, the
// limits every shocker shares (with Separate limits for friends: a set of
// friends' own, counted apart), and the behaviours you drag shockers onto.
//
// There is no hub behind it. What a shocker would do shows on its card --
// a test is the app's own (level 10 for 0.5 s, capped by the shocker, a
// vibrate while shocks aren't armed, then the rest after it) -- and the
// Friends page's "you" panel fires the same shockers through `fire`, which
// keeps the engine's rules: Off, Stop all, each shocker's own switches and
// caps, arming.

import { el, hslider, segmented, toggle } from "./remote-ui.js";

const D = window.OGPDemo;
const TEST_LEVEL = 10;                  // pishock_facade.TEST_INTENSITY
const TEST_MS = 500;                    // .. TEST_DURATION_MS
export const OPS = [["shock", "Shock"], ["vibrate", "Vibrate"], ["beep", "Beep"]];

export const SHOCK = {
  shockers: [
    { name: "Collar", id: 24325, shock: 25, vibrate: 60, pulse: 1.0, on: true, out: null, until: 0, restUntil: 0,
      ops: { shock: true, vibrate: true, beep: true } },
    { name: "Thigh", id: 24326, shock: 40, vibrate: 80, pulse: 2.0, on: true, out: null, until: 0, restUntil: 0,
      ops: { shock: true, vibrate: true, beep: true } },
  ],
  /** The shockers in use (their card's switch on): what friends, the
   *  behaviours and Home see -- an Off one gets nothing. */
  inUse() { return this.shockers.filter((s) => s.on); },
  timing: { rest: 0.5, hold: 10, brk: 2.0 },
  // Separate limits for friends (off by default): on, friends -- the "you"
  // panel too, as the app's Me -- keep to their own timing, counted apart,
  // and to their own caps, which only ever lower each shocker's own
  separate: false,
  friendTiming: null,          // a copy of `timing` the first time it goes on
  friendCaps: null,            // { shock, vibrate, pulse }: the highest any shocker has, then
  stopped: false,
  listeners: [],
};

/** One pulse on shocker `i`, through the rules the engine keeps: Off and
 *  Stop all hold it back, an op switched off on the shocker's card is
 *  refused (never turned into another), a shock is a vibrate until armed --
 *  refused too where Vibrate is off -- and every level and length stays
 *  within the shocker's own caps. What it would do: [op, level, ms]. */
export function fire(i, op, level, ms, group = "avatar") {
  const s = SHOCK.shockers[i], st = D.state.shock;
  const now = performance.now();
  if (!s || !s.on || !st.on || SHOCK.stopped || now < s.until || now < restOf(s, group) || !s.ops[op]) return null;
  if (op === "shock" && !st.armed) {
    op = "vibrate";
    if (!s.ops.vibrate) return null;
  }
  const [shockCap, vibCap, longest] = capsOf(s, group);
  const cap = op === "vibrate" ? vibCap : shockCap;
  const lvl = op === "beep" ? 0 : Math.max(1, Math.min(cap, Math.round(level)));
  const len = Math.max(100, Math.min(ms, longest));
  s.out = [op, lvl];
  s.until = now + len;
  rest(s, group, s.until);
  paint();
  return [op, lvl, len];
}

/** [max shock, max vibrate, longest pulse ms] of shocker `s` as `group`
 *  gets them: its own, lowered to the friends' own while limits are
 *  separate (PiShockEngine._caps_of). */
export function capsOf(s, group = "avatar") {
  const own = [s.shock, s.vibrate, Math.round(s.pulse * 1000)];
  const f = SHOCK.separate && group === "friends" ? SHOCK.friendCaps : null;
  return f ? [Math.min(own[0], f.shock), Math.min(own[1], f.vibrate), Math.min(own[2], Math.round(f.pulse * 1000))] : own;
}
/** The timing `group` keeps to: friends' own while limits are separate. */
export function timingOf(group) {
  return SHOCK.separate && group === "friends" && SHOCK.friendTiming ? SHOCK.friendTiming : SHOCK.timing;
}
/** When `group`'s rest after its last pulse ends on shocker `s`. */
function restOf(s, group) {
  return group === "friends" ? (s.friendRestUntil || 0) : s.restUntil;
}
/** `group`'s rest after a pulse ending at `end` -- everyone's while the
 *  limits aren't separate (one count). */
function rest(s, group, end) {
  const until = end + timingOf(group).rest * 1000;
  if (!SHOCK.separate || group === "avatar") s.restUntil = until;
  if (!SHOCK.separate || group === "friends") s.friendRestUntil = until;
}

/** A held op let go: it ends now, and the rest after a pulse starts. */
export function release(i, group = "avatar") {
  const s = SHOCK.shockers[i], now = performance.now();
  if (!s || !s.out || now >= s.until) return;
  s.until = now;
  rest(s, group, now);
  paint();
}

function stopAll() {
  SHOCK.stopped = !SHOCK.stopped;
  for (const s of SHOCK.shockers) { s.out = null; s.until = 0; s.restUntil = 0; s.friendRestUntil = 0; }
  paint();
}

// ---- the page --------------------------------------------------------------

const W = { cards: [], stopBtn: null, arm: null, share: null, behaviours: null, chips: [], addRow: null };

/** A card's switch: off, the shocker is out of use everywhere -- stopped,
 *  greyed where it is, its chips grey, gone from friends and Home. */
function setOn(s, on) {
  s.on = on;
  if (!on) { s.out = null; s.until = 0; }
  W.chips.forEach((draw) => draw());
  const names = SHOCK.inUse().map((x) => x.name);
  const row = document.querySelector('.o-dev[data-dev="shock"] .o-tzones');
  if (row) row.textContent = names.length ? `PiShock · ${names.join(", ")}` : "PiShock · no shocker in use";
  D.emit("shockers");
  paint();
}

/** One of its Shock / Vibrate / Beep switched: refused at once -- a pulse
 *  of it running stops -- for behaviours, friends, the menu alike. */
function setOp(s, op, on) {
  s.ops[op] = on;
  if (!on && s.out && s.out[0] === op) { s.out = null; s.until = 0; }
  W.chips.forEach((draw) => draw());
  D.emit("shockers");
  paint();
}

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
export function valueRow(label, { min, max, value, hue, fmt, onInput, title }) {
  const val = el("b.pg-val", {}, fmt(value));
  const s = hslider({ min, max, value, hue, onInput: (x) => { val.textContent = fmt(x); onInput && onInput(x); } });
  return el("div.pg-vrow", { title }, el("div.pg-vhead", {}, el("span", {}, label), val), s);
}
const secs = (x) => `${(x / 10).toFixed(1)} s`;

// How the shocker switches stack (shocker_switches.STACK), in a title
const STACK = "\n\nHow the shocker switches stack, from everyone to one friend: On (the hub) → Arm shocks (real "
  + "shocks) → Share with friends (friends at all) → each friend's own Shockers switch on the Friends page (and the "
  + "web remote's). Off stops everything, whatever the rest say.";

/** Arm shocks, the same setting as on Home's row: switched on it asks
 *  "Arm shocks? Yes / No" in its own place for five seconds, then falls back
 *  to off; the red words say which it is (shocker_switches.ArmSwitch). */
function armSwitch() {
  const st = D.state.shock;
  const sw = toggle("Arm shocks", st.armed, () => { sw.set(st.armed); D.arm("flip"); },
    "Until this is on, every shock - a behaviour's, a friend's, a test - goes out as a vibrate instead. Switching it "
    + "on here asks first, in the switch's place: Yes arms. The red words beside it say which it is now." + STACK);
  const ask = el("span.pg-armask", { hidden: true },
    el("span", {}, "Arm shocks?"),
    el("button.pg-btn.danger", { type: "button", onclick: () => D.arm("yes") }, "Yes"),
    el("button.pg-btn", { type: "button", onclick: () => D.arm("no") }, "No"));
  const words = el("span.pg-armw", { title: "Whether your shocks are real right now: Shocks armed, or Shocks not armed - "
    + "then every shock goes out as a vibrate. Home's shocker row says the same." }, "Shocks armed");
  const root = el("span.pg-arm", {}, sw, ask, words);
  return {
    root,
    paint() {
      const asking = st.asking > 0;
      sw.hidden = asking;
      ask.hidden = !asking;
      words.hidden = asking;
      sw.set(st.armed);
      words.textContent = st.armed ? "Shocks armed" : "Shocks not armed";
      words.classList.toggle("not", !st.armed);
    },
  };
}

function hubCard() {
  const st = D.state.shock;
  W.arm = armSwitch();
  W.share = toggle("Share with friends", st.share, (on) => { st.share = on; D.emit("shock"); },
    "Sharing only, for all your friends at once: off, your friends don't see your shockers at all and nothing they "
    + "send reaches them." + STACK);
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
      W.arm.root, W.share, W.stopBtn),
    tellRow("Tell VRChat while a shocker is connected", "OGP/ShockerConnected"));
}

/** A "connected" avatar parameter (presence_facade): on by default, under
 *  its default name -- the hub's on one line, a shocker's stacked. */
function tellRow(label, name, stacked = false) {
  const sw = toggle(label, true, () => {});
  const line = el("div.pg-row.tight", {}, el("span.o-in.pg-param", { title: name }, name),
    el("button.pg-btn", { type: "button" }, "Pick…"));
  if (stacked) return el("div.pg-tell", {}, sw, line);
  line.prepend(sw);
  return line;
}

// Each op's own switch on a shocker (op_chips.SHOCKER_OP_TIPS)
const OP_TIPS = {
  shock: "Shock on this shocker. Off: no shock reaches this shocker, whoever sends it - behaviours, friends, the web "
    + "remote, your avatar's menu. A shock asked for is dropped, not turned into a vibrate. Friends see their Shock "
    + "button greyed.",
  vibrate: "Vibrate on this shocker. Off: no vibrate reaches this shocker, whoever sends it. A shock that isn't armed "
    + "goes out as a vibrate, so it stops too, and a friend's warning beeps instead.",
  beep: "Beep on this shocker. Off: no beep reaches this shocker, whoever sends it. A friend's warning then vibrates.",
};

/** Switch chips in one row (op_chips.OpChips): lit on, grey off. */
export function opChips(label, items, isOn, onFlip, tips = {}) {
  const row = el("div.pg-ops", {}, label ? el("span.pg-muted", {}, label) : "");
  const chips = {};
  for (const [key, text] of items) {
    const b = el("button.pg-op", { type: "button", title: tips[key] || "" }, text);
    b.onclick = () => { onFlip(key, !isOn(key)); draw(); };
    chips[key] = b;
    row.append(b);
  }
  const draw = () => { for (const [key] of items) chips[key].classList.toggle("on", Boolean(isOn(key))); };
  draw();
  row.draw = draw;
  return row;
}

/** A card's Limits: a box headed by the ceiling icon and "Limits", one line
 *  on what they are, then the sliders (pishock_cards.limits_group). Nothing
 *  in it sends anything. */
function limitsBox(hint, title, ...rows) {
  return el("div.pg-limits", { title },
    el("div.pg-lhead", {}, icon("limits", "pg-lic"), el("b", {}, "Limits")),
    el("p.pg-lhint", {}, hint), ...rows);
}

function shockerCard(s, i) {
  const pill = el("span.pg-pill.ok", {}, "READY");
  const grip = el("span.pg-grip", { draggable: "true", title: "Drag onto a behaviour to drive it" }, "⠿");
  const use = toggle("", s.on, (on) => { card.classList.toggle("off", !on); setOn(s, on); },
    "In use. Off: this shocker gets nothing - behaviours skip it, friends don't see it, Home leaves it out.");
  grip.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/ogp-shocker", String(i)); e.dataTransfer.effectAllowed = "copy"; });
  const tests = {};
  const test = (op) => (tests[op] = el("button.pg-btn", { type: "button", onclick: () => fire(i, op, TEST_LEVEL, TEST_MS),
    title: `Sends one short ${op} at strength 10 to this shocker, now. `
      + (op === "shock" ? "It only shocks while shocks are armed; otherwise it vibrates." : "It stays under this shocker's limits.") },
    op[0].toUpperCase() + op.slice(1)));
  const ops = opChips("Allowed", OPS, (op) => s.ops[op], (op, on) => setOp(s, op, on), OP_TIPS);
  const card = hued(el("div.pg-scard", {},
    el("div.pg-shead", {}, grip, el("b", {}, s.name), el("span.grow"), use),
    el("div.pg-sid", {}, el("span", {}, `ID ${s.id}`), pill),
    ops,
    limitsBox("The most anything may send: friends, behaviours, the menu. Nothing is sent from here.",
      "The most anything may send to this shocker: behaviours, friends, the web remote and your avatar's menu. "
      + "Nothing is sent from here - these only set the ceiling. The Test buttons below are what send.",
      valueRow("Up to shock strength", { min: 1, max: 100, value: s.shock, hue: "yellow", fmt: String, onInput: (x) => { s.shock = x; },
        title: "No shock on this shocker goes above this, whatever a behaviour, a friend or the menu asks for. Moving it sends nothing." }),
      valueRow("Up to vibrate strength", { min: 1, max: 100, value: s.vibrate, hue: "pink", fmt: String, onInput: (x) => { s.vibrate = x; },
        title: "The most any vibrate on this shocker may carry. A shock that isn't armed goes out as a vibrate under this one. Moving it sends nothing." }),
      valueRow("Up to a pulse of", { min: 1, max: 150, value: Math.round(s.pulse * 10), hue: "yellow", fmt: secs,
        onInput: (x) => { s.pulse = x / 10; }, title: "The longest one pulse on this shocker may run. Moving it sends nothing." })),
    tellRow("Tell VRChat", `OGP/Shocker${i + 1}Connected`, true),
    el("div.pg-rule"),
    el("div.pg-thead", {}, el("b", {}, "Test"), el("span.grow"), el("span.pg-lhint", {}, "sends one short pulse")),
    el("div.pg-tests", {}, test("beep"), test("vibrate"), test("shock"))), "yellow");
  W.cards.push({ s, pill, tests, ops });
  return card;
}

/** The three timing limits for one set (the app's TIMING_LIMITS). */
function timingRows(t, whose = "") {
  const pre = whose ? `${whose} own, while their limits are separate: ` : "";
  const tip = (text) => pre + (pre ? text[0].toLowerCase() + text.slice(1) : text);
  return [
    valueRow("At least a rest of", { min: 1, max: 50, value: t.rest * 10, hue: "yellow", fmt: secs, onInput: (x) => { t.rest = x / 10; },
      title: tip("How long a shocker rests after a pulse ends before the next one - the least it gets. Moving it sends nothing.") }),
    valueRow("Up to a hold of", { min: 1, max: 60, value: t.hold, hue: "yellow", fmt: fmtSeconds, onInput: (x) => { t.hold = x; D.emit("shockers"); },
      title: tip("Continuous, While touching and a friend's hold run at most this long in one go, then the shocker takes a forced break. Moving it sends nothing.") }),
    valueRow("Then a forced break of", { min: 5, max: 100, value: t.brk * 10, hue: "yellow", fmt: secs, onInput: (x) => { t.brk = x / 10; },
      title: tip("How long that forced break lasts. Moving it sends nothing.") })];
}

/** The friends' own caps (the app's FRIEND_CAPS): each only ever lowers a
 *  shocker's own, for friends. */
function friendCapRows(c) {
  const moved = (key) => (x) => { c[key] = key === "pulse" ? x / 10 : x; D.emit("shockers"); };
  return [
    valueRow("Up to shock strength", { min: 1, max: 100, value: c.shock, hue: "yellow", fmt: String, onInput: moved("shock"),
      title: "No shock a friend sends goes above this, on any shocker - where a shocker's own limit is lower, that one "
        + "holds. Your avatar keeps each shocker's own. Moving it sends nothing." }),
    valueRow("Up to vibrate strength", { min: 1, max: 100, value: c.vibrate, hue: "pink", fmt: String, onInput: moved("vibrate"),
      title: "The most any vibrate a friend sends may carry, on any shocker - a shocker's own limit still wins where it "
        + "is lower. Moving it sends nothing." }),
    valueRow("Up to a pulse of", { min: 1, max: 150, value: Math.round(c.pulse * 10), hue: "yellow", fmt: secs,
      onInput: moved("pulse"), title: "The longest one pulse a friend sends may run, on any shocker - a shocker's own "
        + "still wins where it is shorter. Moving it sends nothing." })];
}

const SEPARATE_TIP = "Separate limits for friends: gives friends limits of their own: a max shock, max vibrate and "
  + "longest pulse - which only ever lower each shocker's own - and a rest, longest hold and forced break, counted "
  + "apart from your avatar's. Off, everyone keeps to one set - the easy way, and the default. On, your avatar (your "
  + "behaviours, ShockOSC's and your avatar menu) keeps to each shocker's own caps and the timing above, and friends "
  + "(Me and the web remote too) to theirs, so a friend's long hold never blocks your contact shocks, and the other "
  + "way round. The catch: your avatar's longest hold and a friend's can then run back to back, without the forced "
  + "break between them. Arming and each shocker's switches stay shared either way. Switching it sends nothing.";

function everyCard() {
  const avatarHead = el("div.pg-lsub", {}, "Your avatar");
  const friendsBox = el("div.pg-lset", {});
  const show = () => { avatarHead.hidden = !SHOCK.separate; friendsBox.hidden = !SHOCK.separate; };
  const separate = toggle("Separate limits for friends", SHOCK.separate, (on) => {
    if (on && !SHOCK.friendTiming) {
      // the first time: a copy of the values now -- each cap the highest
      // any shocker has, so switching it on lowers nobody
      SHOCK.friendTiming = { ...SHOCK.timing };
      const top = (key) => Math.max(...SHOCK.shockers.map((s) => s[key]));
      SHOCK.friendCaps = { shock: top("shock"), vibrate: top("vibrate"), pulse: top("pulse") };
      friendsBox.append(el("div.pg-lsub", {}, icon("friends", "pg-lic"), "Friends"),
        ...friendCapRows(SHOCK.friendCaps), ...timingRows(SHOCK.friendTiming, "Friends'"));
    }
    if (!on) {
      // one count again: every rest as long as the longer
      for (const s of SHOCK.shockers) s.restUntil = s.friendRestUntil = Math.max(s.restUntil, s.friendRestUntil || 0);
    }
    SHOCK.separate = on;
    show();
    D.emit("shockers");
  }, SEPARATE_TIP);
  show();
  return hued(el("div.pg-scard.every", {},
    el("b", {}, "Every shocker"),
    limitsBox("All shockers keep to these: friends, behaviours, the menu. Nothing is sent from here.",
      "The timing every shocker on the hub keeps to, whoever drives it: behaviours, friends, the web remote and your "
      + "avatar's menu. Nothing is sent from here - these only set the limits.",
      separate, avatarHead, ...timingRows(SHOCK.timing), friendsBox)), "yellow");
}

/** The shockers a behaviour drives: chips with ×, the + to add, and a drop
 *  target for a shocker card's ⠿ (pishock_cards.ShockerChips). A chip greys
 *  for a shocker switched off on its card, or with the behaviour's op off. */
function chipBox(names, opNow = () => "") {
  const box = el("div.pg-chips");
  const plus = el("button.pg-plus", { type: "button", title: "Pick the shockers it drives" }, "+");
  const draw = () => {
    const op = opNow();
    const off = new Map(SHOCK.shockers.map((s) => [s.name,
      !s.on ? "Switched off on its card - this behaviour skips it"
        : op && !s.ops[op] ? `${op[0].toUpperCase()}${op.slice(1)} is switched off on its card - this behaviour skips it` : ""]));
    box.replaceChildren(...names.map((n) => el(`span.pg-schip${off.get(n) ? ".off" : ""}`,
      { title: off.get(n) || "" }, n,
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
  W.chips.push(() => { if (box.isConnected) draw(); });
  box.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/ogp-shocker")) { e.preventDefault(); box.classList.add("over"); } });
  box.addEventListener("dragleave", () => box.classList.remove("over"));
  box.addEventListener("drop", (e) => {
    e.preventDefault(); box.classList.remove("over");
    const s = SHOCK.shockers[Number(e.dataTransfer.getData("text/ogp-shocker"))];
    if (s) add(s.name);
  });
  box.redraw = draw;
  draw();
  return box;
}

// The kinds a behaviour can be (pishock_rules.KINDS): pill, name, what it does
const KINDS = {
  zones: ["TOUCH ZONES", "Touch zones", "Several contacts, each driving its own shockers - the neck the collar, a thigh its shocker. Drop a shocker onto each contact's row."],
  triggers: ["CONTACT", "Contact", "One on/off contact at a fixed strength: a pulse each time it is touched, or for as long as it is touched."],
  continuous: ["CONTINUOUS", "Continuous", "A value from your avatar - usually a proximity contact - runs the shockers while it is above a threshold. The closer, the stronger."],
  impacts: ["IMPACT", "Impact", "Several OnEnter contacts on one spot, each with a different Min Velocity on the avatar: the hardest hit that fired picks the strength."],
  pulls: ["PULL", "Pull", "A PhysBone - a tail, an ear: something while it is held, and letting go after a stretch fires once, the harder the pull the stronger. ShockOSC's PhysBone works this way."],
};
const OP_KEYS = ["vibrate", "shock", "beep"];
const HELD = ["none", "vibrate", "shock", "beep"];
// pishock_cards.fmt_seconds / fmt_short
export const fmtSeconds = (s) => (s >= 10 ? `${s.toFixed(0)} s` : `${s.toFixed(1)} s`);
const holdText = (v) => (v < 1 ? "at once" : v >= 1000 ? fmtSeconds(v / 1000)
  : `${(v / 1000).toFixed(2).replace(/0+$/, "").replace(/\.$/, "")} s`);

function param(value, placeholder) {
  return el("div.pg-row.tight", {}, el("input.su-input.pg-pfield", { type: "text", value: value || "", placeholder }),
    el("button.pg-btn", { type: "button", title: "Pick a parameter your avatar sends" }, "Pick"));
}

/** A behaviour's card (pishock_rules._build_pishock_behaviour). */
function behaviourCard(kind, r) {
  const [pillText, defName, blurb] = KINDS[kind];
  const remove = el("button.pg-x.big", { type: "button", title: "Delete this behaviour" }, "×");
  const head = el("div.pg-bhead", {}, el("b", {}, r.name || defName), el("span.grow"),
    el("span.pg-muted", { title: "What this behaviour sees from your avatar right now." }, r.live || "off"),
    el("span.pg-pill.run", {}, pillText),
    toggle("", r.on !== false, () => {}, "Off stops this behaviour without losing its settings."), remove);
  const card = hued(el("div.pg-bcard", { title: blurb }, head), "cyan");
  let op = r.op || "vibrate";
  const drops = [];
  const redraw = () => drops.forEach((d) => d.redraw());
  if (kind === "triggers" || kind === "continuous") card.append(param(r.param, "Avatar parameter, e.g. Contact/Headpat"));
  if (kind === "pulls") card.append(param(r.param, "PhysBone parameter, e.g. ShockOsc/Tail"));
  const opSeg = segmented(["Vibrate", "Shock", "Beep"], "yellow", (k) => { op = OP_KEYS[k]; redraw(); }, OP_KEYS.indexOf(op));
  const line = el("div.pg-segs", {}, kind === "pulls" ? el("span.pg-muted", {}, "When let go") : "", opSeg);
  card.append(line);
  const pulseOnly = [];
  if (kind === "triggers" || kind === "zones") {
    const show = (pulse) => pulseOnly.forEach((n) => { n.hidden = !pulse; });
    line.append(segmented(["Pulse once", "While touching"], "cyan", (k) => show(k === 0), r.mode === "hold" ? 1 : 0));
    queueMicrotask(() => show(r.mode !== "hold"));
  }
  if (kind === "pulls") {
    card.append(el("div.pg-segs", {}, el("span.pg-muted", {}, "While held"),
      segmented(["Nothing", "Vibrate", "Shock", "Beep"], "yellow", () => {}, HELD.indexOf(r.held || "vibrate"))));
  }
  const len = () => valueRow("Length", { min: 1, max: 150, value: Math.round((r.length || 0.5) * 10), hue: "yellow", fmt: secs });
  if (kind === "triggers" || kind === "zones") {
    card.append(valueRow("Strength", { min: 1, max: 100, value: r.strength || 20, hue: "yellow", fmt: String,
      title: "Always this strength, 1-100 - never above a shocker's own max." }));
    const l = len();
    pulseOnly.push(l);
    card.append(l);
    if (kind === "triggers") {
      const h = valueRow("Touch for at least", { min: 0, max: 40, value: (r.hold || 0) / 50, hue: "cyan", fmt: (x) => holdText(x * 50),
        title: "How long the contact has to stay touched before the pulse - a brush that's shorter does nothing. ShockOSC waits 0.25 s." });
      pulseOnly.push(h);
      card.append(h);
    }
  } else if (kind === "continuous") {
    card.append(valueRow("Starts above", { min: 0, max: 99, value: Math.round((r.threshold || 0) * 100), hue: "cyan",
                                           fmt: (x) => (x / 100).toFixed(2), title: "It runs while the value is above this. 0 = any contact at all." }),
      valueRow("Strength just past it", { min: 1, max: 100, value: r.min || 5, hue: "yellow", fmt: String }),
      valueRow("Strength at 1", { min: 1, max: 100, value: r.max || 30, hue: "yellow", fmt: String, title: "In between, the strength follows the value." }));
  } else if (kind === "pulls") {
    card.append(valueRow("Strength at a slight pull", { min: 1, max: 100, value: r.min || 5, hue: "yellow", fmt: String,
                                                         title: "Let go after the smallest stretch: this strength." }),
      valueRow("Strength at full stretch", { min: 1, max: 100, value: r.max || 30, hue: "yellow", fmt: String,
        title: "In between, the strength follows the stretch at the moment it is let go - never above a shocker's own max." }),
      len());
  } else if (kind === "impacts") {
    card.append(len(), el("div.pg-row.tight", {}, el("span.pg-muted", {}, "Tier 1"),
      el("input.su-input.pg-pfield", { type: "text", placeholder: "OnEnter receiver parameter" }),
      el("button.pg-btn", { type: "button" }, "Pick")),
    valueRow("Strength", { min: 1, max: 100, value: 20, hue: "yellow", fmt: String }),
    el("button.pg-btn", { type: "button", title: "One more velocity step (up to 8)" }, "＋ Add tier"));
  }
  if (kind === "zones") {
    for (const [p, names] of r.contacts) {
      const d = chipBox(names, () => op);
      drops.push(d);
      card.append(el("div.pg-row.tight", {}, el("span.o-in.pg-field.short", {}, p),
        el("button.pg-btn", { type: "button" }, "Pick"), d, el("button.pg-x", { type: "button" }, "×")));
    }
    card.append(el("button.pg-btn.wide", { type: "button" }, "+  Add a contact"));
  } else {
    const d = chipBox(r.shockers || [], () => op);
    drops.push(d);
    card.append(d);
  }
  remove.onclick = () => card.remove();
  return card;
}

function build(root) {
  root.append(
    el("div.o-viewtitle", {}, "Shockers"),
    el("p.pg-intro", {}, "Your PiShock or OpenShock hub over its USB cable — no account, no internet, straight from your "
      + "avatar's contacts to the shockers. Connect the hub, set each shocker's limits, then drag the shockers onto the "
      + "behaviours below."),
    hubCard());
  const shockers = hued(el("div.pg-cat", {},
    el("div.pg-bar", {}, icon("shock"), el("span", {}, "SHOCKERS")),
    el("div.pg-sgrid", {}, ...SHOCK.shockers.map(shockerCard), everyCard())), "yellow");
  const add = el("button.pg-btn.onbar", { type: "button", title: "Touch zones, Contact, Continuous, Impact or Pull." }, "+  Add behaviour");
  W.behaviours = el("div.pg-bgrid", {},
    behaviourCard("zones", { live: "Neck", op: "vibrate", mode: "pulse", strength: 25, length: 0.6,
                             contacts: [["Contact/Neck", ["Collar"]], ["Contact/ThighL", ["Thigh"]]] }),
    behaviourCard("triggers", { name: "Headpat", param: "Headpat", op: "shock", mode: "pulse", strength: 15,
                                shockers: ["Collar", "Thigh"] }),
    behaviourCard("pulls", { name: "Tail", param: "Tail", op: "shock", held: "vibrate", min: 5, max: 30, length: 0.5,
                             shockers: ["Collar"] }));
  // what + Add behaviour opens: one button per kind, in the page
  W.addRow = el("div.pg-row.pg-addrow", { hidden: true }, Object.entries(KINDS).map(([kind, [, label, blurb]]) =>
    el("button.pg-btn", { type: "button", title: blurb, onclick: () => {
      W.behaviours.append(behaviourCard(kind, { contacts: [["", []]], shockers: [] }));
      W.addRow.hidden = true;
    } }, `＋ ${label}`)));
  add.onclick = () => { W.addRow.hidden = !W.addRow.hidden; };
  const behaviours = hued(el("div.pg-cat", {},
    el("div.pg-bar", {}, el("span", {}, "BEHAVIOURS"), el("span.grow"), add),
    el("p.pg-note", {}, "What your avatar's contacts do. Drag a shocker card's ⠿ onto a behaviour (or press its  +) to "
      + "pick the shockers it drives; × takes one off. A new behaviour drives none until you do."),
    W.addRow, W.behaviours), "cyan");
  root.append(shockers, behaviours);
}

/** Each card's state, the app's words (pishock.py _refresh_pishock_live). */
function paint() {
  const st = D.state.shock, now = performance.now();
  for (const { s, pill, tests } of W.cards) {
    let text, tone;
    if (!s.on) { text = "OFF"; tone = "idle"; }
    else if (s.out && now < s.until) { text = `${s.out[0].toUpperCase()}${s.out[1] ? " " + s.out[1] : ""}`; tone = { shock: "shock", vibrate: "live" }[s.out[0]] || "info"; }
    else if (now < Math.max(s.restUntil, s.friendRestUntil || 0)) { text = "BREAK"; tone = "warn"; }
    else if (!st.on || SHOCK.stopped) { text = "STOPPED"; tone = "idle"; }
    else { text = "READY"; tone = "ok"; s.out = null; }
    if (pill.textContent !== text) { pill.textContent = text; pill.className = `pg-pill ${tone}`; }
    // a Test button rests while its op is switched off
    for (const [op, b] of Object.entries(tests)) b.disabled = !s.ops[op];
  }
  if (W.arm) {
    W.arm.paint();
    W.share.set(st.share);
    W.stopBtn.textContent = SHOCK.stopped ? "Resume" : "Stop all";
  }
}

build(D.page("Shockers"));
D.on("shock", paint);
setInterval(paint, 100);
paint();
