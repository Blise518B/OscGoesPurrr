/*!
 * ogp-chain.js - the OscGoesPurrr motor signal chain, ported line for line
 * from the app's Python (src/motor_router.py MotorRouter._calculate_motor_target,
 * src/mixer.py, src/config_manager.py preset_motor_mix).
 *
 * Dependency-free, ES5 syntax. Browser: window.OGPChain. Node: module.exports.
 * Verified against the real MotorRouter by gen_reference.py + check.js.
 *
 * One "motor" = the list of chains on one toy motor plus the merge op.
 * Every tick: each chain turns its contact value (0..1) into a level, the
 * chains are merged, and that merged level is what the toy is sent.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module && module.exports) {
    module.exports = api;
  } else {
    root.OGPChain = api;
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ------------------------------------------------------------------
  // Constants (MotorRouter class attributes / mixer module constants)
  // ------------------------------------------------------------------
  var SPEED_NORMALIZATION = 0.75;
  var SPEED_INPUT_DEADBAND = 0.005;
  var SPEED_OUTPUT_CUTOFF = 0.02;
  var SPEED_DECAY_TAU_S = 0.30;
  var SPEED_DECAY_MS_MIN = 10.0;
  var SPEED_DECAY_MS_MAX = 2000.0;

  var ANTISTUCK_EPSILON = 0.001;
  var ANTISTUCK_SATURATED = 0.95;
  var ANTISTUCK_RAMP_S = 3.0;

  var DUCK_THRESHOLD = 0.02;
  var DUCK_ATTACK_S = 0.06;
  var DUCK_RELEASE_MS_DEFAULT = 400.0;
  var DUCK_RELEASE_MS_MAX = 3000.0;

  var MAX_CHAINS_PER_MOTOR = 6;
  var OUTPUT_GAIN_MAX = 2.0;
  var OUTPUT_SILENCE_EPS = 0.01;

  var PUNCH_FULL_RATE_PER_S = 3.0;
  var PUNCH_MIN_RATE_PER_S = 0.35;
  var PUNCH_DECAY_MS_MIN = 30.0;
  var PUNCH_DECAY_MS_MAX = 1000.0;

  var THRUST_MIN_SWING = 0.15;
  var THRUST_TIMES_CAP = 32;

  var TEXTURE_RATE_HZ_MIN = 0.2;
  var TEXTURE_RATE_HZ_MAX = 8.0;
  var TEXTURE_AMOUNT_MAX = 0.9;
  var TAU = 2.0 * Math.PI;                  // == math.tau
  var TEXTURE_PHASE_TOP = 1.5 * Math.PI;

  // mixer.py
  var POWER_PARAM_MIN = 0.3;
  var POWER_PARAM_MAX = 3.0;
  var S_CURVE_ITERS_MIN = 1;
  var S_CURVE_ITERS_MAX = 8;
  var ACTIVITY_TAU_MIN_S = 0.01;
  var SMOOTH_SNAP_EPSILON = 0.005;
  var RANDOM_SECTION_S = 5.0;

  var CHAIN_TYPE_TOUCH = 'touch';
  var CHAIN_TYPE_PENETRATION = 'penetration';
  var CHAIN_TYPE_CUSTOM = 'custom';

  var WAVEFORMS = ['sine', 'square', 'triangle', 'sawtooth', 'random'];
  var COMBINE_OPS = ['add', 'max', 'multiply'];   // cycle order of the button
  var MERGE_OPS = ['add', 'max', 'multiply'];

  // What a fresh install runs with (config_manager.ModeManager.DEFAULT_STRENGTH,
  // settings/app.py toy_antistuck_*, router_poll_rate_hz).
  var APP_DEFAULTS = {
    strength: 0.85,
    antistuck: { enabled: true, active_s: 1, peaked_s: 10 },
    routerHz: 90,
    simTickS: 0.016          // the app's simulator publishes on a 16 ms timer
  };

  // MotorRouter.SLEEP_WAKE_OVERRIDE - forced onto every chain while Sleep is on.
  var SLEEP_WAKE_OVERRIDE = {
    enabled: true, mode: 'strokes', thrusts: 3, window_s: 6.0,
    disarm_after_s: 45.0
  };

  // The trace ids each chain reports, in the order the app's emit dict has them.
  var TRACE_IDS = [
    'd_raw', 's_raw', 'd_shaped', 's_shaped', 'punch',
    's_in_shaped', 's_out_shaped', 'punch_in', 'punch_out',
    'mixed', 'wake_mode', 'wake_open', 'wake_meter', 'wake_out',
    'smoothed', 'textured', 'out', 'duck'
  ];

  // Which traces each stage card draws (ui/motor_signal_chain.py _STAGE_TRACES)
  // and which one drives its level number / border (_STAGE_LEVEL_TRACE).
  var STAGE_ORDER = ['input', 'depth', 'speed', 'punch', 'combine', 'wake',
    'envelope', 'zerocut', 'output'];
  var STAGE_LABELS = {
    input: 'Input', depth: 'Depth', speed: 'Speed', punch: 'Punch',
    combine: 'Combine', wake: 'Wake', envelope: 'Envelope',
    zerocut: 'Zero cut', output: 'Output'
  };
  var STAGE_TRACES = {
    input: ['d_raw'],
    depth: ['d_raw', 'd_shaped'],
    speed: ['s_raw', 's_in_shaped', 's_out_shaped'],
    punch: ['d_raw', 'punch_in', 'punch_out'],
    combine: ['d_shaped', 's_shaped', 'mixed'],
    wake: ['mixed', 'wake_meter', 'wake_out'],
    envelope: ['wake_out', 'smoothed', 'textured'],
    zerocut: ['textured', 'out'],
    output: ['out']
  };
  var STAGE_LEVEL_TRACE = {
    input: 'd_raw', depth: 'd_shaped', speed: 's_shaped', punch: 'punch',
    combine: 'mixed', wake: 'wake_out', envelope: 'textured',
    zerocut: 'out', output: 'out'
  };
  // Trace colours as 518 palette hue names (_TRACE_STYLE); 'accent' = the green.
  var TRACE_HUES = {
    d_raw: 'blue', s_raw: 'amber', d_shaped: 'blue', s_shaped: 'amber',
    punch: 'pink', s_in_shaped: 'amber', s_out_shaped: 'cyan',
    punch_in: 'pink', punch_out: 'purple', mixed: 'purple',
    wake_meter: 'yellow', wake_out: 'cyan', smoothed: 'cyan',
    textured: 'grey', out: 'accent'
  };

  // ------------------------------------------------------------------
  // Small helpers that reproduce Python semantics
  // ------------------------------------------------------------------
  function isObj(v) {
    return v !== null && typeof v === 'object' &&
      Object.prototype.toString.call(v) !== '[object Array]';
  }
  function isArr(v) {
    return Object.prototype.toString.call(v) === '[object Array]';
  }
  /** dict.get(key, default) - `undefined` counts as "key absent". */
  function get(obj, key, dflt) {
    if (obj !== null && obj !== undefined &&
        Object.prototype.hasOwnProperty.call(obj, key) &&
        obj[key] !== undefined) {
      return obj[key];
    }
    return dflt;
  }
  function sub(chain, key) {       // chain.get(key, {}) guarded to a dict
    var v = get(chain, key, null);
    return isObj(v) ? v : {};
  }
  /** Python float(value); returns NaN where Python would raise. */
  function toFloat(value) {
    if (typeof value === 'number') { return value; }
    if (typeof value === 'boolean') { return value ? 1.0 : 0.0; }
    if (typeof value === 'string') {
      var s = value.replace(/^\s+|\s+$/g, '');
      if (s === '') { return NaN; }
      var n = Number(s);
      return n;
    }
    return NaN;
  }
  /** MotorRouter._coerce_float */
  function coerceFloat(value, dflt, lo, hi) {
    if (lo === undefined) { lo = -1e9; }
    if (hi === undefined) { hi = 1e9; }
    var v = toFloat(value);
    if (!isFinite(v)) { return dflt; }
    if (v < lo) { return lo; }
    if (v > hi) { return hi; }
    return v;
  }
  function clampUnit(x) {
    if (x < 0.0) { return 0.0; }
    if (x > 1.0) { return 1.0; }
    return x;
  }
  /** Python's float % (result takes the sign of the divisor). */
  function pyMod(a, b) {
    var r = a % b;
    if (r !== 0 && ((r < 0) !== (b < 0))) { r += b; }
    return r;
  }
  /** utilities.normalize_osc_value for a float input. */
  function normalizeInput(v) {
    var f = toFloat(v);
    if (!isFinite(f)) { return 0.0; }
    return Math.max(0.0, Math.min(1.0, f));
  }
  function deepCopy(v) {
    var out, i, k;
    if (isArr(v)) {
      out = [];
      for (i = 0; i < v.length; i++) { out.push(deepCopy(v[i])); }
      return out;
    }
    if (isObj(v)) {
      out = {};
      for (k in v) {
        if (Object.prototype.hasOwnProperty.call(v, k)) { out[k] = deepCopy(v[k]); }
      }
      return out;
    }
    return v;
  }

  // ------------------------------------------------------------------
  // mixer.py - pure functions
  // ------------------------------------------------------------------
  /** Python round() to an int: round-half-to-even. */
  function roundHalfEven(x) {
    var f = Math.floor(x);
    var d = x - f;
    if (d > 0.5) { return f + 1; }
    if (d < 0.5) { return f; }
    return (f % 2 === 0) ? f : f + 1;
  }

  function applyCurve(x, kind, param) {
    x = clampUnit(x);
    if (kind === 'power') {
      var exponent = Math.max(POWER_PARAM_MIN, Math.min(POWER_PARAM_MAX, param));
      return Math.pow(x, exponent);
    }
    if (kind === 's_curve') {
      var n = Math.max(S_CURVE_ITERS_MIN,
        Math.min(S_CURVE_ITERS_MAX, roundHalfEven(param)));
      for (var i = 0; i < n; i++) { x = x * x * (3.0 - 2.0 * x); }
      return x;
    }
    return x;                                   // linear / unknown
  }

  function combine(dShaped, sShaped, op) {
    var out;
    if (op === 'add') {
      out = dShaped + sShaped;
    } else if (op === 'multiply') {
      out = dShaped * sShaped;
    } else {
      out = Math.max(dShaped, sShaped);         // 'max' + anything unknown
    }
    return clampUnit(out);
  }

  function mergeChains(values, op) {
    if (!values.length) { return 0.0; }
    if (values.length === 1) { return clampUnit(values[0]); }
    var result = values[0];
    for (var i = 1; i < values.length; i++) {
      var v = values[i];
      if (op === 'add') {
        result = result + v;
      } else if (op === 'multiply') {
        result = result * v;
      } else if (v > result) {
        result = v;
      }
    }
    return clampUnit(result);
  }

  function activityMeter(prev, signal, dtS, attackTauS, releaseTauS) {
    var sig = clampUnit(signal);
    if (dtS <= 0.0) { return prev; }
    var tau;
    if (sig > prev) {
      tau = Math.max(ACTIVITY_TAU_MIN_S, attackTauS);
    } else {
      tau = Math.max(ACTIVITY_TAU_MIN_S, releaseTauS);
    }
    var alpha = 1.0 - Math.exp(-dtS / tau);
    return clampUnit(prev + (sig - prev) * alpha);
  }

  /** returns [open, belowSince] (belowSince null = not counting) */
  function activityGate(prevOpen, belowSince, meter, nowS, wakeThreshold, sleepDelayS) {
    if (meter >= wakeThreshold) { return [true, null]; }
    if (!prevOpen) { return [false, null]; }
    if (belowSince === null || belowSince === undefined) { belowSince = nowS; }
    var elapsed = nowS - belowSince;
    if (elapsed >= sleepDelayS) { return [false, null]; }
    return [true, belowSince];
  }

  function smooth(prev, mixed, dtMs, riseMs, fallMs) {
    var tau = (mixed > prev) ? riseMs : fallMs;
    if (tau <= 0.0 || dtMs <= 0.0) { return mixed; }
    var alpha = 1.0 - Math.exp(-dtMs / tau);
    var next = prev + (mixed - prev) * alpha;
    if (Math.abs(next - mixed) < SMOOTH_SNAP_EPSILON) { return mixed; }
    return next;
  }

  // ---- the input simulator (mixer.sample_pattern) --------------------
  function hash01(n) {
    var x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
    return x - Math.floor(x);
  }
  function smoothstep(x) { return x * x * (3.0 - 2.0 * x); }
  function randomPattern(freqHz, tS) {
    var sec = tS / RANDOM_SECTION_S;
    var si = Math.floor(sec);
    var ease = smoothstep(sec - si);
    var a = hash01(si), b = hash01(si + 1);
    var level = 0.2 + 0.8 * (a + (b - a) * ease);     // the section's intensity
    var cyc = freqHz * tS;
    var ci = Math.floor(cyc);
    var phase = cyc - ci;
    var depth = 0.4 + 0.6 * hash01(1000 + ci);        // this stroke's depth
    var stroke = 0.5 - 0.5 * Math.cos(2.0 * Math.PI * phase);
    return Math.max(0.0, Math.min(1.0, level * depth * stroke));
  }
  /** One sample of the app's simulator wave. Output in [0, amp]. */
  function samplePattern(freqHz, amp, waveform, tS) {
    if (!(freqHz > 0.0)) { return 0.0; }
    var phase = pyMod(freqHz * tS, 1.0);
    if (waveform === 'sine') {
      return amp * (0.5 + 0.5 * Math.sin(2.0 * Math.PI * phase));
    }
    if (waveform === 'square') { return phase < 0.5 ? amp : 0.0; }
    if (waveform === 'triangle') {
      if (phase < 0.5) { return amp * (2.0 * phase); }
      return amp * (2.0 * (1.0 - phase));
    }
    if (waveform === 'sawtooth') { return amp * phase; }
    if (waveform === 'random') { return amp * randomPattern(freqHz, tS); }
    return 0.0;
  }
  /**
   * simWave('Sine', 1.0, 1.0) -> function (tSeconds) -> value.
   * `shape` is one of WAVEFORMS, any capitalisation (the app's dropdown shows
   * them capitalised and lower-cases before sampling).
   */
  function simWave(shape, hz, amp) {
    var wf = String(shape).toLowerCase();
    var f = (hz === undefined) ? 1.0 : +hz;
    var a = (amp === undefined) ? 1.0 : +amp;
    return function (tSeconds) { return samplePattern(f, a, wf, tSeconds); };
  }

  // ------------------------------------------------------------------
  // Default config (MotorRouter.DEFAULT_MIX_CONFIG + preset_motor_mix)
  // ------------------------------------------------------------------
  /** One untuned chain - MotorRouter.DEFAULT_MIX_CONFIG["chains"][0]. */
  function defaultChain() {
    return {
      depth: { gain: 1.0, curve: 'linear', curve_param: 1.0 },
      // `gain_out` deliberately absent: absent means "follow gain".
      speed: { gain: 1.0, curve: 'linear', curve_param: 1.0, decay_ms: 300.0 },
      punch: { gain: 0.0, gain_out: 0.0, decay_ms: 120.0 },
      combine: 'max',
      wake: {
        enabled: false, mode: 'activity', source: 'both',
        wake_threshold: 0.05, sleep_delay_s: 0.5,
        attack_s: 0.05, release_s: 0.5,
        thrusts: 3, window_s: 6.0, disarm_after_s: 45.0
      },
      smoothing: { rise_ms: 50.0, fall_ms: 20.0 },
      texture: { enabled: false, amount: 0.25, rate_hz: 2.0,
        follow_speed: false, depth_follow: 'off' },
      zerocut: { enabled: false, threshold: 0.0 },
      duck: { enabled: false, release_ms: 400.0 },
      output: { gain: 1.0, min: 0.0, max: 1.0 }
    };
  }

  // config_manager._DEFAULT_FEEL / _TOUCH_FEEL
  var DEFAULT_FEEL = {
    depth_gain: 0.38, speed_gain: 0.41, speed_decay_ms: 350.0,
    rise_ms: 120.0, fall_ms: 200.0, combine: 'add',
    punch: { gain: 1.32, decay_ms: 120.0 },
    wake: { enabled: true, mode: 'activity' },
    zerocut: { enabled: true }
  };
  var TOUCH_FEEL = {
    depth_gain: 0.62, speed_gain: 0.22, speed_decay_ms: 180.0,
    rise_ms: 45.0, fall_ms: 260.0, combine: 'add',
    punch: { gain: 0.0, decay_ms: 120.0 },
    wake: { enabled: false, mode: 'activity' },
    zerocut: { enabled: true },
    duck: { enabled: false, release_ms: 400.0 }
  };
  function applyFeel(chain, feel) {
    chain.depth.gain = feel.depth_gain;
    chain.speed.gain = feel.speed_gain;
    chain.speed.decay_ms = feel.speed_decay_ms;
    chain.smoothing.rise_ms = feel.rise_ms;
    chain.smoothing.fall_ms = feel.fall_ms;
    if (feel.combine !== undefined) { chain.combine = feel.combine; }
    var stages = ['wake', 'punch', 'texture', 'zerocut', 'duck'];
    for (var i = 0; i < stages.length; i++) {
      var st = feel[stages[i]];
      if (st) {
        for (var k in st) {
          if (Object.prototype.hasOwnProperty.call(st, k)) {
            chain[stages[i]][k] = st[k];
          }
        }
      }
    }
    return chain;
  }
  /**
   * preset_motor_mix(): what a new motor ships with - a Penetration chain and
   * a Touch chain, merged max-wins. Fresh deep copy on every call.
   */
  function defaults() {
    var pen = applyFeel(defaultChain(), DEFAULT_FEEL);
    pen.type = CHAIN_TYPE_PENETRATION;
    var touch = applyFeel(defaultChain(), TOUCH_FEEL);
    touch.type = CHAIN_TYPE_TOUCH;
    return { chains: [pen, touch], merge: 'max' };
  }

  // ------------------------------------------------------------------
  // Per-chain state + the stateful detectors
  // ------------------------------------------------------------------
  function makeChainState() {
    return {
      last_position: 0.0,
      smoothed_speed_in: 0.0,
      smoothed_speed_out: 0.0,
      smoothed_output: 0.0,
      activity_meter: 0.0,
      gate_open: false,
      below_since: null,
      as_last_draw: null,
      as_static_since: -1.0,
      duck_level: 0.0
      // lazily added: punch_last_d, punch_env_in, punch_env_out,
      // thrust_ext, thrust_base, thrust_dir, thrust_times, last_thrust_t,
      // armed, texture_phase
    };
  }

  /** MotorRouter._derive_speed_signal -> [in, out] */
  function deriveSpeedSignal(cs, position, dt, decayTauS) {
    var prevIn = cs.smoothed_speed_in;
    var prevOut = cs.smoothed_speed_out;
    var decayTau = Math.max(SPEED_DECAY_MS_MIN / 1000.0, decayTauS);
    var cutoff = SPEED_OUTPUT_CUTOFF;
    var smIn, smOut;
    if (dt <= 0.0) {
      smIn = prevIn; smOut = prevOut;       // first sample: reuse
    } else {
      var delta = position - cs.last_position;
      var magnitude = Math.abs(delta);
      var signal;
      if (magnitude <= SPEED_INPUT_DEADBAND) {
        signal = 0.0;
      } else {
        signal = Math.min(1.0,
          ((magnitude - SPEED_INPUT_DEADBAND) / dt) * SPEED_NORMALIZATION);
      }
      var decay = Math.exp(-dt / decayTau);
      // only the direction actually travelled is struck; the other rings down
      smIn = Math.max(delta > 0.0 ? signal : 0.0, prevIn * decay);
      smOut = Math.max(delta < 0.0 ? signal : 0.0, prevOut * decay);
    }
    cs.smoothed_speed_in = smIn;
    cs.smoothed_speed_out = smOut;
    cs.last_position = position;
    var denom = Math.max(1.0 - cutoff, 1e-6);
    return [
      smIn <= cutoff ? 0.0 : Math.min(1.0, (smIn - cutoff) / denom),
      smOut <= cutoff ? 0.0 : Math.min(1.0, (smOut - cutoff) / denom)
    ];
  }

  /** MotorRouter._derive_punch_signal -> [envIn, envOut] */
  function derivePunchSignal(cs, position, dt, decayTauS) {
    var lastD = (cs.punch_last_d === undefined) ? -1.0 : cs.punch_last_d;
    var envIn = (cs.punch_env_in === undefined) ? 0.0 : cs.punch_env_in;
    var envOut = (cs.punch_env_out === undefined) ? 0.0 : cs.punch_env_out;
    if (dt > 0.0) {
      var decay = Math.exp(-dt / Math.max(1e-3, decayTauS));
      envIn *= decay;
      envOut *= decay;
      if (lastD >= 0.0) {
        var rate = (position - lastD) / dt;
        var strike;
        if (rate >= PUNCH_MIN_RATE_PER_S) {
          strike = Math.min(1.0, rate / PUNCH_FULL_RATE_PER_S);
          if (strike > envIn) { envIn = strike; }
        } else if (-rate >= PUNCH_MIN_RATE_PER_S) {
          strike = Math.min(1.0, -rate / PUNCH_FULL_RATE_PER_S);
          if (strike > envOut) { envOut = strike; }
        }
      }
    }
    cs.punch_last_d = position;
    cs.punch_env_in = envIn;
    cs.punch_env_out = envOut;
    return [envIn, envOut];
  }

  /**
   * MotorRouter._detect_thrust - true exactly once per completed in-stroke:
   * when the value turns back down after a rise of at least 0.15.
   */
  function detectThrust(st, dRaw) {
    if (st.thrust_ext === undefined || st.thrust_ext === null) {
      st.thrust_ext = dRaw;
      st.thrust_base = dRaw;
      st.thrust_dir = 0;
      return false;
    }
    var ext = st.thrust_ext;
    var direction = (st.thrust_dir === undefined) ? 0 : st.thrust_dir;
    var base = (st.thrust_base === undefined) ? ext : st.thrust_base;
    if (direction >= 0) {
      if (dRaw >= ext) {
        st.thrust_ext = dRaw;
        if (direction === 0 && dRaw - base >= THRUST_MIN_SWING) {
          st.thrust_dir = 1;
        }
        return false;
      }
      if (ext - dRaw >= THRUST_MIN_SWING) {
        var counted = (direction === 1 && ext - base >= THRUST_MIN_SWING);
        st.thrust_dir = -1;
        st.thrust_base = ext;
        st.thrust_ext = dRaw;
        return counted;
      }
      return false;
    }
    // direction == -1: riding a fall
    if (dRaw <= ext) {
      st.thrust_ext = dRaw;
      return false;
    }
    if (dRaw - ext >= THRUST_MIN_SWING) {
      st.thrust_dir = 1;
      st.thrust_base = ext;
      st.thrust_ext = dRaw;
    }
    return false;
  }

  /** MotorRouter._wake_source */
  function wakeSource(cfg, dRaw, sRaw) {
    var source = String(get(cfg, 'source', 'both')).toLowerCase();
    if (source === 'depth') { return dRaw; }
    if (source === 'speed') { return sRaw; }
    return dRaw * sRaw;
  }

  /** MotorRouter._wake_activity -> [waked, open, meter] */
  function wakeActivity(cs, activitySrc, mixed, dt, now, cfg) {
    var wakeThreshold = coerceFloat(get(cfg, 'wake_threshold', 0.05), 0.05, 0.0, 1.0);
    var sleepDelayS = coerceFloat(get(cfg, 'sleep_delay_s', 0.5), 0.5, 0.0, 60.0);
    var attackS = coerceFloat(get(cfg, 'attack_s', 0.05), 0.05, 0.01, 10.0);
    var releaseS = coerceFloat(get(cfg, 'release_s', 0.5), 0.5, 0.01, 10.0);
    var meter = activityMeter(cs.activity_meter, activitySrc, dt, attackS, releaseS);
    cs.activity_meter = meter;
    var g = activityGate(!!cs.gate_open, cs.below_since, meter, now,
      wakeThreshold, sleepDelayS);
    cs.gate_open = g[0];
    cs.below_since = g[1];
    return [g[0] ? mixed : 0.0, g[0], meter];
  }

  /** MotorRouter._wake_strokes -> [waked, armed, progress] */
  function wakeStrokes(cs, chainDRaw, mixed, dt, now, cfg) {
    var needF = coerceFloat(get(cfg, 'thrusts', 3), 3.0, 1.0, 10.0);
    var need = needF < 0 ? Math.ceil(needF) : Math.floor(needF);   // int()
    var windowS = coerceFloat(get(cfg, 'window_s', 6.0), 6.0, 1.0, 30.0);
    var disarmAfterS = coerceFloat(get(cfg, 'disarm_after_s', 45.0), 45.0, 5.0, 600.0);
    if (!cs.thrust_times) { cs.thrust_times = []; }
    var times = cs.thrust_times;
    // a swing's two halves must not straddle a gap longer than the window
    if (dt > windowS) {
      delete cs.thrust_ext;
      delete cs.thrust_base;
      delete cs.thrust_dir;
    }
    // disarm FIRST, against the pre-tick deadline
    if (cs.armed) {
      var prevLastT = (cs.last_thrust_t === undefined) ? -1.0 : cs.last_thrust_t;
      if (prevLastT < 0.0 || now - prevLastT > disarmAfterS) {
        cs.armed = false;
        times.length = 0;
      }
    }
    if (detectThrust(cs, chainDRaw)) {
      times.push(now);
      if (times.length > THRUST_TIMES_CAP) { times.shift(); }
      cs.last_thrust_t = now;
    }
    while (times.length && now - times[0] > windowS) { times.shift(); }
    var armed = !!cs.armed;
    if (!armed && times.length >= need) { armed = true; }
    cs.armed = armed;
    var progress = (need > 0) ? Math.min(1.0, times.length / need) : 0.0;
    return [armed ? mixed : 0.0, armed, progress];
  }

  /** MotorRouter._wake_reset */
  function wakeReset(cs) {
    cs.activity_meter = 0.0;
    cs.gate_open = false;
    cs.below_since = null;
    cs.armed = false;
    delete cs.thrust_times;
    delete cs.thrust_ext;
    delete cs.thrust_base;
    delete cs.thrust_dir;
    delete cs.last_thrust_t;
  }

  /** MotorRouter._antistuck_factor (cfg null/disabled -> always 1.0) */
  function antistuckFactor(cs, dRaw, now, cfg) {
    var last = cs.as_last_draw;
    if (last === null || last === undefined ||
        Math.abs(dRaw - last) > ANTISTUCK_EPSILON) {
      cs.as_last_draw = dRaw;             // input moved (or first sample)
      cs.as_static_since = now;
    }
    if (!cfg || !get(cfg, 'enabled', false)) {
      cs.as_static_since = now;
      return 1.0;
    }
    if (dRaw <= ANTISTUCK_EPSILON) { return 1.0; }
    var since = (cs.as_static_since === undefined) ? now : cs.as_static_since;
    var elapsed = now - since;
    if (elapsed < 0.0) { elapsed = 0.0; }
    if (dRaw >= ANTISTUCK_SATURATED) {
      // saturated hold: longer fuse, then a gentle ramp
      var peakedS = coerceFloat(get(cfg, 'peaked_s', 10.0), 10.0, 0.0, 600.0);
      if (elapsed < peakedS) { return 1.0; }
      var ramp = 1.0 - (elapsed - peakedS) / ANTISTUCK_RAMP_S;
      return Math.max(0.0, Math.min(1.0, ramp));
    }
    // mid-range hold: a frozen sender - hard cut after the fuse
    var activeS = coerceFloat(get(cfg, 'active_s', 1.0), 1.0, 0.0, 600.0);
    return (elapsed >= activeS) ? 0.0 : 1.0;
  }

  /** MotorRouter._duck_gain */
  function duckGain(cs, duckCfg, chainType, penRaw, dt) {
    var level = (cs.duck_level === undefined) ? 0.0 : cs.duck_level;
    var enabled = (!!get(duckCfg, 'enabled', false)) &&
      chainType !== CHAIN_TYPE_PENETRATION;
    if (!enabled) {
      if (level) { cs.duck_level = 0.0; }
      return 1.0;
    }
    var target = (penRaw > DUCK_THRESHOLD) ? 1.0 : 0.0;
    if (dt > 0.0 && target !== level) {
      if (target > level) {
        level = Math.min(1.0, level + dt / DUCK_ATTACK_S);
      } else {
        var releaseS = coerceFloat(
          get(duckCfg, 'release_ms', DUCK_RELEASE_MS_DEFAULT),
          DUCK_RELEASE_MS_DEFAULT, 0.0, DUCK_RELEASE_MS_MAX) / 1000.0;
        level = (releaseS <= 0.0) ? 0.0 : Math.max(0.0, level - dt / releaseS);
      }
      cs.duck_level = level;
    }
    return 1.0 - level;
  }

  // ------------------------------------------------------------------
  // Motor
  // ------------------------------------------------------------------
  /**
   * create(config, options) -> motor
   *   config   a mix block as returned by defaults(); kept BY REFERENCE and
   *            re-read on every step, so editing it (a slider drag) takes
   *            effect on the next tick, exactly like the app.
   *   options  { strength: 0..1, off: bool, sleep: bool,
   *              antistuck: {enabled, active_s, peaked_s} | null }
   *            Defaults are a fresh install's: strength 0.85, anti-stuck on
   *            (1 s / 10 s), off false, sleep false.
   */
  function Motor(config, options) {
    this.config = config || defaults();
    this.options = {
      strength: APP_DEFAULTS.strength,
      off: false,
      sleep: false,
      antistuck: deepCopy(APP_DEFAULTS.antistuck)
    };
    this.setOptions(options);
    this.reset();
  }

  Motor.prototype.setOptions = function (options) {
    if (!options) { return this; }
    for (var k in options) {
      if (Object.prototype.hasOwnProperty.call(options, k) &&
          options[k] !== undefined) {
        this.options[k] = options[k];
      }
    }
    return this;
  };

  /** Forget all signal state (MotorRouter.reset_outputs + a fresh clock). */
  Motor.prototype.reset = function () {
    this.now = 0.0;
    this.state = { last_time: -1.0, chains: [makeChainState()] };
    this.globalThrust = {};
    this.strokeCount = 0;
    this.band = null;
    this.last = null;
    return this;
  };

  /**
   * Advance the clock by `dt` seconds and compute one tick.
   * The very first tick after create()/reset() has no elapsed time (the
   * router sees dt = 0 on its first evaluation), so its `dt` is ignored.
   * inputs = { pen: 0..1, touch: 0..1 } - the contact values right now.
   * options (optional) is merged into motor.options first.
   */
  Motor.prototype.step = function (dt, inputs, options) {
    if (options) { this.setOptions(options); }
    if (this.state.last_time >= 0.0) { this.now += (+dt || 0.0); }
    return this._tick(this.now, inputs || {});
  };

  /** Same, driven by an absolute clock in seconds (e.g. performance.now()/1000). */
  Motor.prototype.stepAt = function (tSeconds, inputs, options) {
    if (options) { this.setOptions(options); }
    this.now = +tSeconds;
    return this._tick(this.now, inputs || {});
  };

  /** MotorRouter._calculate_motor_target */
  Motor.prototype._tick = function (now, inputs) {
    var opts = this.options;
    var mix = isObj(this.config) ? this.config : {};
    var chainsCfg = mix.chains;
    if (!isArr(chainsCfg) || !chainsCfg.length) { chainsCfg = [DEFAULT_CHAIN_RO]; }
    if (chainsCfg.length > MAX_CHAINS_PER_MOTOR) {
      chainsCfg = chainsCfg.slice(0, MAX_CHAINS_PER_MOTOR);
    }
    var mergeOp = String(get(mix, 'merge', 'max'));

    // Global strength / Off: ModeManager.get_master_scale, folded into each
    // chain's Output stage below.
    var rawScale = opts.off ? 0.0 : opts.strength;
    var masterScale = coerceFloat(rawScale, 1.0, 0.0, 1.0);

    var state = this.state;
    while (state.chains.length < chainsCfg.length) {
      state.chains.push(makeChainState());
    }

    // --- every chain resolves its OWN input from its type ---------------
    var pen = normalizeInput(get(inputs, 'pen', 0.0));
    var touch = normalizeInput(get(inputs, 'touch', 0.0));
    var chainInputs = [];
    var ci, chain, chainType;
    var liveDRaw = 0.0;
    var penRaw = 0.0;
    for (ci = 0; ci < chainsCfg.length; ci++) {
      chain = isObj(chainsCfg[ci]) ? chainsCfg[ci] : {};
      chainType = String(get(chain, 'type', CHAIN_TYPE_CUSTOM));
      var allowTouch = true, allowPen = true;       // custom: hears both
      if (chainType === CHAIN_TYPE_TOUCH) { allowPen = false; }
      else if (chainType === CHAIN_TYPE_PENETRATION) { allowTouch = false; }
      var d = 0.0;
      if (allowPen && pen > d) { d = pen; }
      if (allowTouch && touch > d) { d = touch; }
      chainInputs.push(d);
      if (ci === 0 || d > liveDRaw) { liveDRaw = d; }
      if (chainType === CHAIN_TYPE_PENETRATION && d > penRaw) { penRaw = d; }
    }

    // --- Sleep toggle: swapping wake algorithms starts the stage clean ---
    var sleeping = !!opts.sleep;
    if (sleeping !== !!state.sleeping) {
      state.sleeping = sleeping;
      for (ci = 0; ci < state.chains.length; ci++) { wakeReset(state.chains[ci]); }
    }

    var lastT = state.last_time;
    var dt = (lastT >= 0.0) ? (now - lastT) : 0.0;

    var emits = [];
    var chainOutputs = [];
    var chainCeilings = [];
    var chainFloors = [];
    var chainContact = [];

    for (ci = 0; ci < chainsCfg.length; ci++) {
      chain = isObj(chainsCfg[ci]) ? chainsCfg[ci] : DEFAULT_CHAIN_RO;
      var cs = state.chains[ci];
      var chainDRaw = chainInputs[ci];

      var depth = sub(chain, 'depth');
      var speed = sub(chain, 'speed');

      // ---- Speed detector (directional pair) --------------------------
      var speedDecayS = coerceFloat(
        get(speed, 'decay_ms', SPEED_DECAY_TAU_S * 1000.0),
        SPEED_DECAY_TAU_S * 1000.0,
        SPEED_DECAY_MS_MIN, SPEED_DECAY_MS_MAX) / 1000.0;
      var sPair = deriveSpeedSignal(cs, chainDRaw, dt, speedDecayS);
      var sInRaw = sPair[0], sOutRaw = sPair[1];
      var sRaw = Math.max(sInRaw, sOutRaw);

      // ---- Depth ------------------------------------------------------
      var dShaped = applyCurve(
        chainDRaw,
        String(get(depth, 'curve', 'linear')),
        coerceFloat(get(depth, 'curve_param', 1.0), 1.0)
      ) * coerceFloat(get(depth, 'gain', 1.0), 1.0, 0.0, 2.0);

      // ---- Speed: one curve, a gain per stroke direction -------------
      var sCurve = String(get(speed, 'curve', 'linear'));
      var sCurveParam = coerceFloat(get(speed, 'curve_param', 1.0), 1.0);
      var sGainIn = coerceFloat(get(speed, 'gain', 1.0), 1.0, 0.0, 2.0);
      var sGainOut = coerceFloat(get(speed, 'gain_out', sGainIn), sGainIn, 0.0, 2.0);
      var sInShaped = applyCurve(sInRaw, sCurve, sCurveParam) * sGainIn;
      var sOutShaped = applyCurve(sOutRaw, sCurve, sCurveParam) * sGainOut;
      var sShaped = Math.max(sInShaped, sOutShaped);

      // ---- Punch ------------------------------------------------------
      var punchCfg = sub(chain, 'punch');
      var punchGain = coerceFloat(get(punchCfg, 'gain', 0.0), 0.0, 0.0, 2.0);
      var punchGainOut = coerceFloat(get(punchCfg, 'gain_out', 0.0), 0.0, 0.0, 2.0);
      var punchIn, punchOut, punch;
      if (punchGain > 0.0 || punchGainOut > 0.0) {
        var punchDecayS = coerceFloat(get(punchCfg, 'decay_ms', 120.0), 120.0,
          PUNCH_DECAY_MS_MIN, PUNCH_DECAY_MS_MAX) / 1000.0;
        var pPair = derivePunchSignal(cs, chainDRaw, dt, punchDecayS);
        punchIn = Math.min(1.0, pPair[0] * punchGain);
        punchOut = Math.min(1.0, pPair[1] * punchGainOut);
        punch = Math.max(punchIn, punchOut);
      } else {
        // keep the memory tracking so enabling punch mid-motion doesn't
        // read the whole current depth as one giant rise
        cs.punch_last_d = chainDRaw;
        cs.punch_env_in = 0.0;
        cs.punch_env_out = 0.0;
        punchIn = punchOut = punch = 0.0;
      }

      // ---- Combine (punch joins max-wins AFTER the depth/speed op) ----
      var mixed = combine(dShaped, sShaped, String(get(chain, 'combine', 'max')));
      if (punch > mixed) { mixed = punch; }

      // ---- Wake -------------------------------------------------------
      var wakeCfg = sleeping ? SLEEP_WAKE_OVERRIDE : sub(chain, 'wake');
      var wakeMode = String(get(wakeCfg, 'mode', 'activity'));
      var waked, wakeOpen, wakeMeter, w;
      if (!get(wakeCfg, 'enabled', false)) {
        wakeReset(cs);
        waked = mixed; wakeOpen = true; wakeMeter = 0.0;
      } else if (wakeMode === 'strokes') {
        w = wakeStrokes(cs, chainDRaw, mixed, dt, now, wakeCfg);
        waked = w[0]; wakeOpen = w[1]; wakeMeter = w[2];
      } else {
        w = wakeActivity(cs, wakeSource(wakeCfg, chainDRaw, sRaw),
          mixed, dt, now, wakeCfg);
        waked = w[0]; wakeOpen = w[1]; wakeMeter = w[2];
      }

      // ---- Envelope: smoothing ---------------------------------------
      var smoothing = sub(chain, 'smoothing');
      var riseMs = coerceFloat(get(smoothing, 'rise_ms', 50.0), 50.0, 0.0, 2000.0);
      var fallMs = coerceFloat(get(smoothing, 'fall_ms', 20.0), 20.0, 0.0, 2000.0);
      var smoothedChain = smooth(cs.smoothed_output, waked, dt * 1000.0,
        riseMs, fallMs);

      // ---- Envelope: texture (downward-only wobble) -------------------
      var textureCfg = sub(chain, 'texture');
      var texturedChain = smoothedChain;
      if (get(textureCfg, 'enabled', false) && smoothedChain > 0.0) {
        var txAmount = coerceFloat(get(textureCfg, 'amount', 0.25), 0.25,
          0.0, TEXTURE_AMOUNT_MAX);
        var txRate = coerceFloat(get(textureCfg, 'rate_hz', 2.0), 2.0,
          TEXTURE_RATE_HZ_MIN, TEXTURE_RATE_HZ_MAX);
        if (get(textureCfg, 'follow_speed', false)) {
          txRate = Math.min(TEXTURE_RATE_HZ_MAX,
            txRate * (1.0 + Math.max(0.0, Math.min(1.0, sShaped))));
        }
        var depthFollow = String(get(textureCfg, 'depth_follow', 'off')).toLowerCase();
        if (depthFollow === 'up' || depthFollow === 'down') {
          var mv = Math.max(0.0, Math.min(1.0, sShaped));
          if (depthFollow === 'down') {
            txAmount *= (1.0 - mv);
          } else {
            txAmount = Math.min(TEXTURE_AMOUNT_MAX, txAmount * (1.0 + mv));
          }
        }
        var prevPhase = (cs.texture_phase === undefined)
          ? TEXTURE_PHASE_TOP : cs.texture_phase;
        var phase = pyMod(prevPhase + TAU * txRate * dt, TAU);
        cs.texture_phase = phase;
        texturedChain = smoothedChain *
          (1.0 - txAmount * 0.5 * (1.0 + Math.sin(phase)));
      } else {
        cs.texture_phase = TEXTURE_PHASE_TOP;
      }

      // ---- Zero cut ---------------------------------------------------
      var smoothedEmit = smoothedChain;      // pre-cut, for the traces
      var texturedEmit = texturedChain;
      var zerocut = sub(chain, 'zerocut');
      if (get(zerocut, 'enabled', false)) {
        var zcThreshold = coerceFloat(get(zerocut, 'threshold', 0.0), 0.0, 0.0, 0.5);
        if (chainDRaw <= zcThreshold) {
          smoothedChain = 0.0;
          texturedChain = 0.0;
        }
      }
      // the envelope tracks the post-cut, PRE-texture value
      cs.smoothed_output = smoothedChain;

      // ---- Output: gain x strength, then the toy's band ---------------
      var outCfg = sub(chain, 'output');
      var outGain = coerceFloat(get(outCfg, 'gain', 1.0), 1.0, 0.0, OUTPUT_GAIN_MAX);
      var outMax = coerceFloat(get(outCfg, 'max', 1.0), 1.0, 0.0, 1.0);
      var outMin = coerceFloat(get(outCfg, 'min', 0.0), 0.0, 0.0, 1.0);
      if (outMin > outMax) { outMin = outMax; }
      var chainOut = texturedChain * outGain * masterScale;
      chainOut = Math.max(0.0, Math.min(1.0, chainOut));
      if (outMin > 0.0 || outMax < 1.0) {
        chainOut = (chainOut <= OUTPUT_SILENCE_EPS)
          ? 0.0 : outMin + chainOut * (outMax - outMin);
      }
      chainCeilings.push(outMax);
      chainFloors.push(outMin);

      // ---- Anti-stuck (per chain, after Output) -----------------------
      var chainAs = antistuckFactor(cs, chainDRaw, now, opts.antistuck);
      if (chainAs < 1.0) { chainOut *= chainAs; }

      // ---- Sidechain duck (Touch chains that opted in) ----------------
      var dGain = duckGain(cs, sub(chain, 'duck'),
        String(get(chain, 'type', CHAIN_TYPE_CUSTOM)), penRaw, dt);
      if (dGain < 1.0) { chainOut *= dGain; }

      chainOutputs.push(chainOut);
      chainContact.push(texturedChain * chainAs * dGain);
      emits.push({
        d_raw: chainDRaw,
        s_raw: sRaw,
        d_shaped: dShaped,
        s_shaped: sShaped,
        punch: punch,
        s_in_shaped: sInShaped,
        s_out_shaped: sOutShaped,
        punch_in: punchIn,
        punch_out: punchOut,
        mixed: mixed,
        wake_mode: wakeMode,
        wake_open: wakeOpen,
        wake_meter: wakeMeter,
        wake_out: waked,
        smoothed: smoothedEmit,
        textured: texturedEmit,
        out: chainOut,
        duck: 1.0 - dGain
      });
    }

    // ---- Merge + ceiling safety net ------------------------------------
    var finalOut = mergeChains(chainOutputs, mergeOp);
    var k, ceiling = 0.0, floor = 0.0;
    if (chainCeilings.length) {
      ceiling = chainCeilings[0]; floor = chainFloors[0];
      for (k = 1; k < chainCeilings.length; k++) {
        if (chainCeilings[k] > ceiling) { ceiling = chainCeilings[k]; }
        if (chainFloors[k] > floor) { floor = chainFloors[k]; }
      }
      if (finalOut > ceiling) { finalOut = ceiling; }
      this.band = [floor, ceiling];
    }

    // contact twin (what the "mirror to VRChat parameter" feature reports)
    var contactOut = Math.max(0.0, Math.min(1.0, mergeChains(chainContact, mergeOp)));

    state.last_time = now;

    // usage statistics: one stroke = one count, on the strongest contact
    var stroke = detectThrust(this.globalThrust, liveDRaw);
    if (stroke) { this.strokeCount += 1; }

    this.last = {
      out: finalOut,
      contact: contactOut,
      chains: emits,
      t: now,
      dt: dt,
      stroke: stroke,
      strokes: this.strokeCount,
      sleeping: sleeping,
      masterScale: masterScale
    };
    return this.last;
  };

  /** MotorRouter.map_into_output_band for this motor (the OGP/Test pulse). */
  Motor.prototype.mapIntoOutputBand = function (level) {
    var lvl = toFloat(level);
    if (!isFinite(lvl) || lvl <= 0.0) { return 0.0; }
    lvl = Math.min(1.0, lvl);
    if (!this.band) { return lvl; }
    var floor = this.band[0], ceiling = this.band[1];
    if (floor <= 0.0 && ceiling >= 1.0) { return lvl; }
    return Math.max(0.0, Math.min(1.0, floor + lvl * (ceiling - floor)));
  };

  var DEFAULT_CHAIN_RO = defaultChain();     // fallback for malformed entries

  function create(config, options) { return new Motor(config, options); }

  // ------------------------------------------------------------------
  // Python number formatting (for the summary strings)
  // ------------------------------------------------------------------
  /** exact tie test: is x * 10^n exactly k + 0.5 ?  (x >= 0, n >= 0) */
  function isDecimalTie(x, n) {
    // x*10^n = k + 1/2 with x a binary float  <=>  x * 2^(n+1) is an odd integer
    var y = x * Math.pow(2, n + 1);
    return y === Math.floor(y) && (y % 2 === 1);
  }
  /** Python f"{x:.{n}f}" (round-half-even on the exact value). */
  function pyFixed(x, n) {
    var neg = x < 0 || (x === 0 && 1 / x < 0);
    var a = Math.abs(x);
    var s = a.toFixed(n);                  // correctly rounded, ties away
    if (isDecimalTie(a, n)) {
      var last = s.charCodeAt(s.length - 1) - 48;
      if (last % 2 === 1) {                // odd -> step back to the even one
        s = s.substring(0, s.length - 1) + String(last - 1);
      }
    }
    return (neg ? '-' : '') + s;
  }
  /** Python f"{x:.{p}g}" */
  function pyGeneral(x, p) {
    if (p === undefined) { p = 6; }
    if (p < 1) { p = 1; }
    if (x !== x) { return 'nan'; }
    if (x === Infinity) { return 'inf'; }
    if (x === -Infinity) { return '-inf'; }
    var neg = x < 0 || (x === 0 && 1 / x < 0);
    var a = Math.abs(x);
    if (a === 0) { return neg ? '-0' : '0'; }
    var e = a.toExponential(p - 1);        // "d.ddde+X", ties away
    var parts = e.split('e');
    var digits = parts[0].replace('.', '');
    var exp = parseInt(parts[1], 10);
    // half-even fix-up for an exact tie at the rounding position
    var pos = exp - (p - 1);               // decimal exponent of the last kept digit
    var tie = false;
    if (pos <= 0) {
      tie = isDecimalTie(a, -pos);         // -pos decimals are kept
    } else if (a === Math.floor(a) && a < 9007199254740992) {
      var unit = Math.pow(10, pos);
      tie = (a % unit === unit / 2);
    }
    if (tie) {
      var lastDigit = digits.charCodeAt(digits.length - 1) - 48;
      if (lastDigit % 2 === 1) {
        digits = digits.substring(0, digits.length - 1) + String(lastDigit - 1);
      }
    }
    var out;
    if (exp < -4 || exp >= p) {
      var mant = digits.charAt(0);
      var frac = digits.substring(1).replace(/0+$/, '');
      if (frac) { mant += '.' + frac; }
      var ae = Math.abs(exp);
      out = mant + 'e' + (exp < 0 ? '-' : '+') + (ae < 10 ? '0' : '') + ae;
    } else if (exp >= 0) {
      var intPart = digits.substring(0, exp + 1);
      var fr = digits.substring(exp + 1).replace(/0+$/, '');
      out = intPart + (fr ? '.' + fr : '');
    } else {
      var z = '';
      for (var i = 0; i < -exp - 1; i++) { z += '0'; }
      out = '0.' + z + digits.replace(/0+$/, '');
    }
    return (neg ? '-' : '') + out;
  }

  function numField(chain, section, key, dflt) {
    var sec = get(chain, section, null);
    if (!isObj(sec)) { return dflt; }
    var v = toFloat(get(sec, key, dflt));
    return (v !== v) ? dflt : v;
  }
  function clampNum(value, dflt, lo, hi) {         // ui _clamp_num
    var v = toFloat(value);
    if (v !== v) { return dflt; }
    return Math.max(lo, Math.min(hi, v));
  }
  function outputStage(chain) {                    // ui _get_output_stage
    var cfg = sub(chain, 'output');
    var gain = clampNum(get(cfg, 'gain', 1.0), 1.0, 0.0, OUTPUT_GAIN_MAX);
    var outMax = clampNum(get(cfg, 'max', 1.0), 1.0, 0.0, 1.0);
    var outMin = clampNum(get(cfg, 'min', 0.0), 0.0, 0.0, 1.0);
    return [gain, Math.min(outMin, outMax), outMax];
  }

  var SEP = '  ·  ';   // two spaces, middle dot, two spaces

  /**
   * The folded chain's one-line summary (ui _chain_summary_line), e.g.
   *   "All SPS·O  ·  d0.38  ·  s0.41  ·  p1.3  ·  add  ·  wake 0.05  ·  120/200ms  ·  cut"
   * routing (optional): { zones: "All SPS", self: false, others: true,
   *                       params: ["MyParam", ...], sim: false }
   *   zones   the chain's zone selection string (comma separated)
   *   params  custom avatar parameters mapped onto the motor
   *   sim     true = the chain's "Simulated input" toggle is on (adds "sim")
   */
  function summaryLine(chain, routing) {
    if (!isObj(chain)) { return ' '; }
    routing = routing || {};
    var bits = [];
    var zonesStr = get(routing, 'zones', 'All SPS');
    if (zonesStr === null) { zonesStr = 'All SPS'; }
    var rawZones = String(zonesStr).split(',');
    var zones = [], i, z;
    for (i = 0; i < rawZones.length; i++) {
      z = rawZones[i].replace(/^\s+|\s+$/g, '');
      if (z && z !== 'None') { zones.push(z); }
    }
    var zoneTxt;
    if (!zones.length) {
      zoneTxt = 'no zones';
    } else if (zones.indexOf('All SPS') !== -1) {
      var rest = [];
      for (i = 0; i < zones.length; i++) {
        if (zones[i] !== 'All SPS') { rest.push(zones[i]); }
      }
      zoneTxt = 'All SPS' + (rest.length ? ' +' + rest.join('+') : '');
    } else {
      zoneTxt = zones.join('+');
    }
    var selfOn = get(routing, 'self', false);
    var othersOn = get(routing, 'others', true);
    if (selfOn === null) { selfOn = false; }
    if (othersOn === null) { othersOn = true; }
    var so = (selfOn ? 'S' : '') + (othersOn ? 'O' : '');
    bits.push(zoneTxt + '·' + (so ? so : '—'));

    var params = [];
    var rawParams = get(routing, 'params', []);
    if (typeof rawParams === 'string') { rawParams = [rawParams]; }
    var hasSim = !!get(routing, 'sim', false);
    for (i = 0; i < (rawParams || []).length; i++) {
      var p = rawParams[i];
      if (typeof p !== 'string' || !p.replace(/^\s+|\s+$/g, '')) { continue; }
      if (p === 'OGP/Sim/Pen' || p === 'OGP/Sim/Touch') { hasSim = true; continue; }
      params.push(p);
    }
    if (hasSim) { params.push('sim'); }
    if (params.length) { bits.push('@' + params.join('+')); }

    var d = numField(chain, 'depth', 'gain', 1.0);
    var sIn = numField(chain, 'speed', 'gain', 1.0);
    var sOut = numField(chain, 'speed', 'gain_out', sIn);
    bits.push('d' + pyGeneral(d, 2));
    bits.push(sIn === sOut ? 's' + pyGeneral(sIn, 2)
      : 's' + pyGeneral(sIn, 2) + '/' + pyGeneral(sOut, 2));
    var pIn = numField(chain, 'punch', 'gain', 0.0);
    var pOut = numField(chain, 'punch', 'gain_out', 0.0);
    if (pIn > 0 || pOut > 0) {
      bits.push(pOut === 0.0 ? 'p' + pyGeneral(pIn, 2)
        : 'p' + pyGeneral(pIn, 2) + '/' + pyGeneral(pOut, 2));
    }
    bits.push(String(get(chain, 'combine', 'max')));

    var wake = sub(chain, 'wake');
    if (get(wake, 'enabled', false)) {
      if (String(get(wake, 'mode', 'activity')) === 'strokes') {
        bits.push('wake ' + pyFixed(numField(chain, 'wake', 'thrusts', 3), 0) + '×');
      } else {
        bits.push('wake ' + pyGeneral(numField(chain, 'wake', 'wake_threshold', 0.05), 2));
      }
    }
    var duck = sub(chain, 'duck');
    if (get(duck, 'enabled', false) && String(get(chain, 'type', '')) !== 'penetration') {
      bits.push('duck');
    }
    bits.push(pyFixed(numField(chain, 'smoothing', 'rise_ms', 50.0), 0) + '/' +
      pyFixed(numField(chain, 'smoothing', 'fall_ms', 20.0), 0) + 'ms');
    if (get(sub(chain, 'texture'), 'enabled', false)) { bits.push('tex'); }
    if (get(sub(chain, 'zerocut'), 'enabled', false)) { bits.push('cut'); }
    var os = outputStage(chain);
    if (os[1] > 0.005 || os[2] < 0.995) {
      bits.push(pyFixed(os[1] * 100, 0) + '–' + pyFixed(os[2] * 100, 0) + '%');
    } else if (Math.abs(os[0] - 1.0) >= 0.005) {
      bits.push('×' + pyFixed(os[0], 2));
    }
    return bits.join(SEP);
  }

  /**
   * The small muted line on a collapsed stage card (ui _summary_for_stage).
   * stageId: depth | speed | punch | combine | wake | envelope | zerocut | output
   * opts.kind: motor kind for the Output card ("vib" by default; "lin" etc.)
   */
  function stageSummary(stageId, chain, opts) {
    chain = isObj(chain) ? chain : {};
    var cfg, gain;
    if (stageId === 'depth' || stageId === 'speed') {
      cfg = sub(chain, stageId);
      gain = toFloat(get(cfg, 'gain', 1.0));
      var curve = String(get(cfg, 'curve', 'linear'));
      return (curve === 'linear' ? '' : curve.charAt(0) + ' ') + '×' + pyGeneral(gain, 2);
    }
    if (stageId === 'punch') {
      gain = numField(chain, 'punch', 'gain', 0.0);
      if (gain <= 0.0) { return 'off'; }
      return '×' + pyGeneral(gain, 2) + ' · ' +
        pyFixed(numField(chain, 'punch', 'decay_ms', 120.0), 0) + ' ms';
    }
    if (stageId === 'combine') { return String(get(chain, 'combine', 'max')); }
    if (stageId === 'wake') {
      var wc = sub(chain, 'wake');
      if (!get(wc, 'enabled', false)) { return 'off'; }
      if (String(get(wc, 'mode', 'activity')) === 'strokes') {
        return pyFixed(numField(chain, 'wake', 'thrusts', 3), 0) + '× in ' +
          pyFixed(numField(chain, 'wake', 'window_s', 6.0), 0) + 's';
      }
      return 'Activity · wake ' +
        pyGeneral(numField(chain, 'wake', 'wake_threshold', 0.05), 2);
    }
    if (stageId === 'envelope') {
      var tc = sub(chain, 'texture');
      if (!get(tc, 'enabled', false)) { return 'texture off'; }
      return 'texture ' + pyFixed(numField(chain, 'texture', 'amount', 0.25) * 100.0, 0) +
        '% @ ' + pyFixed(numField(chain, 'texture', 'rate_hz', 2.0), 1) + 'Hz';
    }
    if (stageId === 'zerocut') {
      var zc = sub(chain, 'zerocut');
      if (!get(zc, 'enabled', false)) { return 'off'; }
      return '≤' + pyGeneral(numField(chain, 'zerocut', 'threshold', 0.0), 2) + '→0';
    }
    if (stageId === 'output') {
      var os = outputStage(chain);
      if (os[1] > 0.005 || os[2] < 0.995) {
        return pyFixed(os[1] * 100, 0) + '–' + pyFixed(os[2] * 100, 0) + '%';
      }
      if (Math.abs(os[0] - 1.0) >= 0.005) { return '×' + pyFixed(os[0], 2); }
      return (opts && opts.kind) ? String(opts.kind) : 'vib';
    }
    return '';
  }

  // ------------------------------------------------------------------
  // The quick controls on the collapsed stage cards
  // ------------------------------------------------------------------
  function fmtGain(v) { return '×' + pyFixed(v, 2); }
  /**
   * One entry per control on a collapsed card, in card order.
   *   id       handle for readControl / applyControl
   *   stage    which card it sits on            label  text next to it ('' = none)
   *   type     'slider' | 'cycle' | 'toggle'
   *   path     config key(s) inside one chain that it writes
   *   min/max/step   slider range in config units (drag step)
   *   snap     drag-magnetic detents, radius in config units
   *   format   value -> the readout text the app shows
   */
  var CONTROLS = [
    { id: 'depth.gain', stage: 'depth', label: '', type: 'slider',
      path: [['depth', 'gain']], min: 0, max: 2, step: 0.01, dflt: 1.0,
      snap: { at: [0, 0.5, 1, 1.5, 2], radius: 0.08 }, format: fmtGain },
    { id: 'speed.gain', stage: 'speed', label: 'In', type: 'slider',
      path: [['speed', 'gain']], min: 0, max: 2, step: 0.01, dflt: 1.0,
      snap: { at: [0, 0.5, 1, 1.5, 2], radius: 0.08 }, format: fmtGain },
    { id: 'speed.gain_out', stage: 'speed', label: 'Out', type: 'slider',
      path: [['speed', 'gain_out']], min: 0, max: 2, step: 0.01,
      dfltFrom: ['speed', 'gain'], dflt: 1.0,
      snap: { at: [0, 0.5, 1, 1.5, 2], radius: 0.08 }, format: fmtGain },
    { id: 'punch.gain', stage: 'punch', label: 'In', type: 'slider',
      path: [['punch', 'gain']], min: 0, max: 2, step: 0.01, dflt: 0.0,
      snap: { at: [0, 0.5, 1, 1.5, 2], radius: 0.08 }, format: fmtGain },
    { id: 'punch.gain_out', stage: 'punch', label: 'Out', type: 'slider',
      path: [['punch', 'gain_out']], min: 0, max: 2, step: 0.01, dflt: 0.0,
      snap: { at: [0, 0.5, 1, 1.5, 2], radius: 0.08 }, format: fmtGain },
    { id: 'combine', stage: 'combine', label: '', type: 'cycle',
      path: [['combine']], options: COMBINE_OPS, dflt: 'max',
      format: function (v) {
        return { add: 'Add', max: 'Max', multiply: 'Multiply' }[v] || String(v);
      } },
    { id: 'wake.wake_threshold', stage: 'wake', label: '', type: 'slider',
      path: [['wake', 'wake_threshold']], min: 0, max: 1, step: 0.01, dflt: 0.05,
      when: 'wake.mode != strokes',
      format: function (v) { return pyFixed(v, 2); } },
    { id: 'wake.thrusts', stage: 'wake', label: '', type: 'slider',
      path: [['wake', 'thrusts']], min: 1, max: 10, step: 1, dflt: 3,
      when: 'wake.mode == strokes', integer: true,
      format: function (v) { return pyFixed(v, 0) + '×'; } },
    { id: 'smoothing.ms', stage: 'envelope', label: '', type: 'slider',
      // ONE slider writes BOTH times; it shows the slower of the two.
      path: [['smoothing', 'rise_ms'], ['smoothing', 'fall_ms']],
      min: 0, max: 500, step: 1, dflt: 50, read: 'max',
      snap: { at: [0, 100, 200, 300, 400, 500], radius: 15 },
      format: function (v) { return String(Math.floor(v)) + 'ms'; } },
    { id: 'texture.enabled', stage: 'envelope', label: 'Texture', type: 'toggle',
      path: [['texture', 'enabled']], dflt: false },
    { id: 'zerocut.enabled', stage: 'zerocut', label: 'Cut', type: 'toggle',
      path: [['zerocut', 'enabled']], dflt: false },
    { id: 'output.gain', stage: 'output', label: '', type: 'slider',
      path: [['output', 'gain']], min: 0, max: 2, step: 0.01, dflt: 1.0,
      format: fmtGain }
  ];
  function findControl(id) {
    for (var i = 0; i < CONTROLS.length; i++) {
      if (CONTROLS[i].id === id) { return CONTROLS[i]; }
    }
    return null;
  }
  function readPath(chain, path) {
    var cur = chain;
    for (var i = 0; i < path.length; i++) {
      if (!isObj(cur)) { return undefined; }
      cur = get(cur, path[i], undefined);
    }
    return cur;
  }
  /** Current value of a quick control, as the app seeds the widget. */
  function readControl(chain, id) {
    var c = findControl(id);
    if (!c) { return undefined; }
    var v = readPath(chain, c.path[0]);
    if (v === undefined) {
      v = c.dfltFrom ? readPath(chain, c.dfltFrom) : undefined;
      if (v === undefined) { v = c.dflt; }
    }
    if (c.read === 'max') {
      var v2 = readPath(chain, c.path[1]);
      if (v === undefined) { v = 50.0; }
      if (v2 === undefined) { v2 = 20.0; }
      v = Math.max(+v, +v2);
    }
    return v;
  }
  /** Write a quick control's value into a chain config (in place). */
  function applyControl(chain, id, value) {
    var c = findControl(id);
    if (!c) { return chain; }
    if (c.type === 'slider') {
      value = Math.max(c.min, Math.min(c.max, +value));
      if (c.integer) { value = roundHalfEven(value); }
    } else if (c.type === 'toggle') {
      value = !!value;
    }
    for (var i = 0; i < c.path.length; i++) {
      var path = c.path[i], cur = chain;
      for (var j = 0; j < path.length - 1; j++) {
        if (!isObj(cur[path[j]])) { cur[path[j]] = {}; }
        cur = cur[path[j]];
      }
      cur[path[path.length - 1]] = value;
    }
    return chain;
  }

  // ------------------------------------------------------------------
  return {
    // config
    defaults: defaults,
    defaultChain: defaultChain,
    // engine
    create: create,
    Motor: Motor,
    // simulator
    simWave: simWave,
    samplePattern: samplePattern,
    WAVEFORMS: WAVEFORMS,
    // text
    summaryLine: summaryLine,
    stageSummary: stageSummary,
    // quick controls
    CONTROLS: CONTROLS,
    readControl: readControl,
    applyControl: applyControl,
    COMBINE_OPS: COMBINE_OPS,
    MERGE_OPS: MERGE_OPS,
    // metadata
    TRACE_IDS: TRACE_IDS,
    STAGE_ORDER: STAGE_ORDER,
    STAGE_LABELS: STAGE_LABELS,
    STAGE_TRACES: STAGE_TRACES,
    STAGE_LEVEL_TRACE: STAGE_LEVEL_TRACE,
    TRACE_HUES: TRACE_HUES,
    APP_DEFAULTS: APP_DEFAULTS,
    SLEEP_WAKE_OVERRIDE: SLEEP_WAKE_OVERRIDE,
    // pure maths, exposed for tests / custom drawing (curve previews etc.)
    math: {
      applyCurve: applyCurve, combine: combine, mergeChains: mergeChains,
      smooth: smooth, activityMeter: activityMeter, activityGate: activityGate,
      detectThrust: detectThrust, pyFixed: pyFixed, pyGeneral: pyGeneral
    }
  };
}));
