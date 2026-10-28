// The web remote's building blocks: a few DOM helpers in the app's look
// (docs/remote.html styles them), and the app's glyphs as SVG -- the same
// shapes as src/ui/icons.py's glyph_icon and wave_icon, so a card reads the
// same in the browser as in OGP.

const P = window.OGPRemoteProto;

/** el("div.card.toy", {title: "x", onclick: fn}, child, "text", ...) */
export function el(spec, attrs, ...kids) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k in node && k !== "list") node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export const pct = (v) => `${Math.round(v * 100)} %`;

/** A horizontal slider in the app's look: groove, round handle, fill up to
 *  the handle -- reaching both ends. Integer `min`..`max`. */
export function hslider({ min = 0, max = 1000, value = 0, hue = "pink", onInput, onChange, title }) {
  const input = el("input.hs", { type: "range", min, max, step: 1, value, title });
  input.style.setProperty("--fill", `var(--${hue})`);
  const paint = () => {
    const span = Number(input.max) - Number(input.min) || 1;
    input.style.setProperty("--v", `${((Number(input.value) - Number(input.min)) / span) * 100}%`);
  };
  input.addEventListener("input", () => { paint(); onInput && onInput(Number(input.value)); });
  input.addEventListener("change", () => onChange && onChange(Number(input.value)));
  input.setQuiet = (v) => { input.value = v; paint(); };
  input.busy = false;
  input.addEventListener("pointerdown", () => { input.busy = true; });
  window.addEventListener("pointerup", () => { input.busy = false; });
  paint();
  return input;
}

/** Buttons side by side, one picked. onPick(index). */
export function segmented(labels, hue, onPick, picked = 0) {
  const box = el("div.seg");
  const buttons = labels.map((label, i) => el("button.seg-b", {
    type: "button", onclick: () => { set(i); onPick(i); },
  }, label));
  box.style.setProperty("--hue", `var(--${hue})`);
  box.style.setProperty("--hue-tint", `var(--${hue}-tint)`);
  function set(i) { buttons.forEach((b, k) => b.classList.toggle("on", k === i)); box.picked = i; }
  box.append(...buttons);
  box.set = set;
  set(picked);
  return box;
}

/** The app's ToggleSwitch: a pill with a knob, and its label. */
export function toggle(label, on, onChange, title) {
  const box = el("label.sw", { title });
  const input = el("input", { type: "checkbox", checked: on });
  input.addEventListener("change", () => onChange(input.checked));
  box.append(input, el("span.knob"), el("span.sw-l", {}, label));
  box.input = input;
  box.set = (v) => { input.checked = Boolean(v); };
  return box;
}

// ---- glyphs (src/ui/icons.py glyph_icon, 16-unit grid) -----------------------
const SVGNS = "http://www.w3.org/2000/svg";
function svg(viewBox, inner, size) {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("viewBox", viewBox);
  s.setAttribute("width", size);
  s.setAttribute("height", size);
  s.setAttribute("class", "glyph");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = inner;
  return s;
}
const ST = 'fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"';
const GLYPHS = {
  bolt: '<path fill="currentColor" d="M9.5 .5 3 9h4.5L6 15.5 13 6.5H8.5z"/>',
  vibrate: `<g ${ST} stroke-width="1.5"><rect x="5" y="2" width="6" height="12" rx="1.5"/>`
    + '<path d="M2.5 4 1.3 6 2.5 8 1.3 10 2.5 12M13.5 4l1.2 2-1.2 2 1.2 2-1.2 2"/></g>',
  bell: `<g ${ST} stroke-width="1.5"><path d="M3 12c1.5-2 1-9 5-9s3.5 7 5 9z"/><path d="M6.5 14.5h3"/></g>`,
  dice: `<rect ${ST} stroke-width="1.4" x="2" y="2" width="12" height="12" rx="2.5"/>`
    + '<g fill="currentColor"><circle cx="5" cy="5" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="11" cy="11" r="1.3"/></g>',
  up: `<path ${ST} stroke-width="1.6" d="M4 8l4-4 4 4M4 13l4-4 4 4"/>`,
  down: `<path ${ST} stroke-width="1.6" d="M4 3l4 4 4-4M4 8l4 4 4-4"/>`,
  clock: `<g ${ST} stroke-width="1.5"><circle cx="8" cy="8" r="6.2"/><path d="M8 4.2V8l2.8 1.6"/></g>`,
  alert: `<g ${ST} stroke-width="1.5"><circle cx="8" cy="8" r="4.6"/><path d="M8 5.6v3"/>`
    + '<path d="M3.2 2.6a7 7 0 0 0 0 10.8M12.8 2.6a7 7 0 0 1 0 10.8"/></g><circle fill="currentColor" cx="8" cy="10.6" r=".9"/>',
  tap: '<g fill="currentColor"><rect x="5.6" y="1" width="3" height="9" rx="1.5"/><rect x="4" y="7.2" width="9" height="7.8" rx="2.6"/>'
    + '<rect x="2" y="8.4" width="3.4" height="4.2" rx="1.6"/></g>',
  remote: `<g ${ST} stroke-width="1.4"><rect x="5.5" y="6" width="5" height="9" rx="1.4"/>`
    + '<path d="M5.3 4.4a4 4 0 0 1 5.4 0M3.6 2.6a7 7 0 0 1 8.8 0"/></g><circle fill="currentColor" cx="8" cy="9" r="1.1"/>',
  infinity: `<path ${ST} stroke-width="1.7" d="M8 8c2.5-3.8 7-3.4 7 0s-4.5 3.8-7 0-7-3.4-7 0 4.5 3.8 7 0z"/>`,
  stop: '<path fill="currentColor" fill-rule="evenodd" d="M5.2 1.2h5.6l4 4v5.6l-4 4H5.2l-4-4V5.2zM6.9 4h2.2v5.6H6.9zM8 10.35a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5z"/>',
  gauge: `<g ${ST} stroke-width="1.6"><path d="M3.1 13.9A6.5 6.5 0 1 1 12.9 13.9"/><path d="M8 9l3.4-3.6"/></g>`
    + '<circle fill="currentColor" cx="8" cy="9" r="1.4"/>',
  lock: `<g ${ST} stroke-width="1.5"><rect x="3.5" y="7" width="9" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></g>`,
};
export function glyph(kind, size = 16) {
  return svg("0 0 16 16", GLYPHS[kind] || "", size);
}

/** A mode's own curve (src/ui/icons.py wave_icon): Random a die, Direct
 *  control a level line, Oscillate a swing around one. */
export function waveIcon(wave, w = 22, h = 14) {
  if (wave === "random") return glyph("dice", h + 2);
  if (wave === "linear") {
    return svg(`0 0 ${w} ${h}`, `<path ${ST} stroke-width="1.6" d="M1 ${h * 0.45}H${w - 1}"/>`, h);
  }
  const cycles = wave === "build" || wave === "heart" ? 1 : 2;
  const [lo, hi] = wave === "osc" ? [0.25, 0.75] : [0, 1];
  const n = 64;
  let d = "";
  for (let i = 0; i <= n; i++) {
    const x = i / n;
    const y = lo + (hi - lo) * P.shape(wave, x * cycles, x * 3.0, 1.0);
    d += `${i ? "L" : "M"}${(1 + x * (w - 2)).toFixed(2)} ${(h - 2 - y * (h - 4)).toFixed(2)}`;
  }
  const dash = wave === "osc"
    ? `<path fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="2 2" d="M1 ${h / 2}H${w - 1}"/>` : "";
  const s = svg(`0 0 ${w} ${h}`, `${dash}<path ${ST} stroke-width="1.6" d="${d}"/>`, h);
  s.setAttribute("width", w);
  return s;
}

/** The app's identity icons (src/ui/icons.py): toys, shockers, avatar. */
export function identity(what, size = 16) {
  const shapes = {
    toys: `<g ${ST} stroke-width="1.5"><rect x="7.25" y="2" width="5.5" height="16" rx="2.75"/><path d="M7.25 13.5h5.5"/>`
      + '<path d="M4.4 5l1.4 1.75-1.4 1.75 1.4 1.75-1.4 1.75 1.4 1.75M15.6 5l-1.4 1.75 1.4 1.75-1.4 1.75 1.4 1.75-1.4 1.75"/></g>',
    shock: '<path fill="currentColor" d="M11.26 1.6 5.38 11.26h4.62l-1.68 7.14 9.24-10.08h-4.62z"/>',
    params: `<g ${ST} stroke-width="1.5"><rect x="5.5" y="1.75" width="9" height="16.5" rx="2.5"/><circle cx="10" cy="6.5" r="2.2"/></g>`
      + '<g fill="currentColor"><circle cx="8" cy="11.5" r="1.05"/><circle cx="12" cy="11.5" r="1.05"/>'
      + '<circle cx="8" cy="14.75" r="1.05"/><circle cx="12" cy="14.75" r="1.05"/></g>',
  };
  const s = svg("0 0 20 20", shapes[what] || "", size);
  s.classList.add(`id-${what}`);
  return s;
}
