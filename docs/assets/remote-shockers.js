// The shockers on the web remote: PiShock's own shocker panel per shocker
// and its Party Mode -- src/ui/views/shocker_card.py and shock_party.py,
// ported, so whoever knows PiShock (docs.pishock.com, "Shocker Interface")
// is at home here too:
//
//        SHOCK                 [Use Mode]                 VIBRATE
//     [Operate ] ┃   ⇈           [STOP]            ⇈   ┃ [Operate ]
//     [Duration] ┃   🎲          [Beep]            ⇊   ┃ [Duration]
//     [Warning ] ┃   ⇊                                 ┃
//
// Use Mode -- Tap: a press is one operation of the set Duration; Remote: it
// runs while the button is held; Continuous: the sliders drive the shocker
// for as long as they're above 0. Random (the die): two handles on the shock
// slider, every shock picks a strength between them. Warning: None / Small
// 1-3 s / Mid 3-6 s / Long 6-9 s of vibration before a shock, at the vibrate
// strength. Strengths go out as 0..1 of THEIR caps, which the slider tops
// show; a party's card stands in percent and real seconds up to 10 s.
// Narrow, the card folds: Use Mode, STOP and Beep go under the columns.

import { el, glyph, segmented } from "./remote-ui.js";

const P = window.OGPRemoteProto;
const DURATIONS_MS = [100, 300, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000];
const WARNINGS = [null, [1000, 3000], [3000, 6000], [6000, 9000]];
const WARNING_NAMES = ["NONE", "SMALL", "MID", "LONG"];
const WARNING_PICKS = ["None", "Small · 1–3 s", "Mid · 3–6 s", "Long · 6–9 s"];
const USES = ["tap", "remote", "continuous"];
const USE_NAMES = ["TAP", "REMOTE", "CONTINUOUS"];
const USE_PICKS = ["Tap", "Remote", "Continuous"];
const USE_GLYPHS = ["tap", "remote", "infinity"];
export const PARTY_CAPS = [100, 100, DURATIONS_MS[DURATIONS_MS.length - 1]];
const NUDGE = 0.05;
const randint = (a, b) => a + Math.floor(Math.random() * (b - a + 1));
const secs = (ms) => `${+(ms / 1000).toFixed(3)}`;

/** A vertical slider in the app's look, integers min..max; `range` gives it
 *  two handles (Random's low and high). The handle reaches both ends. */
class VSlider {
  constructor({ min = 1, max = 100, value = 1, range = false, hue = "yellow", onInput, title }) {
    this.min = min;
    this.max = max;
    this.range = range;
    this.values = range ? [...value] : [value];
    this.onInput = onInput;
    this.busy = false;
    this.fill = el("div.vs-fill");
    this.knobs = this.values.map(() => el("div.vs-knob"));
    this.root = el(`div.vs${range ? ".range" : ""}`, { title, role: "slider", tabIndex: 0 },
                   el("div.vs-track", {}, this.fill), ...this.knobs);
    this.root.style.setProperty("--fill", `var(--${hue})`);
    let drag = -1;
    const at = (ev) => {
      const r = this.root.getBoundingClientRect(), k = r.width / 2;
      const f = 1 - (ev.clientY - r.top - k) / Math.max(1, r.height - 2 * k);
      return Math.round(this.min + Math.max(0, Math.min(1, f)) * (this.max - this.min));
    };
    this.root.addEventListener("pointerdown", (ev) => {
      if (this.disabled) return;
      ev.preventDefault();
      this.root.setPointerCapture(ev.pointerId);
      this.busy = true;
      const v = at(ev);
      drag = this.range ? (Math.abs(v - this.values[0]) <= Math.abs(v - this.values[1]) ? 0 : 1) : 0;
      this.set(drag, v, true);
    });
    this.root.addEventListener("pointermove", (ev) => { if (drag >= 0) this.set(drag, at(ev), true); });
    const end = () => { drag = -1; this.busy = false; };
    this.root.addEventListener("pointerup", end);
    this.root.addEventListener("pointercancel", end);
    this.root.addEventListener("keydown", (ev) => {
      const step = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[ev.key];
      if (step && !this.disabled) { ev.preventDefault(); this.set(this.range ? 1 : 0, this.values[this.range ? 1 : 0] + step, true); }
    });
    this.paint();
  }
  get value() { return this.values[0]; }
  set(i, v, user) {
    v = Math.max(this.min, Math.min(this.max, Math.round(v)));
    if (this.values[i] === v) return;
    this.values[i] = v;
    this.paint();
    if (user && this.onInput) this.onInput();
  }
  setQuiet(v) { this.values[0] = Math.max(this.min, Math.min(this.max, v)); this.paint(); }
  setRange(lo, hi) {
    this.values = [Math.max(this.min, Math.min(this.max, lo)), Math.max(this.min, Math.min(this.max, hi))];
    this.paint();
  }
  setLimits(min, max) { this.min = min; this.max = max; this.values = this.values.map((v) => Math.max(min, Math.min(max, v))); this.paint(); }
  setDisabled(d) { this.disabled = d; this.root.classList.toggle("disabled", d); }
  frac(v) { return this.max > this.min ? (v - this.min) / (this.max - this.min) : 0; }
  paint() {
    // the knob's centre runs from a radius above the bottom to a radius
    // below the top, so it sits flush with both ends (CSS does the radius)
    this.knobs.forEach((k, i) => k.style.setProperty("--p", this.frac(this.values[i])));
    const a = this.range ? Math.min(...this.values.map((v) => this.frac(v))) : 0;
    const b = this.range ? Math.max(...this.values.map((v) => this.frac(v))) : this.frac(this.values[0]);
    this.fill.style.setProperty("--a", a);
    this.fill.style.setProperty("--b", b);
    this.root.setAttribute("aria-valuenow", this.values.join("-"));
  }
}

/** A tile, as PiShock's (shocker_parts.Tile): an icon on top, a value
 *  under it, a caption at the bottom. */
function tile(label, hue, { filled = false, wide = false, glyphKind = "", cls = "" } = {}) {
  const value = el("span.tile-v", { hidden: true });
  const g = el("span.tile-g", {}, glyphKind ? glyph(glyphKind, 18) : null);
  const kind = cls || (hue ? "hued" : "plain");
  const b = el(`button.optile.${kind}${filled ? ".filled" : ""}${wide ? ".wide" : ""}`,
               { type: "button" }, g, value, el("span.tile-l", {}, label));
  if (hue) {
    b.style.setProperty("--hue", `var(--${hue})`);
    b.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
    b.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
  }
  b.setValue = (text) => { value.textContent = text; value.hidden = !text; };
  b.setGlyph = (kind) => { g.replaceChildren(glyph(kind, 18)); };
  return b;
}

export class ShockerCard {
  /** cb: onFire(op, intensity, length, warnMs, warnIntensity) -- Tap;
   *  onHold(op, intensity) / onRelease() -- Remote and Continuous (a
   *  warning holds "vibrate" first, then "shock"); onStop(). */
  constructor(title, cb, { party = false, partyBox = false } = {}) {
    this.cb = cb;
    this.caps = [...PARTY_CAPS];
    this.capsKnown = false;
    this.holdS = 0;
    this.holding = "";
    this.pending = "";
    this.pendingV = 1;
    this.use = "tap";
    this.warn = 0;
    this.random = false;
    this.blocked = false;
    this.dur = { shock: 300, vibrate: 1000 };
    this.beforeCont = null;
    this.warnTimer = null;
    this.picker = null;
    this.party = party;

    this.t = {
      shock: tile("Operate", "yellow", { filled: true, glyphKind: "bolt" }),
      shock_dur: tile("Duration", "yellow", { glyphKind: "clock" }),
      warn: tile("Warning", "yellow", { glyphKind: "alert" }),
      vibrate: tile("Operate", "pink", { filled: true, glyphKind: "vibrate" }),
      vibrate_dur: tile("Duration", "pink", { glyphKind: "clock" }),
      use: tile("Use Mode", "", { wide: true, glyphKind: "tap" }),
      stop: tile("STOP", "", { wide: true, glyphKind: "stop", cls: "stop" }),
      beep: tile("Beep", "", { wide: true, glyphKind: "bell" }),
    };
    this.t.shock.title = "Shock at this strength for the Duration (Remote: while you hold it)";
    this.t.vibrate.title = "Vibrate at this strength for the Duration (Remote: while you hold it)";
    this.t.shock_dur.title = this.t.vibrate_dur.title =
      "How long it runs - 0.1 s, 0.3 s, then whole seconds to 10 s, never past their longest";
    this.t.warn.querySelector(".tile-g").style.color = "var(--warn)";   // the app's amber
    this.t.warn.title = "Vibration before a shock: Small 1-3 s, Mid 3-6 s, Long 6-9 s - how long "
      + "exactly is random, at the vibrate strength. Works in every Use Mode.";
    this.t.stop.title = "Emergency Stop: this shocker stops now - a running pulse, a hold, a "
      + "shock waiting after its warning";
    this.t.beep.title = "A beep (Remote: while you hold it)";
    for (const op of ["shock", "vibrate", "beep"]) this.wire(this.t[op], op);
    this.t.shock_dur.onclick = () => this.openPicker("shock_dur");
    this.t.vibrate_dur.onclick = () => this.openPicker("vibrate_dur");
    this.t.warn.onclick = () => this.openPicker("warn");
    this.t.use.onclick = () => this.openPicker("use");
    this.t.stop.onclick = () => this.stop();

    this.sliders = {
      shock: new VSlider({ value: 25, hue: "yellow", title: "Shock Intensity", onInput: () => this.strengthMoved("shock") }),
      vibrate: new VSlider({ value: 50, hue: "pink", title: "Vibrate Intensity", onInput: () => this.strengthMoved("vibrate") }),
    };
    this.rangeS = new VSlider({ value: [10, 40], range: true, hue: "yellow",
                                title: "Random: every shock picks a strength between the two handles",
                                onInput: () => this.showValues() });
    this.maxL = { shock: el("span.vs-max", { title: "The top of the slider: their strongest" }),
                  vibrate: el("span.vs-max", { title: "The top of the slider: their strongest" }) };
    const col = (op) => el("div.vcol", {}, this.maxL[op], this.sliders[op].root,
                           op === "shock" ? this.rangeS.root : null,
                           el("span.gauge", { title: `${op === "shock" ? "Shock" : "Vibrate"} Intensity` }, glyph("gauge", 16)));
    const mini = (kind, tip, fn, hue) => {
      const b = el("button.mini", { type: "button", title: tip, onclick: fn }, glyph(kind, 14));
      b.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
      b.style.setProperty("--hue", `var(--${hue})`);
      b.style.color = `var(--${hue})`;
      return b;
    };
    this.dice = mini("dice", "Random Intensity: two handles on the slider, and every shock picks a "
                     + "strength between them", () => this.toggleRandom(), "yellow");
    const nudgesShock = el("div.nudges", {},
      mini("up", "Stronger", () => this.nudge("shock", +1), "yellow"), this.dice,
      mini("down", "Weaker", () => this.nudge("shock", -1), "yellow"));
    const nudgesVib = el("div.nudges", {},
      mini("up", "Stronger", () => this.nudge("vibrate", +1), "pink"),
      mini("down", "Weaker", () => this.nudge("vibrate", -1), "pink"));

    const block = (title, hue, ...kids) => {
      const b = el("div.opblock", {}, el("div.opblock-h", {}, title), el("div.opblock-b", {}, ...kids));
      b.style.setProperty("--hue", `var(--${hue})`);
      b.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
      b.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
      return b;
    };
    const shock = block("SHOCK", "yellow",
      el("div.tiles", {}, this.t.shock, this.t.shock_dur, this.t.warn), col("shock"));
    const vibrate = block("VIBRATE", "pink",
      col("vibrate"), el("div.tiles", {}, this.t.vibrate, this.t.vibrate_dur));
    this.center = el("div.sk-center", {}, this.t.use, this.t.stop, this.t.beep);

    this.partyBox = null;
    if (partyBox) {
      this.partyBox = el("input.ck", { type: "checkbox" });
      this.partyBoxLabel = el("label.partybox", { title: "Party Mode: drive this shocker together with "
        + "the others you tick - all at once, one at random or one after the other" }, this.partyBox, "Party");
    }
    this.root = el("div.fcard.shocker", {},
      title ? el("div.card-head", {}, el("span.card-name", {}, title), el("span.grow"),
                 this.partyBoxLabel || null) : null,
      el("div.sk-body", {}, shock, nudgesShock, this.center, nudgesVib, vibrate));
    this.showControls();
  }

  wire(button, op) {
    button.addEventListener("click", () => this.tap(op));
    button.addEventListener("pointerdown", (ev) => {
      if (this.use === "remote") { button.setPointerCapture(ev.pointerId); this.press(op); }
    });
    const up = () => { if (this.use === "remote") this.release(); };
    button.addEventListener("pointerup", up);
    button.addEventListener("pointercancel", up);
  }

  // -- numbers
  cap(op) { return Math.max(1, op === "vibrate" ? this.caps[1] : this.caps[0]); }
  toFraction(op, v) { const c = this.cap(op); return c <= 1 ? 1 : Math.max(0, (v - 1) / (c - 1)); }
  strength(op) {
    if (op === "shock" && this.random) {
      const [lo, hi] = [...this.rangeS.values].sort((a, b) => a - b);
      return randint(lo, hi);
    }
    return this.sliders[op] ? this.sliders[op].value : 1;
  }
  length(op) {
    const ms = this.dur[op], top = Math.max(P.SHOCK_MIN_MS, this.caps[2]);
    return top <= P.SHOCK_MIN_MS ? 0 : (Math.min(ms, top) - P.SHOCK_MIN_MS) / (top - P.SHOCK_MIN_MS);
  }
  durations() {
    const top = Math.max(P.SHOCK_MIN_MS, this.caps[2]);
    const steps = DURATIONS_MS.filter((d) => d <= top);
    return steps.includes(top) ? steps : [...steps, top];
  }
  warnMs() { const span = WARNINGS[this.warn]; return span ? randint(span[0], span[1]) : 0; }
  warnFraction() {
    let v = this.sliders.vibrate.value;
    if (v <= 0 && this.beforeCont) v = this.beforeCont.vibrate;
    return this.toFraction("vibrate", Math.max(1, v));
  }

  // -- showing
  showValues() {
    const t = this.t;
    if (this.random && this.use !== "continuous") {
      const [lo, hi] = [...this.rangeS.values].sort((a, b) => a - b);
      t.shock.setValue(`${lo}–${hi}`);
    } else {
      t.shock.setValue(String(this.sliders.shock.value));
    }
    t.vibrate.setValue(String(this.sliders.vibrate.value));
    for (const op of ["shock", "vibrate"]) {
      t[`${op}_dur`].setValue(`${secs(this.dur[op])} s`);
      this.maxL[op].textContent = String(this.cap(op));
    }
    t.warn.setValue(WARNING_NAMES[this.warn]);
    t.use.setValue(USE_NAMES[USES.indexOf(this.use)]);
  }
  showControls() {
    const cont = this.use === "continuous", tap = this.use === "tap", t = this.t;
    for (const k of ["shock", "vibrate", "beep"]) t[k].disabled = cont || this.blocked;
    t.shock_dur.disabled = !tap;
    t.vibrate_dur.disabled = !tap;
    this.dice.disabled = cont;
    this.dice.classList.toggle("on", this.random);
    const randomOn = this.random && !cont;
    this.sliders.shock.root.hidden = randomOn;
    this.rangeS.root.hidden = !randomOn;
    const hold = this.holdS ? ` - up to ${+this.holdS.toFixed(1)} s at a time, then a break` : "";
    t.use.title = "Use Mode - Tap: a press is one operation of the set Duration. Remote: it runs "
      + "while you hold the button. Continuous: the sliders drive it for as long as they're "
      + `above 0${hold}.`;
    t.use.setGlyph(USE_GLYPHS[USES.indexOf(this.use)]);
    this.showValues();
  }
  /** [shock cap, vibrate cap, longest pulse ms] on their side. Before the
   *  first, the card stands in percent; then it starts where those were. */
  setCaps(caps, holdS = 0) {
    caps = caps && caps.length === 3 ? caps : PARTY_CAPS;
    if (caps.join() === this.caps.join() && holdS === this.holdS) return;
    const first = !this.capsKnown && caps.join() !== PARTY_CAPS.join();
    const prev = this.caps;
    this.caps = [...caps];
    this.holdS = holdS;
    this.capsKnown = this.capsKnown || caps.join() !== PARTY_CAPS.join();
    const scale = (op, v) => {
      const cap = this.cap(op), old = Math.max(1, op === "vibrate" ? prev[1] : prev[0]);
      return Math.min(Math.max(1, first ? Math.round(v * cap / old) : v), cap);
    };
    for (const op of ["shock", "vibrate"]) {
      const s = this.sliders[op];
      const v = s.value === 0 ? 0 : scale(op, s.value);
      s.setLimits(s.min, this.cap(op));
      s.setQuiet(v);
    }
    this.rangeS.setLimits(1, this.cap("shock"));
    this.rangeS.setRange(scale("shock", this.rangeS.values[0]), scale("shock", this.rangeS.values[1]));
    if (this.beforeCont) for (const op of Object.keys(this.beforeCont)) this.beforeCont[op] = scale(op, this.beforeCont[op]);
    const steps = this.durations();
    for (const op of Object.keys(this.dur)) {
      if (!steps.includes(this.dur[op])) {
        this.dur[op] = steps.reduce((a, b) => (Math.abs(b - this.dur[op]) < Math.abs(a - this.dur[op]) ? b : a));
      }
    }
    this.showControls();
  }
  setBlocked(blocked) {
    if (blocked !== this.blocked) { this.blocked = blocked; this.showControls(); }
  }

  // -- the pickers: over the card, never a window of their own
  openPicker(which) {
    this.closePicker();
    let options, current, cols = 1, onPick, hue = "";
    if (which === "warn") {
      options = WARNING_PICKS.map((n) => [n, true]);
      current = this.warn;
      onPick = (i) => { this.warn = i; this.showValues(); };
      hue = "yellow";
    } else if (which === "use") {
      options = USE_PICKS.map((n) => [n, true]);
      current = USES.indexOf(this.use);
      onPick = (i) => this.modePicked(i);
    } else {
      const op = which.slice(0, -4), steps = this.durations();
      const extra = steps.filter((d) => !DURATIONS_MS.includes(d));
      const every = [...DURATIONS_MS, ...extra];
      options = every.map((d) => [secs(d).replace(/^0/, ""), steps.includes(d)]);
      current = every.indexOf(this.dur[op]);
      cols = 3;
      onPick = (i) => { this.dur[op] = every[i]; this.showValues(); };
      hue = op === "shock" ? "yellow" : "pink";
    }
    const picker = el(`div.picker.${cols === 3 ? "round" : "wide"}${hue ? ".hued" : ""}`, { role: "dialog" });
    picker.style.setProperty("--cols", cols);
    if (hue) {
      picker.style.setProperty("--hue", `var(--${hue})`);
      picker.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
    }
    options.forEach(([label, ok], i) => {
      picker.append(el(`button.pick${i === current ? ".on" : ""}`, {
        type: "button", disabled: !ok, onclick: (ev) => { ev.stopPropagation(); this.closePicker(); onPick(i); },
      }, label));
    });
    const opener = this.t[which];
    this.root.append(picker);
    const cr = this.root.getBoundingClientRect(), orr = opener.getBoundingClientRect();
    let x = which === "vibrate_dur" ? orr.left - cr.left - picker.offsetWidth - 6
      : which === "use" ? orr.left - cr.left + (orr.width - picker.offsetWidth) / 2
      : orr.right - cr.left + 6;
    let y = which === "use" ? orr.bottom - cr.top : orr.top - cr.top;
    x = Math.max(0, Math.min(x, cr.width - picker.offsetWidth));
    y = Math.max(0, Math.min(y, cr.height - picker.offsetHeight));
    picker.style.left = `${x}px`;
    picker.style.top = `${y}px`;
    this.picker = picker;
    this.pickerAway = (ev) => {
      if (ev.type === "keydown" ? ev.key === "Escape" : !picker.contains(ev.target) && ev.target !== opener
          && !opener.contains(ev.target)) this.closePicker();
    };
    setTimeout(() => {
      document.addEventListener("pointerdown", this.pickerAway, true);
      document.addEventListener("keydown", this.pickerAway, true);
    });
  }
  closePicker() {
    if (!this.picker) return;
    this.picker.remove();
    this.picker = null;
    document.removeEventListener("pointerdown", this.pickerAway, true);
    document.removeEventListener("keydown", this.pickerAway, true);
  }

  // -- the hand
  modePicked(i) {
    this.release();
    const was = this.use;
    this.use = USES[i];
    const cont = this.use === "continuous";
    if (cont && was !== "continuous") {
      this.beforeCont = { shock: this.sliders.shock.value, vibrate: this.sliders.vibrate.value };
    }
    for (const [op, s] of Object.entries(this.sliders)) {
      s.setLimits(cont ? 0 : 1, s.max);
      if (cont) s.setQuiet(0);
      else if (was === "continuous" && this.beforeCont) s.setQuiet(this.beforeCont[op]);
    }
    if (!cont) this.beforeCont = null;
    this.showControls();
  }
  toggleRandom() {
    this.random = !this.random;
    if (this.random && this.rangeS.values[0] >= this.rangeS.values[1]) {
      const v = this.sliders.shock.value;
      this.rangeS.setRange(Math.max(1, Math.floor(v / 2)), Math.max(v, 2));
    }
    this.showControls();
  }
  strengthMoved(op) {
    this.showValues();
    const v = this.sliders[op].value;
    if (this.use === "continuous") {
      // the slider is the control: above 0 it runs, at 0 it stops
      if (op === "shock" && this.pending) {
        if (v > 0) return;                   // it starts at this when its warning ends
        clearTimeout(this.warnTimer);
        this.pending = "";
        this.holding = "shock";              // let go below
      }
      if (v > 0) {
        if (op === "shock" && this.holding !== "shock" && this.warn) { this.startWarning(v); return; }
        this.holding = op;
        this.cb.onHold(op, this.toFraction(op, v));
      } else if (this.holding === op) {
        const other = op === "shock" ? "vibrate" : "shock";
        this.holding = "";
        if (this.sliders[other].value > 0) this.strengthMoved(other);
        else this.cb.onRelease();
      }
    } else if (this.holding === op && !(op === "shock" && this.random)) {
      this.cb.onHold(op, this.toFraction(op, v));
    }
  }
  nudge(op, sign) {
    let step = sign * Math.max(1, Math.round(this.cap(op) * NUDGE));
    if (op === "shock" && this.random && this.use !== "continuous") {
      const [lo, hi] = [...this.rangeS.values].sort((a, b) => a - b);
      step = Math.max(1 - lo, Math.min(this.cap(op) - hi, step));     // the range moves whole
      this.rangeS.setRange(lo + step, hi + step);
      this.showValues();
      return;
    }
    const s = this.sliders[op];
    s.set(0, s.value + step, true);
  }
  startWarning(strength) {
    this.pending = "shock";
    this.pendingV = strength;
    this.holding = "vibrate";
    this.cb.onHold("vibrate", this.warnFraction());
    this.warnTimer = setTimeout(() => this.warned(), Math.max(1, this.warnMs()));
  }
  warned() {
    if (this.pending !== "shock") return;
    this.pending = "";
    const v = this.use === "continuous" ? this.sliders.shock.value : this.pendingV;
    if (v > 0) { this.holding = "shock"; this.cb.onHold("shock", this.toFraction("shock", v)); }
  }
  tap(op) {
    if (this.use !== "tap" || this.blocked) return;
    const warnMs = op === "shock" ? this.warnMs() : 0;
    const strength = op !== "beep" ? this.strength(op) : 1;
    this.cb.onFire(op, op !== "beep" ? this.toFraction(op, strength) : 0,
                   this.length(op !== "beep" ? op : "vibrate"), warnMs, this.warnFraction());
  }
  press(op) {
    if (this.use !== "remote" || this.blocked) return;
    if (op === "shock" && this.warn) { this.startWarning(this.strength("shock")); return; }
    this.holding = op;
    const strength = op !== "beep" ? this.strength(op) : 1;
    this.cb.onHold(op, op !== "beep" ? this.toFraction(op, strength) : 0);
  }
  stop() {
    clearTimeout(this.warnTimer);
    this.holding = this.pending = "";
    if (this.use === "continuous") { for (const s of Object.values(this.sliders)) s.setQuiet(0); this.showValues(); }
    this.cb.onStop();
  }
  /** Let go of whatever this card holds (Remote or Continuous, a warning too). */
  release() {
    clearTimeout(this.warnTimer);
    if (this.holding || this.pending) { this.holding = this.pending = ""; this.cb.onRelease(); }
  }
  settings() {
    return { use: this.use, warn: this.warn, random: this.random, dur: { ...this.dur },
             values: { shock: this.sliders.shock.value, vibrate: this.sliders.vibrate.value,
                       range: [...this.rangeS.values] },
             before: this.beforeCont ? { ...this.beforeCont } : null };
  }
  /** Set up like the card this one replaces (after setCaps). A Continuous
   *  card comes back quiet: its hold was let go. */
  restore(st) {
    this.use = st.use;
    this.warn = st.warn;
    this.random = st.random;
    Object.assign(this.dur, st.dur);
    this.beforeCont = st.before ? { ...st.before } : null;
    const cont = this.use === "continuous";
    for (const op of ["shock", "vibrate"]) {
      const s = this.sliders[op];
      s.setLimits(cont ? 0 : 1, s.max);
      s.setQuiet(cont ? 0 : st.values[op]);
    }
    this.rangeS.setRange(...st.values.range);
    this.showControls();
  }
}

/** PiShock's Party Mode: one card in percent and real seconds over the
 *  shockers ticked in its list -- Sync (all at once), Random (one, picked
 *  anew every press) or Round Robin (one after the other; the next is
 *  marked, a click on a name makes it next). Pairs here are slot numbers. */
export class ShockParty {
  constructor(cb) {
    this.cb = cb;                            // onFire(slots, op, it, ms, wms, wi), onHold, onRelease, onStop, onTicks
    this.mode = "sync";
    this.targets = [];                       // [slot, label]
    this.ticked = new Set();
    this.next = 0;
    this.held = [];
    this.title = el("span.card-name");
    this.card = new ShockerCard("", {
      onFire: (op, it, len, wms, wi) => this.fire(op, it, len, wms, wi),
      onHold: (op, it) => this.hold(op, it),
      onRelease: () => this.releaseHeld(),
      onStop: () => this.stopAll(),
    }, { party: true });
    this.card.setCaps(PARTY_CAPS);
    this.modes = segmented(["Sync", "Random", "Round Robin"], "yellow", (i) => {
      this.card.release();
      this.mode = ["sync", "random", "robin"][i];
      this.show();
    });
    this.modes.title = "Sync: all of them at once.\nRandom: one of them, picked anew every press.\n"
      + "Round Robin: one after the other - the next one is marked; click a name to make it next.";
    this.list = el("div.party-list");
    this.root = el("div.party", {},
      el("div.party-head", {}, this.title, el("span.small", {}, "· strengths in % of each one's max")),
      this.card.root, el("div.center-row", {}, this.modes), this.list);
  }
  setTargets(targets, ticked) {
    this.targets = targets;
    if (ticked) this.ticked = new Set(ticked);
    this.ticked = new Set([...this.ticked].filter((s) => targets.some(([t]) => t === s)));
    this.list.replaceChildren(...targets.map(([slot, label]) => {
      const cb = el("input.ck", { type: "checkbox", checked: this.ticked.has(slot),
                                onchange: () => this.tick(slot, cb.checked) });
      const nxt = el("button.mini.next", { type: "button", title: "Round Robin: this one is next - click "
        + "another name to make it next", onclick: () => this.makeNext(slot) }, "▶");
      nxt.dataset.slot = slot;
      return el("span.party-item", {}, nxt, el("label", {}, cb, label));
    }));
    this.show();
  }
  setTicked(ticked) { this.setTargets(this.targets, ticked); }
  tickedList() { return this.targets.map(([s]) => s).filter((s) => this.ticked.has(s)); }
  tick(slot, on) {
    if (on) this.ticked.add(slot); else this.ticked.delete(slot);
    this.show();
    this.cb.onTicks(new Set(this.ticked));
  }
  makeNext(slot) {
    if (!this.ticked.has(slot)) { this.ticked.add(slot); this.setTargets(this.targets); this.cb.onTicks(new Set(this.ticked)); }
    const list = this.tickedList();
    this.next = Math.max(0, list.indexOf(slot));
    this.show();
  }
  show() {
    const list = this.tickedList(), n = list.length;
    this.title.textContent = `Party · ${n} shocker${n === 1 ? "" : "s"}`;
    const nxt = n ? list[this.next % n] : null;
    for (const b of this.list.querySelectorAll(".next")) {
      b.hidden = this.mode !== "robin";
      b.classList.toggle("on", Number(b.dataset.slot) === nxt);
    }
    this.card.root.classList.toggle("disabled", n === 0);
  }
  pick() {
    const list = this.tickedList();
    if (!list.length) return [];
    if (this.mode === "random") return [list[Math.floor(Math.random() * list.length)]];
    if (this.mode === "robin") {
      const slot = list[this.next % list.length];
      this.next = (this.next + 1) % list.length;
      this.show();
      return [slot];
    }
    return list;
  }
  fire(op, it, len, wms, wi) {
    const slots = this.pick();
    // the card's length: 0..1 of PiShock's 10 s, in milliseconds
    if (slots.length) this.cb.onFire(slots, op, it, Math.round(P.SHOCK_MIN_MS + len * (PARTY_CAPS[2] - P.SHOCK_MIN_MS)), wms, wi);
  }
  hold(op, it) {
    if (!this.held.length) this.held = this.pick();      // one press, one pick (a warning included)
    if (this.held.length) this.cb.onHold(this.held, op, it);
  }
  releaseHeld() {
    const held = this.held;
    this.held = [];
    if (held.length) this.cb.onRelease(held);
  }
  stopAll() {
    this.held = [];
    const slots = this.targets.map(([s]) => s);
    if (slots.length) this.cb.onStop(slots);             // STOP stops every one of them
  }
  release() { this.card.release(); }
  settings() { return { card: this.card.settings(), mode: this.mode, ticked: [...this.ticked], next: this.next }; }
  restore(st) {
    this.card.restore(st.card);
    this.mode = st.mode;
    this.modes.set(["sync", "random", "robin"].indexOf(this.mode));
    this.next = st.next || 0;
    this.show();
  }
}
