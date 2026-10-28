// The web remote: a friend's panel in a browser, no OGP installed.
//
// The page opens a web remote link (remote.html#<id>.<code>.<nick>,
// src/friend_links.py), dials that OGP over iroh -- compiled to WebAssembly
// in tools/web_guest, relay-only because a browser can't send UDP -- and
// speaks src/remote_protocol.py as a Friends client: a hello with ``web``
// and the link's code, then what a friend's OGP sends -- ``cmd`` (levels,
// auto modes, Override, the strength slider, held shockers, Sync with
// others), ``shk`` / ``stp``, ``lw``, and for their avatar ``pw`` / ``pst`` /
// ``ph`` (src/remote_params.py). The OGP lets it in as a web guest
// (src/controllers/friends_web.py): what the Web remote row's Toys /
// Shockers / Avatar switches allow, and every friend rule holds there
// (strength, Off, output band, Pause all friends, arming and each
// shocker's caps, locked categories, zero when our updates stop, logged).
//
// The panel is the app's (src/ui/views/friends_panel.py): their toys
// (remote-toys.js), their shockers as PiShock's panel with Party Mode
// (remote-shockers.js), their avatar's board (remote-board.js). The
// browser keeps its own key (localStorage), so it is the same guest next
// time -- and a kicked one stays kicked until that storage is cleared.

import init, { Guest } from "./web_guest/ogp_web_guest.js";
import { el, identity, pct, toggle, hslider } from "./remote-ui.js";
import { ToyCard } from "./remote-toys.js";
import { ShockerCard, ShockParty } from "./remote-shockers.js";
import { Board } from "./remote-board.js";

const P = window.OGPRemoteProto;
const SEND_MS = 250;        // remote_session.SEND_S
const PING_MS = 5000;       // remote_session.PING_S
const DEAD_MS = 16000;      // remote_session.DEAD_S
const HELLO_MS = 60000;     // remote_session.HELLO_S
const REFRESH_MS = 10000;   // remote_session.STATE_REFRESH_S
const CMD_HZ = 60;          // remote_session.CMD_HZ
const REPEATS = 2;          // a change goes out 1 + REPEATS times
const STRENGTH_RESEND_MS = 3000;   // friends_control._STRENGTH_RESEND_S
const OWN_MS = 1500;        // your own avatar set shows over theirs this long
const ASK_AGAIN_MS = 4000;  // a board that hasn't come is asked for again
const KEY_STORE = "ogp-web-remote-key";
const NICK_STORE = "ogp-web-remote-nick";
const SYNC_STORE = "ogp-web-remote-sync";
const RETRY_MS = [1000, 2000, 5000, 10000, 30000];

const enc = new TextEncoder();
const dec = new TextDecoder();
const $ = (id) => document.getElementById(id);
const now = () => performance.now();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const target = P.parseLink(location.hash);
let guest = null;
let link = null;
let linked = false;
let ended = "";
let stopped = false;
let theirNick = target ? target.nick : "";
let tries = 0, helloCount = 0;
let lastTx = 0, lastRx = 0, lastHello = 0, lastCmd = 0, cmdTimer = null;
const rtts = [];

// what you do to them (friends_control.py's state, for one friend)
const S = {
  status: null,                 // their st, read
  others: 0,                    // how many others drive them (a count: no names)
  levels: {},                   // toy -> 0..1 (or P.ALL)
  override: new Set(),
  patterns: {},                 // toy -> [wave, period, lo, hi]
  holds: {},                    // shocker slot -> [op, 0..1]
  strength: null,               // [seq, value, when]
  strengthT: 0,                 // your hand on their strength slider
  mySeq: 0,
  sync: store(SYNC_STORE) !== "0",
  pseq: 0,                      // Sync with others: your panel's version
  board: null, values: {}, ownSets: {}, paramHolds: new Set(), hadParamHolds: false,
  paramSeq: Date.now(), yoloOpen: false,
  shockMemory: {}, partyMemory: null, partyTicked: new Set(),
};
// what was last sent of each state slot, and when
const slots = { cmd: { sig: "", t: 0, reps: 0 }, lw: { sig: "", t: 0, reps: 0 },
                pw: { sig: "", t: 0, reps: 0 }, ph: { sig: "", t: 0, reps: 0 } };
// the panel's widgets
const W = { key: null, toys: [], shockers: [], party: null, board: null, strength: null };

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* private window: a new guest every visit */ }
  return null;
}

function loadKey() {
  const hex = store(KEY_STORE) || "";
  if (/^[0-9a-f]{64}$/.test(hex)) return Uint8Array.from(hex.match(/../g), (b) => parseInt(b, 16));
  const key = crypto.getRandomValues(new Uint8Array(32));
  store(KEY_STORE, Array.from(key, (b) => b.toString(16).padStart(2, "0")).join(""));
  return key;
}

// --- sending -----------------------------------------------------------------------

function send(msg) {
  if (!link) return;
  try {
    link.send(enc.encode(JSON.stringify(msg)));
    lastTx = now();
  } catch (e) {
    log(`sending failed: ${e.message || e}`);
  }
}

/** A one-off (a shock, a Stop, a set): sent a few times, acted on once. */
function sendEvent(msg, repeat = 3) {
  for (let i = 0; i < repeat; i++) setTimeout(() => send(msg), 30 * i);
}

/** A state slot (remote_session.send_state): sent when it changes (plus
 *  REPEATS copies), again every REFRESH_MS -- and every tick while it
 *  `drives` something the other side lets go of when it stops coming. */
function sendState(name, msg, drives = false) {
  const st = slots[name], t = now();
  const sig = JSON.stringify(msg, (k, v) => (k === "ts" ? undefined : v));
  if (sig !== st.sig) { st.sig = sig; st.reps = REPEATS + 1; }
  if (drives || st.reps > 0 || t - st.t >= REFRESH_MS) {
    send(msg);
    st.t = t;
    if (st.reps > 0) st.reps--;
  }
}

function hello() {
  return { t: "hello", nick: myNick(), v: P.PROTOCOL_VERSION, ask: 1, web: 1, invite: target.code };
}

function buildCmd() {
  const s = S.strength;
  const strength = s && now() - s[2] < STRENGTH_RESEND_MS ? [s[0], s[1]] : null;
  const msg = P.makeCmd(S.levels, strength, [...S.override], S.patterns, S.holds,
                        S.sync ? S.pseq : null);
  // ts: when this left the browser, for tools/web_guest/test_host.py's
  // latency check; OGP ignores it.
  msg.ts = Date.now();
  return msg;
}

/** A control moved: the cmd now, at most CMD_HZ a second. */
function pushCmd() {
  if (!linked || cmdTimer) return;
  const wait = lastCmd + 1000 / CMD_HZ - now();
  if (wait <= 0) flushCmd();
  else cmdTimer = setTimeout(() => { cmdTimer = null; flushCmd(); }, wait);
}
function flushCmd() {
  lastCmd = now();
  const msg = buildCmd();
  sendState("cmd", msg, P.drives(msg));
  if (!P.drives(msg)) sendEvent(msg, REPEATS + 1);   // letting go must arrive
}

// --- the link ----------------------------------------------------------------------

async function run() {
  while (!stopped) {
    setState("connecting", `Connecting to ${theirNick || "your friend"}…`);
    const t0 = now();
    try {
      link = await guest.connect(target.id, P.ALPN);
      log(`connected in ${Math.round(now() - t0)} ms`);
      ended = await session(link);
    } catch (e) {
      ended = String(e.message || e);
      log(`no link: ${ended}`);
    }
    link = null;
    linked = false;
    letGoOfEverything();
    render();
    // their OGP's reasons (src/remote_link.py WEB_CLOSED / WEB_KICKED)
    if (/nolink|kicked|removed|refused/.test(ended)) {
      stopped = true;
      const who = theirNick || "Your friend";
      setState("bad", /kicked|removed/.test(ended)
        ? `${who} took this browser off their web remote.`
        : `This link doesn't work any more - ask ${theirNick || "them"} for a new one.`);
      return;
    }
    await sleep(RETRY_MS[Math.min(tries++, RETRY_MS.length - 1)]);
  }
}

async function session(l) {
  lastRx = now();
  helloCount = 0;
  for (const st of Object.values(slots)) Object.assign(st, { sig: "", t: 0, reps: 0 });
  send(hello());
  const ticker = setInterval(tick, SEND_MS);
  streams(l);
  try {
    for (;;) {
      const data = await l.recv();
      lastRx = now();
      let msg = null;
      try { msg = JSON.parse(dec.decode(data)); } catch (e) { continue; }
      if (msg && typeof msg.t === "string") onMsg(msg);
    }
  } catch (e) {
    return String(e.message || e);
  } finally {
    clearInterval(ticker);
    if (cmdTimer) { clearTimeout(cmdTimer); cmdTimer = null; }
  }
}

/** Their streams: one message each -- an avatar board (``pbd``). */
async function streams(l) {
  try {
    for (;;) {
      const data = await l.recv_stream(P.MAX_BLOB);
      lastRx = now();
      let msg = null;
      try { msg = JSON.parse(dec.decode(data)); } catch (e) { continue; }
      if (msg && msg.t === "pbd") boardIn(msg);
    }
  } catch (e) { /* the link ended: session() says why */ }
}

function tick() {
  const t = now();
  if (!linked) {
    // being let in: say who we are, quickly at first (OGP listens for 2 s)
    if (helloCount < 8 || t - lastHello >= PING_MS) {
      helloCount++;
      lastHello = t;
      send(hello());
    }
  } else {
    const msg = buildCmd();
    sendState("cmd", msg, P.drives(msg));
    const visible = document.visibilityState === "visible";
    sendState("lw", visible ? { t: "lw", on: 1 } : { t: "lw" });
    watchBoard(visible);
    if (S.paramHolds.size || S.hadParamHolds) {
      sendState("ph", P.makeHolds(S.paramHolds), S.paramHolds.size > 0);
      if (!S.paramHolds.size && slots.ph.reps === 0) S.hadParamHolds = false;
    }
    if (t - lastHello >= HELLO_MS) { lastHello = t; send(hello()); }
  }
  if (t - lastTx >= PING_MS) send({ t: "ping", n: Math.round(t * 1000) });
  if (t - lastRx > DEAD_MS && link) link.close(2, "timeout");
  update();
}

function onMsg(msg) {
  switch (msg.t) {
    case "ping":
      send({ t: "pong", n: msg.n });
      break;
    case "pong": {
      const sent = Number(msg.n) / 1000;
      if (Number.isFinite(sent) && sent > 0 && sent <= now()) {
        rtts.push(now() - sent);
        if (rtts.length > 50) rtts.shift();
      }
      break;
    }
    case "wait":
      setState("connecting", `Waiting for ${theirNick || "your friend"} to let you in…`);
      break;
    case "hello":
      theirNick = P.cleanNick(msg.nick) || theirNick;
      if (!linked) {
        linked = true;
        tries = 0;
        log(`linked with ${theirNick}`);
        send({ t: "ping", n: Math.round(now() * 1000) });
      }
      render();
      break;
    case "st":
      S.status = P.readStatus(msg);
      render();
      break;
    case "oth":
      S.others = P.readOthers(msg).length;
      break;
    case "pnl":
      panelIn(msg);
      break;
    case "pv":
      if (S.board) Object.assign(S.values, P.readValues(msg, S.board));
      break;
    default:
      break;
  }
}

// --- their toys (friends_control.py) ------------------------------------------------

function panelChanged() {
  if (S.sync) S.pseq += 1;           // past the newest seen: it wins over the others'
}
function setLevel(toy, v) {
  const was = Object.values(S.levels).some((x) => x > 0);
  v = P.unit(v);
  if (v > 0) S.levels[toy] = v; else delete S.levels[toy];
  panelChanged();
  pushCmd();
  const nowOn = Object.values(S.levels).some((x) => x > 0);
  if (nowOn !== was) log(`You ${nowOn ? "started" : "stopped"} driving ${theirNick}'s toys`);
}
function setOverride(toy, on) {
  if (on) S.override.add(toy); else S.override.delete(toy);
  panelChanged();
  pushCmd();
}
function setPattern(toy, wave, period, lo, hi) {
  const c = wave ? P.cleanPattern(wave, period, lo, hi) : null;
  const was = S.patterns[toy];
  if (c) S.patterns[toy] = c; else delete S.patterns[toy];
  panelChanged();
  pushCmd();
  const what = toy === P.ALL ? "all their toys" : toy;
  if (!c && was) log(`You stopped the auto mode on ${theirNick}'s ${what}`);
  else if (c && (!was || was[0] !== c[0])) log(`You started ${P.WAVE_LABELS[c[0]]} on ${theirNick}'s ${what}`);
}
function setStrength(v) {
  S.mySeq = Math.max(S.mySeq + 1, Date.now());
  S.strength = [S.mySeq, P.unit(v), now()];
  S.strengthT = now();
  pushCmd();
}
function setSync(on) {
  S.sync = on;
  store(SYNC_STORE, on ? "1" : "0");
  S.pseq = 0;                        // joining takes the shared panel as it stands
  pushCmd();
  log(on ? "You share one panel with the others" : "You drive on your own");
}
/** Their OGP's shared panel: newer than yours, or the same version won by
 *  someone else -- take it as your own (friends_control._friend_panel_in). */
function panelIn(msg) {
  const got = P.readPanel(msg);
  if (!got || !S.sync) return;
  const [seq, levels, override, patterns] = got;
  if (seq < S.pseq) return;          // yours is newer: on its way to them
  const same = JSON.stringify([S.levels, [...S.override].sort(), S.patterns])
    === JSON.stringify([levels, [...override].sort(), patterns]);
  S.pseq = seq;
  if (same) return;
  S.levels = { ...levels };
  S.override = new Set(override);
  S.patterns = { ...patterns };
  pushCmd();
}

// --- their shockers ------------------------------------------------------------------

function capsOf(slot) { return P.shockerCaps(S.status, slot); }
function shock(slots, intensity, length, op, warnMs, warnIntensity) {
  const st = S.status;
  if (!st || !st.allowShock || !slots.length) return;
  const msg = P.makeShock(P.newId(), slots, intensity, length, op, warnMs > 0 ? "vibrate" : "",
                          warnIntensity, warnMs);
  sendEvent(msg, 3);
  const [cap, , top] = capsOf(msg.slots[0]);
  const [lvl, ms] = P.shockValues(msg.int, msg.len, op === "vibrate" ? capsOf(msg.slots[0])[1] : cap, top);
  const names = msg.slots.map((s) => st.shockers[s]).filter(Boolean).join(", ");
  const first = msg.warn ? `${(warnMs / 1000).toFixed(1)} s warning, then ` : "";
  const what = op === "beep" ? "beep" : op === "shock" && !st.armed ? `vibrate ${lvl} (their shocks aren't armed)`
    : `${op} ${lvl}`;
  log(`You → ${theirNick}: ${first}${what} · ${(ms / 1000).toFixed(1)} s on ${names}`);
}
function hold(slots, op, intensity) {
  for (const s of slots) S.holds[s] = [op, P.unit(intensity)];
  pushCmd();
}
function release(slots) {
  for (const s of slots) delete S.holds[s];
  pushCmd();
}
function stop(slots) {
  release(slots);
  sendEvent(P.makeStop(P.newId(), slots), 3);
  log(`You stopped ${theirNick}'s shockers`);
}
/** Party: the length is real time, each shocker's own longest pulse at
 *  most (friends_control.party_shock). */
function partyShock(slots, op, intensity, lengthMs, warnMs, warnIntensity) {
  const byLength = {};
  for (const slot of slots) {
    const top = Math.max(P.SHOCK_MIN_MS, capsOf(slot)[2]);
    const ms = Math.max(P.SHOCK_MIN_MS, Math.min(lengthMs, top));
    const length = top <= P.SHOCK_MIN_MS ? 0 : (ms - P.SHOCK_MIN_MS) / (top - P.SHOCK_MIN_MS);
    (byLength[P.round(length, 3)] = byLength[P.round(length, 3)] || []).push(slot);
  }
  for (const [length, group] of Object.entries(byLength)) {
    shock(group, intensity, Number(length), op, warnMs, warnIntensity);
  }
}

// --- their avatar (friends_params.py) ------------------------------------------------

function boardIn(msg) {
  const board = P.readBoard(msg);
  if (!board) return;
  S.board = board;
  S.values = {};
}
function theirBoard() {
  const prm = S.status && S.status.prm;
  if (!prm) return null;
  let board = S.board;
  // they changed avatar and its board hasn't come: never show the old one as theirs
  if (board && prm.avatar && board.avatar !== prm.avatar) board = null;
  const values = board ? { ...S.values } : {};
  const t = now();
  for (const [name, [v, at]] of Object.entries(S.ownSets)) if (t - at < OWN_MS) values[name] = v;
  return { prm, board, values };
}
function watchBoard(visible) {
  const prm = S.status && S.status.prm;
  if (prm && visible) {
    const have = S.board ? S.board.ver : "";
    // a newer board on its way: ask again every few seconds
    const retry = prm.ver && prm.ver !== have ? Math.floor(now() / ASK_AGAIN_MS) : 0;
    sendState("pw", P.makeWatch(have, S.yoloOpen, retry));
  } else if (slots.pw.sig && !slots.pw.sig.includes('"off"')) {
    sendState("pw", P.WATCH_OFF);
    letGoOfParams();
  } else if (slots.pw.sig) {
    sendState("pw", P.WATCH_OFF);
  }
}
/** What setting a control sends (param_board.send_value), shown at once. */
function sendValue(c, v) {
  if (c.ptype === "Bool") { const b = Boolean(v); return c.invert ? !b : b; }
  if (P.isIntSwitch(c)) { const [on, off] = P.intSwitchValues(c); return v ? on : off; }
  let x = Number(v);
  if (!Number.isFinite(x)) return null;
  if (c.min !== undefined) x = Math.max(c.min, x);
  if (c.max !== undefined) x = Math.min(c.max, x);
  return c.ptype === "Int" ? Math.max(0, Math.min(255, Math.round(x))) : Math.max(-1, Math.min(1, x));
}
function control(id) {
  const tb = theirBoard();
  if (!tb || !tb.board || tb.prm.stop) return null;
  const c = tb.board.controls.find((x) => x.id === id);
  const cat = c && tb.board.categories.find((x) => x.id === c.cat);
  return c && !(cat && cat.locked) ? c : null;
}
function paramSet(id, value) {
  const c = control(id);
  if (!c) return;
  const out = sendValue(c, value);
  if (out === null) return;
  S.ownSets[c.param] = [out, now()];
  S.paramSeq += 1;
  sendEvent(P.makeSet(S.paramSeq, value, id), 3);
  log(`You set ${theirNick}'s ${c.label} to ${typeof out === "boolean" ? (out ? "on" : "off") : out}`);
}
function paramHold(id, held) {
  const c = control(id);
  if (!c || c.kind !== "button") return;
  if (held) S.paramHolds.add(id); else S.paramHolds.delete(id);
  if (S.paramHolds.size) S.hadParamHolds = true;
  S.ownSets[c.param] = [sendValue(c, held), now()];
  send(P.makeHolds(S.paramHolds));           // now, not at the next tick
  if (held) log(`You held ${theirNick}'s ${c.label}`);
}
function paramSetAny(name, value) {
  const tb = theirBoard();
  if (!tb || !tb.board || !tb.prm.yolo || !tb.board.all || tb.prm.stop) return;
  const entry = tb.board.all.find(([n]) => n === name);
  if (!entry) return;
  const ptype = entry[1];
  let out;
  if (ptype === "Bool") out = Boolean(value);
  else if (ptype === "Int") out = Math.max(0, Math.min(255, Math.round(Number(value))));
  else out = Math.max(-1, Math.min(1, Number(value)));
  if (!Number.isFinite(Number(out))) return;
  S.ownSets[name] = [out, now()];
  S.paramSeq += 1;
  sendEvent(P.makeSet(S.paramSeq, out, "", name), 3);
  log(`You set ${theirNick}'s ${name} to ${out} (YOLO)`);
}
function letGoOfParams() {
  if (S.paramHolds.size) { S.paramHolds.clear(); sendEvent(P.makeHolds([]), 1); }
}
function letGoOfEverything() {
  for (const card of W.shockers) card.release();
  if (W.party) W.party.release();
  S.holds = {};
  S.paramHolds.clear();
}

// --- the page ----------------------------------------------------------------------

function myNick() { return P.cleanNick($("nick").value) || "Web guest"; }

function setState(kind, text) {
  const node = $("state");
  node.className = `state ${kind}`;
  node.textContent = text;
}

function log(line) {
  const node = el("div", {}, `${new Date().toTimeString().substring(0, 8)}  ${line}`);
  $("log").prepend(node);
  while ($("log").childElementCount > 80) $("log").lastChild.remove();
}

function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

function section(title, hue, what) {
  const head = el("div.section-h", {}, identity(what, 15), el("span.micro", {}, title), el("span.grow"));
  const body = el("div.section-b");
  const box = el("section.friend-section", {}, head, body);
  box.style.setProperty("--hue", `var(--${hue})`);
  box.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
  return { box, head, body };
}

/** What the panel is made of: rebuilt when this changes (friends_panel._panel_key). */
function panelKey() {
  const st = S.status;
  if (!linked || !st) return JSON.stringify([linked]);
  return JSON.stringify([st.allowToys, st.toys.map((t) => t[0]), st.allowShock, st.shockers,
                         Boolean(st.prm)]);
}

function render() {
  $("who").textContent = theirNick || "A friend";
  document.title = `${theirNick || "A friend"}'s panel - OscGoesPurrr`;
  $("panel").hidden = !linked;
  if (!linked) {
    if (ended && !stopped) setState("connecting", `Link lost (${ended.slice(0, 60)}) - trying again…`);
    W.key = null;
    return;
  }
  const key = panelKey();
  if (key !== W.key) {
    W.key = key;
    build();
  }
  update();
}

function build() {
  // the cards about to go: nothing they hold keeps running, and the ones
  // that replace them start where these were (friends_shockers._keep_shockers)
  W.shockers.forEach((card, i) => { card.release(); S.shockMemory[i] = card.settings(); });
  if (W.party) { W.party.release(); S.partyMemory = W.party.settings(); }
  const panel = $("sections");
  panel.replaceChildren();
  W.toys = [];
  W.shockers = [];
  W.party = null;
  W.board = null;
  W.strength = null;
  const st = S.status;
  if (!st) { panel.append(el("p.small", {}, "Waiting for their state…")); return; }

  // their toys
  const toys = section("THEIR TOYS", "pink", "toys");
  panel.append(toys.box);
  if (!st.allowToys) {
    toys.body.append(el("p.small", {}, "They haven't allowed you their toys."));
  } else {
    const sync = toggle("Sync with others", S.sync, setSync,
      "On: everyone who drives them with Sync on shares one set of toy cards - a level, auto mode or "
      + "Override one of you picks shows up on the others' panels too, and their toys play it once: the "
      + "newest change wins. Off: your cards are your own, and their toys follow whichever of you is "
      + "higher. Their strength slider is shared either way.");
    const val = el("span.val");
    const s = hslider({ max: 1000, hue: "accent", value: Math.round(st.strength * 1000),
                        title: "Their own strength slider, top left in their OGP: it scales everything "
                          + "their toys do. Whoever moves it last wins.",
                        onInput: (x) => { val.textContent = pct(x / 1000); setStrength(x / 1000); } });
    s.classList.add("strength");
    val.textContent = pct(st.strength);
    W.strength = { s, val };
    toys.head.append(sync, el("span.strength-g", {}, el("span.small", {}, "Their strength"), s, val));
    const every = st.toys.length ? [[P.ALL, "All their toys"]] : [];
    for (const [key, title] of [...every, ...st.toys.map(([n]) => [n, n])]) {
      const card = new ToyCard(key, title, {
        onLevel: (v) => setLevel(key, v), onOverride: (on) => setOverride(key, on),
        onPattern: (w, pd, lo, hi) => setPattern(key, w, pd, lo, hi), meter: key !== P.ALL });
      W.toys.push(card);
    }
    toys.body.append(el("div.grid", {}, W.toys.map((c) => c.root)));
    if (!st.toys.length) toys.body.append(el("p.small", {}, "No toy connected on their side."));
  }

  // their shockers: only while they let you use them
  if (st.allowShock) {
    const sh = section("THEIR SHOCKERS", "yellow", "shock");
    panel.append(sh.box);
    if (st.shockers.length > 1) {
      sh.head.append(el("button.btn.danger.sm", { type: "button", title: "Every one of their shockers stops now",
        onclick: () => W.shockers.forEach((c) => c.stop()) }, "Stop all"));
    }
    W.strip = el("div.shock-state", { title: "Armed: their shocks are real. Not armed: a shock arrives as a "
      + "vibration. Paused or Off: nothing reaches them until they switch it back. Every strength and length "
      + "here is a part of their own caps - you can't go past them." },
      el("b.state-h"), el("span.state-r"));
    sh.body.append(W.strip);
    if (!st.shockers.length) {
      sh.body.append(el("p.small", {}, "They allow you their shockers, but none is connected right now."));
    } else {
      if (st.shockers.length > 1) {
        W.party = new ShockParty({
          onFire: partyShock, onHold: (s, op, it) => hold(s, op, it), onRelease: release, onStop: stop,
          onTicks: (ticked) => partyTicked(ticked),
        });
        W.party.setTargets(st.shockers.map((n, i) => [i, `${i + 1} · ${n}`]), S.partyTicked);
        if (S.partyMemory) W.party.restore(S.partyMemory);
        W.party.root.hidden = !S.partyTicked.size;
        sh.body.append(W.party.root);
      }
      st.shockers.forEach((n, i) => {
        const card = new ShockerCard(`${i + 1} · ${n}`, {
          onFire: (op, it, len, wms, wi) => shock([i], it, len, op, wms, wi),
          onHold: (op, it) => hold([i], op, it), onRelease: () => release([i]), onStop: () => stop([i]),
        }, { partyBox: Boolean(W.party) });
        card.setCaps(capsOf(i), st.maxHoldS);
        if (S.shockMemory[i]) card.restore(S.shockMemory[i]);
        if (card.partyBox) {
          card.partyBox.checked = S.partyTicked.has(i);
          card.partyBox.onchange = () => {
            const ticked = new Set(S.partyTicked);
            if (card.partyBox.checked) ticked.add(i); else ticked.delete(i);
            W.party.setTicked(ticked);
            partyTicked(ticked);
          };
        }
        W.shockers.push(card);
      });
      sh.body.append(el("div.grid.wide", {}, W.shockers.map((c) => c.root)));
    }
  }

  // their avatar
  if (st.prm) {
    const av = section("THEIR AVATAR", "green", "params");
    W.board = new Board({ onSet: paramSet, onHold: paramHold, onSetAny: paramSetAny });
    W.board.onFold = () => { S.yoloOpen = W.board.yoloOpen; update(); };
    av.head.append(W.board.note);
    av.body.append(W.board.root);
    panel.append(av.box);
  }
}

function partyTicked(ticked) {
  S.partyTicked = new Set(ticked);
  W.shockers.forEach((card, i) => { if (card.partyBox) card.partyBox.checked = ticked.has(i); });
  if (W.party) {
    if (!ticked.size) W.party.release();
    W.party.root.hidden = !ticked.size;
  }
}

/** The live part: every tick and on every message. */
function update() {
  if (!linked) return;
  const m = median(rtts);
  const parts = [`Linked with ${theirNick || "your friend"}`, "through a relay"];
  if (m !== null) parts.push(`${Math.round(m)} ms round trip`);
  setState("ok", parts.join(" · "));
  const others = $("others");
  others.hidden = !S.others;
  others.textContent = `+${S.others} OTHER${S.others > 1 ? "S" : ""}`;
  const st = S.status;
  if (!st) return;
  const note = st.paused ? `${theirNick} paused all friends - nothing you send reaches them.`
    : st.off ? `${theirNick}'s Off is on - nothing you send reaches them.` : "";
  $("note").textContent = note;
  $("note").hidden = !note;
  if (W.strength && !W.strength.s.busy && now() - S.strengthT > 1000) {
    W.strength.s.setQuiet(Math.round(st.strength * 1000));
    W.strength.val.textContent = pct(st.strength);
  }
  const outs = st.outputs;
  for (const card of W.toys) {
    const out = card.toy === P.ALL ? Math.max(0, ...Object.values(outs)) : (outs[card.toy] || 0);
    card.setState(S.levels[card.toy] || 0, S.override.has(card.toy), S.patterns[card.toy], out);
    if (card.toy !== P.ALL) card.setBattery(st.batteries[card.toy]);
  }
  const blocked = st.paused || st.off;
  W.shockers.forEach((card, i) => { card.setCaps(capsOf(i), st.maxHoldS); card.setBlocked(blocked); });
  if (W.party) W.party.card.setBlocked(blocked);
  if (W.strip) {
    const [head, rest, tone] = st.paused ? ["Paused", "they paused all friends - nothing reaches them", ""]
      : st.off ? ["Off", "their Off is on - nothing reaches them", ""]
      : st.armed ? ["⚠  ARMED", "shocks are real", "armed"]
      : ["Not armed", "a shock arrives as a vibration", ""];
    W.strip.firstChild.textContent = head;
    W.strip.lastChild.textContent = `·  ${rest}`;
    W.strip.classList.toggle("armed", tone === "armed");
  }
  if (W.board) {
    const tb = theirBoard();
    if (tb) W.board.update(tb.prm, tb.board, tb.values);
  }
}

function stopAll() {
  for (const card of W.toys) card.pick("off");
  S.levels = {};
  S.patterns = {};
  panelChanged();
  for (const card of W.shockers) card.stop();
  flushCmd();
}

async function main() {
  if (!target) {
    $("broken").hidden = false;
    return;
  }
  $("ok").hidden = false;
  $("who").textContent = theirNick || "A friend";
  $("nick").value = store(NICK_STORE) || "";
  $("stop").addEventListener("click", stopAll);
  document.addEventListener("visibilitychange", () => { if (linked) tick(); });
  window.addEventListener("pagehide", () => { if (link) link.close(0, "bye"); });
  setInterval(() => W.toys.forEach((c) => c.tick()), 33);
  $("go").addEventListener("submit", async (e) => {
    e.preventDefault();
    store(NICK_STORE, myNick());
    $("go").hidden = true;
    $("me").textContent = `You're ${myNick()}`;
    setState("connecting", "Starting…");
    try {
      await init();
      guest = await Guest.spawn(loadKey());
      log(`this browser is ${guest.id().slice(0, 8)}`);
    } catch (err) {
      setState("bad", `This browser can't run the remote (${err.message || err}).`);
      return;
    }
    run();
  });
  // for checks from the console: what the page knows
  window.ogpRemote = {
    get linked() { return linked; },
    get rtts() { return [...rtts]; },
    get state() { return S; },
    get widgets() { return W; },
    get id() { return guest ? guest.id() : ""; },
    set(toy, v) { setLevel(toy, v); },
  };
}

main();
