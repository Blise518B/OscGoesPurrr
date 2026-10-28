// A toy card on the web remote: src/ui/views/toy_card.py's ToyCard, ported.
//
// Modes: Off (the toy at 0 -- the card then only asks you to pick one),
// Direct control (the level you set), the auto modes (Sine, Square,
// Triangle, Saw, Random, Heartbeat, Build-up) with speed and a low-high
// range, and Oscillate (a swing around your level, as deep as you set). The
// receiving OGP plays an auto mode by itself from the numbers sent; the
// graph shows what you send. Higher / Override decides how your level meets
// their own output.

import { el, hslider, pct, segmented, waveIcon } from "./remote-ui.js";

const P = window.OGPRemoteProto;
const DEFAULT_PERIOD = { sine: 2.0, square: 1.0, triangle: 2.0, saw: 2.0, random: 1.5,
                         heart: 1.0, build: 30.0, osc: 2.0 };
const MODES = ["off", "linear", ...P.WAVES];
const FIRST_ROW = ["off", "linear", "random"];
const GRAPH_S = 6.0;
const now = () => performance.now() / 1000;

export class ToyCard {
  /** callbacks: onLevel(v), onOverride(on), onPattern(wave, period, lo, hi) -- wave "" for none */
  constructor(toy, title, { onLevel, onOverride, onPattern, meter = true }) {
    this.toy = toy;
    this.cb = { onLevel, onOverride, onPattern };
    this.mode = "off";
    this.level = 0.0;                        // Direct control's, kept while other modes run
    this.period = 2.0;
    this.lo = 0.2;
    this.hi = 0.8;
    this.center = 0.5;                       // Oscillate
    this.depth = 0.2;
    this.t0 = this.ts = now();
    this.ph0 = 0.0;
    this.hist = [];

    this.out = el("span.small");
    this.battery = el("span.small.battery", { title: "Their toy's battery", hidden: true });
    this.over = segmented(["Higher", "Override"], "pink", (i) => this.cb.onOverride(i === 1));
    this.over.title = "Higher: whichever is higher, their own output (SPS, contacts) or yours, "
      + "wins. Override: while you drive this, yours replaces theirs. Their Off, Pause, "
      + "strength and the toy's max still hold.";
    this.hint = el("div.small", {}, "Select a waveform to begin");

    this.levelS = hslider({ max: 1000, hue: "pink", onInput: (x) => this.levelMoved(x) });
    this.levelL = el("span.val");
    this.levelRow = el("div.row", {}, this.levelS, this.levelL);
    this.depthS = hslider({ max: 500, hue: "pink", onInput: (x) => this.depthMoved(x) });
    this.depthL = el("span.val.w62");
    this.depthRow = el("div.row", {}, el("span.small", {}, "depth"), this.depthS, this.depthL);
    this.loS = hslider({ max: 1000, hue: "pink", onInput: () => this.rangeMoved() });
    this.hiS = hslider({ max: 1000, hue: "pink", onInput: () => this.rangeMoved() });
    this.rangeL = el("span.val.w62");
    this.rangeRow = el("div.row", {}, el("span.small", {}, "low"), this.loS,
                       el("span.small", {}, "high"), this.hiS, this.rangeL);

    this.chips = {};
    const chip = (mode) => {
      const label = { off: "Off", linear: "Direct control", random: "Random" }[mode];
      const tip = mode === "off" ? "Off: their toy at 0"
        : mode === "linear" ? "Direct control: the level you set with the slider"
        : mode === "osc" ? "Oscillate: a swing around the level you set, as deep as you set"
        : `Auto mode: ${P.WAVE_LABELS[mode]}`;
      const b = el(`button.chip${FIRST_ROW.includes(mode) ? ".main" : ""}`,
                   { type: "button", title: tip, onclick: () => this.pick(mode) },
                   mode === "off" ? null : waveIcon(mode), label || null);
      this.chips[mode] = b;
      return b;
    };
    const main = el("div.chips", {}, FIRST_ROW.map(chip));
    const waves = el("div.chips", {}, MODES.filter((m) => !FIRST_ROW.includes(m)).map(chip));

    // right = faster: the slider runs the other way to the period
    this.speedS = hslider({ max: 1000, hue: "pink", onInput: (x) => this.speedMoved(1000 - x) });
    this.speedL = el("span.val.w62");
    this.speedRow = el("div.row", {}, el("span.small", {}, "speed"), this.speedS, this.speedL);

    this.graph = el("canvas.graph", { title: "What you send: the level their toy gets, straight - "
      + "no chain or smoothing on their side (their strength, Off and the toy's max still apply)" });
    this.meter = meter ? el("div.meter", { title: "What this toy is doing on their side right now" },
                            el("span")) : null;

    this.root = el("div.card.toy", {},
      el("div.card-head", {}, el("span.card-name", {}, title), this.out, this.battery,
         el("span.grow"), this.over),
      this.hint, this.levelRow, this.depthRow, this.rangeRow, main, waves, this.speedRow,
      this.graph, this.meter);
    this.showMode();
  }

  // -- what the mode plays (also here, for the graph)
  pattern() {
    if (this.mode === "off" || this.mode === "linear") return null;
    if (this.mode === "osc") {
      return P.cleanPattern("osc", this.period, Math.max(0, this.center - this.depth),
                            Math.min(1, this.center + this.depth));
    }
    return P.cleanPattern(this.mode, this.period, this.lo, this.hi);
  }
  sample() {
    const pat = this.pattern();
    if (!pat) return this.mode === "linear" ? this.level : 0.0;
    const t = now();
    return P.patternLevel(pat, t - this.ts, this.ph0 + (t - this.t0) / pat[1]);
  }
  restartCycle() { this.t0 = this.ts = now(); this.ph0 = 0.0; }
  keepCycle(period) {
    const t = now();
    this.ph0 += (t - this.t0) / Math.max(0.01, this.period);
    this.t0 = t;
    this.period = period;
  }

  // -- the hand
  pick(mode) {
    const was = this.mode;
    this.mode = mode;
    if (mode === "off") {
      this.cb.onPattern("", this.period, 0, 0);
      this.cb.onLevel(0);
    } else if (mode === "linear") {
      this.cb.onPattern("", this.period, 0, 0);
      this.cb.onLevel(this.level);
    } else {
      if (mode !== was) {
        this.period = DEFAULT_PERIOD[mode] || 2.0;
        this.restartCycle();
        if (mode === "osc") this.center = this.level > 0 ? this.level : 0.5;
      }
      this.cb.onLevel(0);                    // the mode is the level now
      this.sendPattern();
    }
    this.showMode();
  }
  levelMoved(x) {
    const v = x / 1000;
    this.levelL.textContent = pct(v);
    if (this.mode === "osc") { this.center = v; this.sendPattern(); return; }
    this.level = v;
    if (this.mode === "linear") this.cb.onLevel(v);
  }
  depthMoved(x) {
    this.depth = x / 1000;
    this.depthL.textContent = `± ${Math.round(this.depth * 100)} %`;
    this.sendPattern();
  }
  rangeMoved() {
    this.lo = this.loS.value / 1000;
    this.hi = this.hiS.value / 1000;
    const [a, b] = [this.lo, this.hi].sort((p, q) => p - q);
    this.rangeL.textContent = `${Math.round(a * 100)}–${Math.round(b * 100)} %`;
    this.sendPattern();
  }
  speedMoved(x) {
    this.keepCycle(P.sliderToPeriod(x));
    this.speedL.textContent = P.fmtPeriod(this.period);
    this.sendPattern();
  }
  sendPattern() {
    const pat = this.pattern();
    if (pat) this.cb.onPattern(...pat);
  }

  // -- showing
  showMode() {
    const mode = this.mode;
    const auto = mode !== "off" && mode !== "linear";
    this.hint.hidden = mode !== "off";
    this.levelRow.hidden = !(mode === "linear" || mode === "osc");
    this.depthRow.hidden = mode !== "osc";
    this.rangeRow.hidden = !(auto && mode !== "osc");
    this.speedRow.hidden = !auto;
    this.graph.hidden = !auto;
    if (this.meter) this.meter.hidden = mode !== "linear";
    if (!auto) this.hist = [];
    const lv = mode === "osc" ? this.center : this.level;
    if (!this.levelS.busy) this.levelS.setQuiet(Math.round(lv * 1000));
    this.levelL.textContent = pct(lv);
    this.depthS.setQuiet(Math.round(this.depth * 1000));
    this.depthL.textContent = `± ${Math.round(this.depth * 100)} %`;
    this.loS.setQuiet(Math.round(this.lo * 1000));
    this.hiS.setQuiet(Math.round(this.hi * 1000));
    this.rangeL.textContent = `${Math.round(this.lo * 100)}–${Math.round(this.hi * 100)} %`;
    this.speedS.setQuiet(1000 - P.periodToSlider(this.period));
    this.speedL.textContent = P.fmtPeriod(this.period);
    for (const [m, b] of Object.entries(this.chips)) b.classList.toggle("on", m === mode);
  }
  setBattery(pctValue) {
    const has = pctValue !== undefined && pctValue !== null;
    this.battery.hidden = !has;
    if (has) {
      this.battery.textContent = `🔋 ${pctValue} %`;
      this.battery.classList.toggle("low", pctValue <= 20);
    }
  }
  busy() {
    return [this.levelS, this.depthS, this.loS, this.hiS, this.speedS].some((s) => s.busy);
  }
  /** What is set (the shared panel, or what came back) and what the toy
   *  does -- never under the hand. */
  setState(level, override, pattern, output) {
    if (output !== null && output !== undefined) {
      this.out.textContent = `out ${Math.round(output * 100)} %`;
      if (this.meter) this.meter.firstChild.style.width = `${Math.round(output * 100)}%`;
    }
    if (this.busy()) return;
    if (this.over.picked !== (override ? 1 : 0)) this.over.set(override ? 1 : 0);
    let mode;
    if (pattern) {
      mode = pattern[0];
      if (mode !== this.mode) this.restartCycle();
      this.period = pattern[1];
      if (mode === "osc") {
        this.center = (pattern[2] + pattern[3]) / 2;
        this.depth = (pattern[3] - pattern[2]) / 2;
      } else {
        this.lo = pattern[2];
        this.hi = pattern[3];
      }
    } else if (level > 0) {
      mode = "linear";
      this.level = level;
    } else if (this.mode === "off" || this.mode === "linear") {
      mode = this.mode;
      if (mode === "linear") this.level = level;
    } else {
      mode = "linear";                       // an auto mode ended elsewhere
    }
    const changed = mode !== this.mode;
    this.mode = mode;
    if (changed || pattern || level > 0) this.showMode();
  }
  /** Drawn by the page's timer while an auto mode plays. */
  tick() {
    if (this.graph.hidden) return;
    const t = now();
    this.hist.push([t, this.sample()]);
    while (this.hist.length && t - this.hist[0][0] > GRAPH_S) this.hist.shift();
    const c = this.graph, dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (!w || !h) return;
    if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    if (this.hist.length < 2) return;
    g.strokeStyle = getComputedStyle(this.root).getPropertyValue("--pink").trim();
    g.lineWidth = 2;
    g.lineJoin = "round";
    g.beginPath();
    this.hist.forEach(([ht, v], i) => {
      const x = w - 2 - ((t - ht) / GRAPH_S) * (w - 4);
      const y = h - 3 - Math.max(0, Math.min(1, v)) * (h - 6);
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    });
    g.stroke();
  }
}
