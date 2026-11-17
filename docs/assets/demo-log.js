// The demo window's Log page (src/ui/views/log_page.py, log_people.py) and
// the log the Friends page writes to (event_log.py): who did what, person by
// person -- what friends, Me and the web remote did, what you did to them,
// and what your own avatar fired on your shockers.
//
// The entries are the app's demo log (tools/app_shots.py _demo_event_log),
// plus everything the visitor does on the Friends page. They live in this
// page only, like everything in the demo.

import { el } from "./remote-ui.js";

const D = window.OGPDemo;

// What the log's kinds are called (event_log.KIND_LABELS), their icon and
// colour, and the Show chips' hover words (log_page._KIND_TITLES / _TIPS)
const KINDS = [
  ["toys", "Toys", "toys", "pink", "Show toys", "Shows driving toys: levels, auto modes, Override and strength."],
  ["shock", "Shocks", "shock", "yellow", "Show shocks", "Shows shocks, vibrates and beeps, with holds, warnings and Stops."],
  ["params", "Avatar Remote", "params", "accent", "Show Avatar Remote", "Shows Avatar Remote: toggles, buttons and sliders set on an avatar."],
  ["link", "Link", "friends", "cyan", "Show the link", "Shows the link: friends coming online and going, requests and invites."],
  ["settings", "Switches", "settings", "", "Show switches", "Shows switches: what each friend may use, Pause, groups and the like."],
];
const SPANS = [["Last hour", 3600], ["Today", "today"], ["Last 7 days", 7 * 86400], ["Last 30 days", null]];
const SHOCKER_OPS = ["shock", "vibrate", "beep"];
const ROLE_WORDS = {
  friend: "a friend", me: "you, as the Me row on the Friends page", web: "someone on your web remote",
  group: "a group of friends", avatar: "your own avatar's behaviours on the Shockers page", you: "you, switching things on the page",
};

/** One record per thing that happened (event_log.Event). `correction`: what
 *  went out instead of what was asked, and why (Event.correction), shown
 *  muted under the entry. */
function ev(agoS, who, name, role, kind, op, text, extra = {}) {
  return { t: Date.now() / 1000 - agoS, who, name, role, kind, op, text, held: "", asked: "", ...extra };
}
const standsOut = (e) => e.kind === "shock" && !e.held && (e.op === "shock" || (e.op === "hold" && e.asked === "shock"));
const shockerOp = (e) => e.kind === "shock" && !e.held && (SHOCKER_OPS.includes(e.op) || e.op === "hold");

export const LOG = {
  // newest first
  events: [
    ev(40, "kiko", "Kiko", "friend", "shock", "beep", "Kiko: beep · 0.3 s on Collar"),
    ev(95, "mika", "Mika", "friend", "toys", "strength", "You set Mika's strength to 55 %"),
    ev(180, "mika", "Mika", "friend", "shock", "shock", "Mika: shock 25 · 0.5 s on Collar, Thigh"),
    ev(288, "avatar", "Your avatar", "avatar", "shock", "let-go", "Your avatar (Continuous · Prox) let go of Collar after 12.0 s (up to vibrate 22)", { asked: "vibrate" }),
    ev(300, "avatar", "Your avatar", "avatar", "shock", "hold", "Your avatar (Continuous · Prox) is holding vibrate 12 on Collar", { asked: "vibrate" }),
    ev(420, "mika", "Mika", "friend", "toys", "strength", "Mika set your strength to 70 %"),
    ev(600, "mika", "Mika", "friend", "toys", "start", "Mika started driving your toys"),
    ev(900, "mika", "Mika", "friend", "link", "online", "Mika is online"),
    ev(1200, "avatar", "Your avatar", "avatar", "shock", "vibrate", "Your avatar (Touch zones · Neck): vibrate 18 · 0.5 s on Collar"),
    ev(1320, "me", "You (Me)", "me", "shock", "shock", "You (Me): shock 10 · 0.3 s on Thigh"),
    ev(1500, "kiko", "Kiko", "friend", "link", "online", "Kiko is online"),
    // asked for 2.0 s, sent Collar's longest pulse (event_log.correction_text)
    ev(1800, "mika", "Mika", "friend", "shock", "vibrate", "Mika: vibrate 30 · 2.0 s on Collar",
       { correction: "Cut to 1.0 s: your longest pulse" }),
    ev(2100, "avatar", "Your avatar", "avatar", "shock", "vibrate", "Your avatar (Touch zones · Neck): vibrate 15 · 0.5 s on Collar"),
    ev(2400, "sam", "Sam (web)", "web", "toys", "start", "Sam (web) started driving your toys"),
    ev(3000, "sam", "Sam (web)", "web", "link", "online", "Sam opened your web remote"),
    ev(2 * 3600, "nova", "Nova", "friend", "shock", "shock", "Nova tried to shock you - held back: your shockers aren't shared with friends",
       { held: "your shockers aren't shared with friends" }),
    ev(4 * 3600, "nova", "Nova", "friend", "params", "set", "Nova turned your Tail wag on"),
    ev(5 * 3600, "avatar", "Your avatar", "avatar", "shock", "shock", "Your avatar (Contact · Tap): shock 15 · 0.3 s on Collar"),
    ev(26 * 3600, "kiko", "Kiko", "friend", "shock", "vibrate", "Kiko: vibrate 20 · 0.8 s on Collar"),
    ev(2 * 86400, "you", "You", "you", "link", "online", "You went online"),
  ],
  listeners: [],
  /** a new entry, now: {who, name, role, kind, op, text, held} */
  add(e) {
    this.events.unshift({ t: Date.now() / 1000, held: "", asked: "", ...e });
    if (this.events.length > 2000) this.events.pop();
    this.listeners.forEach((fn) => fn());
  },
  onChange(fn) { this.listeners.push(fn); },
};

// ---- words -------------------------------------------------------------------

const p2 = (n) => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
/** The Log page's time column: the clock for today, the day before it for older (event_log.when). */
export function when(t) {
  const d = new Date(t * 1000);
  const clock = `${p2(d.getHours())}:${p2(d.getMinutes())}`;
  return sameDay(d, new Date()) ? `${clock}:${p2(d.getSeconds())}` : `${d.getDate()} ${MONTHS[d.getMonth()]} ${clock}`;
}
/** How long ago, the way a person says it (event_log.ago). */
export function ago(s) {
  s = Math.max(0, s);
  if (s < 10) return "just now";
  if (s < 60) return `${Math.floor(s)} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const days = Math.floor(s / 86400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
function icon(name, hue) {
  const i = el("i.lg-ic");
  i.innerHTML = D.icons[name] || "";
  if (hue) i.style.color = `var(--${hue})`;
  return i;
}
function tone(node, e) {
  if (standsOut(e)) node.classList.add("out");
  else if (shockerOp(e)) node.classList.add("op");
  else if (e.held) node.classList.add("held");
  return node;
}

/** The log by person (event_log.by_person): a row per person, newest first. */
function byPerson(events) {
  const rows = new Map();
  for (const e of events) {
    let p = rows.get(e.who);
    if (!p) rows.set(e.who, (p = { who: e.who, name: e.name, role: e.role, last: e, shocks: 0, recent: [] }));
    p.shocks += standsOut(e) ? 1 : 0;
    if (p.recent.length < 30) p.recent.push(e);
  }
  return [...rows.values()];
}

/** People: a row each that unfolds into what they did (log_people.PersonLog).
 *  `onPick`: their Only them (the Log page's), none on the Friends page. */
export function personLog(empty, onPick) {
  const root = el("div.lg-people");
  const open = new Set();
  const rows = {};
  root.show = (events) => {
    const people = byPerson(events);
    root.replaceChildren();
    if (!people.length) { root.append(el("p.pg-note", {}, empty)); return; }
    for (const p of people) {
      const n = p.shocks;
      const agoNode = el("span.lg-ago", {}, ago(Date.now() / 1000 - p.last.t));
      const head = el("div.lg-phead", { title: "Who it is, the last thing they did and how long ago. Click to unfold what they did, newest first; shocks stand out in yellow." },
        el("span.lg-caret", {}, open.has(p.who) ? "▾" : "▸"),
        el("b.lg-pname", { title: `${p.name}: ${ROLE_WORDS[p.role] || ""}` }, p.name),
        n ? el("span.lg-shocks", {}, `${n} shock${n === 1 ? "" : "s"}`) : "",
        el("span.grow"), agoNode,
        onPick ? el("button.lg-only", { type: "button", title: "Shows only this person's entries in the list beside it. Pick Everyone in the Person filter to see everyone again.",
                                        onclick: (x) => { x.stopPropagation(); onPick(p.who); } }, "Only them") : "");
      const row = el("div.lg-person", {}, head, el("div.lg-last", {}, p.last.text));
      if (open.has(p.who)) {
        // a corrected entry: what went out and why, muted under it (log_people.history_html)
        row.append(el("div.lg-body", {}, p.recent.flatMap((e) => [
          tone(el("div", {}, el("span.lg-when", {}, when(e.t)), e.text), e),
          ...(e.correction ? [el("div.lg-fix", {}, e.correction)] : [])])));
      }
      head.onclick = () => { if (open.has(p.who)) open.delete(p.who); else open.add(p.who); root.show(events); };
      rows[p.who] = { agoNode, p };
      root.append(row);
    }
  };
  root.tickAgo = () => {
    for (const { agoNode, p } of Object.values(rows)) agoNode.textContent = ago(Date.now() / 1000 - p.last.t);
  };
  return root;
}

// ---- the page ------------------------------------------------------------------

const F = { person: "", span: null, kinds: new Set(KINDS.map((k) => k[0])), words: "" };
const W = {};

function matches(e) {
  if (F.person === "~avatar" ? e.who === "avatar" : F.person && e.who !== F.person) return false;
  if (!F.kinds.has(e.kind)) return false;
  const now = Date.now() / 1000;
  if (F.span === "today") { if (!sameDay(new Date(e.t * 1000), new Date())) return false; }
  else if (F.span && now - e.t > F.span) return false;
  if (F.words) {
    const hay = `${e.text} ${e.name}`.toLowerCase();
    if (!F.words.split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

function people() {
  const seen = new Map();
  for (const e of LOG.events) if (!seen.has(e.who)) seen.set(e.who, e.name);
  return [...seen.entries()];
}

function fillPersonBox() {
  const box = W.person, keep = F.person;
  box.replaceChildren(el("option", { value: "" }, "Everyone"), el("option", { value: "~avatar" }, "Everyone but your avatar"),
    ...people().map(([who, name]) => el("option", { value: who }, name)));
  box.value = keep;
}

function refresh() {
  if (!W.table) return;
  const shown = LOG.events.filter(matches);
  W.count.textContent = shown.length ? `${shown.length} entr${shown.length === 1 ? "y" : "ies"}`
    : "Nothing here yet for these filters.";
  W.table.replaceChildren(...shown.slice(0, 300).map((e) => {
    const k = KINDS.find((x) => x[0] === e.kind) || KINDS[4];
    // a corrected entry gets a second line in WHAT, muted: what went out and
    // why (log_page.CorrectionDelegate)
    const what = e.correction
      ? el("span.lg-what", {}, el("span.lg-line", {}, e.text), el("span.lg-fix", {}, e.correction))
      : el("span.lg-what", {}, e.text);
    return tone(el(e.correction ? "div.lg-row.fixed" : "div.lg-row", {},
      el("span.lg-c1", {}, when(e.t)), el("span.lg-c2", {}, e.name),
      el("span.lg-c3", { title: e.correction ? `${e.text}\n${e.correction}` : e.text },
        icon(k[2], k[3]), what)), e);
  }));
  W.people.show(shown);
  fillPersonBox();
}

function select(options, value, onPick, title) {
  const s = el("select.lg-select", { title }, options.map(([label, v]) => el("option", { value: v }, label)));
  s.value = value;
  s.onchange = () => onPick(s.value);
  return s;
}

function build(root) {
  W.person = el("select.lg-select.wide", { title: "Shows everyone, everyone but your avatar's own behaviours, or just one person." });
  W.person.onchange = () => { F.person = W.person.value; refresh(); };
  const span = select(SPANS.map(([l], i) => [l, String(i)]), "3", (v) => { F.span = SPANS[+v][1]; refresh(); },
    "How far back the list goes: the last hour, today, the last 7 days or everything kept (30 days).");
  const search = el("input.su-input.lg-search", { type: "search", placeholder: "Search: a name, a shocker, a toy…",
    title: "Shows only entries with all of these words, in the entry or the person's name." });
  search.addEventListener("input", () => { F.words = search.value.trim().toLowerCase(); refresh(); });
  const ask = el("div.lg-ask", { hidden: true },
    el("span.grow", {}, "Delete the whole log on this PC - every entry of the last 30 days? It can't be undone."),
    el("button.pg-btn.danger", { type: "button", onclick: () => { LOG.events.length = 0; ask.hidden = true; refresh(); } }, "Delete"),
    el("button.pg-btn", { type: "button", onclick: () => { ask.hidden = true; } }, "Keep"));
  const clear = el("button.pg-btn.lg-clear", { type: "button", title: "Deletes the whole log on this PC, every day of it, after asking. It can't be undone.",
                                               onclick: () => { ask.hidden = false; } }, "Clear log");
  const chips = KINDS.map(([key, label, ic, hue, title, tip]) => {
    const b = el("button.lg-kind.on", { type: "button", title: `${title}. ${tip}` }, icon(ic, hue), label);
    b.onclick = () => {
      if (F.kinds.has(key)) F.kinds.delete(key); else F.kinds.add(key);
      b.classList.toggle("on", F.kinds.has(key));
      refresh();
    };
    return b;
  });
  W.people = personLog("Nobody in the log for these filters yet.", (who) => { F.person = who; W.person.value = who; refresh(); });
  W.count = el("p.pg-note");
  W.table = el("div.lg-tbody");
  root.append(
    el("div.o-viewtitle", {}, "Log"),
    el("p.pg-intro", {}, "Who did what, person by person: everything friends, Me and your web remote did - and you did to them "
      + "- and what your own avatar fired on your shockers. Kept on this PC for 30 days, never sent to anyone."),
    el("div.o-card.pg-card.lg-filters", {},
      el("div.pg-row.tight", {}, el("span", {}, "Person"), el("span.lg-selwrap", {}, W.person), el("span", {}, "Time"),
        el("span.lg-selwrap", {}, span), search, clear),
      el("div.pg-row.tight", {}, el("span", {}, "Show"), ...chips), ask),
    el("div.lg-cols", {},
      el("div.o-card.pg-card.lg-card", {}, el("div.pg-bar.solid", {}, "People"), W.people),
      el("div.o-card.pg-card.lg-card", {}, el("div.pg-bar.solid", {}, "Entries"), W.count,
        el("div.lg-table", { title: "The log itself, newest first: when, who, and what happened. Shocks stand out in yellow; what was held back is grey." },
          el("div.lg-row.th", {}, el("span.lg-c1", {}, "WHEN"), el("span.lg-c2", {}, "WHO"), el("span.lg-c3", {}, "WHAT")), W.table))));
  refresh();
}

build(D.page("Log"));
window.OGPDemoLog = LOG;          // Statistics (a classic script) counts what reached your shockers from it
LOG.onChange(refresh);
setInterval(() => { if (D.state.page === "Log") W.people.tickAgo(); }, 1000);
