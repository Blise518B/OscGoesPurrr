// The demo window's Friends page (src/ui/views/friends.py, friends_list.py,
// friends_panel.py, friends_account.py): you and your friends with what each
// may do, each friend's VRChat account, who is in your VRChat instance,
// groups, and the picked one's panel -- built from the web remote's own
// pieces (remote-toys.js, remote-shockers.js, remote-board.js), which are
// 1-to-1 with the app's panel.
//
// Your own row is the app's "Me": a friend who may do everything, over a
// local loop. Its panel drives the demo's real toys -- through the engine's
// friend hook (demo.js setDrive: your strength, Off and each toy's output
// band hold) -- fires the Shockers page's shockers and sets the avatar on My
// Avatar Remote. A demo friend's panel works on screen; nobody is at the
// other end, so what their toys do is your level at their strength, and a
// friend who shows offline never answers a check. VRChat's log is faked: the
// same three people are always in your instance.

import { el, identity, toggle, hslider, segmented, pct } from "./remote-ui.js";
import { ToyCard } from "./remote-toys.js";
import { ShockerCard, ShockParty } from "./remote-shockers.js";
import { Board } from "./remote-board.js";
import { SHOCK, capsOf, fire, release, timingOf } from "./demo-shockers.js";
import { AVATAR } from "./demo-avatar.js";
import { LOG, personLog } from "./demo-log.js";

const D = window.OGPDemo;
const P = window.OGPRemoteProto;

// Mika's avatar, as their OGP would send it (the app's friends demo)
const MIKA_BOARD = {
  ver: "basev7-1", name: "Base V7", avatar: "", keys: [], all: null,
  categories: [{ id: "o", name: "Outfit", color: "green", locked: false }, { id: "s", name: "Shader", color: "blue", locked: false },
               { id: "h", name: "Haptics", color: "red", locked: false }, { id: "l", name: "Locomotion", color: "amber", locked: true }],
  controls: [
    { id: "halo", cat: "o", label: "BinaryHaloOff", param: "BinaryHaloOff", ptype: "Bool", kind: "toggle" },
    { id: "jacket", cat: "o", label: "JacketOff", param: "JacketOff", ptype: "Bool", kind: "toggle" },
    { id: "o1", cat: "o", label: "Outfit 1", param: "Outfit", ptype: "Int", kind: "toggle", on: 1, off: 0 },
    { id: "o2", cat: "o", label: "Outfit 2", param: "Outfit", ptype: "Int", kind: "toggle", on: 2, off: 0 },
    { id: "bright", cat: "s", label: "MaxBrightness", param: "MaxBrightness", ptype: "Float", kind: "slider", min: 0, max: 1 },
    { id: "outline", cat: "s", label: "OutlineThickness", param: "OutlineThickness", ptype: "Float", kind: "slider", min: 0, max: 1 },
    { id: "audio", cat: "s", label: "AudioLinkOff", param: "AudioLinkOff", ptype: "Bool", kind: "toggle" },
    { id: "hap", cat: "h", label: "518H_HapticsOff", param: "518H_HapticsOff", ptype: "Bool", kind: "toggle" },
    { id: "wave", cat: "h", label: "Wave", param: "Emote", ptype: "Int", kind: "button", on: 3, off: 0 },
    { id: "crouch", cat: "l", label: "CrouchIdle", param: "CrouchIdle", ptype: "Int", kind: "int", min: 0, max: 10 },
    { id: "prone", cat: "l", label: "ProneIdle", param: "ProneIdle", ptype: "Int", kind: "int", min: 0, max: 10 },
  ],
};

// What each friend allows you (theirs) and you them (allow: the list's boxes);
// vrc: the VRChat account a friend is linked to (VRChat's log says who is in
// your instance: INSTANCE)
const FRIENDS = [
  { id: "me", nick: "Blise", hue: "cyan", me: true },
  { id: "web", nick: "Web remote", web: true, guests: ["Sam"], allow: { toys: true, shock: false, params: false }, anyway: false },
  { id: "mika", nick: "Mika", hue: "blue", rtt: 18, path: "direct", others: ["Sam"], allow: { toys: true, shock: true, params: true },
    vrc: "MikaPaws", anywhere: false,
    theirs: { strength: 0.8, toys: [["Lovense Lush 3", 90], ["Lovense Hush 2", 65]], shockers: [["Collar", [40, 40, 3000]]],
              armed: false, holdS: 10, board: MIKA_BOARD,
              values: { BinaryHaloOff: true, JacketOff: false, Outfit: 1, MaxBrightness: 1, OutlineThickness: 0.5,
                        AudioLinkOff: false, "518H_HapticsOff": false, Emote: 0, CrouchIdle: 5, ProneIdle: 2 } } },
  { id: "kiko", nick: "Kiko", hue: "purple", rtt: 64, path: "relay", allow: { toys: true, shock: false, params: true },
    vrc: "", anywhere: false,
    theirs: { strength: 1, toys: [["We-Vibe Sync", 72]], shockers: null, board: null } },
  // Nova has switched Shock off on their Leg: your panel greys it, and says why
  { id: "nova", nick: "Nova", hue: "cyan", rtt: 31, path: "direct", allow: { toys: true, shock: true, params: false },
    vrc: "", anywhere: false,
    theirs: { strength: 0.6, toys: [["Lovense Gush 2", 58]], shockers: [["Collar", [30, 50, 2000]], ["Leg", [50, 60, 1500]]],
              shockerOps: [["shock", "vibrate", "beep"], ["vibrate", "beep"]], shockerOff: [[], ["shock"]],
              armed: true, holdS: 8, board: null } },
  { id: "rin", nick: "Rin", hue: "blue", offline: true, allow: { toys: true, shock: true, params: true }, vrc: "", anywhere: false },
];
const GROUPS = [{ id: "g1", nick: "Night crew", group: true, members: ["mika", "kiko", "nova"] },
                { id: "g2", nick: "Pair", group: true, members: ["mika", "nova"] }];
const COLS = [["toys", "pink"], ["shock", "yellow"], ["params", "accent"]];
// Who VRChat's log says is in your instance now
const INSTANCE = ["MikaPaws", "Juno", "Pixelfox"];
const CHECK_GAP_S = 10;          // remote_link: one look per friend per 10 s
const CHECK_SHOW_S = 2;          // nobody answers in the demo: checking… then offline

const S = { picked: "mika", online: true, paused: false, panels: {}, rows: {}, log: null, logMode: 0,
            vrcLog: true, instanceOnly: false, checks: {} };
const byId = (id) => FRIENDS.find((f) => f.id === id) || GROUPS.find((g) => g.id === id);
const DRAG = "text/x-ogp-friend";   // a friend's row, dragged into a group
const DRAG_VRC = "text/x-ogp-vrchat";   // someone in your instance, dragged onto a friend's row
// A group row's count, as the app's (friends_list._members_text)
function membersText(members) {
  const n = members.filter((m) => m !== "me").length;
  const friends = `${n} friend${n === 1 ? "" : "s"}`;
  if (!members.includes("me")) return friends;
  return n ? `you + ${friends}` : "just you";
}
function joinGroup(g, id) {
  const f = byId(id);
  if (!f || f.group || f.web || g.members.includes(id)) return;
  g.members.push(id);
  log(`${f.me ? "You (Me)" : f.nick} joins ${g.nick}`);
  render();
}
// A group's row and its members box take a friend's row dropped on them
function dropTarget(node, g) {
  node.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes(DRAG)) return;
    e.preventDefault();
    node.classList.add("drop");
  });
  node.addEventListener("dragleave", () => node.classList.remove("drop"));
  node.addEventListener("drop", (e) => {
    node.classList.remove("drop");
    if (!e.dataTransfer.types.includes(DRAG)) return;
    e.preventDefault();
    joinGroup(g, e.dataTransfer.getData(DRAG));
  });
}
// A friend's row (and their VRChat account box) take someone from your
// instance dropped on them: linked (one account per friend)
function vrcTarget(node, f) {
  node.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes(DRAG_VRC)) return;
    e.preventDefault();
    node.classList.add("drop");
  });
  node.addEventListener("dragleave", () => node.classList.remove("drop"));
  node.addEventListener("drop", (e) => {
    node.classList.remove("drop");
    if (!e.dataTransfer.types.includes(DRAG_VRC)) return;
    e.preventDefault();
    link(f, e.dataTransfer.getData(DRAG_VRC));
  });
}
function link(f, name) {
  for (const o of FRIENDS) if (o.vrc === name) o.vrc = "";
  f.vrc = name;
  log(`You linked ${f.nick} to their VRChat account`);
  render();
}
const hhmmss = (t) => new Date(t * 1000).toTimeString().slice(0, 8);

/** One line in the log, kept in the demo's log (demo-log.js) with who it was
 *  about: the Friends page shows everyone's but your avatar's, the Log page
 *  everything. */
function log(line, meta = {}) {
  LOG.add({ who: "you", name: "You", role: "you", kind: "settings", op: "", text: line, ...meta });
}
const about = (f, kind, op = "") => ({ who: f.id, name: f.nick, role: "friend", kind, op });
const ME = (kind, op = "") => ({ who: "me", name: "You (Me)", role: "me", kind, op });

function hued(node, hue) {
  node.style.setProperty("--hue", `var(--${hue})`);
  node.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
  node.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
  return node;
}
function icon(name) { const i = el("i.fr-ic"); i.innerHTML = D.icons[name] || ""; return i; }
function pill(text, tone, title) { return el(`span.pg-pill.${tone}`, { title }, text); }
function section(title, hue, what) {
  const head = el("div.section-h", {}, identity(what, 15), el("span.micro", {}, title), el("span.grow"));
  const body = el("div.section-b");
  const box = el("section.friend-section", {}, head, body);
  box.style.setProperty("--hue", `var(--${hue})`);
  box.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
  return { box, head, body };
}
function notInDemo(btn, label, says = "Not in the demo - the app copies a link here") {
  btn.onclick = () => { btn.textContent = says; setTimeout(() => { btn.textContent = label; }, 1800); };
  return btn;
}

// ---- only friends in my instance (friends_account.py) -------------------------

const here = (f) => Boolean(S.vrcLog && f.vrc && INSTANCE.includes(f.vrc));
/** Is this friend held back by Only friends in my instance? */
const notHere = (f) => S.instanceOnly && !f.me && !f.web && !f.group && !here(f) && !f.anywhere;
/** The line under Only friends in my instance (friends_account.instance_line). */
function instanceLine() {
  const friends = FRIENDS.filter((f) => !f.me && !f.web);
  const may = friends.filter((f) => !notHere(f)).length;
  const anywhere = friends.filter((f) => f.anywhere).length;
  if (S.vrcLog) return `Only friends in your instance can drive you - ${may} of ${friends.length} can right now.`;
  const why = "Read VRChat's log is off, so nobody is seen in your instance";
  if (anywhere) return `${why}: only ${anywhere === 1 ? "the friend" : `the ${anywhere} friends`} allowed from anywhere can drive you.`;
  return `${why}: no friend can drive you.`;
}

// ---- check whether a friend is online, now (friends_list.py) ------------------

function check(ids) {
  const now = performance.now() / 1000;
  for (const id of ids) {
    const c = S.checks[id];
    if (c && now < c.wait) continue;                     // at most once every CHECK_GAP_S
    S.checks[id] = { until: now + CHECK_SHOW_S, wait: now + CHECK_GAP_S };
  }
  paintRows();
}
const checking = (f) => { const c = S.checks[f.id]; return Boolean(c && performance.now() / 1000 < c.until); };
const checkReady = (f) => { const c = S.checks[f.id]; return !c || performance.now() / 1000 >= c.wait; };
const showsOffline = (f) => !f.me && !f.web && !f.group && (f.offline || !S.online);

// ---- the list ------------------------------------------------------------------

const W = { box: null, checkAll: null, instance: null, logView: null, people: null };

function listCard() {
  // a header with its own +/- box, the fold hanging from it: one card
  // while open (the app's friends_list.py)
  const sign = el("span.fr-sign", {}, "+");
  const add = el("button.fr-addhead", { type: "button" }, sign, el("span", {}, "Add a friend (they need OGP too)"));
  const fold = el("div.fr-fold", { hidden: true },
    el("div.fr-micro", {}, "SEND AN INVITE LINK"),
    segmented(["Once", "1 day", "1 week", "No end"], "accent", () => {}, 0),
    el("p.pg-note", {}, "Works once - the first friend who clicks it, within a day."),
    el("div.pg-row", {}, notInDemo(el("button.pg-btn.grow", { type: "button" }, "Copy invite link"), "Copy invite link"),
      el("button.pg-btn.icon", { type: "button", title: "Close your invite links, or get a new ID" }, "⋯")),
    el("div.pg-row", {}, el("span.pg-mono.grow", {}, "Your ID: b115e518…"), el("button.pg-btn.ghost", { type: "button" }, "Copy")),
    el("div.fr-micro", {}, "GOT THEIR LINK OR ID?"),
    el("div.pg-row", {}, el("input.pg-filter.grow", { type: "text", placeholder: "invite link or ID" }),
      el("button.pg-btn.primary", { type: "button" }, "Add")),
    el("p.pg-note", {}, "An invite link links you at once; with a bare ID they click Accept in their OGP."));
  const showAdd = () => { sign.textContent = fold.hidden ? "+" : "−"; add.classList.toggle("open", !fold.hidden); };
  add.onclick = () => { fold.hidden = !fold.hidden; showAdd(); };
  showAdd();
  const web = notInDemo(el("button.pg-btn.wide", { type: "button" }, "Copy web remote link (no OGP needed)"),
                        "Copy web remote link (no OGP needed)");
  const onlinePill = pill("ONLINE", "ok");
  const online = toggle("Online", true, (on) => { S.online = on; onlinePill.textContent = on ? "ONLINE" : "OFFLINE";
                                                 onlinePill.className = `pg-pill ${on ? "ok" : "idle"}`; render(); });
  const pause = toggle("Pause all", false, (on) => { S.paused = on; log(on ? "You paused all friends" : "You let your friends back in"); });
  // Sync with others: yours alone to choose (the app's friends_list.py)
  const sync = toggle("Sync friends", true, (on) => log(on ? "Everyone driving your toys shares one set of toy cards"
    : "Everyone driving your toys drives on their own"),
    "On: everyone driving your toys shares one set of toy cards - friends, the web remote and you (Me). When one of "
    + "them moves a level, starts an auto mode or picks Override, it moves on everyone's cards, and your toys play that "
    + "one change (the newest wins). Off: each drives on their own - their cards are just theirs, and your toys follow "
    + "whichever of them is higher. Yours alone to choose: their panels say SYNCED or SEPARATE beside +1 OTHER and "
    + "can't change it. On by default.");
  const heads = el("div.fr-heads", {}, COLS.map(([what]) => {
    const h = el("span.fr-head", { title: "Set this column for every friend: off first while anyone has it" }, icon(what));
    h.onclick = () => {
      const anyOn = FRIENDS.some((f) => f.allow && f.allow[what]);
      FRIENDS.forEach((f) => { if (f.allow) f.allow[what] = !anyOn; });
      render();
    };
    return h;
  }));
  W.checkAll = el("button.fr-checkall", { type: "button", title: "Looks for every friend who shows offline right now, one after the "
    + "other, instead of waiting for OGP's next look in the background. Each friend is looked for at most once every 10 seconds.",
    onclick: () => check(FRIENDS.filter(showsOffline).map((f) => f.id)) }, "↻ Check all");
  const rows = el("div.fr-rows", {}, FRIENDS.map(friendRow));
  const groups = el("div.fr-rows", {}, GROUPS.map(friendRow));
  return el("div.o-card.pg-card.fr-list", {},
    el("div.pg-row", {}, el("span.o-in.grow.fr-nick", {}, "Blise"), onlinePill),
    el("div.pg-row", {}, online, el("span.grow"), pause),
    el("div.pg-row", {}, el("span.grow"), sync),
    el("div.fr-addcard", {}, add, fold), web,
    el("div.pg-row.fr-sect", {}, el("span.fr-micro", {}, "FRIENDS"), W.checkAll, el("span.grow"), heads),
    rows, instanceSection(),
    el("div.pg-row.fr-sect", {}, el("span.fr-micro", {}, "GROUPS"), el("span.grow"), el("button.pg-link", { type: "button" }, "+ Group")),
    groups);
}

/** Under the friends: VRChat's log, Only friends in my instance, and the
 *  people in your instance to drag onto a friend (friends_account.py). */
function instanceSection() {
  const logSw = toggle("Read VRChat's log", S.vrcLog, (on) => {
    S.vrcLog = on;
    render();
  }, "On: OGP reads who's in your VRChat instance from VRChat's own log on this PC, so you can link a friend to their "
    + "VRChat account and see when they're with you. Nothing leaves this PC. Switched off while Only friends in my "
    + "instance is on, nobody can drive you.");
  const onlySw = toggle("Only friends in my instance", S.instanceOnly, (on) => {
    S.instanceOnly = on;
    if (on && !S.vrcLog) { S.vrcLog = true; logSw.set(true); }     // it needs the log
    log(on ? "You switched on Only friends in my instance" : "You switched off Only friends in my instance");
    render();
  }, "On: only friends who are in your VRChat instance right now can drive you - toys, shockers and your avatar - "
    + "plus anyone you allow from anywhere. Switching it on switches on Read VRChat's log. Only your own log decides: "
    + "nothing new is sent to anyone.");
  const line = el("p.pg-note.fr-instline");
  const chips = el("div.fr-vrcchips");
  const hint = el("p.pg-note.fr-small");
  W.instance = { logSw, onlySw, line, chips, hint };
  return el("div.fr-inst", {},
    el("div.pg-row.fr-sect", {}, el("span.fr-micro", {}, "IN YOUR VRCHAT INSTANCE"), el("span.grow"), logSw),
    el("div.pg-row", {}, el("span.grow"), onlySw), line, chips, hint);
}

function paintInstance() {
  const w = W.instance;
  w.logSw.set(S.vrcLog);
  w.onlySw.set(S.instanceOnly);
  w.line.hidden = !S.instanceOnly;
  w.line.textContent = instanceLine();
  w.chips.hidden = !S.vrcLog;
  w.chips.replaceChildren(...INSTANCE.map((name) => {
    const owner = FRIENDS.find((f) => f.vrc === name);
    const chip = el("span.fr-vchip", { draggable: "true", title: owner ? `Linked to ${owner.nick} - drag onto another friend to link them instead`
      : "Drag onto a friend's row to link them to this VRChat account" }, name);
    if (owner) hued(chip, owner.hue).classList.add("linked");
    chip.addEventListener("dragstart", (e) => { e.dataTransfer.setData(DRAG_VRC, name); e.dataTransfer.effectAllowed = "link"; });
    return chip;
  }));
  w.hint.textContent = S.vrcLog ? "Drag someone onto a friend's row to link them to that VRChat account."
    : "Off. On, the people in your VRChat instance show up here and you drag one onto a friend to link them. Read from "
      + "VRChat's log on this PC; nothing leaves it.";
}

function friendRow(f) {
  const mark = f.web ? icon("web") : hued(el("span.fr-av", {}, f.nick[0]), f.group ? "accent" : f.hue);
  const meta = el("span.fr-meta");
  const boxes = el("span.fr-boxes", {}, f.allow && !f.group ? COLS.map(([what, hue]) => {
    const ck = hued(el("input.ck", { type: "checkbox", checked: f.allow[what] }), hue);
    ck.onclick = (e) => { e.stopPropagation(); f.allow[what] = ck.checked; render(); };
    return ck;
  }) : []);
  const sub = f.group ? el("span.fr-sub", {}, ` ${membersText(f.members)}`) : null;
  const name = el("span.fr-name", {}, f.me ? `${f.nick} (you)` : f.nick, sub || "");
  // a friend who shows offline: look for them now
  const chk = el("button.fr-check", { type: "button", hidden: true, onclick: (e) => { e.stopPropagation(); check([f.id]); } }, "↻");
  // the second line: their VRChat account, and whether they're with you
  const vrc = el("div.fr-vrcline", { hidden: true }, el("span.fr-vname"), el("span.fr-vtag"));
  // the web remote while only friends in your instance may drive you: a
  // browser can never be in it
  const webNh = f.web ? el("span.fr-vtag.warn", { hidden: true, title: "Only friends in your VRChat instance can drive you right now, "
    + "and a browser can't be in one - your web remote is blocked. Allow the web remote anyway is on its panel." }, "not here") : null;
  const row = hued(el("div.fr-row", { onclick: () => { S.picked = f.id; render(); } },
    el("div.fr-line", {}, mark, name, webNh || "", el("span.grow"), meta, chk, boxes), vrc), f.hue || "accent");
  if (f.group) {
    row.title = "Drag a friend here to add them; right-click to rename or delete";
    dropTarget(row, f);
  } else if (!f.web) {
    // yours too: a group with you and a friend drives both of you
    row.draggable = true;
    row.addEventListener("dragstart", (e) => { e.dataTransfer.setData(DRAG, f.id); e.dataTransfer.effectAllowed = "copy"; });
    if (!f.me) vrcTarget(row, f);
  }
  S.rows[f.id] = { row, meta, boxes, f, sub, chk, vrc, webNh };
  return row;
}

function paintRows() {
  let anyOffline = false, anyChecking = false, anyReady = false;
  for (const { row, meta, boxes, f, sub, chk, vrc, webNh } of Object.values(S.rows)) {
    if (webNh) webNh.hidden = !(S.instanceOnly && !f.anyway);
    row.classList.toggle("on", f.id === S.picked);
    if (sub) sub.textContent = ` ${membersText(f.members)}`;
    let text = "", tone = "";
    const off = showsOffline(f), busy = off && checking(f);
    if (f.me) { text = "this PC"; tone = "ok"; }
    else if (f.web) { text = `${f.guests.length} on`; tone = "ok"; }
    else if (f.group) text = "";
    else if (off) { text = busy ? "checking…" : "offline"; }
    else { text = `${f.rtt} ms`; tone = "ok"; }
    if (off && S.online) { anyOffline = true; anyChecking ||= busy; anyReady ||= checkReady(f); }
    meta.textContent = text;
    meta.className = `fr-meta ${tone}`;
    chk.hidden = !(off && S.online && !busy);
    chk.disabled = !checkReady(f);
    chk.title = checkReady(f) ? "Check now: looks for this friend right now instead of waiting for OGP's next look in the background."
      : "Check now: looked moments ago - you can look again in a few seconds.";
    if (f.allow) [...boxes.children].forEach((ck, i) => { ck.checked = f.allow[COLS[i][0]]; });
    // the second line (friends_account.row_tag): their VRChat name and "in
    // your instance" -- or, while only friends in your instance may drive
    // you, why they can't
    if (!f.me && !f.web && !f.group) {
      const [vname, vtag] = vrc.children;
      const nh = notHere(f);
      vname.textContent = f.vrc || "";
      vtag.textContent = nh ? (f.vrc ? "not here" : "not here · link their VRChat account")
        : here(f) ? "in your instance" : S.instanceOnly && f.anywhere ? "from anywhere" : "";
      vtag.className = `fr-vtag ${nh ? "warn" : here(f) ? "ok" : ""}`;
      vrc.hidden = !vname.textContent && !vtag.textContent;
    }
  }
  W.checkAll.hidden = !anyOffline;
  W.checkAll.textContent = anyChecking ? "Checking…" : "↻ Check all";
  W.checkAll.disabled = anyChecking || !anyReady;
  paintInstance();
}

// ---- a panel ------------------------------------------------------------------

function panelHead(name, hue, ...pills) {
  return el("div.fp-head", {}, hued(el("span.fp-name", {}, name), hue), ...pills, el("span.grow"),
    el("button.pg-btn.fp-control", { type: "button", title: "The panel fills the window, everything big - for VR" }, "⤢  Control mode"),
    notInDemo(el("button.pg-btn.fp-control", { type: "button", title: "Pop out: this panel, big as in Control mode, in a window "
      + "of its own - for XSOverlay, OVR Toolkit or Desktop+ to show in VR. It follows whoever you pick here, can stay on top, "
      + "and closing it puts it back." }, "⧉  Pop out"), "⧉  Pop out", "Not in the demo - the app opens a window of its own"));
}

/** The friend's VRChat account: who they're linked to, Link / Change (a
 *  picker folding out in the panel), Unlink, and their Allow from anywhere
 *  while only friends in your instance may drive you. */
function accountBox(f) {
  const name = el("span.fr-vname.big"), tag = el("span.fr-vtag");
  const pick = el("button.pg-link", { type: "button" }, "Link…");
  const unlink = el("button.pg-link.muted", { type: "button", title: "Forgets which VRChat account this friend is. They stay your friend.",
    onclick: () => { f.vrc = ""; log(`You unlinked ${f.nick} from their VRChat account`); render(); } }, "Unlink");
  const anywhere = toggle("Allow from anywhere", f.anywhere, (on) => { f.anywhere = on; render(); },
    "On: this friend can drive you even when they aren't in your VRChat instance - the one exception to Only friends in "
    + "my instance. Off by default.");
  const picker = el("div.fr-vpick", { hidden: true });
  pick.onclick = () => {
    picker.hidden = !picker.hidden;
    picker.replaceChildren(el("span.fr-micro", {}, "IN YOUR INSTANCE"),
      el("div.fr-vrcchips", {}, S.vrcLog ? INSTANCE.map((n) => el("button.fr-vchip", { type: "button", onclick: () => { picker.hidden = true; link(f, n); } }, n))
        : el("span.pg-note", {}, "Who's in your instance shows here once \"Read VRChat's log\" is on, under your friends list.")),
      el("div.pg-row", {}, notInDemo(el("button.pg-btn", { type: "button" }, "Import from VRCX"), "Import from VRCX",
        "Not in the demo - the app reads VRCX's friend list")));
  };
  const box = el("div.fr-account", { title: "Which VRChat account this friend is, so OGP can tell when they're in your instance. "
    + "Pick it here, or drag someone from your instance onto here or onto their row. Kept on this PC by their VRChat user id, so a "
    + "new display name doesn't break it, and never sent to anyone." },
    el("div.pg-row.tight", {}, el("span.fr-micro", {}, "VRCHAT ACCOUNT"), name, tag, el("span.grow"), pick, unlink),
    el("div.pg-row", {}, anywhere), picker);
  vrcTarget(box, f);
  box.paint = () => {
    name.textContent = f.vrc;
    const nh = notHere(f);
    tag.textContent = nh ? "not here" : here(f) ? "in your instance" : "";
    tag.className = `fr-vtag ${nh ? "warn" : "ok"}`;
    pick.textContent = f.vrc ? "Change…" : "Link…";
    unlink.hidden = !f.vrc;
    anywhere.hidden = !S.instanceOnly;
    anywhere.set(f.anywhere);
  };
  box.paint();
  return box;
}

/** Their toys: a card per toy and one for all, as remote.js builds them. */
function toysSection(P_, toys, strength) {
  const sec = section("THEIR TOYS", "pink", "toys");
  const val = el("span.val", {}, pct(strength.get()));
  const s = hslider({ max: 1000, hue: "accent", value: Math.round(strength.get() * 1000),
                      onInput: (x) => { val.textContent = pct(x / 1000); strength.set(x / 1000); } });
  s.classList.add("strength");
  // read-only, while others drive them too: how they have Sync with others
  // (their call) -- in the toys' header, as the app has it
  const synced = P_.others ? pill("SYNCED", "idle", "Whether everyone driving them shares one set of toy cards - their choice, not yours. SYNCED: a level, an auto mode or Override one of you sets moves on everyone's cards, and their toys play that one change (the newest wins). SEPARATE: your cards are just yours, and their toys follow whichever of you is higher. Their strength slider is shared either way.") : "";
  sec.head.append(synced, el("span.strength-g", {}, el("span.small", {}, "Their strength"), s, val));
  const st = { levels: {}, override: new Set(), patterns: {}, cards: [], s, val, strength };
  // "All their toys" only for two toys or more; one toy's card is the
  // all-toys one underneath (the app's friends_panel.py)
  const keys = toys.length === 1 ? [[P.ALL, toys[0][0], toys[0][0]]]
    : [[P.ALL, "All their toys", P.ALL], ...toys.map(([n]) => [n, n, n])];
  for (const [key, title, shows] of keys) {
    const card = new ToyCard(key, title, {
      onLevel: (v) => { if (v > 0) st.levels[key] = v; else delete st.levels[key]; P_.onLevel && P_.onLevel(key, v); },
      onOverride: (on) => { if (on) st.override.add(key); else st.override.delete(key); },
      onPattern: (w, pd, lo, hi) => {
        const c = w ? P.cleanPattern(w, pd, lo, hi) : null;
        if (c) st.patterns[key] = c; else delete st.patterns[key];
        P_.onPattern && P_.onPattern(key, c);
      }, meter: shows !== P.ALL });
    const batt = toys.find(([n]) => n === shows);
    if (batt) card.setBattery(batt[1]);
    st.cards.push(card);
  }
  sec.body.append(el("div.grid", {}, st.cards.map((c) => c.root)));
  return { sec, st };
}
/** What a card plays now, the "all" card joining in (friends_receive). */
function playing(st, key) {
  const all = st.cards[0], card = st.cards.find((c) => c.toy === key);
  const lvl = Math.max(card ? card.sample() : 0, all.sample());
  const over = (card && card.over.picked === 1) || all.over.picked === 1;
  return [lvl, over];
}

/** [ops you may send, why, warning can play] on some of their shockers --
 *  or what any of them lets through (a party): remote.js rulesOf, on their
 *  status. */
function rulesOf(st, slots) {
  const ops = new Set();
  for (const slot of slots) for (const op of P.shockerOps(st, slot)) ops.add(op);
  const warnOk = !slots.length || slots.some((s) => P.canWarn(st, s));
  const why = warnOk ? {} : { warn: P.WARN_OFF_WHY };
  for (const op of P.OPS) {
    if (ops.has(op) || !slots.length) continue;
    const said = new Set(slots.map((s) => P.shockerWhy(st, s, op)).filter(Boolean));
    why[op] = said.size === 1 ? [...said][0] : `None of them lets you ${op}`;
  }
  return [ops, why, warnOk];
}

function shockSection(caps, holdS, label, onShock, onHold, onRelease, onStop) {
  const sec = section("THEIR SHOCKERS", "yellow", "shock");
  const strip = el("div.shock-state", { title: "Armed: their shocks are real. Not armed: a shock arrives as a vibration." },
    el("b"), el("span"));
  sec.body.append(strip);
  const n = caps().length, cards = [];
  let party = null;
  const ticked = new Set();
  if (n > 1) {
    sec.head.append(el("button.btn.danger.sm", { type: "button", onclick: () => cards.forEach((c) => c.stop()) }, "Stop all"));
    party = new ShockParty({
      onFire: (slots, op, it, lengthMs, wms, wi) => slots.forEach((slot) => {
        const top = Math.max(P.SHOCK_MIN_MS, caps()[slot][2]);
        const ms = Math.max(P.SHOCK_MIN_MS, Math.min(lengthMs, top));
        onShock(slot, it, top <= P.SHOCK_MIN_MS ? 0 : (ms - P.SHOCK_MIN_MS) / (top - P.SHOCK_MIN_MS), op, wms, wi);
      }),
      onHold: (slots, op, it) => slots.forEach((s) => onHold(s, op, it)),
      onRelease: (slots) => slots.forEach(onRelease), onStop: (slots) => slots.forEach(onStop),
      onTicks: () => {},
    });
    party.setTargets(caps().map((_c, i) => [i, label(i)]), ticked);
    party.root.hidden = true;
    sec.body.append(party.root);
  }
  for (let i = 0; i < n; i++) {
    const card = new ShockerCard(label(i), {
      onFire: (op, it, len, wms, wi) => onShock(i, it, len, op, wms, wi),
      onHold: (op, it) => onHold(i, op, it), onRelease: () => onRelease(i), onStop: () => onStop(i),
    }, { partyBox: Boolean(party) });
    card.setCaps(caps()[i], holdS());
    if (card.partyBox) {
      card.partyBox.onchange = () => {
        if (card.partyBox.checked) ticked.add(i); else ticked.delete(i);
        party.setTicked(new Set(ticked));
        party.root.hidden = !ticked.size;
        if (!ticked.size) party.release();
      };
    }
    cards.push(card);
  }
  sec.body.append(el("div.grid.wide", {}, cards.map((c) => c.root)));
  /** their shockers' switches: greyed buttons, and why (setRules) */
  const rules = (st) => {
    cards.forEach((c, i) => c.setRules(...rulesOf(st, [i])));
    if (party) party.card.setRules(...rulesOf(st, cards.map((_c, i) => i)));
  };
  return { sec, strip, cards, party, rules };
}
function showStrip(strip, paused, off, armed) {
  const [head, rest, tone] = paused ? ["Paused", "nothing reaches them", ""] : off ? ["Off", "their Off is on - nothing reaches them", ""]
    : armed ? ["⚠  ARMED", "shocks are real", "armed"] : ["Not armed", "a shock arrives as a vibration", ""];
  strip.firstChild.textContent = head;
  strip.lastChild.textContent = `·  ${rest}`;
  strip.classList.toggle("armed", tone === "armed");
}

/** Your own panel: the Me row, a friend who may do everything. */
function mePanel() {
  const root = el("div.fr-panel");
  const toys = D.toys.filter((t) => t.on).map((t) => [t.name, t.batt]);
  const tsec = toysSection({
    onLevel: (key, v) => { if (v > 0) log(`You drive your ${key === P.ALL ? "toys" : key} at ${pct(v)}`, ME("toys", "level")); },
  }, toys, { get: () => D.state.strength, set: (v) => D.setStrength(v) });
  // your shockers as a friend sees them: the ones in use (their card's
  // switch on), numbered among themselves -- rebuilt when that changes
  const used = () => SHOCK.inUse();
  const at = (slot) => SHOCK.shockers.indexOf(used()[slot]);
  // as friends get them: the friends' own caps while limits are separate
  const capsNow = () => used().map((s) => capsOf(s, "friends"));
  // what each of your shockers lets through: its own Allowed chips, so Me's
  // buttons grey like a friend's would
  const myStatus = () => {
    const off = used().map((s) => ["shock", "vibrate", "beep"].filter((op) => !s.ops[op]));
    const ops = used().map((s, k) => ["shock", "vibrate", "beep"].filter((op) => s.ops[op]
      && !(op === "shock" && !D.state.shock.armed && off[k].includes("vibrate"))));
    return { shockerOps: ops, shockerOff: off, armed: D.state.shock.armed };
  };
  const shocked = (slot, it, len, op, wms) => {
    const i = at(slot), name = SHOCK.shockers[i].name;
    const [cap, vcap, top] = capsNow()[slot];
    const [lvl, ms] = P.shockValues(it, len, op === "vibrate" ? vcap : cap, top);
    const go = () => {
      const got = fire(i, op, lvl, ms, "friends");
      if (got) log(`You (Me): ${got[0] === op ? op : `${got[0]} (shocks aren't armed)`} ${got[1] || ""} · ${(got[2] / 1000).toFixed(1)} s on ${name}`,
                   { ...ME("shock", got[0]), level: got[1], ms: got[2], on: [name] });
      else log(`You (Me) tried to ${op} ${name} - held back: it is resting, stopped, Off, not in use or has ${op} switched off`,
               { ...ME("shock", op), held: "held back" });
    };
    if (wms > 0) { log(`You (Me): ${(wms / 1000).toFixed(1)} s warning first on ${name}`, ME("shock", "warn")); setTimeout(go, wms); } else go();
  };
  // Me is in the friends' count: their own longest hold while limits are separate
  const buildShock = () => shockSection(capsNow, () => timingOf("friends").hold, (slot) => `${slot + 1} · ${used()[slot].name}`, shocked,
    (slot, op, it) => { const [cap, vcap] = capsNow()[slot]; fire(at(slot), op, Math.max(1, Math.round(it * (op === "vibrate" ? vcap : cap))), timingOf("friends").hold * 1000, "friends"); },
    (slot) => release(at(slot), "friends"), (slot) => { release(at(slot), "friends"); log(`You stopped your ${used()[slot].name}`, ME("shock", "stop")); });
  let ssec = buildShock(), usedKey = used().map((s) => s.id).join();
  const asec = section("THEIR AVATAR", "green", "params");
  const board = new Board({ onSet: (id, v) => { AVATAR.set(id, v); log(`You (Me) set your ${AVATAR.board.controls.find((c) => c.id === id).label}`, ME("params", "set")); },
                            onHold: (id, held) => AVATAR.hold(id, held), onSetAny() {},
                            onHeight: (mode, h) => AVATAR.height(mode, h) });
  asec.head.append(board.note);
  asec.body.append(board.root);
  root.append(panelHead("Blise (you)", "cyan", pill("THIS PC · a local loop", "ok")), tsec.sec.box, ssec.sec.box, asec.box,
    el("p.pg-note", {}, "Your own panel is what a friend who may do everything sees - and every friend rule holds for it: "
      + "your strength, Off, Pause all, each toy's output band, the shockers' switches, arming and caps, locked categories."));
  return {
    root,
    tick() {
      const st = tsec.st, d = D.state, drive = {};
      if (!S.paused) {
        for (const t of D.toys) if (t.on) { const [lvl, over] = playing(st, t.name); if (lvl > 0 || over) drive[t.id] = [lvl, over]; }
      }
      D.setDrive(drive);
      const outs = D.outputs();
      for (const card of st.cards) {
        const out = card.toy === P.ALL ? Math.max(0, ...Object.values(outs)) : (outs[D.toys.find((t) => t.name === card.toy).id] || 0);
        card.setState(st.levels[card.toy] || 0, st.override.has(card.toy), st.patterns[card.toy], out);
        card.tick();
      }
      if (!st.s.busy) { st.s.setQuiet(Math.round(d.strength * 1000)); st.val.textContent = pct(d.strength); }
      const sh = d.shock, key = used().map((s) => s.id).join();
      if (key !== usedKey) {                      // a shocker switched on or off
        usedKey = key;
        ssec.cards.forEach((c) => c.release());
        const fresh = buildShock();
        ssec.sec.box.replaceWith(fresh.sec.box);
        ssec = fresh;
      }
      ssec.sec.box.hidden = !(sh.share && sh.on && d.features.pishock && used().length);
      showStrip(ssec.strip, S.paused, d.off || !sh.on, sh.armed);
      ssec.cards.forEach((c) => { c.setCaps(capsNow()[ssec.cards.indexOf(c)], timingOf("friends").hold); c.setBlocked(S.paused || d.off); });
      ssec.rules(myStatus());
      asec.box.hidden = !d.features.params;
      board.update({ ver: AVATAR.board.ver, stop: S.paused, yolo: false }, AVATAR.friendBoard(),
                   { ...AVATAR.values, "OGP/Strength": d.strength }, false, AVATAR.heightNow());
    },
  };
}

function friendPanel(f) {
  const root = el("div.fr-panel");
  const t = f.theirs;
  const others = f.others ? pill(`+${f.others.length} OTHER`, "run", `Also driving ${f.nick} now: ${f.others.join(", ")}`) : "";
  const account = accountBox(f);
  root.append(panelHead(f.nick, f.hue, pill(`ONLINE · ${f.path} · ${f.rtt} ms`, "ok"), others), account);
  const tsec = toysSection({
    others: Boolean(f.others),
    onLevel: (key, v) => log(`You set ${f.nick}'s ${key === P.ALL ? "toys" : key} to ${pct(v)}`, about(f, "toys", "level")),
    onPattern: (key, c) => { if (c) log(`You started ${P.WAVE_LABELS[c[0]]} on ${f.nick}'s ${key === P.ALL ? "toys" : key}`, about(f, "toys", "pattern")); },
  }, t.toys, { get: () => t.strength, set: (v) => { t.strength = v; } });
  root.append(tsec.sec.box);
  let ssec = null;
  if (t.shockers) {
    const caps = () => t.shockers.map(([, c]) => c);
    const shocked = (i, it, len, op, wms) => {
      const [cap, vcap, top] = caps()[i];
      const [lvl, ms] = P.shockValues(it, len, op === "vibrate" ? vcap : cap, top);
      const first = wms > 0 ? `${(wms / 1000).toFixed(1)} s warning, then ` : "";
      const what = op === "beep" ? "beep" : op === "shock" && !t.armed ? `vibrate ${lvl} (their shocks aren't armed)` : `${op} ${lvl}`;
      log(`You → ${f.nick}: ${first}${what} · ${(ms / 1000).toFixed(1)} s on ${t.shockers[i][0]}`, about(f, "shock", op === "shock" && !t.armed ? "vibrate" : op));
    };
    ssec = shockSection(caps, () => t.holdS, (i) => `${i + 1} · ${t.shockers[i][0]}`, shocked,
      (i, op) => log(`You hold ${f.nick}'s ${t.shockers[i][0]} (${op})`, about(f, "shock", "hold")), () => {},
      (i) => log(`You stopped ${f.nick}'s ${t.shockers[i][0]}`, about(f, "shock", "stop")));
    root.append(ssec.sec.box);
  }
  let board = null;
  if (t.board) {
    const asec = section("THEIR AVATAR", "green", "params");
    board = new Board({
      onSet: (id, v) => {
        const c = t.board.controls.find((x) => x.id === id);
        t.values[c.param] = P.isIntSwitch(c) ? P.intSwitchValues(c)[v ? 0 : 1] : c.ptype === "Bool" ? Boolean(v) : Number(v);
        log(`You set ${f.nick}'s ${c.label}`, about(f, "params", "set"));
      },
      onHold: (id, held) => { const c = t.board.controls.find((x) => x.id === id); t.values[c.param] = P.intSwitchValues(c)[held ? 0 : 1]; },
      onSetAny() {},
    });
    asec.head.append(board.note);
    asec.body.append(board.root);
    root.append(asec.box);
  }
  root.append(el("div.pg-row", {}, el("span.grow"), el("button.pg-link", { type: "button" }, `Unfriend ${f.nick}…`)));
  return {
    root,
    paint() { account.paint(); },
    tick() {
      const st = tsec.st;
      for (const card of st.cards) {
        // nobody at the other end: their toy plays your level at their strength
        const out = card.toy === P.ALL
          ? Math.max(0, ...t.toys.map(([n]) => playing(st, n)[0])) * t.strength
          : playing(st, card.toy)[0] * t.strength;
        card.setState(st.levels[card.toy] || 0, st.override.has(card.toy), st.patterns[card.toy], out);
        card.tick();
      }
      if (ssec) { showStrip(ssec.strip, false, false, t.armed); ssec.rules(t); }
      if (board) board.update({ ver: t.board.ver, stop: false, yolo: false }, t.board, t.values);
    },
  };
}

function webPanel(f) {
  const sw = (label, what) => toggle(label, f.allow[what], (on) => { f.allow[what] = on; render(); });
  const root = el("div.fr-panel", {},
    el("div.fp-head", {}, icon("web"), hued(el("span.fp-name", {}, "Web remote"), "cyan"), pill(`${f.guests.length} ON`, "ok")),
    el("p.pg-note", {}, "Anyone with your web remote link gets a friend's panel in their browser - no OGP, no account: your toys, "
      + "and your shockers and avatar's board if you tick them below. Everything a friend's must, holds: your strength, Off, "
      + "Pause all, each toy's output band, arming and each shocker's caps, locked categories - and a browser that stops "
      + "sending lets go within a second."));
  const link = section("YOUR LINK", "cyan", "toys");
  link.head.firstChild.replaceWith(icon("web"));
  link.head.append(toggle("On", true, () => {}));
  link.body.append(el("div.pg-row", {}, notInDemo(el("button.pg-btn", { type: "button" }, "Copy link"), "Copy link"),
    el("button.pg-btn", { type: "button" }, "New link…")),
    el("p.small", {}, "It opens remote.html on OGP's website. Everything after the # stays in the browser - the website "
      + "never learns who drives whom."));
  const may = section("WHAT THEY MAY DO", "cyan", "toys");
  may.head.firstChild.replaceWith(icon("web"));
  // only friends in my instance: a browser can't be in one, so it's blocked
  // unless this is on (friends_web_panel.py)
  const anyway = toggle("Allow the web remote anyway", f.anyway, (on) => { f.anyway = on; render(); },
    "On: everyone on your web remote can drive you while Only friends in my instance is on - a browser can never be in "
    + "your VRChat instance, so without this it's blocked. Everything else still holds. Off by default.");
  const blocked = el("p.small", {}, "Only friends in my instance is on, and a browser can't be in your VRChat instance: nobody on "
    + "your web remote can drive you unless you allow it anyway. They're told why - never your friends' names or where you are.");
  may.body.append(el("div.pg-row", {}, sw("Toys", "toys"), sw("Shockers", "shock"), sw("Avatar", "params")),
    el("p.small", {}, "For everyone on the link at once. Shockers and Avatar start off: anyone with the link gets what you tick here."),
    el("div.pg-row", {}, anyway), blocked);
  const now = section("ON NOW", "cyan", "toys");
  now.head.firstChild.replaceWith(icon("web"));
  const guest = el("span.grow");
  now.body.append(...f.guests.map(() => el("div.pg-row", {}, guest, el("button.pg-btn", { type: "button" }, "Kick"))));
  root.append(link.box, may.box, now.box, el("div.pg-row", {}, el("span.grow"), el("button.pg-link", { type: "button" }, "Remove web remote…")));
  return {
    root,
    paint() {
      anyway.hidden = blocked.hidden = !S.instanceOnly;
      anyway.set(f.anyway);
      guest.textContent = `${f.guests[0]} · in a browser${S.instanceOnly && !f.anyway ? " · not here" : ""}`;
    },
    tick() {},
  };
}

function groupPanel(g) {
  // Only the members, as chips -- never every friend, the list gets long;
  // more come by dragging a friend's row (yours too) onto the box
  const count = pill("", "ok");
  const box = el("div.fr-drop");
  dropTarget(box, g);
  const fill = () => {
    count.textContent = membersText(g.members);
    box.replaceChildren(...g.members.map(byId).map((m) => {
      const chip = hued(el("button.fr-chip", { type: "button", title: "Click to take them out of the group" },
                           `${m.me ? `${m.nick} (you)` : m.nick}  ×`), m.hue);
      chip.onclick = () => {
        g.members = g.members.filter((id) => id !== m.id);
        log(`${m.me ? "You (Me)" : m.nick} leaves ${g.nick}`);
        render();
      };
      return chip;
    }), el("span.fr-drophint", {}, g.members.length ? "＋  Drag more here" : "＋  Drag a friend here from your list"));
  };
  fill();
  const root = el("div.fr-panel", {},
    el("div.fp-head", {}, hued(el("span.fp-name", {}, g.nick), "accent"), count),
    el("span.fr-micro", {}, "MEMBERS"), box);
  const tsec = toysSection({ onLevel: (key, v) => log(`You set ${g.nick}'s toys to ${pct(v)}`, { who: g.id, name: g.nick, role: "group", kind: "toys", op: "level" }) },
    [], { get: () => 1, set() {} });
  tsec.sec.head.querySelector(".strength-g").remove();
  root.append(tsec.sec.box, el("p.pg-note", {}, "One card drives every member's toys at once - each within what they allow you."));
  return { root, fill, paint() {},
           tick() { const c = tsec.st.cards[0]; c.setState(tsec.st.levels[P.ALL] || 0, false, tsec.st.patterns[P.ALL], null); c.tick(); } };
}

function offlinePanel(f, why) {
  const account = f.me || f.web || f.group ? null : accountBox(f);
  const root = el("div.fr-panel", {}, el("div.fp-head", {}, hued(el("span.fp-name", {}, f.nick), f.hue), pill("OFFLINE", "idle")),
    account || "", el("p.pg-note", {}, why));
  return { root, paint() { if (account) account.paint(); }, tick() {} };
}

// ---- the log card: as it happens, or by person -------------------------------

const friendsEntries = () => LOG.events.filter((e) => e.role !== "avatar");     // your avatar's: the Log page only
function paintLog() {
  if (S.logMode === 0) {
    W.logView.replaceChildren(...friendsEntries().slice(0, 40).map((e) => el("div", {}, `${hhmmss(e.t)}  ${e.text}`)));
  } else {
    W.people.show(friendsEntries().filter((e) => e.role !== "you"));
  }
}
function logCard() {
  W.logView = el("div.fr-logbody");
  W.people = personLog("Nobody has done anything yet. When friends drive you, each gets a row here with what they did last.");
  const peopleBox = el("div.fr-people", { hidden: true }, W.people);
  const seg = segmented(["As it happens", "By person"], "accent", (i) => {
    S.logMode = i;
    W.logView.hidden = i !== 0;
    peopleBox.hidden = i !== 1;
    paintLog();
  }, 0);
  seg.children[0].title = "Every entry as it comes in, newest first: who linked, who drove whose toys, every strength change and every shock.";
  seg.children[1].title = "A row per person with the last thing they did and how long ago. Click one to unfold what they did; shocks stand out in yellow.";
  return el("div.o-card.pg-card", {},
    el("div.pg-row.tight", {}, el("div.pg-bar.solid.grow", {}, "Log"), seg),
    W.logView, peopleBox,
    el("div.pg-row", {}, el("span.grow"), el("button.pg-btn", { type: "button", onclick: () => D.go("Log"),
      title: "Opens the Log page: everything of the last 30 days, filtered by person, kind, time or words." }, "Whole log ▸")));
}

// ---- the page -------------------------------------------------------------------

function panelFor(id) {
  const f = byId(id);
  const key = f.me || f.web || f.group || (!f.offline && S.online) ? id : `${id}-off`;
  if (!S.panels[key]) {
    S.panels[key] = f.me ? mePanel() : f.web ? webPanel(f) : f.group ? groupPanel(f)
      : f.offline ? offlinePanel(f, `${f.nick} isn't online - OGP links up by itself when they open theirs, or ↻ looks now.`)
      : !S.online ? offlinePanel(f, "You're offline - nobody can reach you, and you reach nobody. Switch Online back on above.")
      : friendPanel(f);
    S.panels[key].root.hidden = true;
    W.box.append(S.panels[key].root);
  }
  return S.panels[key];
}

function render() {
  paintRows();
  const want = panelFor(S.picked);
  if (want.fill) want.fill();
  if (want.paint) want.paint();
  for (const p of Object.values(S.panels)) p.root.hidden = p !== want;
}

function build(root) {
  W.box = el("div.o-card.pg-card.fr-panelbox");
  hued(W.box, "blue");
  root.append(
    el("div.o-viewtitle", {}, "Friends"),
    el("p.pg-intro", {}, "Link with other OGP users over the internet, no account needed. Tick what each friend may control here, "
      + "pick a friend or a group on the left and control them on the right. Every friend you allow can act at the same time, "
      + "and everything is logged."),
    listCard(), W.box, logCard(),
    el("p.pg-note.ok", {}, "✓ Your avatar has the OGP Friends menu - control from VRChat is on: OscGoesPurrr ▸ Friends acts on the "
      + "friend or group picked here."));
  render();
  paintLog();
  panelFor("me");                                 // your own panel drives the toys from any page
}

build(D.page("Friends"));
LOG.onChange(paintLog);
D.on("features", render);
setInterval(() => {
  const me = S.panels.me;
  if (me) me.tick();                              // its levels reach the toys wherever you are
  if (D.state.page !== "Friends") return;
  const shown = Object.values(S.panels).find((p) => !p.root.hidden);
  if (shown && shown !== me) shown.tick();
}, 33);
// "checking…" ends by itself; "3 min ago" moves on
setInterval(() => {
  if (D.state.page !== "Friends") return;
  if (Object.keys(S.checks).length) paintRows();
  if (S.logMode === 1) W.people.tickAgo();
}, 500);
