/* Compares the website's colour port, docs/assets/ogp-accent.js, with a
 * reference written by check_accent.py from the app's accent_shift.py.
 * Colour strings must be equal character for character; doubles are
 * compared bit for bit and the largest difference is reported.
 *
 *   node tools/site_ports/check_accent.js [accent_reference.json | its folder] [--js FILE]
 *
 *   reference   default: <system temp>/ogp-site-ports/accent_reference.json
 *   --js FILE   check this file instead of docs/assets/ogp-accent.js
 *
 * Exit code 0 only when everything matches. The last line is
 * machine-readable: RESULT {json}.
 */
'use strict';
var fs = require('fs');
var os = require('os');
var path = require('path');

var REPO = path.resolve(__dirname, '..', '..');
// hueOf / deltaFor go through atan2 and pow, which V8 and the Microsoft C
// runtime round differently in the last bit, so those doubles get a
// tolerance (in degrees). Everything else must be exact.
var DOUBLE_TOL = 1e-9;

var argv = process.argv.slice(2);
var jsPath = path.join(REPO, 'docs', 'assets', 'ogp-accent.js');
var refPath = path.join(os.tmpdir(), 'ogp-site-ports', 'accent_reference.json');
for (var ai = 0; ai < argv.length; ai++) {
  if (argv[ai] === '--js') {
    jsPath = path.resolve(argv[++ai]);
  } else {
    refPath = path.resolve(argv[ai]);
  }
}
if (fs.existsSync(refPath) && fs.statSync(refPath).isDirectory()) {
  refPath = path.join(refPath, 'accent_reference.json');
}
process.chdir(REPO);
if (!fs.existsSync(refPath)) {
  console.log('no reference at ' + refPath +
    '\nrun: venv\\Scripts\\python.exe tools\\site_ports\\check_accent.py');
  process.exitCode = 2;
} else if (!fs.existsSync(jsPath)) {
  console.log('port not found: ' + jsPath);
  process.exitCode = 2;
} else {
  main();
}

function main() {
  var A = require(jsPath);
  var ref = JSON.parse(fs.readFileSync(refPath, 'utf8'));
  console.log('port under test: ' + jsPath);
  console.log('reference:       ' + refPath + (ref.quick ? '  (quick set)' : ''));

  var failed = false;
  var stringsTotal = 0, stringsBad = 0;

  function strings(label, rows, hexIdx, deltaIdx, wantIdx) {
    var ok = 0, bad = 0;
    rows.forEach(function (r) {
      var got = A.shiftHex(r[hexIdx], r[deltaIdx]);
      if (got === r[wantIdx]) { ok++; } else {
        bad++;
        if (bad <= 8) {
          console.log('  MISMATCH ' + r[hexIdx] + ' by ' + r[deltaIdx] +
            ': python ' + r[wantIdx] + '  js ' + got);
        }
      }
    });
    console.log(label + ': ' + ok + '/' + rows.length + ' identical' +
      (bad ? '   <-- ' + bad + ' DIFFER' : ''));
    stringsTotal += rows.length;
    stringsBad += bad;
    if (bad || !rows.length) { failed = true; }
  }

  function doubles(label, pairs, tol) {
    var exact = 0, worst = 0;
    pairs.forEach(function (p) {
      if (p[0] === p[1]) { exact++; }
      var d = Math.abs(p[0] - p[1]);
      if (!(d <= worst)) { worst = d; }
    });
    console.log(label + ': ' + exact + '/' + pairs.length +
      ' bit-identical, max |diff| ' + (worst === 0 ? '0' : worst.toExponential(2)));
    if (!(worst <= tol) || !pairs.length) { failed = true; }
    return worst;
  }

  console.log('\nshiftHex');
  strings('  tokens    (NEON + MIDNIGHT + PALETTE.green, ' + ref.required_hex_count +
    ' hexes x ' + ref.required_delta_count + ' turns)', ref.required, 1, 2, 3);
  strings('  extended  (whole palette, retired, primaries, greys; fractional/negative turns)',
    ref.extended, 0, 1, 2);
  strings('  random    (random colours x random turns)', ref.random, 0, 1, 2);

  // zero turn = untouched, character for character (case and missing # kept)
  var same = A.shiftHex('#31F272', 0) === '#31F272' && A.shiftHex('31f272', 0) === '31f272' &&
    A.shiftHex('#808080', 77) === '#808080';
  console.log('  zero turn / grey returned untouched: ' + (same ? 'OK' : 'MISMATCH'));
  if (!same) { failed = true; }

  console.log('shiftTokens (each mode turned onto each palette hue)');
  var okT = 0, nT = 0;
  ref.turned.forEach(function (row) {
    var mode = row[0], d = row[2], want = row[3];
    var got = A.shiftTokens(ref.tokens[mode], d);
    Object.keys(want).forEach(function (k) {
      nT++;
      if (got[k] === want[k]) { okT++; } else {
        if (nT - okT <= 8) {
          console.log('  MISMATCH ' + mode + '.' + k + ' -> ' + row[1] + ': python ' +
            want[k] + '  js ' + got[k]);
        }
        failed = true;
      }
    });
  });
  console.log('  ' + okT + '/' + nT + ' tokens identical');
  if (!nT) { failed = true; }

  console.log('doubles');
  doubles('  math.hypot port', ref.hypot.map(function (r) {
    return [A._pyHypot(r[0], r[1]), r[2]];
  }), 0);
  doubles('  round(x, 4) port', ref.round.map(function (r) {
    return [A._pyRound(r[0], 4), r[1]];
  }), 0);
  doubles('  round(x, 3) port', ref.round.map(function (r) {
    return [A._pyRound(r[0], 3), r[2]];
  }), 0);
  var worstHue = doubles('  hueOf', ref.hues.map(function (r) {
    return [A.hueOf(r[0]), r[1]];
  }), DOUBLE_TOL);
  var lch = [];
  ref.oklch.forEach(function (r) {
    var got = A.toOklch(r[0]);
    lch.push([got[0], r[1][0]]); lch.push([got[1], r[1][1]]); lch.push([got[2], r[1][2]]);
  });
  doubles('  toOklch (L, C, h)', lch, DOUBLE_TOL);
  var worstDelta = doubles('  deltaFor', ref.deltas.map(function (r) {
    return [A.deltaFor(r[0], r[1]), r[2]];
  }), DOUBLE_TOL);

  console.log('');
  console.log(failed ? 'FAIL' : 'PASS - every shifted colour equals Python\'s string');
  console.log('RESULT ' + JSON.stringify({
    ok: !failed,
    strings: stringsTotal + nT,
    strings_bad: stringsBad + (nT - okT),
    token_cases: ref.required.length,
    worst_hue_diff: (worstHue === worstHue) ? worstHue : null,
    worst_delta_diff: (worstDelta === worstDelta) ? worstDelta : null
  }));
  process.exitCode = failed ? 1 : 0;
}
