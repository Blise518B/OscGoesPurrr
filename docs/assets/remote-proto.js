/*!
 * remote-proto.js - the web remote's half of OGP's Friends protocol, ported
 * from the app's Python: src/remote_protocol.py (cmd, shk, stp, st, pnl,
 * oth), src/remote_params.py (an avatar board: pw, pbd, pv, pst, ph; the
 * Height box's ht, pv's h and pht), src/avatar_height.py (the Height box's
 * log slider and its numbers), src/friend_patterns.py (the auto modes'
 * shapes, for the card's graph) and the speed slider's mapping in
 * src/ui/views/card_parts.py.
 *
 * What the page sends must read back on OGP's side exactly as an OGP
 * friend's would: tests/test_web_remote.py runs these builders in node and
 * reads their messages with the Python readers. Browser: window.OGPRemoteProto
 * (needs ogp-chain.js first, for the simulator's waves). Node: module.exports.
 */
(function (root, factory) {
  'use strict';
  var chain = root && root.OGPChain;
  if (!chain && typeof require === 'function') { chain = require('./ogp-chain.js'); }
  var api = factory(chain);
  if (typeof module === 'object' && module && module.exports) {
    module.exports = api;
  } else {
    root.OGPRemoteProto = api;
  }
}(typeof self !== 'undefined' ? self : this, function (chain) {
  'use strict';

  var ALPN = 'ogp/friends/1';
  var PROTOCOL_VERSION = 2;
  var ALL = '*';                      // remote_protocol.ALL_TOYS
  var MAX_DATAGRAM = 1100;
  var TOY_NAME_MAX = 40;
  var NICK_MAX = 24;
  var MAX_TOYS = 8;
  var MAX_SHOCKERS = 4;
  var SHOCK_MIN_MS = 100;
  var OPS = ['shock', 'vibrate', 'beep'];
  var WARNINGS = ['vibrate', 'beep'];
  var WARN_MS = 1000;
  var WARN_MAX_MS = 9000;
  var DRIVE_STALE_S = 1.0;
  var MAX_CONTROLS = 400;
  var MAX_CATEGORIES = 40;
  var MAX_ALL = 1500;
  var NAME_MAX = 200;
  var LABEL_MAX = 80;
  var AVATAR_NAME_MAX = 80;
  var MAX_BLOB = 256 * 1024;
  var PTYPES = ['Bool', 'Int', 'Float'];
  var KINDS_FOR_PTYPE = { Bool: ['toggle', 'button'], Int: ['int', 'slider', 'toggle', 'button'],
                          Float: ['slider'] };
  var CATEGORY_HUES = ['green', 'pink', 'red', 'amber', 'yellow', 'cyan', 'blue', 'purple'];
  // avatar_height
  var HEIGHT_SAFE_MIN = 0.1;
  var HEIGHT_SAFE_MAX = 100.0;
  var HEIGHT_MODES = ['grow', 'now', 'reset'];

  // friend_patterns
  var WAVES = ['sine', 'square', 'triangle', 'saw', 'random', 'heart', 'build', 'osc'];
  var WAVE_LABELS = { sine: 'Sine', square: 'Square', triangle: 'Triangle', saw: 'Saw',
                      random: 'Random', heart: 'Heartbeat', build: 'Build-up', osc: 'Oscillate' };
  var PERIOD_MIN_S = 0.25;
  var PERIOD_MAX_S = 120.0;
  var SAMPLER = { sine: 'sine', square: 'square', triangle: 'triangle', saw: 'sawtooth',
                  random: 'random', osc: 'sine' };

  function round(v, places) {
    var k = Math.pow(10, places);
    return Math.round(v * k) / k;
  }
  function unit(v) {
    var x = Number(v);
    return isFinite(x) ? Math.max(0, Math.min(1, x)) : 0;
  }
  function isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
  function str(v, max) { return String(v === undefined || v === null ? '' : v).slice(0, max); }
  function cleanNick(text) {
    return String(text || '').replace(/[\u0000-\u001f\u007f]/g, '').replace(/\s+/g, ' ')
      .trim().slice(0, NICK_MAX);
  }
  /** The link's #<id>.<code>.<nick> (src/friend_links.py) -> {id, code,
   *  nick}, or null. The nick is percent-encoded, so the first character
   *  that encoding never writes ends the link: a browser that joins the
   *  copied link with the line under it -- "(Drive Blise's toys ...)" --
   *  hands that over too. */
  function parseLink(hash) {
    var parts = String(hash || '').replace(/^#/, '').split('.');
    var id = (parts[0] || '').toLowerCase(), code = (parts[1] || '').toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(id) || !/^[0-9a-f]{16}$/.test(code)) { return null; }
    var raw = parts.slice(2).join('.').split(/[^A-Za-z0-9_.~%-]/)[0], nick = '';
    try { nick = decodeURIComponent(raw); } catch (e) { nick = ''; }
    return { id: id, code: code, nick: cleanNick(nick) };
  }
  function newId() {
    var b = new Uint8Array(8);
    (typeof crypto !== 'undefined' ? crypto : require('crypto').webcrypto).getRandomValues(b);
    return Array.prototype.map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
  }
  function encode(msg) { return JSON.stringify(msg); }
  function byteLength(msg) {
    var s = encode(msg);
    return typeof TextEncoder !== 'undefined' ? new TextEncoder().encode(s).length : Buffer.byteLength(s);
  }

  // ---- auto modes (friend_patterns) -------------------------------------
  function cleanPattern(wave, period, lo, hi) {
    if (WAVES.indexOf(wave) < 0) { return null; }
    period = Number(period); lo = Number(lo); hi = Number(hi);
    if (!isFinite(period) || !isFinite(lo) || !isFinite(hi)) { return null; }
    period = Math.max(PERIOD_MIN_S, Math.min(PERIOD_MAX_S, period));
    lo = Math.max(0, Math.min(1, lo));
    hi = Math.max(0, Math.min(1, hi));
    if (hi < lo) { var t = lo; lo = hi; hi = t; }
    return [wave, period, lo, hi];
  }
  function shape(wave, phase, t, period) {
    var p = ((phase % 1) + 1) % 1;
    if (SAMPLER[wave]) {
      if (wave === 'random') { return chain.samplePattern(1.0 / period, 1.0, 'random', t); }
      return chain.samplePattern(1.0, 1.0, SAMPLER[wave], p);
    }
    if (wave === 'heart') {
      var beat = 0.0;
      [[0.0, 1.0], [0.22, 0.7]].forEach(function (b) {
        var x = (p - b[0]) / 0.14;
        if (x >= 0 && x < 1) { beat = Math.max(beat, b[1] * Math.sin(Math.PI * x)); }
      });
      return beat;
    }
    if (wave === 'build') {
      if (p > 0.94) { return 0.0; }
      var ramp = p / 0.94;
      var ripple = 0.5 + 0.5 * Math.sin(2.0 * Math.PI * p * 12.0);
      return ramp * (0.75 + 0.25 * ripple);
    }
    return 0.0;
  }
  function patternLevel(pattern, t, phase) {
    var lo = pattern[2], hi = pattern[3];
    return lo + (hi - lo) * Math.max(0, Math.min(1, shape(pattern[0], phase, t, pattern[1])));
  }
  // the speed slider: 0..1000, log between the shortest and longest period
  function periodToSlider(period) {
    period = Math.max(PERIOD_MIN_S, Math.min(PERIOD_MAX_S, period));
    return Math.round(1000 * Math.log(period / PERIOD_MIN_S) / Math.log(PERIOD_MAX_S / PERIOD_MIN_S));
  }
  function sliderToPeriod(x) {
    return PERIOD_MIN_S * Math.pow(PERIOD_MAX_S / PERIOD_MIN_S, x / 1000.0);
  }
  function fmtPeriod(period) {
    return period < 1 ? period.toFixed(2) + ' s' : (period < 10 ? period.toFixed(1) + ' s'
                                                               : period.toFixed(0) + ' s');
  }

  // ---- cmd: what you want --------------------------------------------------
  function fit(msg) {
    ['pat', 'ovr', 'lvl'].forEach(function (key) {
      while (byteLength(msg) > MAX_DATAGRAM) {
        var part = msg[key];
        if (!part) { break; }
        var names = (Array.isArray(part) ? part : Object.keys(part)).filter(function (k) { return k !== ALL; });
        if (!names.length) { break; }
        var last = names[names.length - 1];
        if (Array.isArray(part)) { part.splice(part.indexOf(last), 1); } else { delete part[last]; }
        if ((Array.isArray(part) ? part.length : Object.keys(part).length) === 0) { delete msg[key]; }
      }
    });
    return msg;
  }
  /** levels {toy: 0..1}, strength [seq, v] or null, override [toy], patterns
   *  {toy: [wave, period, lo, hi]}, holds {slot: [op, v]}, syn int or null */
  function makeCmd(levels, strength, override, patterns, holds, syn) {
    var lvl = {};
    Object.keys(levels || {}).forEach(function (k) {
      var v = Number(levels[k]);
      if (v > 0 && Object.keys(lvl).length < MAX_TOYS + 1) { lvl[str(k, TOY_NAME_MAX)] = round(v, 3); }
    });
    var msg = { t: 'cmd', lvl: lvl };
    var ovr = Array.from(new Set((override || []).map(function (k) { return str(k, TOY_NAME_MAX); }))).sort();
    if (ovr.length) { msg.ovr = ovr.slice(0, MAX_TOYS + 1); }
    var pat = {};
    Object.keys(patterns || {}).forEach(function (toy) {
      var raw = patterns[toy];
      var c = raw ? cleanPattern(raw[0], raw[1], raw[2], raw[3]) : null;
      if (c && Object.keys(pat).length < MAX_TOYS + 1) {
        pat[str(toy, TOY_NAME_MAX)] = [c[0], round(c[1], 2), round(c[2], 3), round(c[3], 3)];
      }
    });
    if (Object.keys(pat).length) { msg.pat = pat; }
    var hold = {};
    Object.keys(holds || {}).forEach(function (slot) {
      var h = holds[slot], s = parseInt(slot, 10);
      if (h && OPS.indexOf(h[0]) >= 0 && s >= 0 && s < MAX_SHOCKERS) {
        hold[String(s)] = [h[0], round(unit(h[1]), 3)];
      }
    });
    if (Object.keys(hold).length) { msg.hold = hold; }
    if (strength) { msg.str = [Math.trunc(strength[0]), round(Number(strength[1]), 3)]; }
    if (syn !== null && syn !== undefined) { msg.syn = Math.max(0, Math.trunc(syn)); }
    return fit(msg);
  }
  /** Their owner has each friend drive on their own (``sep`` in their
   *  ``st``; remote_protocol.read_separate). Absent: synced. */
  function readSeparate(msg) {
    return Boolean(msg && msg.sep);
  }
  function drives(msg) {
    return Boolean((msg.lvl && Object.keys(msg.lvl).length) || msg.pat || msg.hold);
  }

  // ---- shk / stp ------------------------------------------------------------
  function slotList(slots) {
    return Array.from(new Set((slots || []).map(Number).filter(function (s) {
      return s >= 0 && s < MAX_SHOCKERS && Math.floor(s) === s;
    }))).sort(function (a, b) { return a - b; });
  }
  function makeShock(id, slots, intensity, length, op, warn, warnIntensity, warnMs) {
    var msg = { t: 'shk', id: str(id, 16), slots: slotList(slots),
                int: round(unit(intensity), 3), len: round(unit(length), 3) };
    op = op || 'shock';
    if (op !== 'shock' && OPS.indexOf(op) >= 0) { msg.op = op; }
    if (WARNINGS.indexOf(warn) >= 0) {
      msg.warn = warn;
      msg.wi = round(unit(warnIntensity), 3);
      msg.wms = Math.max(100, Math.min(WARN_MAX_MS, Math.trunc(warnMs === undefined ? WARN_MS : warnMs)));
    }
    return msg;
  }
  function makeStop(id, slots) { return { t: 'stp', id: str(id, 16), slots: slotList(slots) }; }
  /** ``sop``: what you may send on one of their shockers, one bit per op */
  var OP_BITS = { shock: 1, vibrate: 2, beep: 4 };
  function maskOps(mask) { return OPS.filter(function (op) { return (mask & OP_BITS[op]) !== 0; }); }
  /** the op names you may send on one of their shockers (all of them from a
   *  copy that doesn't say -- shocker_ops) */
  function shockerOps(st, slot) {
    var own = st.shockerOps || [];
    return slot >= 0 && slot < own.length ? own[slot].slice() : OPS.slice();
  }
  /** can a warning play on one of their shockers? (can_warn) -- it vibrates,
   *  or beeps where Vibrate is off; with both off it can't */
  var WARN_OFF_WHY = 'Can\'t warn: vibrate and beep are both off on their side';
  function canWarn(st, slot) {
    var own = st.shockerOff || [];
    var off = slot >= 0 && slot < own.length ? own[slot] : [];
    return !(off.indexOf('vibrate') >= 0 && off.indexOf('beep') >= 0);
  }
  /** why you can't send `op` on one of their shockers ('' when you can) --
   *  the line a greyed button says (remote_protocol.shocker_why) */
  function shockerWhy(st, slot, op) {
    if (shockerOps(st, slot).indexOf(op) >= 0) { return ''; }
    var own = st.shockerOff || [];
    var off = slot >= 0 && slot < own.length ? own[slot] : [];
    var has = function (o) { return off.indexOf(o) >= 0; };
    if (has(op)) { return op.charAt(0).toUpperCase() + op.slice(1) + ' is switched off on their side'; }
    if (op === 'shock' && has('vibrate') && !st.armed) {
      return 'Vibrate is switched off on their side - and a shock that isn\'t armed goes out as a vibrate';
    }
    return 'They don\'t let you ' + op;
  }
  /** (shock cap, vibrate cap, longest pulse ms) of one of their shockers */
  function shockerCaps(st, slot) {
    var own = st.shockerCaps || [];
    if (slot >= 0 && slot < own.length) { return own[slot]; }
    var shock = st.maxIntensity || 1;
    return [shock, st.maxVibrate || shock, st.maxPulseMs || SHOCK_MIN_MS];
  }
  /** Python's round(): a half goes to the even neighbour (20.5 -> 20). */
  function pyRound(x) {
    return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : Math.round(x);
  }
  function shockValues(intensity, length, cap, longest) {
    var top = Math.max(1, cap), lng = Math.max(SHOCK_MIN_MS, longest);
    var level = Math.max(1, Math.min(top, pyRound(1 + intensity * (top - 1))));
    var ms = pyRound(SHOCK_MIN_MS + length * (lng - SHOCK_MIN_MS));
    return [level, Math.max(SHOCK_MIN_MS, Math.min(lng, ms))];
  }

  // ---- st: their state (read_status) -----------------------------------------
  function intIn(v, dflt, lo, hi) {
    var x = Math.trunc(Number(v));
    return isFinite(x) ? Math.max(lo, Math.min(hi, x)) : dflt;
  }
  function unitOrNull(v) {
    var x = Number(v);
    return v === null || v === undefined || !isFinite(x) ? null : Math.max(0, Math.min(1, x));
  }
  function readStatus(msg) {
    var toys = [];
    (Array.isArray(msg.toys) ? msg.toys : []).slice(0, MAX_TOYS).forEach(function (item) {
      if (Array.isArray(item) && item.length === 2) {
        toys.push([str(item[0], TOY_NAME_MAX), intIn(item[1], 1, 1, 16)]);
      }
    });
    var outRaw = isObj(msg.out) ? msg.out : {}, outputs = {};
    toys.forEach(function (t) { var v = unitOrNull(outRaw[t[0]]); outputs[t[0]] = v === null ? 0 : v; });
    var allow = isObj(msg.allow) ? msg.allow : {}, lim = isObj(msg.lim) ? msg.lim : {};
    var batRaw = isObj(msg.bat) ? msg.bat : {}, batteries = {};
    toys.forEach(function (t) {
      if (batRaw[t[0]] !== undefined && batRaw[t[0]] !== null) { batteries[t[0]] = intIn(batRaw[t[0]], 0, 0, 100); }
    });
    var shockers = (Array.isArray(msg.shk) ? msg.shk : []).slice(0, MAX_SHOCKERS).map(function (s) {
      return str(s, TOY_NAME_MAX);
    });
    var caps = [];
    var slim = Array.isArray(msg.slim) ? msg.slim : [];
    var count = Math.min(shockers.length, MAX_SHOCKERS);
    for (var i = 0; i < Math.min(slim.length, count); i++) {
      var c = slim[i];
      if (!Array.isArray(c) || c.length !== 3) { caps = []; break; }
      caps.push([intIn(c[0], 1, 1, 100), intIn(c[1], 1, 1, 100), intIn(c[2], SHOCK_MIN_MS, SHOCK_MIN_MS, 15000)]);
    }
    if (caps.length !== count) { caps = []; }
    var readOps = function (raw) {
      var out = [];
      raw = Array.isArray(raw) ? raw : [];
      for (var k = 0; k < Math.min(raw.length, count); k++) {
        if (typeof raw[k] !== 'number' || !isFinite(raw[k])) { return []; }
        out.push(maskOps(intIn(raw[k], 0, 0, 7)));
      }
      return out.length === count ? out : [];
    };
    var ops = readOps(msg.sop);
    var strength = unitOrNull(msg.str);
    var maxInt = intIn(lim.int, 0, 0, 100);
    return {
      toys: toys, outputs: outputs, strength: strength === null ? 1 : strength,
      off: Boolean(msg.off), paused: Boolean(msg.pause), notHere: Boolean(msg.nh),
      allowToys: Boolean(allow.toys), allowShock: Boolean(allow.shock),
      shockers: shockers, armed: Boolean(msg.armed),
      maxIntensity: maxInt, maxPulseMs: intIn(lim.ms, 0, 0, 15000),
      maxVibrate: intIn(lim.vib, maxInt, 0, 100),
      maxHoldS: Math.max(0, Math.min(600, Number(lim.hold) || 0)),
      shockerCaps: caps, shockerOps: ops, shockerOff: readOps(msg.soff),
      prm: isObj(msg.prm) ? readPrm(msg.prm) : null, batteries: batteries
    };
  }
  function readOthers(msg) {
    return (Array.isArray(msg.n) ? msg.n : []).map(cleanNick).filter(Boolean);
  }
  /** pnl: [seq, levels, override (array), patterns] or null */
  function readPanel(msg) {
    var seq = Math.trunc(Number(msg.seq));
    if (!isFinite(seq) || seq < 0) { return null; }
    var levels = {};
    var raw = isObj(msg.lvl) ? msg.lvl : {};
    Object.keys(raw).slice(0, MAX_TOYS + 1).forEach(function (k) {
      var v = unitOrNull(raw[k]);
      if (v) { levels[str(k, TOY_NAME_MAX)] = v; }
    });
    var ovr = (Array.isArray(msg.ovr) ? msg.ovr : []).slice(0, MAX_TOYS + 1).map(function (k) { return str(k, TOY_NAME_MAX); });
    var pats = {};
    var rawPat = isObj(msg.pat) ? msg.pat : {};
    Object.keys(rawPat).slice(0, MAX_TOYS + 1).forEach(function (k) {
      var p = rawPat[k];
      var c = Array.isArray(p) && p.length === 4 ? cleanPattern(p[0], p[1], p[2], p[3]) : null;
      if (c) { pats[str(k, TOY_NAME_MAX)] = c; }
    });
    return [seq, levels, ovr, pats];
  }

  // ---- the avatar board (remote_params) -----------------------------------------
  function hexKey(v) { return typeof v === 'string' && v.length <= 16 ? v : ''; }
  function readPrm(raw) {
    if (!isObj(raw)) { return null; }
    var ver = raw.b;
    return { ver: typeof ver === 'string' && ver.length <= 32 ? ver : '', yolo: Boolean(raw.y),
             stop: Boolean(raw.stop), avatar: hexKey(raw.a) };
  }
  function makeWatch(have, yoloOpen, retry) {
    var msg = { t: 'pw', b: String(have || '') };
    if (yoloOpen) { msg.y = 1; }
    if (retry) { msg.r = Math.trunc(retry); }
    return msg;
  }
  var WATCH_OFF = { t: 'pw', off: 1 };
  function num(v) { var x = Number(v); return v === null || v === undefined || v === '' || !isFinite(x) ? null : x; }
  function wire(v) {
    if (v === null || v === undefined) { return null; }
    if (v === true || v === false) { return v ? 1 : 0; }
    var x = num(v);
    if (x === null) { return null; }
    return Number.isInteger(x) ? x : round(x, 2);
  }
  function makeSet(seq, value, control, param) {
    var msg = { t: 'pst', id: Math.trunc(seq), v: wire(value) };
    if (control) { msg.c = str(control, 32); } else { msg.p = str(param, NAME_MAX); }
    return msg;
  }
  function makeHolds(ids) {
    return { t: 'ph', h: Array.from(ids || []).map(function (i) { return str(i, 32); }).sort().slice(0, MAX_CONTROLS) };
  }
  function intSwitchValues(c) {
    function clamp(v, d) { var x = Math.round(Number(v)); return isFinite(x) ? Math.max(0, Math.min(255, x)) : d; }
    return [clamp(c.on, 1), clamp(c.off, 0)];
  }
  function isIntSwitch(c) { return c.ptype === 'Int' && (c.kind === 'toggle' || c.kind === 'button'); }
  function showsOn(c, value) {
    if (value === null || value === undefined) { return false; }
    if (isIntSwitch(c)) { return Math.round(Number(value)) === intSwitchValues(c)[0]; }
    return Boolean(value) !== Boolean(c.invert);
  }
  function readBoard(msg) {
    if (msg.t !== 'pbd' || typeof msg.b !== 'string') { return null; }
    var cats = [];
    (Array.isArray(msg.cats) ? msg.cats : []).slice(0, MAX_CATEGORIES).forEach(function (c) {
      if (!isObj(c) || !c.id) { return; }
      cats.push({ id: str(c.id, 32), name: str(c.name, 60),
                  color: CATEGORY_HUES.indexOf(c.color) >= 0 ? c.color : 'green', locked: Boolean(c.locked) });
    });
    var ids = cats.map(function (c) { return c.id; });
    var ctl = [];
    (Array.isArray(msg.ctl) ? msg.ctl : []).slice(0, MAX_CONTROLS).forEach(function (raw) {
      if (!isObj(raw) || PTYPES.indexOf(raw.ptype) < 0) { return; }
      var c = { id: str(raw.id, 32), param: str(raw.param, NAME_MAX), ptype: raw.ptype, kind: raw.kind,
                label: str(raw.label || raw.param, LABEL_MAX), cat: String(raw.cat || '') };
      if (!c.id || !c.param || ids.indexOf(c.cat) < 0 || KINDS_FOR_PTYPE[c.ptype].indexOf(c.kind) < 0) { return; }
      ['min', 'max'].forEach(function (k) { var v = num(raw[k]); if (v !== null) { c[k] = v; } });
      if (isIntSwitch(c)) { var sw = intSwitchValues(raw); c.on = sw[0]; c.off = sw[1]; }
      if (c.ptype === 'Bool' && raw.invert) { c.invert = true; }
      ctl.push(c);
    });
    var keys = (Array.isArray(msg.keys) ? msg.keys : []).slice(0, MAX_CONTROLS + MAX_ALL)
      .filter(function (k) { return typeof k === 'string'; }).map(function (k) { return k.slice(0, NAME_MAX); });
    var all = null;
    if (Array.isArray(msg.all)) {
      all = [];
      msg.all.slice(0, MAX_ALL).forEach(function (item) {
        if (Array.isArray(item) && item.length === 2 && PTYPES.indexOf(item[1]) >= 0 && typeof item[0] === 'string') {
          all.push([item[0].slice(0, NAME_MAX), item[1]]);
        }
      });
    }
    return { ver: msg.b.slice(0, 32), name: str(msg.name, AVATAR_NAME_MAX), avatar: hexKey(msg.a),
             categories: cats, controls: ctl, keys: keys, all: all, height: readHeightBox(msg.ht) };
  }
  function readValues(msg, board) {
    if (msg.b !== board.ver) { return {}; }
    var start = Math.trunc(Number(msg.o || 0));
    if (!isFinite(start)) { return {}; }
    var types = {};
    board.controls.forEach(function (c) { types[c.param] = c.ptype; });
    (board.all || []).forEach(function (a) { types[a[0]] = a[1]; });
    var out = {};
    (Array.isArray(msg.x) ? msg.x : []).some(function (raw, i) {
      var at = start + i;
      if (at < 0 || at >= board.keys.length) { return true; }
      var name = board.keys[at], ptype = types[name];
      if (raw === null || ptype === undefined) { out[name] = null; return false; }
      var v = num(raw);
      if (v === null) { return false; }
      out[name] = ptype === 'Bool' ? v !== 0 : (ptype === 'Int' ? Math.round(v) : v);
      return false;
    });
    return out;
  }

  // ---- their height: the Height box (avatar_height, remote_params) ----------------
  function heightSafe(v) { return Math.max(HEIGHT_SAFE_MIN, Math.min(HEIGHT_SAFE_MAX, v)); }
  /** The board's ht -> {lo, hi, locked, allowed}, or null (the box is off). */
  function readHeightBox(raw) {
    if (!isObj(raw)) { return null; }
    var lo = num(raw.lo), hi = num(raw.hi);
    if (lo === null || hi === null) { return null; }
    lo = heightSafe(lo);
    hi = heightSafe(hi);
    if (hi <= lo) { return null; }
    return { lo: lo, hi: hi, locked: Boolean(raw.lk), allowed: !raw.no };
  }
  /** Their height right now, off the first pv (null: it carries none). */
  function readHeight(msg) {
    var v = num(msg.h);
    return v !== null && v > 0 ? heightSafe(v) : null;
  }
  /** Grow (glide) / now (jump) to value, or reset. */
  function makeHeightSet(seq, mode, value) {
    var msg = { t: 'pht', id: Math.trunc(seq), m: String(mode) };
    if (value !== null && value !== undefined && mode !== 'reset') { msg.v = round(Number(value), 3); }
    return msg;
  }
  /** The slider is a log scale: equal steps are equal factors. */
  function heightToSlider(h, lo, hi) {
    if (h === null || h === undefined || !(h > 0) || !(lo > 0) || !(hi > lo)) { return null; }
    var c = Math.max(lo, Math.min(hi, h));
    return (Math.log(c) - Math.log(lo)) / (Math.log(hi) - Math.log(lo));
  }
  function sliderToHeight(x, lo, hi) {
    var t = Math.max(0, Math.min(1, Number(x)));
    if (t <= 0) { return Number(lo); }
    if (t >= 1) { return Number(hi); }
    return Math.exp(Math.log(lo) + t * (Math.log(hi) - Math.log(lo)));
  }
  // --- the shocker buttons: PiShock's panel or OpenShock's (src/shocker_layout.py) ---
  var LAYOUTS = ['pishock', 'openshock'];
  var LAYOUT_DEFAULT = 'pishock';
  var OS = { INTENSITY_DEFAULT: 25, DURATION_DEFAULT_MS: 1000, DURATION_MIN_MS: 300,
             DURATION_STEP_MS: 100, OPS: ['beep', 'vibrate', 'shock'],
             OP_NAMES: { beep: 'Sound', vibrate: 'Vibrate', shock: 'Shock' },
             LIVE_DEFAULT_OP: 'vibrate', LIVE_STEP: 0.05 };
  function cleanLayout(v) { return LAYOUTS.indexOf(v) >= 0 ? v : LAYOUT_DEFAULT; }
  function jsRound(x) { return Math.floor(x + 0.5); }
  /** a strength 1..cap as 0..1 of their cap (to_fraction) */
  function toFraction(strength, cap) {
    cap = Math.max(1, cap);
    return cap <= 1 ? 1 : Math.max(0, (strength - 1) / (cap - 1));
  }
  /** a length in ms as 0..1 of their longest pulse (length_fraction) */
  function lengthFraction(ms, top) {
    top = Math.max(SHOCK_MIN_MS, top);
    return top <= SHOCK_MIN_MS ? 0 : (Math.min(ms, top) - SHOCK_MIN_MS) / (top - SHOCK_MIN_MS);
  }
  /** [shortest, longest] on the Duration dial (duration_range) */
  function durationRange(top) {
    var hi = Math.max(SHOCK_MIN_MS, top);
    return [Math.min(OS.DURATION_MIN_MS, hi), hi];
  }
  /** `ms` on the dial's tenths (snap_duration) */
  function snapDuration(ms, top) {
    var r = durationRange(top), steps = jsRound((ms - r[0]) / OS.DURATION_STEP_MS);
    return Math.max(r[0], Math.min(r[1], r[0] + steps * OS.DURATION_STEP_MS));
  }
  /** Live control: the pad's point (0 top .. 1 bottom) as 0..cap (live_strength) */
  function liveStrength(y, cap) {
    y = Math.max(0, Math.min(1, y));
    return Math.max(0, Math.min(cap, jsRound((1 - y) * Math.max(0, cap))));
  }

  /** "1.62 m" (a centimetre under 10 m, a decimetre past it), "–" unknown --
   *  avatar_height.fmt to the digit. */
  function fmtHeight(h) {
    if (h === null || h === undefined) { return '\u2013'; }
    return h < 10 ? chain.math.pyFixed(h, 2) + ' m' : chain.math.pyFixed(h, 1) + ' m';
  }

  return {
    ALPN: ALPN, PROTOCOL_VERSION: PROTOCOL_VERSION, ALL: ALL, MAX_DATAGRAM: MAX_DATAGRAM,
    NICK_MAX: NICK_MAX, MAX_SHOCKERS: MAX_SHOCKERS, SHOCK_MIN_MS: SHOCK_MIN_MS, OPS: OPS,
    DRIVE_STALE_S: DRIVE_STALE_S, MAX_BLOB: MAX_BLOB, WAVES: WAVES, WAVE_LABELS: WAVE_LABELS,
    PERIOD_MIN_S: PERIOD_MIN_S, PERIOD_MAX_S: PERIOD_MAX_S, WATCH_OFF: WATCH_OFF,
    round: round, unit: unit, cleanNick: cleanNick, parseLink: parseLink, newId: newId,
    encode: encode,
    cleanPattern: cleanPattern, shape: shape, patternLevel: patternLevel,
    periodToSlider: periodToSlider, sliderToPeriod: sliderToPeriod, fmtPeriod: fmtPeriod,
    makeCmd: makeCmd, drives: drives, makeShock: makeShock, makeStop: makeStop,
    shockerCaps: shockerCaps, shockerOps: shockerOps, shockerWhy: shockerWhy, OP_BITS: OP_BITS,
    canWarn: canWarn, WARN_OFF_WHY: WARN_OFF_WHY,
    shockValues: shockValues,
    LAYOUTS: LAYOUTS, LAYOUT_DEFAULT: LAYOUT_DEFAULT, OS: OS, cleanLayout: cleanLayout,
    toFraction: toFraction, lengthFraction: lengthFraction, durationRange: durationRange,
    snapDuration: snapDuration, liveStrength: liveStrength,
    readStatus: readStatus, readSeparate: readSeparate, readOthers: readOthers, readPanel: readPanel,
    readPrm: readPrm, makeWatch: makeWatch, makeSet: makeSet, makeHolds: makeHolds, wire: wire,
    isIntSwitch: isIntSwitch, intSwitchValues: intSwitchValues, showsOn: showsOn,
    readBoard: readBoard, readValues: readValues,
    HEIGHT_MODES: HEIGHT_MODES, readHeightBox: readHeightBox, readHeight: readHeight,
    makeHeightSet: makeHeightSet, heightToSlider: heightToSlider, sliderToHeight: sliderToHeight,
    fmtHeight: fmtHeight
  };
}));
