// The demo window's Friends page (src/ui/views/friends.py, friends_list.py,
// friends_panel.py): you and your friends with what each may do, groups, and
// the picked one's panel -- built from the web remote's own pieces
// (remote-toys.js, remote-shockers.js, remote-board.js), which are 1-to-1
// with the app's panel.
//
// Your own row is the app's "Me": a friend who may do everything, over a
// local loop. Its panel drives the demo's real toys -- through the engine's
// friend hook (demo.js setDrive: your strength, Off and each toy's output
// band hold) -- fires the Shockers page's shockers and sets the avatar on My
// Avatar Remote. A demo friend's panel works on screen; nobody is at the
// other end, so what their toys do is your level at their strength.

import { el, identity, toggle, hslider, segmented, pct } from "./remote-ui.js";
import { ToyCard } from "./remote-toys.js";
import { ShockerCard, ShockParty } from "./remote-shockers.js";
import { Board } from "./remote-board.js";
import { SHOCK, fire, release } from "./demo-shockers.js";
import { AVATAR } from "./demo-avatar.js";

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

// What each friend allows you (theirs) and you them (allow: the list's boxes)
const FRIENDS = [
  { id: "me", nick: "Blise", hue: "cyan", me: true },
  { id: "web", nick: "Web remote", web: true, guests: ["Sam"], allow: { toys: true, shock: false, params: false } },
  { id: "mika", nick: "Mika", hue: "blue", rtt: 18, path: "direct", others: ["Sam"], allow: { toys: true, shock: true, params: true },
    theirs: { strength: 0.8, toys: [["Lovense Lush 3", 90], ["Lovense Hush 2", 65]], shockers: [["Collar", [40, 40, 3000]]],
              armed: false, holdS: 10, board: MIKA_BOARD,
              values: { BinaryHaloOff: true, JacketOff: false, Outfit: 1, MaxBrightness: 1, OutlineThickness: 0.5,
                        AudioLinkOff: false, "518H_HapticsOff": false, Emote: 0, CrouchIdle: 5, ProneIdle: 2 } } },
  { id: "kiko", nick: "Kiko", hue: "purple", rtt: 64, path: "relay", allow: { toys: true, shock: false, params: true },
    theirs: { strength: 1, toys: [["We-Vibe Sync", 72]], shockers: null, board: null } },
  { id: "nova", nick: "Nova", hue: "cyan", rtt: 31, path: "direct", allow: { toys: true, shock: true, params: false },
    theirs: { strength: 0.6, toys: [["Lovense Gush 2", 58]], shockers: [["Collar", [30, 50, 2000]], ["Leg", [50, 60, 1500]]],
              armed: true, holdS: 8, board: null } },
  { id: "rin", nick: "Rin", hue: "blue", offline: true, allow: { toys: true, shock: true, params: true } },
];
const GROUPS = [{ id: "g1", nick: "Night crew", group: true, members: ["mika", "kiko", "nova"] },
                { id: "g2", nick: "Pair", group: true, members: ["mika", "nova"] }];
const COLS = [["toys", "pink"], ["shock", "yellow"], ["params", "accent"]];

const S = { picked: "mika", online: true, paused: false, panels: {}, rows: {}, log: null };
const byId = (id) => FRIENDS.find((f) => f.id === id) || GROUPS.find((g) => g.id === id);
const hhmmss = () => new Date().toTimeString().slice(0, 8);

function log(line) {
  if (!S.log) return;
  S.log.prepend(el("div", {}, `${hhmmss()}  ${line}`));
  while (S.log.childElementCount > 40) S.log.lastChild.remove();
}
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
function notInDemo(btn, label) {
  btn.onclick = () => { btn.textContent = "Not in the demo - the app copies a link here"; setTimeout(() => { btn.textContent = label; }, 1800); };
  return btn;
}

// ---- the list ------------------------------------------------------------------

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
  const heads = el("div.fr-heads", {}, COLS.map(([what]) => {
    const h = el("span.fr-head", { title: "Set this column for every friend: off first while anyone has it" }, icon(what));
    h.onclick = () => {
      const anyOn = FRIENDS.some((f) => f.allow && f.allow[what]);
      FRIENDS.forEach((f) => { if (f.allow) f.allow[what] = !anyOn; });
      paintRows();
    };
    return h;
  }));
  const rows = el("div.fr-rows", {}, FRIENDS.map(friendRow));
  const groups = el("div.fr-rows", {}, GROUPS.map(friendRow));
  return el("div.o-card.pg-card.fr-list", {},
    el("div.pg-row", {}, el("span.o-in.grow.fr-nick", {}, "Blise"), onlinePill),
    el("div.pg-row", {}, online, el("span.grow"), pause),
    el("div.fr-addcard", {}, add, fold), web,
    el("div.pg-row.fr-sect", {}, el("span.fr-micro", {}, "FRIENDS"), el("span.grow"), heads),
    rows,
    el("div.pg-row.fr-sect", {}, el("span.fr-micro", {}, "GROUPS"), el("span.grow"), el("button.pg-link", { type: "button" }, "+ Group")),
    groups);
}

function friendRow(f) {
  const mark = f.web ? icon("web") : hued(el("span.fr-av", {}, f.nick[0]), f.group ? "accent" : f.hue);
  const meta = el("span.fr-meta");
  const boxes = el("span.fr-boxes", {}, f.allow && !f.group ? COLS.map(([what, hue]) => {
    const ck = hued(el("input.ck", { type: "checkbox", checked: f.allow[what] }), hue);
    ck.onclick = (e) => { e.stopPropagation(); f.allow[what] = ck.checked; };
    return ck;
  }) : []);
  const name = el("span.fr-name", {}, f.me ? `${f.nick} (you)` : f.nick,
    f.group ? el("span.fr-sub", {}, ` ${f.members.length} friends`) : "");
  const row = hued(el("div.fr-row", { onclick: () => { S.picked = f.id; render(); } }, mark, name, el("span.grow"), meta, boxes),
                   f.hue || "accent");
  S.rows[f.id] = { row, meta, boxes, f };
  return row;
}

function paintRows() {
  for (const { row, meta, boxes, f } of Object.values(S.rows)) {
    row.classList.toggle("on", f.id === S.picked);
    let text = "", tone = "";
    if (f.me) { text = "this PC"; tone = "ok"; }
    else if (f.web) { text = `${f.guests.length} on`; tone = "ok"; }
    else if (f.group) text = "";
    else if (f.offline || !S.online) { text = "offline"; }
    else { text = `${f.rtt} ms`; tone = "ok"; }
    meta.textContent = text;
    meta.className = `fr-meta ${tone}`;
    if (f.allow) [...boxes.children].forEach((ck, i) => { ck.checked = f.allow[COLS[i][0]]; });
  }
}

// ---- a panel ------------------------------------------------------------------

function panelHead(name, hue, ...pills) {
  return el("div.fp-head", {}, hued(el("span.fp-name", {}, name), hue), ...pills, el("span.grow"),
    el("button.pg-btn.fp-control", { type: "button", title: "The panel fills the window, everything big - for VR" }, "⤢  Control mode"));
}

/** Their toys: a card per toy and one for all, as remote.js builds them. */
function toysSection(P_, toys, strength) {
  const sec = section("THEIR TOYS", "pink", "toys");
  const val = el("span.val", {}, pct(strength.get()));
  const s = hslider({ max: 1000, hue: "accent", value: Math.round(strength.get() * 1000),
                      onInput: (x) => { val.textContent = pct(x / 1000); strength.set(x / 1000); } });
  s.classList.add("strength");
  sec.head.append(toggle("Sync with others", true, () => {}),
    el("span.strength-g", {}, el("span.small", {}, "Their strength"), s, val));
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
  return { sec, strip, cards, party };
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
    onLevel: (key, v) => { if (v > 0) log(`You drive your ${key === P.ALL ? "toys" : key} at ${pct(v)}`); },
  }, toys, { get: () => D.state.strength, set: (v) => D.setStrength(v) });
  // your shockers as a friend sees them: the ones in use (their card's
  // switch on), numbered among themselves -- rebuilt when that changes
  const used = () => SHOCK.inUse();
  const at = (slot) => SHOCK.shockers.indexOf(used()[slot]);
  const capsNow = () => used().map((s) => [s.shock, s.vibrate, Math.round(s.pulse * 1000)]);
  const shocked = (slot, it, len, op, wms) => {
    const i = at(slot), name = SHOCK.shockers[i].name;
    const [cap, vcap, top] = capsNow()[slot];
    const [lvl, ms] = P.shockValues(it, len, op === "vibrate" ? vcap : cap, top);
    const go = () => {
      const got = fire(i, op, lvl, ms);
      if (got) log(`You → you: ${got[0] === op ? op : `${got[0]} (shocks not armed)`} ${got[1] || ""} · ${(got[2] / 1000).toFixed(1)} s on ${name}`);
      else log(`Held back: ${name} is resting, stopped, Off or not in use`);
    };
    if (wms > 0) { log(`You → you: ${(wms / 1000).toFixed(1)} s warning first`); setTimeout(go, wms); } else go();
  };
  const buildShock = () => shockSection(capsNow, () => SHOCK.timing.hold, (slot) => `${slot + 1} · ${used()[slot].name}`, shocked,
    (slot, op, it) => { const [cap, vcap] = capsNow()[slot]; fire(at(slot), op, Math.max(1, Math.round(it * (op === "vibrate" ? vcap : cap))), SHOCK.timing.hold * 1000); },
    (slot) => release(at(slot)), (slot) => { release(at(slot)); log(`You stopped your ${used()[slot].name}`); });
  let ssec = buildShock(), usedKey = used().map((s) => s.id).join();
  const asec = section("THEIR AVATAR", "green", "params");
  const board = new Board({ onSet: (id, v) => { AVATAR.set(id, v); log(`You set your ${AVATAR.board.controls.find((c) => c.id === id).label}`); },
                            onHold: (id, held) => AVATAR.hold(id, held), onSetAny() {} });
  asec.head.append(board.note);
  asec.body.append(board.root);
  root.append(panelHead("Blise (you)", "cyan", pill("THIS PC · a local loop", "ok")), tsec.sec.box, ssec.sec.box, asec.box,
    el("p.pg-note", {}, "Your own panel is what a friend who may do everything sees - and every friend rule holds for it: "
      + "your strength, Off, Pause all, each toy's output band, the shockers' arming and caps, locked categories."));
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
      ssec.cards.forEach((c) => { c.setCaps(capsNow()[ssec.cards.indexOf(c)], SHOCK.timing.hold); c.setBlocked(S.paused || d.off); });
      asec.box.hidden = !d.features.params;
      board.update({ ver: AVATAR.board.ver, stop: S.paused, yolo: false }, AVATAR.board,
                   { ...AVATAR.values, "OGP/Strength": d.strength });
    },
  };
}

function friendPanel(f) {
  const root = el("div.fr-panel");
  const t = f.theirs;
  const others = f.others ? pill(`+${f.others.length} OTHER`, "run", `Also driving ${f.nick} now: ${f.others.join(", ")}`) : "";
  root.append(panelHead(f.nick, f.hue, pill(`ONLINE · ${f.path} · ${f.rtt} ms`, "ok"), others));
  const tsec = toysSection({
    onLevel: (key, v) => log(`You set ${f.nick}'s ${key === P.ALL ? "toys" : key} to ${pct(v)}`),
    onPattern: (key, c) => { if (c) log(`You started ${P.WAVE_LABELS[c[0]]} on ${f.nick}'s ${key === P.ALL ? "toys" : key}`); },
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
      log(`You → ${f.nick}: ${first}${what} · ${(ms / 1000).toFixed(1)} s on ${t.shockers[i][0]}`);
    };
    ssec = shockSection(caps, () => t.holdS, (i) => `${i + 1} · ${t.shockers[i][0]}`, shocked,
      (i, op) => log(`You hold ${f.nick}'s ${t.shockers[i][0]} (${op})`), () => {}, (i) => log(`You stopped ${f.nick}'s ${t.shockers[i][0]}`));
    root.append(ssec.sec.box);
  }
  let board = null;
  if (t.board) {
    const asec = section("THEIR AVATAR", "green", "params");
    board = new Board({
      onSet: (id, v) => {
        const c = t.board.controls.find((x) => x.id === id);
        t.values[c.param] = P.isIntSwitch(c) ? P.intSwitchValues(c)[v ? 0 : 1] : c.ptype === "Bool" ? Boolean(v) : Number(v);
        log(`You set ${f.nick}'s ${c.label}`);
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
      if (ssec) showStrip(ssec.strip, false, false, t.armed);
      if (board) board.update({ ver: t.board.ver, stop: false, yolo: false }, t.board, t.values);
    },
  };
}

function webPanel(f) {
  const sw = (label, what) => toggle(label, f.allow[what], (on) => { f.allow[what] = on; paintRows(); });
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
  may.body.append(el("div.pg-row", {}, sw("Toys", "toys"), sw("Shockers", "shock"), sw("Avatar", "params")),
    el("p.small", {}, "For everyone on the link at once. Shockers and Avatar start off: anyone with the link gets what you tick here."));
  const now = section("ON NOW", "cyan", "toys");
  now.head.firstChild.replaceWith(icon("web"));
  now.body.append(...f.guests.map((g) => el("div.pg-row", {}, el("span.grow", {}, `${g} · in a browser`),
    el("button.pg-btn", { type: "button" }, "Kick"))));
  root.append(link.box, may.box, now.box, el("div.pg-row", {}, el("span.grow"), el("button.pg-link", { type: "button" }, "Remove web remote…")));
  return { root, tick() {} };
}

function groupPanel(g) {
  const members = g.members.map(byId);
  const root = el("div.fr-panel", {},
    el("div.fp-head", {}, hued(el("span.fp-name", {}, g.nick), "accent"), pill(`${members.length} friends`, "ok")),
    el("div.pg-row", {}, el("span.fr-micro", {}, "MEMBERS"), ...members.map((m) => hued(el("span.fr-chip", {}, m.nick), m.hue))));
  const tsec = toysSection({ onLevel: (key, v) => log(`You set ${g.nick}'s toys to ${pct(v)}`) }, [], { get: () => 1, set() {} });
  tsec.sec.head.querySelector(".strength-g").remove();
  root.append(tsec.sec.box, el("p.pg-note", {}, "One card drives every member's toys at once - each within what they allow you."));
  return { root, tick() { const c = tsec.st.cards[0]; c.setState(tsec.st.levels[P.ALL] || 0, false, tsec.st.patterns[P.ALL], null); c.tick(); } };
}

function offlinePanel(f, why) {
  return { root: el("div.fr-panel", {}, el("div.fp-head", {}, hued(el("span.fp-name", {}, f.nick), f.hue), pill("OFFLINE", "idle")),
    el("p.pg-note", {}, why)), tick() {} };
}

// ---- the page -------------------------------------------------------------------

const W = { box: null };

function panelFor(id) {
  const f = byId(id);
  const key = f.me || f.web || f.group || (!f.offline && S.online) ? id : `${id}-off`;
  if (!S.panels[key]) {
    S.panels[key] = f.me ? mePanel() : f.web ? webPanel(f) : f.group ? groupPanel(f)
      : f.offline ? offlinePanel(f, `${f.nick} isn't online - OGP links up by itself when they open theirs.`)
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
  for (const p of Object.values(S.panels)) p.root.hidden = p !== want;
}

function build(root) {
  W.box = el("div.o-card.pg-card.fr-panelbox");
  hued(W.box, "blue");
  S.log = el("div.fr-logbody");
  root.append(
    el("div.o-viewtitle", {}, "Friends"),
    el("p.pg-intro", {}, "Link with other OGP users over the internet, no account needed. Tick what each friend may control here, "
      + "pick a friend or a group on the left and control them on the right. Every friend you allow can act at the same time, "
      + "and everything is logged."),
    listCard(), W.box,
    el("div.o-card.pg-card", {}, el("div.pg-bar.solid", {}, "Log"), S.log),
    el("p.pg-note.ok", {}, "✓ Your avatar has the OGP Friends menu - control from VRChat is on: OscGoesPurrr ▸ Friends acts on the "
      + "friend or group picked here."));
  for (const line of ["Mika linked (direct, 18 ms)", "Kiko linked (relay, 64 ms)", "Nova turned your Tail wag on",
                      "Sam started driving Mika's toys too"]) log(line);
  render();
  panelFor("me");                                 // your own panel drives the toys from any page
}

build(D.page("Friends"));
setInterval(() => {
  const me = S.panels.me;
  if (me) me.tick();                              // its levels reach the toys wherever you are
  if (D.state.page !== "Friends") return;
  const shown = Object.values(S.panels).find((p) => !p.root.hidden);
  if (shown && shown !== me) shown.tick();
}, 33);
