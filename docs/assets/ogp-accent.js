/*!
 * ogp-accent.js - port of OscGoesPurrr's src/accent_shift.py.
 *
 * Turns the 518 green into another colour by rotating every token's hue by
 * the same angle in OKLCH (so "equally bright" stays equally bright to the
 * eye), with the app's own gamut search for tokens that fall outside sRGB.
 *
 * Dependency-free, ES5 syntax. Browser: window.OGPAccent. Node: module.exports.
 * Same arithmetic, same operation order and same rounding rules as the
 * Python; verified string-for-string by check_accent.py + check_accent.js.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module && module.exports) {
    module.exports = api;
  } else {
    root.OGPAccent = api;
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var L_SEARCH = 0.14;
  var L_STEP = 0.01;
  var KEEP_CHROMA = 0.8;
  var NEUTRAL_CHROMA = 1e-4;

  var RAD_TO_DEG = 180.0 / Math.PI;      // CPython math.degrees: x * (180/pi)
  var DEG_TO_RAD = Math.PI / 180.0;      // CPython math.radians: x * (pi/180)

  // ---------------------------------------------------------------- helpers
  /** Python float %: the result takes the sign of the divisor. */
  function pyMod(a, b) {
    var r = a % b;
    if (r !== 0 && ((r < 0) !== (b < 0))) { r += b; }
    return r;
  }

  /** Python round(x) -> int: round-half-to-even. */
  function roundHalfEven(x) {
    var f = Math.floor(x);
    var d = x - f;
    if (d > 0.5) { return f + 1; }
    if (d < 0.5) { return f; }
    return (f % 2 === 0) ? f : f + 1;
  }

  /**
   * Python round(x, n) for x >= 0: correctly rounded on the float's exact
   * value, exact halves to even. toFixed() is correctly rounded too but
   * sends exact halves upward, so those are stepped back when odd.
   * (x * 10^n is exactly k + 1/2  <=>  x * 2^(n+1) is an odd integer.)
   */
  function pyRound(x, n) {
    var s = x.toFixed(n);
    var y = x * Math.pow(2, n + 1);
    if (y === Math.floor(y) && (y % 2 === 1)) {
      var last = s.charCodeAt(s.length - 1) - 48;
      if (last % 2 === 1) {
        s = s.substring(0, s.length - 1) + String(last - 1);
      }
    }
    return Number(s);
  }

  /** Error-free product (Dekker): a*b = p + e exactly. */
  function twoProd(a, b) {
    var p = a * b;
    var c = 134217729.0 * a;
    var ah = c - (c - a), al = a - ah;
    c = 134217729.0 * b;
    var bh = c - (c - b), bl = b - bh;
    var e = ((ah * bh - p) + ah * bl + al * bh) + al * bl;
    return [p, e];
  }

  /**
   * math.hypot(a, b) exactly as CPython computes it (mathmodule.c
   * vector_norm: scaled, compensated sum of squares + one differential
   * correction), so the chroma is the same double as in the app.
   */
  function pyHypot(a, b) {
    a = Math.abs(a); b = Math.abs(b);
    var max = 0.0;
    if (a > max) { max = a; }
    if (b > max) { max = b; }
    if (max === Infinity) { return max; }
    if (a !== a || b !== b) { return NaN; }
    if (max === 0.0) { return max; }
    // frexp: max = m * 2^e, m in [0.5, 1); scale = 2^-e (exact)
    var m = max, scale = 1.0;
    while (m >= 1.0) { m *= 0.5; scale *= 0.5; }
    while (m < 0.5) { m *= 2.0; scale *= 2.0; }
    var csum = 1.0, frac1 = 0.0, frac2 = 0.0;
    var vec = [a, b], x, pr, hi, lo, i;
    for (i = 0; i < 2; i++) {
      x = vec[i] * scale;
      pr = twoProd(x, x);
      hi = csum + pr[0];
      lo = (csum - hi) + pr[0];
      csum = hi;
      frac1 += pr[1];
      frac2 += lo;
    }
    var h = Math.sqrt(csum - 1.0 + (frac1 + frac2));
    pr = twoProd(-h, h);
    hi = csum + pr[0];
    lo = (csum - hi) + pr[0];
    csum = hi;
    frac1 += pr[1];
    frac2 += lo;
    x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    return h / scale;
  }

  function toLinear(c) {
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }
  function toSrgb(c) {
    return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  }
  function cbrt(x) {                                // copysign(abs(x) ** (1/3), x)
    var r = Math.pow(Math.abs(x), 1 / 3);
    return (x < 0 || (x === 0 && 1 / x < 0)) ? -r : r;
  }
  function hex2(n) {
    var s = n.toString(16);
    return s.length < 2 ? '0' + s : s;
  }

  // ------------------------------------------------------------------ OKLCH
  /** "#rrggbb" -> [lightness 0..1, chroma, hue in degrees 0..360) */
  function toOklch(hex) {
    var s = String(hex).replace(/^#+/, '');
    var r = toLinear(parseInt(s.substring(0, 2), 16) / 255.0);
    var g = toLinear(parseInt(s.substring(2, 4), 16) / 255.0);
    var b = toLinear(parseInt(s.substring(4, 6), 16) / 255.0);
    var l_ = cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    var m_ = cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    var s_ = cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    var L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_;
    var a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_;
    var bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_;
    return [L, pyHypot(a, bb), pyMod(Math.atan2(bb, a) * RAD_TO_DEG, 360.0)];
  }

  function linearRgb(L, C, h) {
    var a = C * Math.cos(h * DEG_TO_RAD);
    var b = C * Math.sin(h * DEG_TO_RAD);
    var l_ = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3);
    var m_ = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3);
    var s_ = Math.pow(L - 0.0894841775 * a - 1.2914855480 * b, 3);
    return [4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
      -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
      -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_];
  }

  function inGamut(L, C, h) {
    var rgb = linearRgb(L, C, h);
    for (var i = 0; i < 3; i++) {
      if (!(-1e-4 <= rgb[i] && rgb[i] <= 1.0 + 1e-4)) { return false; }
    }
    return true;
  }

  /** [lightness, chroma, hue] -> "#rrggbb", channels clamped to sRGB. */
  function fromOklch(L, C, h) {
    var rgb = linearRgb(L, C, h);
    var out = '#';
    for (var i = 0; i < 3; i++) {
      var c = Math.min(1.0, Math.max(0.0, rgb[i]));
      out += hex2(roundHalfEven(255 * Math.min(1.0, Math.max(0.0, toSrgb(c)))));
    }
    return out;
  }

  var chromaCache = {};
  var chromaCacheSize = 0;
  /** The most saturated colour sRGB can show at this lightness and hue. */
  function maxChroma(L, h) {
    var key = L + '|' + h;
    var hit = chromaCache[key];
    if (hit !== undefined) { return hit; }
    var lo = 0.0, hi = 0.4;
    for (var i = 0; i < 18; i++) {
      var mid = (lo + hi) / 2;
      if (inGamut(L, mid, h)) { lo = mid; } else { hi = mid; }
    }
    if (chromaCacheSize >= 4096) { chromaCache = {}; chromaCacheSize = 0; }
    chromaCache[key] = lo;
    chromaCacheSize++;
    return lo;
  }

  // ------------------------------------------------------------- public API
  /** The OKLCH hue of a colour, in degrees. */
  function hueOf(hex) {
    return toOklch(hex)[2];
  }

  /**
   * Degrees to turn the chrome by so `referenceHex` (the accent) lands on
   * `targetHue`. null / undefined - the house green - is no turn at all.
   */
  function deltaFor(targetHue, referenceHex) {
    if (targetHue === null || targetHue === undefined) { return 0.0; }
    return pyMod(Number(targetHue) - hueOf(referenceHex), 360.0);
  }

  /**
   * One token turned by `delta` degrees. A zero turn returns the token
   * untouched, character for character; so does a grey (no hue to turn).
   */
  function shiftHex(hex, delta) {
    if (!delta) { return hex; }
    var lch = toOklch(hex);
    var L = lch[0], C = lch[1], h = lch[2];
    if (C < NEUTRAL_CHROMA) { return hex; }
    h = pyMod(h + delta, 360.0);
    if (inGamut(L, C, h)) { return fromOklch(L, C, h); }
    // Too saturated for this hue at this lightness: take the nearest
    // lightness that holds most of it...
    var hKey = pyRound(h, 3);
    var bestL = L, bestC = maxChroma(pyRound(L, 4), hKey);
    var steps = roundHalfEven(L_SEARCH / L_STEP);
    for (var i = 1; i <= steps; i++) {
      for (var s = 0; s < 2; s++) {
        var sign = s === 0 ? -1 : 1;
        var L2 = pyRound(Math.min(0.99, Math.max(0.01, L + sign * i * L_STEP)), 4);
        var c2 = maxChroma(L2, hKey);
        if (c2 >= KEEP_CHROMA * C) {
          return fromOklch(L2, Math.min(C, c2), h);
        }
        if (c2 > bestC) { bestL = L2; bestC = c2; }
      }
    }
    // ...and failing that, the most saturated it can be within reach.
    return fromOklch(bestL, Math.min(C, bestC), h);
  }

  /** Every "#rrggbb" value of a token object turned by `delta` degrees. */
  function shiftTokens(tokens, delta) {
    var out = {};
    for (var k in tokens) {
      if (Object.prototype.hasOwnProperty.call(tokens, k)) {
        var v = tokens[k];
        out[k] = (typeof v === 'string' && v.charAt(0) === '#') ? shiftHex(v, delta) : v;
      }
    }
    return out;
  }

  return {
    shiftHex: shiftHex,
    hueOf: hueOf,
    deltaFor: deltaFor,
    shiftTokens: shiftTokens,
    toOklch: toOklch,
    fromOklch: fromOklch,
    maxChroma: maxChroma,
    _pyHypot: pyHypot,
    _pyRound: pyRound
  };
}));
