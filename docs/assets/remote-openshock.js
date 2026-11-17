// The web remote's other shocker buttons: OpenShock's own card -- the app's
// src/ui/views/openshock_card.py and openshock_parts.py, ported, so the page
// stays 1-to-1 with the app's panel. Laid out the way OpenShock's web app has
// it (its Classic control and Live control; read for names, order and
// behaviour, none of its code used):
//
//     1 · Collar                       [Party] [LIVE]
//        ◔ 40%   ◷ 5 s                     (Max Intensity, Max Duration)
//       ( Intensity )   ( Duration )        two round dials
//       [   🔊   ]  [   〰   ]  [   ⚡   ]     Sound · Vibrate · Shock
//
// One Intensity for Vibrate and Shock (each stops at its own cap) and one
// Duration (0.3 s in tenths up to their longest pulse). A press sends one
// operation; the button stays lit while it runs, and pressing it again stops
// it. LIVE swaps the dials for Live control: pick Sound, Vibrate or Shock,
// hold and drag on the pad -- the strength follows the finger, top = their
// strongest -- sent on change as a hold, like the PiShock panel's Remote
// mode. Same
// callbacks as ShockerCard (remote-shockers.js): both send the same message
// for the same press, and the receiver's engine is the last gate.

import { el, glyph } from "./remote-ui.js";
import { PARTY_CAPS } from "./remote-shockers.js";

const P = window.OGPRemoteProto;
const OS = P.OS;
const GLYPHS = { beep: "sound", vibrate: "waves", shock: "bolt" };
const HUES = { beep: "", vibrate: "pink", shock: "yellow" };
const TIPS = {
  beep: "Sound: a beep for the Duration",
  vibrate: "Vibrate at the Intensity for the Duration",
  shock: "Shock at the Intensity for the Duration",
};
const LIVE_TIPS = {
  beep: "Sound: Live control beeps while you hold the pad",
  vibrate: "Vibrate: Live control vibrates at the strength under your finger",
  shock: "Shock: Live control shocks at the strength under your finger",
};
const RUNNING_TIP = "Running - press it again to stop it";
const LIVE_TIP = "Live control: hold and drag on the pad, and the strength follows your finger "
  + "until you let go - top is their strongest. It holds the shocker like PiShock's Remote mode: "
  + "their caps, longest hold and the rest after it still hold, and it stops when you let go or "
  + "the link goes quiet.";
const secs = (ms) => `${+(ms / 1000).toFixed(3)}`;
const ARC = 270;

function hued(node, hue) {
  if (!hue) return node;
  node.style.setProperty("--hue", `var(--${hue})`);
  node.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
  node.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
  return node;
}

/** OpenShock's round slider (openshock_parts.Dial): a 270° arc open at the
 *  bottom, the value in the middle, the name under it. A press jumps the
 *  knob there; dragging past the bottom sticks at the end you came from. */
class Dial {
  constructor(name, hue, lo, hi, step, value, fmt, onInput) {
    this.name = name;
    this.lo = lo;
    this.hi = Math.max(lo, hi);
    this.step = step;
    this.fmt = fmt || String;
    this.onInput = onInput;
    this.v = this.snap(value);
    this.disabled = false;
    const NS = "http://www.w3.org/2000/svg";
    this.svg = document.createElementNS(NS, "svg");
    this.svg.setAttribute("viewBox", "0 0 100 100");
    this.svg.setAttribute("class", "dial-svg");
    this.track = document.createElementNS(NS, "path");
    this.track.setAttribute("class", "dial-track");
    this.fill = document.createElementNS(NS, "path");
    this.fill.setAttribute("class", "dial-fill");
    this.knob = document.createElementNS(NS, "circle");
    this.knob.setAttribute("class", "dial-knob");
    this.knob.setAttribute("r", "9.5");
    this.svg.append(this.track, this.fill, this.knob);
    this.track.setAttribute("d", this.arc(1));
    this.value = el("span.dial-v");
    this.root = hued(el("div.dial", { role: "slider", tabIndex: 0, "aria-label": name }, this.svg,
                        this.value, el("span.dial-l", {}, name)), hue);
    let last = null;
    const at = (ev) => {
      const r = this.svg.getBoundingClientRect();
      const angle = Math.atan2(ev.clientX - (r.left + r.width / 2), (r.top + r.height / 2) - ev.clientY)
        * 180 / Math.PI;
      return Math.max(0, Math.min(1, angle / ARC + 0.5));
    };
    this.root.addEventListener("pointerdown", (ev) => {
      if (this.disabled) return;
      ev.preventDefault();
      this.root.setPointerCapture(ev.pointerId);
      last = at(ev);
      this.byHand(this.lo + last * (this.hi - this.lo));
    });
    this.root.addEventListener("pointermove", (ev) => {
      if (last === null) return;
      let f = at(ev);
      if (Math.abs(f - last) > 0.5) {
        if (last > 0.75 && f < 0.25) f = 1;
        else if (last < 0.25 && f > 0.75) f = 0;
      }
      last = f;
      this.byHand(this.lo + f * (this.hi - this.lo));
    });
    const end = () => { last = null; };
    this.root.addEventListener("pointerup", end);
    this.root.addEventListener("pointercancel", end);
    this.root.addEventListener("keydown", (ev) => {
      const s = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[ev.key];
      if (s && !this.disabled) { ev.preventDefault(); this.byHand(this.v + s * this.step); }
    });
    this.paint();
  }
  snap(v) {
    const steps = Math.floor((v - this.lo) / this.step + 0.5);
    return Math.max(this.lo, Math.min(this.hi, this.lo + steps * this.step));
  }
  get val() { return this.v; }
  setQuiet(v) { this.v = this.snap(v); this.paint(); }
  setRange(lo, hi) { this.lo = lo; this.hi = Math.max(lo, hi); this.v = this.snap(this.v); this.paint(); }
  byHand(v) {
    v = this.snap(v);
    if (v === this.v) return;
    this.v = v;
    this.paint();
    if (this.onInput) this.onInput(v);
  }
  setDisabled(d) { this.disabled = d; this.root.classList.toggle("disabled", d); }
  frac() { return this.hi > this.lo ? (this.v - this.lo) / (this.hi - this.lo) : 0; }
  point(f) {
    const a = (-135 + ARC * f) * Math.PI / 180;
    return [50 + 40 * Math.sin(a), 50 - 40 * Math.cos(a)];
  }
  arc(f) {
    const [x0, y0] = this.point(0), [x1, y1] = this.point(f);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)}A40 40 0 ${ARC * f > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }
  paint() {
    const f = this.frac();
    // the knob right on the value: at the arc's very ends at lo and hi
    this.fill.setAttribute("d", f > 0 ? this.arc(f) : "");
    const [x, y] = this.point(f);
    this.knob.setAttribute("cx", x.toFixed(2));
    this.knob.setAttribute("cy", y.toFixed(2));
    this.value.textContent = this.fmt(this.v);
    this.root.setAttribute("aria-valuenow", this.v);
  }
}

/** Live control's pad (openshock_parts.LivePad): hold and drag, the
 *  strength follows the finger (top = the most), letting go drops it to 0.
 *  Behind the handle the last 3 s as a line moving left -- drawn only while
 *  it moves. onLevel(strength) on change, onRelease() on letting go. */
class LivePad {
  constructor(onLevel, onRelease) {
    this.onLevel = onLevel;
    this.onRelease = onRelease;
    this.cap = 100;
    this.y = 1;
    this.strength = 0;
    this.dragging = false;
    this.disabled = false;
    this.samples = [];
    this.eased = 0;
    this.raf = 0;
    this.canvas = el("canvas.pad-line");
    this.handle = el("span.pad-h", {}, "0%");
    this.root = el("div.pad", { role: "slider", tabIndex: 0, "aria-label": "Live intensity", title: LIVE_TIP },
                   this.canvas, this.handle);
    this.root.addEventListener("pointerdown", (ev) => {
      if (this.disabled) return;
      ev.preventDefault();
      this.root.setPointerCapture(ev.pointerId);
      this.dragging = true;
      this.root.classList.add("held");
      this.moved(this.yAt(ev));
      this.trace();
    });
    this.root.addEventListener("pointermove", (ev) => { if (this.dragging) this.moved(this.yAt(ev)); });
    const up = () => this.letGo();
    this.root.addEventListener("pointerup", up);
    this.root.addEventListener("pointercancel", up);
    this.root.addEventListener("keydown", (ev) => {
      const s = { ArrowUp: -1, ArrowRight: -1, ArrowDown: 1, ArrowLeft: 1 }[ev.key];
      if (!s || this.disabled) return;
      ev.preventDefault();
      this.moved(Math.max(0, Math.min(1, this.y + s * OS.LIVE_STEP)));
      this.trace();
    });
    this.root.addEventListener("blur", () => { if (!this.dragging && this.strength) this.letGo(); });
    this.paint();
  }
  yAt(ev) {
    const r = this.root.getBoundingClientRect(), k = 25;     // the handle sits flush with both ends
    return Math.max(0, Math.min(1, (ev.clientY - r.top - k) / Math.max(1, r.height - 2 * k)));
  }
  moved(y) {
    this.y = y;
    const s = P.liveStrength(y, this.cap);
    this.paint();
    if (s !== this.strength) { this.strength = s; this.paint(); this.onLevel(s); }
  }
  setCap(cap) {
    cap = Math.max(1, cap);
    if (cap === this.cap) return;
    this.cap = cap;
    if (this.dragging) this.moved(this.y);
    this.paint();
  }
  setHue(hue) {
    if (hue) { hued(this.root, hue); return; }
    this.root.style.setProperty("--hue", "var(--txt)");
    this.root.style.setProperty("--hue-mid", "var(--line)");
    this.root.style.setProperty("--hue-tint", "var(--hover)");
  }
  setDisabled(d) {
    this.disabled = d;
    this.root.classList.toggle("disabled", d);
    if (d && (this.dragging || this.strength)) this.letGo();
  }
  /** Back to the bottom, nothing held -- `quiet`: without calling back. */
  letGo(quiet = false) {
    const was = this.dragging || this.strength > 0;
    this.dragging = false;
    this.root.classList.remove("held");
    this.y = 1;
    this.strength = 0;
    this.paint();
    if (was && !quiet) this.onRelease();
  }
  paint() {
    this.root.style.setProperty("--y", this.y);
    this.handle.textContent = `${this.strength}%`;
  }
  trace() {
    if (this.raf) return;
    let lastT = performance.now();
    const step = (now) => {
      const dt = now - lastT;
      lastT = now;
      this.eased += (this.strength - this.eased) * (1 - Math.exp(-dt / 50));
      this.samples.push([now, this.eased]);
      while (this.samples.length && now - this.samples[0][0] > 3100) this.samples.shift();
      this.draw(now);
      if (!this.dragging && !this.strength && this.samples.every(([, v]) => v < 0.05)) {
        this.samples = [];
        this.eased = 0;
        this.draw(now);
        this.raf = 0;
        return;
      }
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  }
  draw(now) {
    const c = this.canvas, dpr = window.devicePixelRatio || 1;
    const w = Math.round(c.clientWidth * dpr), h = Math.round(c.clientHeight * dpr);
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    if (this.samples.length < 2) return;
    const k = 25 * dpr, top = k, bottom = h - k;
    const color = getComputedStyle(this.handle).backgroundColor;     // the hue it plays in
    const grad = ctx.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, "transparent");
    grad.addColorStop(0.4, color);
    grad.addColorStop(1, color);
    ctx.beginPath();
    this.samples.forEach(([t, v], i) => {
      const x = w - ((now - t) / 3000) * w, y = bottom - (Math.min(v, this.cap) / this.cap) * (bottom - top);
      if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.lineWidth = 3 * dpr;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.strokeStyle = grad;
    ctx.stroke();
  }
}

export class OpenShockCard {
  /** The ShockerCard contract: cb.onFire(op, intensity, length, warnMs,
   *  warnIntensity), onHold(op, intensity), onRelease(), onStop(). */
  constructor(title, cb, { party = false, partyBox = false } = {}) {
    this.cb = cb;
    this.party = party;
    this.caps = [...PARTY_CAPS];
    this.capsKnown = false;
    this.holdS = 0;
    this.blocked = false;
    this.ops = new Set(["shock", "vibrate", "beep"]);
    this.why = {};
    this.warnOk = true;
    this.active = "";
    this.activeTimer = null;
    this.live = false;
    this.liveOp = OS.LIVE_DEFAULT_OP;
    this.holding = "";

    this.partyBox = null;
    let partyLabel = null;
    if (partyBox) {
      this.partyBox = el("input.ck", { type: "checkbox" });
      partyLabel = el("label.partybox", { title: "Party Mode: drive this shocker together with the "
        + "others you tick - all at once, one at random or one after the other" }, this.partyBox, "Party");
    }
    this.liveTag = el("button.live-tag", { type: "button", onclick: () => this.toggleLive() }, "LIVE");
    this.whyLine = el("p.small.why");
    this.whyLine.hidden = true;
    this.lim = {
      int: el("span.os-lim", { title: "Max Intensity: the strongest you may send on this shocker - "
        + "its own cap on their side" }, glyph("gauge", 14), el("span")),
      dur: el("span.os-lim", { title: "Max Duration: their longest pulse" }, glyph("clock", 14), el("span")),
    };
    const [lo, hi] = P.durationRange(PARTY_CAPS[2]);
    this.intensity = new Dial("Intensity", "yellow", 1, 100, 1, OS.INTENSITY_DEFAULT, String,
                              () => this.showValues());
    this.intensity.root.title = "Intensity: how strong Vibrate and Shock are - up to their max, each "
      + "stopping at its own";
    this.duration = new Dial("Duration", "yellow", lo, hi, OS.DURATION_STEP_MS, OS.DURATION_DEFAULT_MS,
                             secs, () => this.showValues());
    this.duration.root.title = "Duration: how long a press runs, in seconds - from 0.3 s up to their "
      + "longest pulse";
    const button = (op) => hued(el("button.osb", { type: "button", "aria-label": OS.OP_NAMES[op] },
                                   glyph(GLYPHS[op], 18)), HUES[op]);
    this.buttons = {};
    this.liveTypes = {};
    for (const op of OS.OPS) {
      this.buttons[op] = button(op);
      this.buttons[op].onclick = () => this.press(op);
      this.liveTypes[op] = button(op);
      this.liveTypes[op].onclick = () => this.livePick(op);
    }
    this.pad = new LivePad((s) => this.liveLevel(s), () => this.liveLetGo());
    this.classic = el("div.os-classic", {},
      el("div.os-dials", {}, this.intensity.root, this.duration.root),
      el("div.os-buttons", {}, OS.OPS.map((op) => this.buttons[op])));
    this.liveBox = el("div.os-live", {},
      el("div.os-buttons", {}, OS.OPS.map((op) => this.liveTypes[op])), this.pad.root);
    this.root = el("div.fcard.shocker.oscard", {},
      el("div.card-head", {}, title ? el("span.card-name", {}, title) : null, el("span.grow"),
         partyLabel, this.liveTag),
      this.whyLine,
      el("div.os-limits", {}, this.lim.int, this.lim.dur),
      this.classic, this.liveBox);
    this.showControls();
  }

  // -- numbers
  cap(op) { return Math.max(1, op === "vibrate" ? this.caps[1] : this.caps[0]); }
  strength(op) { return Math.min(this.intensity.val, this.cap(op)); }
  length() { return P.lengthFraction(this.duration.val, this.caps[2]); }

  // -- showing
  showValues() {
    const s = this.cap("shock"), v = this.cap("vibrate");
    this.lim.int.lastChild.textContent = s === v ? `${s}%` : `Shock ${s}% · Vibrate ${v}%`;
    this.lim.dur.lastChild.textContent = `${secs(this.caps[2])} s`;
  }
  showControls() {
    const ops = this.ops;
    for (const op of OS.OPS) {
      const ok = ops.has(op) && !this.blocked;
      const why = !ops.has(op) ? (this.why[op] || "") : "";
      for (const [group, tips] of [[this.buttons, TIPS], [this.liveTypes, LIVE_TIPS]]) {
        const b = group[op];
        b.disabled = !ok;
        let tip = why || tips[op];
        if (group === this.buttons && op === this.active) tip = RUNNING_TIP;
        b.title = tip;
      }
      this.buttons[op].classList.toggle("on", op === this.active);
      this.buttons[op].replaceChildren(glyph(op === this.active ? "stop" : GLYPHS[op], 18));
      this.buttons[op].classList.toggle("running", op === this.active);
      this.liveTypes[op].classList.toggle("on", op === this.liveOp);
    }
    this.intensity.setDisabled(!(ops.has("shock") || ops.has("vibrate")));
    this.duration.setDisabled(!ops.size);
    this.liveTag.title = LIVE_TIP;
    this.liveTag.classList.toggle("on", this.live);
    this.pad.setDisabled(!(ops.has(this.liveOp) && !this.blocked));
    this.pad.setHue(HUES[this.liveOp]);
    this.pad.setCap(this.liveOp !== "beep" ? this.cap(this.liveOp) : 100);
    const lines = [...new Set(["shock", "vibrate", "beep"].filter((o) => !ops.has(o) && this.why[o])
                                                         .map((o) => this.why[o]))];
    this.whyLine.textContent = lines.length ? `${lines.join(". ")}.` : "";
    this.whyLine.hidden = !lines.length;
    this.classic.hidden = this.live;
    this.liveBox.hidden = !this.live;
    this.showValues();
  }
  /** [shock cap, vibrate cap, longest pulse ms] on their side. Before the
   *  first, the card stands in percent; then the Intensity starts where
   *  that percentage was. */
  setCaps(caps, holdS = 0) {
    caps = caps && caps.length === 3 ? caps : PARTY_CAPS;
    if (caps.join() === this.caps.join() && holdS === this.holdS) return;
    const first = !this.capsKnown && caps.join() !== PARTY_CAPS.join();
    const prev = this.caps;
    this.caps = [...caps];
    this.holdS = holdS;
    this.capsKnown = this.capsKnown || caps.join() !== PARTY_CAPS.join();
    const top = Math.max(this.cap("shock"), this.cap("vibrate")), old = Math.max(1, prev[0], prev[1]);
    const v = this.intensity.val;
    this.intensity.setRange(1, top);
    this.intensity.setQuiet(first ? Math.round(v * top / old) : v);
    const [lo, hi] = P.durationRange(caps[2]);
    this.duration.setRange(lo, hi);
    this.showControls();
  }
  /** What that shocker's own switches let you do -- the ShockerCard
   *  contract (the app's OpenShockCard.set_rules). */
  setRules(ops, why = {}, warnOk = true) {
    ops = new Set(ops);
    why = Object.fromEntries(Object.entries(why || {}).filter(([k, text]) =>
      text && (k === "warn" ? !warnOk : !ops.has(k))));
    const same = ops.size === this.ops.size && [...ops].every((o) => this.ops.has(o))
      && JSON.stringify(why) === JSON.stringify(this.why);
    if (same && !!warnOk === this.warnOk) return;
    this.ops = ops;
    this.why = why;
    this.warnOk = !!warnOk;
    if (this.holding && !this.ops.has(this.holding)) this.release();
    this.showControls();
  }
  setBlocked(blocked) {
    if (blocked === this.blocked) return;
    this.blocked = blocked;
    if (blocked) this.release();
    this.showControls();
  }

  // -- the hand: Classic
  press(op) {
    if (this.blocked || !this.ops.has(op)) return;
    if (op === this.active) { this.stopNow(); return; }      // pressed again: OpenShock's Stop
    if (op === "beep") {
      this.cb.onFire("beep", 0, this.length(), 0, 0);
    } else {
      const s = this.strength(op);
      this.cb.onFire(op, P.toFraction(s, this.cap(op)), this.length(), 0,
                     P.toFraction(Math.min(s, this.cap("vibrate")), this.cap("vibrate")));
    }
    this.active = op;
    clearTimeout(this.activeTimer);
    this.activeTimer = setTimeout(() => { this.active = ""; this.showControls(); },
                                  Math.max(1, this.duration.val));
    this.showControls();
  }
  stopNow() {
    clearTimeout(this.activeTimer);
    this.active = "";
    if (this.holding) { this.holding = ""; this.pad.letGo(true); }
    this.cb.onStop();
    this.showControls();
  }

  // -- the hand: Live control
  toggleLive() {
    if (this.live) this.release();
    this.live = !this.live;
    this.showControls();
  }
  livePick(op) {
    if (!this.ops.has(op)) return;
    this.liveOp = op;
    // the pad tops out at this op's cap now (a finger on it moves with that,
    // and liveLevel sends it) ... else still holding: the new one at once
    this.showControls();
    if (this.holding && this.holding !== op && this.pad.strength > 0) {
      this.holding = op;
      this.cb.onHold(op, this.liveFraction(this.pad.strength));
    }
  }
  liveFraction(s) {
    return this.liveOp === "beep" ? 0 : P.toFraction(Math.min(s, this.cap(this.liveOp)), this.cap(this.liveOp));
  }
  liveLevel(s) {
    const op = this.liveOp;
    if (this.blocked || !this.ops.has(op) || !this.live) return;
    if (s <= 0) {
      if (this.holding) { this.holding = ""; this.cb.onRelease(); }
      return;
    }
    this.holding = op;
    this.cb.onHold(op, this.liveFraction(s));
  }
  liveLetGo() { if (this.holding) { this.holding = ""; this.cb.onRelease(); } }

  // -- the panel
  stop() { this.stopNow(); }
  release() {
    this.pad.letGo(true);
    if (this.holding) { this.holding = ""; this.cb.onRelease(); }
  }
  settings() {
    return { layout: "openshock", intensity: this.intensity.val, duration: this.duration.val,
             live: this.live, liveOp: this.liveOp };
  }
  restore(st) {
    if (!st || st.layout !== "openshock") return;          // a PiShock card's: start fresh
    this.intensity.setQuiet(st.intensity);
    this.duration.setQuiet(st.duration);
    this.liveOp = st.liveOp || OS.LIVE_DEFAULT_OP;
    this.live = Boolean(st.live);
    this.showControls();
  }
}
