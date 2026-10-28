// The web remote: someone without OGP drives your toys from a browser.
//
// The page opens your web remote link (remote.html#<id>.<code>.<nick>,
// src/friend_links.py), dials that OGP over iroh -- compiled to WebAssembly
// in tools/web_guest, relay-only because a browser can't send UDP -- and
// speaks src/remote_protocol.py as a Friends client: a hello with ``web``
// and the link's code, ``lw`` while the panel shows, ``cmd`` levels, ping /
// pong. The OGP lets it in as a web guest (src/controllers/friends_web.py):
// toys only, plain levels, and every friend rule holds there (strength, Off,
// output band, Pause all friends, zero when our cmds stop, logged).
//
// The browser keeps its own key (localStorage), so it is the same web guest
// next time -- and a kicked one stays kicked until that storage is cleared.

import init, { Guest } from "./web_guest/ogp_web_guest.js";

const ALPN = "ogp/friends/1";
const PROTOCOL_VERSION = 2;
const SEND_MS = 250;        // remote_session.SEND_S
const PING_MS = 5000;       // remote_session.PING_S
const DEAD_MS = 16000;      // remote_session.DEAD_S
const HELLO_MS = 60000;     // remote_session.HELLO_S
const WATCH_MS = 10000;     // an lw repeats this often
const CMD_HZ = 60;          // remote_session.CMD_HZ
const REPEATS = 2;          // a change goes out 1 + REPEATS times
const ALL = "*";            // remote_protocol.ALL_TOYS
const NICK_MAX = 24;
const KEY_STORE = "ogp-web-remote-key";
const NICK_STORE = "ogp-web-remote-nick";
const RETRY_MS = [1000, 2000, 5000, 10000, 30000];

const enc = new TextEncoder();
const dec = new TextDecoder();
const $ = (id) => document.getElementById(id);

const target = parseHash(location.hash);
let guest = null;
let link = null;
let linked = false;
let ended = "";             // why the last link ended, for the status line
let stopped = false;
let theirNick = target ? target.nick : "";
let status = null;          // their last st
let others = [];
const levels = {};          // toy name (or ALL) -> 0..1
let lastTx = 0, lastRx = 0, lastCmd = 0, lastHello = 0, lastWatch = 0;
let cmdTimer = null;
let linkedAt = 0, tries = 0, helloCount = 0;
const rtts = [];

function parseHash(hash) {
  // <id>.<code>.<nick> -- the shape src/friend_links.py writes
  const parts = hash.replace(/^#/, "").split(".");
  const id = (parts[0] || "").toLowerCase();
  const code = (parts[1] || "").toLowerCase();
  let nick = "";
  try { nick = decodeURIComponent(parts.slice(2).join(".")); } catch (e) { nick = ""; }
  nick = cleanNick(nick);
  if (!/^[0-9a-f]{64}$/.test(id) || !/^[0-9a-f]{16}$/.test(code)) return null;
  return { id, code, nick };
}

function cleanNick(text) {
  return String(text || "").replace(/\s+/g, " ").replace(/[\u0000-\u001f\u007f]/g, "")
    .trim().slice(0, NICK_MAX);
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* private window: a new friend every visit */ }
  return null;
}

function loadKey() {
  const hex = store(KEY_STORE) || "";
  if (/^[0-9a-f]{64}$/.test(hex)) return Uint8Array.from(hex.match(/../g), (b) => parseInt(b, 16));
  const key = crypto.getRandomValues(new Uint8Array(32));
  store(KEY_STORE, Array.from(key, (b) => b.toString(16).padStart(2, "0")).join(""));
  return key;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = () => performance.now();

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

function sendRepeated(msg) {
  for (let i = 0; i <= REPEATS; i++) setTimeout(() => send(msg), 30 * i);
}

function hello() {
  const msg = { t: "hello", nick: myNick(), v: PROTOCOL_VERSION, ask: 1, web: 1 };
  if (target.code) msg.invite = target.code;
  return msg;
}

function cmd() {
  const lvl = {};
  for (const [toy, v] of Object.entries(levels)) {
    if (v > 0) lvl[toy] = Math.round(v * 1000) / 1000;
  }
  // ts: when this left the browser, for tools/web_guest/test_host.py's
  // latency check; OGP ignores it.
  return { t: "cmd", lvl, ts: Date.now() };
}

function drives() {
  return Object.values(levels).some((v) => v > 0);
}

function pushCmd() {
  if (!linked || cmdTimer) return;
  const wait = lastCmd + 1000 / CMD_HZ - now();
  if (wait <= 0) flushCmd();
  else cmdTimer = setTimeout(() => { cmdTimer = null; flushCmd(); }, wait);
}

function flushCmd() {
  lastCmd = now();
  if (drives()) send(cmd());
  else sendRepeated(cmd());       // letting go must arrive
}

function watch(on) {
  sendRepeated(on ? { t: "lw", on: 1 } : { t: "lw" });
  lastWatch = now();
}

// --- the link ----------------------------------------------------------------------

async function run() {
  while (!stopped) {
    setState("connecting", `Connecting to ${theirNick || "your friend"}…`);
    const t0 = now();
    try {
      link = await guest.connect(target.id, ALPN);
      log(`connected in ${Math.round(now() - t0)} ms`);
      ended = await session(link);
    } catch (e) {
      ended = String(e.message || e);
      log(`no link: ${ended}`);
    }
    link = null;
    linked = false;
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
    const wait = RETRY_MS[Math.min(tries++, RETRY_MS.length - 1)];
    await sleep(wait);
  }
}

async function session(l) {
  lastRx = now();
  helloCount = 0;
  send(hello());
  const ticker = setInterval(tick, SEND_MS);
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
    if (drives()) send(cmd());     // a drive has to keep arriving (DRIVE_STALE_S)
    if (document.visibilityState === "visible" && t - lastWatch >= WATCH_MS) watch(true);
    if (t - lastHello >= HELLO_MS) { lastHello = t; send(hello()); }
  }
  if (t - lastTx >= PING_MS) send({ t: "ping", n: Math.round(t * 1000) });
  if (t - lastRx > DEAD_MS && link) link.close(2, "timeout");
  renderLink();
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
      theirNick = cleanNick(msg.nick) || theirNick;
      if (!linked) {
        linked = true;
        tries = 0;
        linkedAt = now();
        log(`linked with ${theirNick}`);
        watch(document.visibilityState === "visible");
        // a ping right away, for the round trip on the status line
        send({ t: "ping", n: Math.round(now() * 1000) });
      }
      render();
      break;
    case "st":
      status = msg;
      render();
      break;
    case "oth":
      others = Array.isArray(msg.n) ? msg.n.map(cleanNick).filter(Boolean) : [];
      renderLink();
      break;
    default:
      break;
  }
}

// --- the page ----------------------------------------------------------------------

function myNick() {
  return cleanNick($("nick").value) || "Web guest";
}

function setState(kind, text) {
  const el = $("state");
  el.className = `state ${kind}`;
  el.textContent = text;
}

function log(line) {
  const el = document.createElement("div");
  el.textContent = `${new Date().toTimeString().substring(0, 8)}  ${line}`;
  $("log").prepend(el);
  while ($("log").childElementCount > 40) $("log").lastChild.remove();
}

function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

function renderLink() {
  if (!linked) return;
  const m = median(rtts);
  const parts = [`Linked with ${theirNick || "your friend"}`, "through a relay"];
  if (m !== null) parts.push(`${Math.round(m)} ms round trip`);
  if (others.length) parts.push(`+${others.length} other${others.length > 1 ? "s" : ""}`);
  setState("ok", parts.join(" · "));
  $("state").title = others.length ? `Also driving: ${others.join(", ")}` : "";
}

function render() {
  $("who").textContent = theirNick || "A friend";
  document.title = `${theirNick || "A friend"}'s toys - OscGoesPurrr`;
  $("panel").hidden = !linked;
  if (!linked) {
    if (ended && !stopped) setState("connecting", `Link lost (${ended.slice(0, 60)}) - trying again…`);
    return;
  }
  renderLink();
  const st = status || {};
  const toys = Array.isArray(st.toys) ? st.toys.filter((t) => Array.isArray(t)).map((t) => String(t[0])) : [];
  const allow = st.allow && typeof st.allow === "object" ? st.allow : {};
  let note = "";
  if (status && !allow.toys) note = `${theirNick} has your Toys switched off.`;
  else if (st.pause) note = `${theirNick} paused all friends.`;
  else if (st.off) note = `${theirNick}'s toys are Off.`;
  else if (status && !toys.length) note = `${theirNick} has no toy connected.`;
  $("note").textContent = note;
  $("note").hidden = !note;
  const strength = Number(st.str);
  $("strength").textContent = Number.isFinite(strength) ? `Their strength ${Math.round(strength * 100)} %` : "";

  const list = $("toys");
  const want = [ALL, ...toys];
  const have = Array.from(list.children).map((c) => c.dataset.toy);
  if (want.join("\n") !== have.join("\n")) {
    list.replaceChildren(...want.map(toyRow));
  }
  const out = st.out && typeof st.out === "object" ? st.out : {};
  for (const row of list.children) {
    const toy = row.dataset.toy;
    const live = toy === ALL ? null : Number(out[toy]);
    const bar = row.querySelector(".live > span");
    if (bar) bar.style.width = `${Math.round(Math.max(0, Math.min(1, live || 0)) * 100)}%`;
    row.classList.toggle("off", !allow.toys);
    row.querySelector("input").disabled = !allow.toys;
  }
}

function toyRow(toy) {
  const row = document.createElement("div");
  row.className = toy === ALL ? "toy all" : "toy";
  row.dataset.toy = toy;
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = toy === ALL ? "All toys" : toy;
  const value = document.createElement("div");
  value.className = "value";
  const input = document.createElement("input");
  input.type = "range";
  input.min = "0";
  input.max = "100";
  input.step = "1";
  input.value = String(Math.round((levels[toy] || 0) * 100));
  input.setAttribute("aria-label", `${name.textContent} level`);
  const show = () => {
    value.textContent = `${input.value} %`;
    input.style.setProperty("--v", `${input.value}%`);
  };
  input.addEventListener("input", () => {
    levels[toy] = Number(input.value) / 100;
    show();
    pushCmd();
  });
  show();
  row.append(name, value, input);
  if (toy !== ALL) {
    const live = document.createElement("div");
    live.className = "live";
    live.title = "What the toy plays now";
    live.append(document.createElement("span"));
    row.append(live);
  }
  return row;
}

function stopAll() {
  for (const toy of Object.keys(levels)) levels[toy] = 0;
  for (const input of document.querySelectorAll("#toys input")) {
    input.value = "0";
    input.dispatchEvent(new Event("input"));
  }
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
  document.addEventListener("visibilitychange", () => {
    if (linked) watch(document.visibilityState === "visible");
  });
  window.addEventListener("pagehide", () => {
    if (link) link.close(0, "bye");
  });
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
  // for the prototype's checks: what the page knows, read from the console
  window.ogpRemote = {
    get linked() { return linked; },
    get rtts() { return [...rtts]; },
    get status() { return status; },
    get id() { return guest ? guest.id() : ""; },
    since() { return linked ? now() - linkedAt : 0; },
    set(toy, v) { levels[toy] = v; pushCmd(); },
  };
}

main();
