// Their avatar on the web remote: the board they built on their Avatar
// Remote page for the avatar they wear -- src/ui/views/friends_board.py and
// param_cards.py, ported. Their categories and cards as they have them; a
// locked category is look-only; with their ⚡ YOLO on, a list of every
// parameter follows, filterable. The page tells their OGP it is watching
// (only then does it send the board and its values).

import { el, hslider } from "./remote-ui.js";

const P = window.OGPRemoteProto;
const YOLO_ROWS = 60;
const SLIDER_STEPS = 1000;

function hued(node, hue) {
  node.style.setProperty("--hue", `var(--${hue})`);
  node.style.setProperty("--hue-mid", `var(--${hue}-mid)`);
  node.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
  return node;
}

/** One control: toggle (ON/OFF), button (Hold), slider, int (a stepper). */
class ParamCard {
  constructor(c, hue, { onSet, onHold }) {
    this.c = c;
    this.ownUntil = 0;
    const marks = [];
    if (c.invert) marks.push(el("span.pmark", { title: "Inverted - ON sends the parameter OFF" }, "⇄"));
    if (P.isIntSwitch(c)) {
      const [on, off] = P.intSwitchValues(c);
      const toggle = c.kind === "toggle";
      marks.push(el("span.pval", { title: `${toggle ? "ON" : "Holding"} sets ${c.param} to ${on}, `
        + `${toggle ? "OFF" : "letting go"} sets it to ${off}` }, `=${on}`));
    }
    const head = el("div.pc-head", {}, el("span.pc-label", { title: `${c.param}  (${c.ptype})` }, c.label || c.param), ...marks);
    this.root = hued(el("div.pcard"), hue);
    if (c.kind === "toggle") {
      this.sw = el("button.pswitch", { type: "button", onclick: () => {
        const on = !this.sw.classList.contains("on");
        this.showToggle(on);
        onSet(c.id, on);
      } }, "OFF");
      this.root.append(head, this.sw);
    } else if (c.kind === "button") {
      const b = el("button.phold", { type: "button" }, "Hold");
      const down = (ev) => { if (b.disabled) return; b.setPointerCapture(ev.pointerId); b.classList.add("down"); onHold(c.id, true); };
      const up = () => { if (!b.classList.contains("down")) return; b.classList.remove("down"); onHold(c.id, false); };
      b.addEventListener("pointerdown", down);
      b.addEventListener("pointerup", up);
      b.addEventListener("pointercancel", up);
      this.hold = b;
      this.root.append(head, b);
    } else if (c.kind === "slider") {
      this.vmin = Number(c.min !== undefined ? c.min : 0);
      this.vmax = Number(c.max !== undefined ? c.max : 1);
      this.val = el("span.pval", {}, "–");
      let timer = null;
      const send = () => { timer = null; onSet(c.id, this.sliderValue()); };
      this.slider = hslider({ max: SLIDER_STEPS, hue, onInput: () => {
        this.val.textContent = this.sliderValue().toFixed(2);
        if (!timer) timer = setTimeout(send, 60);
      }, onChange: send });
      this.root.append(head, el("div.row", {}, this.slider, this.val));
    } else {
      const lo = Math.trunc(Number(c.min !== undefined ? c.min : 0));
      const hi = Math.trunc(Number(c.max !== undefined ? c.max : 255));
      this.num = el("input.pnum", { type: "number", min: lo, max: hi, step: 1, value: lo });
      let timer = null;
      const later = () => { clearTimeout(timer); timer = setTimeout(() => { timer = null; onSet(c.id, Number(this.num.value)); }, 150); };
      this.numTimer = () => timer;
      const step = (d) => {
        this.num.value = String(Math.max(lo, Math.min(hi, Number(this.num.value || lo) + d)));
        later();
      };
      this.num.addEventListener("input", later);
      this.root.append(head, el("div.stepper", {},
        el("button.mini", { type: "button", onclick: () => step(-1) }, "−"), this.num,
        el("button.mini", { type: "button", onclick: () => step(+1) }, "+")));
    }
  }
  sliderValue() { return this.vmin + (this.slider.value / SLIDER_STEPS) * (this.vmax - this.vmin); }
  showToggle(on) { this.sw.classList.toggle("on", on); this.sw.textContent = on ? "ON" : "OFF"; }
  setDisabled(d) {
    this.root.classList.toggle("look", d);
    for (const x of this.root.querySelectorAll("button, input")) x.disabled = d;
  }
  update(value) {
    const c = this.c;
    if (c.kind === "toggle") this.showToggle(P.showsOn(c, value));
    else if (c.kind === "slider" && value !== null && value !== undefined) {
      if (this.slider.busy) return;
      const span = (this.vmax - this.vmin) || 1;
      this.slider.setQuiet(Math.round(((Number(value) - this.vmin) / span) * SLIDER_STEPS));
      this.val.textContent = Number(value).toFixed(2);
    } else if (c.kind === "int" && value !== null && value !== undefined) {
      // only hold off while your own change is on its way out (or half typed)
      if (this.numTimer() || document.activeElement === this.num) return;
      this.num.value = String(Math.round(Number(value)));
    }
  }
}

export class Board {
  /** cb: onSet(controlId, value), onHold(controlId, held), onSetAny(name, value) */
  constructor(cb) {
    this.cb = cb;
    this.key = null;
    this.cards = {};
    this.cats = {};
    this.yoloRows = {};
    this.yoloOpen = false;
    this.yoloFilter = "";
    this.yoloAll = false;
    this.note = el("span.small");
    this.body = el("div.board");
    this.root = el("div", {}, this.body);
  }

  /** prm (their st.prm), board (null until it came), values {param: v} */
  update(prm, board, values) {
    const shape = board ? JSON.stringify([board.categories.map((c) => [c.id, c.color]),
                                          board.controls, board.all]) : null;
    const key = JSON.stringify([Boolean(prm.ver), prm.stop, prm.yolo, shape, this.yoloOpen]);
    if (key !== this.key) {
      this.key = key;
      this.rebuild(prm, board, values);
    } else if (board) {
      for (const cat of board.categories) {
        const box = this.cats[cat.id];
        if (box) box.setState(cat.name, cat.locked, prm.stop);
      }
    }
    let note = board && board.name ? board.name : "";
    if (prm.stop) note = (note ? `${note} · ` : "") + "paused - they paused all friends";
    this.note.textContent = note;
    for (const card of Object.values(this.cards)) {
      if (card.c.param in values) card.update(values[card.c.param]);
    }
    for (const [name, show] of Object.entries(this.yoloRows)) {
      if (name in values && values[name] !== null) show(values[name]);
    }
  }

  rebuild(prm, board, values) {
    this.body.replaceChildren();
    this.cards = {};
    this.cats = {};
    this.yoloRows = {};
    const muted = (t) => el("p.small", {}, t);
    if (!prm.ver) {
      this.body.append(muted("They aren't wearing an avatar right now (VRChat isn't running on their side)."));
      return;
    }
    if (!board) { this.body.append(muted("Getting their board…")); return; }
    if (!board.controls.length && board.all === null) {
      this.body.append(muted("Nothing on this avatar's board yet - they add controls on their Avatar Remote page."));
    }
    for (const cat of board.categories) {
      const controls = board.controls.filter((x) => x.cat === cat.id);
      if (!controls.length) continue;
      const name = el("span.cat-name", {}, cat.name);
      const lock = el("span.cat-lock", { title: "Locked - for looking only" }, "🔒 look only");
      const grid = el("div.cat-grid");
      const box = hued(el(`div.cat.${cat.color}`), cat.color);
      box.append(el("div.cat-head", {}, name, lock), grid);
      const cards = controls.map((c) => {
        const card = new ParamCard(c, cat.color, { onSet: this.cb.onSet, onHold: this.cb.onHold });
        if (c.param in values) card.update(values[c.param]);
        this.cards[c.id] = card;
        grid.append(card.root);
        return card;
      });
      box.setState = (n, locked, stopped) => {
        name.textContent = n;
        lock.hidden = !locked;
        box.classList.toggle("locked", locked);
        cards.forEach((card) => card.setDisabled(locked || stopped));
      };
      box.setState(cat.name, cat.locked, prm.stop);
      this.cats[cat.id] = box;
      this.body.append(box);
    }
    if (board.all !== null) this.yolo(board, values, prm.stop);
  }

  // ---- ⚡ YOLO: every parameter
  yolo(board, values, stopped) {
    const fold = el("button.yolo", { type: "button", title: "They turned YOLO on: every parameter of "
      + "their avatar is yours to set, locks or not (VRChat's own, like Viseme, aside).",
      onclick: () => { this.yoloOpen = !this.yoloOpen; this.yoloAll = false; this.key = null; this.onFold && this.onFold(); } },
      this.yoloOpen ? "⚡ Every parameter ▾" : `⚡ Every parameter (${board.all.length}) ▸`);
    this.body.append(el("div.row", {}, fold));
    if (!this.yoloOpen) return;
    const filt = el("input.filter", { type: "search", placeholder: "Filter parameters…", value: this.yoloFilter });
    const rows = el("div.yolo-rows");
    const more = el("span.small");
    const showAll = el("button.btn.secondary", { type: "button" });
    const moreRow = el("div.row", {}, more, showAll);
    this.body.append(filt, rows, moreRow);
    const fill = () => {
      rows.replaceChildren();
      this.yoloRows = {};
      const needle = this.yoloFilter.toLowerCase();
      const match = board.all.filter(([n]) => !needle || n.toLowerCase().includes(needle));
      const shown = this.yoloAll ? match.length : YOLO_ROWS;
      for (const [name, ptype] of match.slice(0, shown)) rows.append(this.yoloRow(name, ptype, values[name], stopped));
      const extra = match.length - shown;
      more.textContent = extra > 0 ? `${extra} more - type to find them, or` : "";
      showAll.textContent = `Show all ${match.length}`;
      moreRow.hidden = extra <= 0;
    };
    showAll.onclick = () => { this.yoloAll = true; fill(); };
    let timer = null;
    filt.addEventListener("input", () => {
      this.yoloFilter = filt.value.trim();
      clearTimeout(timer);
      timer = setTimeout(fill, 200);
    });
    fill();
  }
  yoloRow(name, ptype, value, stopped) {
    const row = el("div.yrow", {}, el("span.yname", { title: `${name} (${ptype})` }, name));
    let show;
    if (ptype === "Bool") {
      const sw = el("button.pswitch.ysw", { type: "button" }, "OFF");
      show = (v) => { sw.classList.toggle("on", Boolean(v)); sw.textContent = v ? "ON" : "OFF"; };
      sw.onclick = () => { const on = !sw.classList.contains("on"); show(on); this.cb.onSetAny(name, on); };
      row.append(sw);
    } else if (ptype === "Int") {
      const num = el("input.pnum", { type: "number", min: 0, max: 255, step: 1 });
      let timer = null;
      num.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => { timer = null; this.cb.onSetAny(name, Number(num.value)); }, 150);
      });
      show = (v) => { if (!timer && document.activeElement !== num) num.value = String(Math.round(Number(v))); };
      row.append(num);
    } else {
      const val = el("span.pval", {}, "–");
      let timer = null;
      const s = hslider({ min: -100, max: 100, hue: "green", onInput: (x) => {
        val.textContent = (x / 100).toFixed(2);
        if (!timer) timer = setTimeout(() => { timer = null; this.cb.onSetAny(name, s.value / 100); }, 60);
      }, onChange: (x) => this.cb.onSetAny(name, x / 100) });
      show = (v) => { if (!s.busy) { s.setQuiet(Math.round(Number(v) * 100)); val.textContent = Number(v).toFixed(2); } };
      row.append(s, val);
    }
    if (value !== null && value !== undefined) show(value);
    if (stopped) for (const x of row.querySelectorAll("button, input")) x.disabled = true;
    this.yoloRows[name] = show;
    return row;
  }
}
