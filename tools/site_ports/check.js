/* Replays a reference written by gen_reference.py (the real Python
 * MotorRouter) through the website's port, docs/assets/ogp-chain.js, and
 * reports the largest difference per signal per scenario.
 *
 *   node tools/site_ports/check.js [reference.json | its folder] [--js FILE] [--all]
 *
 *   reference   default: <system temp>/ogp-site-ports/reference.json
 *   --js FILE   check this file instead of docs/assets/ogp-chain.js
 *   --all       also print one line per (scenario, config) run
 *
 * Exit code 0 only when every signal in every run is within TOL and every
 * string / default comparison is exact. The last line is machine-readable:
 * RESULT {json}.
 */
'use strict';
var fs = require('fs');
var os = require('os');
var path = require('path');

var REPO = path.resolve(__dirname, '..', '..');
var TOL = 1e-9;

// ---- arguments (resolved against the caller's directory, then cd to the repo)
var argv = process.argv.slice(2);
var SHOW_ALL = false;
var jsPath = path.join(REPO, 'docs', 'assets', 'ogp-chain.js');
var refPath = path.join(os.tmpdir(), 'ogp-site-ports', 'reference.json');
for (var ai = 0; ai < argv.length; ai++) {
  if (argv[ai] === '--all') {
    SHOW_ALL = true;
  } else if (argv[ai] === '--js') {
    jsPath = path.resolve(argv[++ai]);
  } else {
    refPath = path.resolve(argv[ai]);
  }
}
if (fs.existsSync(refPath) && fs.statSync(refPath).isDirectory()) {
  refPath = path.join(refPath, 'reference.json');
}
process.chdir(REPO);
// process.exitCode rather than process.exit(): exit() can cut off output
// that is still queued when stdout is a console.
if (!fs.existsSync(refPath)) {
  console.log('no reference at ' + refPath +
    '\nrun: venv\\Scripts\\python.exe tools\\site_ports\\gen_reference.py');
  process.exitCode = 2;
} else if (!fs.existsSync(jsPath)) {
  console.log('port not found: ' + jsPath);
  process.exitCode = 2;
} else {
  main();
}

function main() {
var OGPChain = require(jsPath);
var ref = JSON.parse(fs.readFileSync(refPath, 'utf8'));
console.log('port under test: ' + jsPath);
console.log('reference:       ' + refPath + (ref.quick ? '  (quick set)' : ''));

var NUMERIC = ref.trace_keys;                      // per-chain numeric traces
var SIGNALS = NUMERIC.concat(['final', 'contact']);
var failures = [];

function deepCopy(v) { return JSON.parse(JSON.stringify(v)); }
function setPath(rootObj, p, value) {
  var cur = rootObj;
  for (var i = 0; i < p.length - 1; i++) { cur = cur[p[i]]; }
  cur[p[p.length - 1]] = value;
}
function deepEqual(a, b) {
  if (a === b) { return true; }
  if (typeof a !== typeof b || a === null || b === null) { return false; }
  if (typeof a !== 'object') { return false; }
  var ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
  if (ka.length !== kb.length) { return false; }
  for (var i = 0; i < ka.length; i++) {
    if (ka[i] !== kb[i] || !deepEqual(a[ka[i]], b[kb[i]])) { return false; }
  }
  return true;
}
function fmt(e) { return e === 0 ? '0' : e.toExponential(2); }
function pad(s, n) { s = String(s); while (s.length < n) { s += ' '; } return s; }

// ---------------------------------------------------------------- 1. defaults
var defaultsOk = (function () {
  var ok1 = deepEqual(OGPChain.defaults(), ref.configs['default']);
  var ok2 = deepEqual({ chains: [OGPChain.defaultChain()], merge: 'max' }, ref.default_chain);
  var ok3 = deepEqual(OGPChain.SLEEP_WAKE_OVERRIDE, ref.sleep_wake_override);
  var ok4 = OGPChain.APP_DEFAULTS.strength === ref.app_defaults.strength &&
    deepEqual(OGPChain.APP_DEFAULTS.antistuck, ref.app_defaults.antistuck) &&
    OGPChain.APP_DEFAULTS.routerHz === ref.app_defaults.router_poll_rate_hz;
  var a = OGPChain.defaults(), b = OGPChain.defaults();
  a.chains[0].depth.gain = 99;
  var ok5 = b.chains[0].depth.gain !== 99;        // deep-copied each call
  console.log('\ndefaults() == preset_motor_mix():            ' + (ok1 ? 'OK' : 'MISMATCH'));
  console.log('defaultChain() == DEFAULT_MIX_CONFIG chain:  ' + (ok2 ? 'OK' : 'MISMATCH'));
  console.log('SLEEP_WAKE_OVERRIDE:                         ' + (ok3 ? 'OK' : 'MISMATCH'));
  console.log('APP_DEFAULTS (strength / anti-stuck / Hz):   ' + (ok4 ? 'OK' : 'MISMATCH'));
  console.log('defaults() returns a fresh copy:             ' + (ok5 ? 'OK' : 'MISMATCH'));
  if (!(ok1 && ok2 && ok3 && ok4 && ok5)) { failures.push('defaults'); return false; }
  return true;
}());

// ------------------------------------------------------------------- 2. runs
var perScenario = {};      // name -> signal -> max err (over configs/chains)
var scenarioOrder = [];
var perSignal = {};
var totalTicks = 0, modeMismatch = 0, strokeMismatch = 0, bandMismatch = 0;
var worstOverall = 0;

ref.runs.forEach(function (run) {
  var config = deepCopy(ref.configs[run.config]);
  var motor = OGPChain.create(config, {
    strength: run.initial.strength,
    off: run.initial.off,
    sleep: run.initial.sleep,
    antistuck: run.initial.antistuck
  });
  var events = run.events.slice();
  var ev = 0;
  var err = {};
  SIGNALS.forEach(function (s) { err[s] = 0; });
  var n = run.ticks;
  for (var i = 0; i < n; i++) {
    while (ev < events.length && events[ev].tick === i) {
      var e = events[ev];
      if (e.kind === 'cfg') {
        setPath(config, e.path, e.value);
      } else {
        var o = {}; o[e.kind] = e.value;
        motor.setOptions(o);
      }
      ev++;
    }
    var r = motor.step(i === 0 ? 0 : run.dt[i - 1],
      { pen: run.pen[i], touch: run.touch[i] });
    var d = Math.abs(r.out - run.final[i]);
    if (!(d <= err['final'])) { err['final'] = d; }
    d = Math.abs(r.contact - run.contact[i]);
    if (!(d <= err.contact)) { err.contact = d; }
    if (r.strokes !== run.strokes[i]) { strokeMismatch++; }
    for (var c = 0; c < run.chains.length; c++) {
      var got = r.chains[c] || {}, want = run.chains[c];
      for (var k = 0; k < NUMERIC.length; k++) {
        var key = NUMERIC[k];
        var g = got[key];
        if (typeof g === 'boolean') { g = g ? 1 : 0; }
        d = Math.abs(g - want[key][i]);
        if (!(d <= err[key])) { err[key] = d; }      // NaN-safe: NaN sticks
      }
      if (got.wake_mode !== run.wake_mode[c][i]) { modeMismatch++; }
    }
    if (r.chains.length !== run.chains.length) { failures.push(run.name + ': chain count'); }
  }
  if (!motor.band || motor.band[0] !== run.band[0] || motor.band[1] !== run.band[1]) {
    bandMismatch++;
  }
  totalTicks += n;
  if (!perScenario[run.name]) { perScenario[run.name] = {}; scenarioOrder.push(run.name); }
  var worst = 0, worstSig = '-';
  SIGNALS.forEach(function (s) {
    var v = err[s];
    if (!(v <= (perScenario[run.name][s] || 0))) { perScenario[run.name][s] = v; }
    if (!(v <= (perSignal[s] || 0))) { perSignal[s] = v; }
    if (!(v <= worst)) { worst = v; worstSig = s; }
  });
  if (!(worst <= worstOverall)) { worstOverall = worst; }
  if (!(worst <= TOL)) { failures.push(run.name + '/' + run.config + ' ' + worstSig + ' ' + worst); }
  if (SHOW_ALL) {
    console.log(pad(run.name, 28) + pad(run.config, 14) + 'ticks=' + pad(n, 6) +
      'max err ' + pad(fmt(worst), 10) + '(' + worstSig + ')');
  }
});

console.log('\nMax |JS - Python| per scenario (over all configs, chains and ticks)');
console.log(pad('scenario', 28) + pad('final out', 11) + pad('contact', 11) +
  pad('worst trace', 13) + 'which');
scenarioOrder.forEach(function (name) {
  var row = perScenario[name];
  var worst = 0, which = '-';
  NUMERIC.forEach(function (s) {
    if (!((row[s] || 0) <= worst)) { worst = row[s]; which = s; }
  });
  console.log(pad(name, 28) + pad(fmt(row['final'] || 0), 11) +
    pad(fmt(row.contact || 0), 11) + pad(fmt(worst), 13) + which);
});

console.log('\nMax |JS - Python| per signal (over every run)');
SIGNALS.forEach(function (s) {
  console.log('  ' + pad(s, 14) + fmt(perSignal[s] || 0));
});

console.log('\nruns: ' + ref.runs.length + '   ticks: ' + totalTicks +
  '   worst error anywhere: ' + fmt(worstOverall) + '   (target <= ' + TOL + ')');
console.log('wake_mode string mismatches: ' + modeMismatch +
  '   stroke-counter mismatches: ' + strokeMismatch +
  '   output-band mismatches: ' + bandMismatch);
if (modeMismatch || strokeMismatch || bandMismatch) { failures.push('discrete mismatches'); }
if (!ref.runs.length) { failures.push('reference holds no runs'); }

// ------------------------------------------- 2b. stepAt() == step(), reset()
(function () {
  if (!ref.runs.length) { return; }
  var run = ref.runs.filter(function (r) {
    return r.config === 'default' && /jittery_dt$/.test(r.name);
  })[0] || ref.runs[0];
  var a = OGPChain.create(deepCopy(ref.configs[run.config]), run.initial);
  var b = OGPChain.create(deepCopy(ref.configs[run.config]), run.initial);
  var clock = 0, same = true, i;
  for (i = 0; i < run.ticks; i++) {
    if (i > 0) { clock += run.dt[i - 1]; }
    var ra = a.step(i === 0 ? 0 : run.dt[i - 1], { pen: run.pen[i], touch: run.touch[i] });
    var rb = b.stepAt(clock, { pen: run.pen[i], touch: run.touch[i] });
    if (ra.out !== rb.out || ra.contact !== rb.contact) { same = false; }
  }
  // reset() must put the motor back to a just-created state
  a.reset();
  var worst = 0;
  for (i = 0; i < run.ticks; i++) {
    var r2 = a.step(i === 0 ? 0 : run.dt[i - 1], { pen: run.pen[i], touch: run.touch[i] });
    var d = Math.abs(r2.out - run.final[i]);
    if (!(d <= worst)) { worst = d; }
  }
  console.log('\nstepAt(clock) identical to step(dt): ' + (same ? 'OK' : 'MISMATCH') +
    '   replay after reset(): max err ' + fmt(worst) + '   (' + run.name + ')');
  if (!same || !(worst <= TOL)) { failures.push('stepAt / reset'); }
}());

// -------------------------------------------------------------- 3. simulator
var simWorst = 0, simSamples = 0;
(function () {
  var rows = 0;
  var byWave = {}, order = [];
  ref.sim.forEach(function (row) {
    var f = OGPChain.simWave(row.wave, row.hz, row.amp);
    var w = 0;
    for (var i = 0; i < row.t.length; i++) {
      var d = Math.abs(f(row.t[i]) - row.v[i]);
      if (!(d <= w)) { w = d; }
      simSamples++;
    }
    rows++;
    if (byWave[row.wave] === undefined) { byWave[row.wave] = 0; order.push(row.wave); }
    if (!(w <= byWave[row.wave])) { byWave[row.wave] = w; }
    if (!(w <= simWorst)) { simWorst = w; }
  });
  console.log('\nsimWave vs mixer.sample_pattern: ' + rows + ' wave/freq/amp sets, ' +
    simSamples + ' samples');
  order.forEach(function (w) { console.log('  ' + pad(w, 10) + fmt(byWave[w])); });
  // capitalised names, as the app's dropdown shows them
  var cap = OGPChain.simWave('Sine', 1, 1)(0.25), low = OGPChain.simWave('sine', 1, 1)(0.25);
  if (cap !== low) { failures.push('simWave capitalisation'); }
  if (!(simWorst <= TOL)) { failures.push('simWave ' + simWorst); }
  if (!simSamples) { failures.push('reference holds no simulator samples'); }
}());

// ------------------------------------------------------------ 4. text output
var lineTotal = 0, lineBad = 0, stageTotal = 0, stageBad = 0;
(function () {
  var s = ref.summary;
  if (!s || s.error) {
    console.log('\nsummary strings: reference unavailable (' + (s && s.error) + ')');
    failures.push('summary reference missing');
    return;
  }
  s.rows.forEach(function (row) {
    var chain = ref.configs[row.config].chains[row.chain];
    var routing = {};
    if (row.routing.zones !== null) { routing.zones = row.routing.zones; }
    if (row.routing.self !== null) { routing.self = row.routing.self; }
    if (row.routing.others !== null) { routing.others = row.routing.others; }
    routing.params = row.routing.params;
    var got = OGPChain.summaryLine(chain, routing);
    lineTotal++;
    if (got !== row.line) {
      lineBad++;
      if (lineBad <= 5) { console.log('  MISMATCH\n    py: ' + row.line + '\n    js: ' + got); }
    }
  });
  s.stages.forEach(function (row) {
    var chain = ref.configs[row.config].chains[row.chain];
    Object.keys(row.subtitles).forEach(function (sid) {
      stageTotal++;
      var got = OGPChain.stageSummary(sid, chain);
      if (got !== row.subtitles[sid]) {
        stageBad++;
        if (stageBad <= 5) {
          console.log('  MISMATCH ' + sid + '  py: ' + row.subtitles[sid] + '  js: ' + got);
        }
      }
    });
  });
  console.log('\nsummaryLine vs _chain_summary_line: ' + (lineTotal - lineBad) + '/' +
    lineTotal + ' identical');
  console.log('stageSummary vs _summary_for_stage: ' + (stageTotal - stageBad) + '/' +
    stageTotal + ' identical');
  console.log('  default Penetration chain: ' +
    OGPChain.summaryLine(OGPChain.defaults().chains[0]));
  console.log('  default Touch chain:       ' +
    OGPChain.summaryLine(OGPChain.defaults().chains[1]));
  if (lineBad || stageBad) { failures.push('summary strings'); }
  if (!lineTotal || !stageTotal) { failures.push('reference holds no summary strings'); }
}());

console.log('');
if (failures.length) {
  console.log('FAIL (' + failures.length + ')');
  failures.slice(0, 20).forEach(function (f) { console.log('  ' + f); });
} else {
  console.log('PASS - every signal within ' + TOL + ', all strings identical');
}
console.log('RESULT ' + JSON.stringify({
  ok: failures.length === 0,
  runs: ref.runs.length,
  scenarios: scenarioOrder.length,
  ticks: totalTicks,
  // null = a NaN turned up somewhere (JSON has no NaN)
  worst: (worstOverall === worstOverall) ? worstOverall : null,
  discrete_mismatches: modeMismatch + strokeMismatch + bandMismatch,
  defaults_ok: defaultsOk,
  sim_samples: simSamples,
  sim_worst: (simWorst === simWorst) ? simWorst : null,
  summary_lines: lineTotal, summary_lines_bad: lineBad,
  stage_subtitles: stageTotal, stage_subtitles_bad: stageBad,
  failures: failures.length
}));
process.exitCode = failures.length ? 1 : 0;
}   // main
