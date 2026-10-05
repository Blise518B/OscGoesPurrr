/* ============================================================================
   The demo: a working copy of the OscGoesPurrr window (see demo.css).

   Nothing in here is animated for show. The contact comes from the app's own
   input simulator (or from the visitor, through OGPDemo.setManual), runs
   through the app's real signal chain -- ogp-chain.js is a port of
   src/motor_router.py, checked against it number for number -- and the
   meters show what each toy would be sent. The knobs on the stage cards
   edit the same settings the app's do.

   Colours: the Appearance card turns the page's tokens with the app's own
   maths (ogp-accent.js, a port of src/accent_shift.py).
   ========================================================================= */
(function () {
  'use strict';
  var host = document.getElementById('ogp-demo');
  if (!host) return;
  var root = document.documentElement;
  var Chain = window.OGPChain, Accent = window.OGPAccent;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function tok(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function el(html) { var d = document.createElement('div'); d.innerHTML = html.trim(); return d.firstChild; }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function $(sel, ctx) { return (ctx || host).querySelector(sel); }
  function $$(sel, ctx) { return [].slice.call((ctx || host).querySelectorAll(sel)); }

  // ── what is on the demo's "PC" ────────────────────────────────────────────
  // Connected toys take the three toy hues in order, like the app.
  var TOYS = [
    { id: 'edge', name: 'Lovense Edge', icon: 'edge_2', hue: 'cyan', batt: 54, motors: 2, on: true },
    { id: 'gush', name: 'Lovense Gush', icon: 'gush_2', hue: 'blue', batt: 67, motors: 1, on: true },
    { id: 'lush', name: 'Lovense Lush', icon: 'lush_3', hue: 'purple', batt: 82, motors: 1, on: true },
    { id: 'domi', name: 'Lovense Domi', icon: 'domi_2', hue: '', batt: 0, motors: 1, on: false }
  ];
  // A mode is a routing: which parts of the avatar drive which toy. The
  // demo's contact is a penetration of the "Pussy" socket.
  var MODES = [
    { name: 'Combined', icon: '🔗', zones: { edge: 'All SPS', gush: 'All SPS', lush: 'All SPS', domi: 'All SPS' } },
    { name: 'Separate', icon: '🔀', zones: { edge: 'Pussy, Anal', gush: 'Penis', lush: 'Pussy', domi: 'Pussy' } },
    { name: 'Custom 1', icon: '🃏', zones: { edge: '', gush: '', lush: 'Pussy', domi: '' } },
    { name: 'Custom 2', icon: '🎲', zones: { edge: 'Anal', gush: 'Penis', lush: 'Mouth', domi: '' } }
  ];
  var CONTACT_ZONE = 'Pussy';
  function zonesOf(toyId) { return MODES[S.mode].zones[toyId]; }
  function hears(toyId) { var z = zonesOf(toyId); return z === 'All SPS' || z.split(', ').indexOf(CONTACT_ZONE) >= 0; }
  function zoneLabel(toyId) {
    var z = zonesOf(toyId), n = z ? z.split(', ').length : 0;
    return z === 'All SPS' ? z : n === 0 ? 'No zones' : n === 1 ? z : n + ' zones';
  }
  var STAGES = ['input', 'depth', 'speed', 'punch', 'combine', 'wake', 'envelope', 'zerocut', 'output'];
  var NOTES = {
    'SPS Sources': 'Builds a zone out of your avatar’s own contact receivers, for avatars whose contacts are not standard SPS / OGB sockets and plugs. A source you make here can be picked for any toy on Home.',
    'OSC Inspector': 'A live table of every parameter your avatar sends over OSC, with search — for finding the contact you want, or checking that one moves at all.',
    'OSC Diagnostics': 'Shows whether VRChat is reaching the app: the port in use, packets per second, when the last one arrived, and buttons to reconnect by hand.',
    'System Log': 'What the app did and when: toys connecting and dropping, the link to VRChat, updates, errors.',
    'Help': 'The app’s own manual: what each page is for and how the signal chain works. Every control also explains itself when you rest the pointer on it.'
  };

  var S = {
    mode: 0, strength: 0.85, off: false, sleep: false, page: 'Home',
    sim: { on: true, hz: 1.0, amp: 1.0, shape: 0 }, manual: null, manualUntil: 0,
    graph: false, graphToy: 'lush', graphMotor: 0, graphChain: 0,
    testUntil: 0, t: 0
  };

  // ── the engine: one real chain object per motor ──────────────────────────
  var SHAPES = ((Chain && Chain.WAVEFORMS) || ['sine']).map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); });
  var ROUTER_DT = 1 / ((Chain && Chain.APP_DEFAULTS.routerHz) || 90);      // the app's routing tick
  var SIM_TICK = (Chain && Chain.APP_DEFAULTS.simTickS) || 0.016;          // its simulator publishes this often
  var TEST_LEVEL = 0.2;                                                    // what Test sends, before the toy's band
  function newMotor() {
    var cfg = Chain.defaults();        // the app's preset: a Penetration and a Touch chain, merged by max
    return { cfg: cfg, m: Chain.create(cfg, { strength: S.strength }), out: 0, res: null, muted: false, testUntil: 0 };
  }
  var motors = {};
  if (Chain) {
    TOYS.forEach(function (toy) {
      motors[toy.id] = [];
      for (var i = 0; i < toy.motors; i++) motors[toy.id].push(newMotor());
    });
  }
  var simFn = null;
  function rebuildSim() {
    simFn = Chain ? Chain.simWave(SHAPES[S.sim.shape], S.sim.hz, S.sim.amp) : null;
  }
  rebuildSim();

  function contactNow() {
    if (S.manual !== null && S.t < S.manualUntil) return S.manual;
    if (!S.sim.on || !simFn) return 0;
    return clamp(simFn(Math.floor(S.t / SIM_TICK) * SIM_TICK), 0, 1);
  }

  // ── build the window ──────────────────────────────────────────────────────
  var HOME_SVG = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"><path d="M3 9.5 10 3.5l7 6"/><path d="M5 8.5V16h10V8.5"/><path d="M8.5 16v-4h3v4"/></svg>';
  var BATT_SVG = '<svg viewBox="0 0 10 14"><rect x="3" y="0" width="4" height="2" rx=".6" fill="currentColor"/><rect x=".6" y="2" width="8.8" height="11.4" rx="1.6" fill="currentColor" opacity=".9"/></svg>';

  function sideHTML() {
    var modes = MODES.map(function (m, i) {
      return '<span class="o-btn o-mode' + (i === S.mode ? ' on' : '') + '" data-mode="' + i + '" data-tip="mode">' + m.name + '<i>' + m.icon + '</i></span>';
    }).join('');
    function nav(name) { return '<span class="n" data-go="' + name + '">' + name + '</span>'; }
    return '<div class="o-side">' +
      '<div class="o-brand" data-go="Home">OscGoesPurrr</div><div class="o-build"><span class="ver-tag"></span>&nbsp;</div>' +
      '<div class="o-grid o-modes">' + modes + '</div>' +
      '<div class="o-strrow" data-tip="strength"><span>Total output strength</span><b class="js-strval">85%</b></div>' +
      '<input type="range" class="big js-strength" min="0" max="100" value="85" tabindex="-1" data-tip="strength">' +
      '<div class="o-grid o-offrow"><span class="o-btn o-mode warn js-off" data-tip="off">Off</span><span class="o-btn o-mode js-sleep" data-tip="sleep">Sleep</span></div>' +
      '<div class="o-nav">' +
        '<span class="n home on" data-go="Home">' + HOME_SVG + 'Home</span>' + nav('Statistics') +
        '<span class="grp">TOOLS</span>' + nav('SPS Sources') + nav('OSC Inspector') + nav('OSC Diagnostics') + nav('System Log') +
        '<span class="gap"></span>' + nav('Settings') + nav('Help') +
      '</div>' +
      '<div class="o-links"><div class="l" data-tip="vrc"><span>VRChat</span><span class="o-pill ok">CONNECTED</span></div>' +
      '<div class="l" data-tip="intiface"><span>Intiface</span><span class="o-pill ok">CONNECTED</span></div></div>' +
      '</div>';
  }

  function toyHTML(toy) {
    var style = toy.hue ? ' style="--hue:var(--' + toy.hue + ');--hue-mid:var(--' + toy.hue + '-mid)"' : '';
    var meters = '';
    for (var i = 0; i < toy.motors; i++) meters += '<span class="o-meter"><i></i></span>';
    var right = toy.on
      ? '<span class="o-batt">' + BATT_SVG + toy.batt + '%</span><span class="o-meters">' + meters + '</span>' +
        '<span class="o-btn small" data-act="mute" data-tip="mute">Mute</span><span class="o-btn small" data-act="test" data-tip="testone">Test</span>'
      : '<span class="o-pill idle">OFFLINE</span>';
    return '<div class="o-toy' + (toy.on ? '' : ' offline') + '" data-toy="' + toy.id + '"' + style + '>' +
      '<div class="o-toybar" data-tip="' + (toy.on ? 'toy' : 'offline') + '">' +
      '<span class="o-ticon"><img src="assets/demo/' + toy.icon + '.png" alt=""></span><span class="o-dot"></span>' +
      '<span class="o-tname">' + toy.name + '</span><span class="o-tzones"></span><span class="o-tspace"></span>' + right +
      '<span class="o-caret">▸</span></div><div class="o-toybody"></div></div>';
  }

  function homeHTML() {
    return '<div class="o-page on" data-page="Home"><div class="o-home">' +
      '<div class="o-homehead"><h4>Toys</h4><span class="o-btn js-testall" data-tip="test">Test all</span></div>' +
      '<div class="o-toys o-scroll">' + TOYS.map(toyHTML).join('') + '</div>' +
      '<div class="o-tools"><div class="o-toolbar" data-tip="tools"><span class="car">▸</span><b>Tuning tools</b><span class="sum">Simulator · signal graph</span></div>' +
      '<div class="o-toolbody">' +
        '<div class="o-card o-simcard">' +
          '<div class="o-simrow"><span>Sim</span>' +
            '<span class="o-in spin" data-spin="hz" data-tip="simhz"><span class="js-hz"></span><span class="ar"><i data-d="1">▲</i><i data-d="-1">▼</i></span></span>' +
            '<span class="o-in spin" data-spin="amp" style="width:84px" data-tip="simamp"><span class="js-amp"></span><span class="ar"><i data-d="1">▲</i><i data-d="-1">▼</i></span></span>' +
            '<span class="o-in combo js-shape" data-tip="simshape"></span>' +
            '<span class="o-sw on" data-tip="simsend"></span><span>Send to toy</span>' +
            '<span class="o-btn js-play" data-tip="simplay"></span></div>' +
          '<div class="o-simrow"><span class="o-sw js-graphsw" data-tip="graph"></span><span>Signal graph</span>' +
            '<span class="o-in combo js-gtarget" style="width:152px" data-tip="graph"></span><span class="o-in combo js-gchain" style="width:108px" data-tip="graph"></span></div>' +
        '</div>' +
        '<div class="o-card o-graph" style="display:none"><canvas></canvas></div>' +
      '</div></div></div></div>';
  }

  function settingsHTML() {
    function line(on, text) { return '<div class="line"><span class="o-sw' + (on ? ' on' : '') + '" data-flip="1"></span><span>' + text + '</span></div>'; }
    return '<div class="o-page" data-page="Settings"><div class="o-viewtitle">Application Settings</div>' +
      '<div class="o-tabs"><span class="on">General</span><span>Sessions</span></div>' +
      '<div class="o-setscroll o-scroll">' +
      '<div class="o-card o-set"><div class="o-sect">Connection Settings</div>' +
        line(1, 'Auto Refresh Devices') + line(1, 'Auto Connect (Intiface)') + line(1, 'Auto Connect (VRChat OSC)') +
        line(1, 'Sound when a toy connects or disconnects') +
        '<div class="line"><span class="o-sw on" data-flip="1"></span><span>Tell VRChat while any toy is connected</span><span class="o-in" style="flex:1">OGP/ToyConnected</span><span class="o-btn">Pick...</span></div></div>' +
      '<div class="o-card o-set"><div class="o-sect">Toy Safety</div>' +
        '<p>VRChat only sends a value when it changes. If a contact stops updating — you swap avatar, your partner leaves, the link drops — its last value would keep a toy running. Anti-stuck notices a value that has frozen and stops the toy. On by default.</p>' +
        line(1, 'Anti-stuck') +
        '<div class="line" style="padding-left:44px"><span>Frozen part-way: stop after</span><span class="o-in spin" style="width:86px">1s<span class="ar"><i>▲</i><i>▼</i></span></span>' +
        '<span style="margin-left:14px">Held at 100%: ease off after</span><span class="o-in spin" style="width:86px">10s<span class="ar"><i>▲</i><i>▼</i></span></span></div></div>' +
      '<div class="o-card o-set js-appearance"><div class="o-sect">Appearance</div>' +
        '<div class="line"><span class="o-lbl">Mode:</span><span class="o-btn seg js-uimode on" data-uimode="neon" data-tip="uimode">Vibrant</span><span class="o-btn seg js-uimode" data-uimode="midnight" data-tip="uimode">Darker</span></div>' +
        '<div class="line"><span class="o-lbl">Colour:</span><span class="js-presets" style="display:flex;gap:8px"></span></div>' +
        '<div class="line"><input type="range" class="o-hue js-hue" min="0" max="359" value="150" tabindex="-1" data-tip="colour"></div>' +
        '<p style="margin-top:4px">Mode and colour change as you pick — no restart.</p></div>' +
      '</div></div>';
  }

  function noteHTML(name) {
    return '<div class="o-page" data-page="' + name + '"><div class="o-viewtitle">' + name + '</div>' +
      '<div class="o-note"><p>' + NOTES[name] + '</p><p class="o-muted">This page is not rebuilt in the website’s demo.</p>' +
      '<span class="o-btn" data-go="Home">Back to Home</span></div></div>';
  }

  var frame = el('<div class="ogp-frame">' +
    '<div class="ogp-title"><img src="assets/ogp-icon.svg" alt=""><span>OscGoesPurrr <span class="ver-tag"></span></span>' +
    '<span class="wc"><span>–</span><span>□</span><span>✕</span></span></div>' +
    '<div class="ogp">' + sideHTML() +
    '<div class="o-main">' + homeHTML() +
      '<div class="o-page" data-page="Statistics"></div>' + settingsHTML() +
      Object.keys(NOTES).map(noteHTML).join('') + '</div>' +
    '<div class="o-status"><span>OscGoesPurrr <span class="ver-tag"></span> · made by <b>Blise518B</b></span></div>' +
    '</div></div>');
  host.classList.add('ogp-stage');
  host.appendChild(frame);
  var app = $('.ogp');

  // ── fit: the window keeps the app's pixel sizes and is scaled as a whole ──
  var FULL_W = 1100, FULL_H = 792, MIN_SCALE = 0.62;
  function fit() {
    var k = clamp(host.clientWidth / FULL_W, MIN_SCALE, 1);
    frame.style.transform = 'scale(' + k + ')';
    host.style.height = Math.round(FULL_H * k) + 'px';
  }
  fit();
  window.addEventListener('resize', fit);
  if (window.ResizeObserver) new ResizeObserver(fit).observe(host);

  function setRange(input) {
    var lo = +input.min, hi = +input.max;
    input.style.setProperty('--v', ((input.value - lo) / (hi - lo) * 100).toFixed(1) + '%');
  }

  // ── a toy's body: its chains ──────────────────────────────────────────────
  var CH = [
    { name: 'Penetration', hue: 'pink' },
    { name: 'Touch', hue: 'amber' }
  ];
  // The node graph, at the app's own coordinates inside the chain block.
  var BOX = {
    input: [10, 140, 67, 70], depth: [95, 65, 105, 61], speed: [95, 132, 105, 74], punch: [95, 212, 105, 74],
    combine: [218, 139, 82, 71], wake: [317, 127, 104, 97], envelope: [439, 124, 105, 103],
    zerocut: [562, 128, 83, 94], output: [663, 132, 104, 87]
  };
  var WIRES = [
    'M77 175H95', 'M43 140V95H95', 'M43 210V249H95', 'M200 95H259V139', 'M200 169H218', 'M200 249H259V210',
    'M300 175H317', 'M421 175H439', 'M544 175H562', 'M645 175H663'
  ];
  var HEADS = [[95, 175, 0], [95, 95, 0], [95, 249, 0], [259, 139, 90], [218, 169, 0], [259, 210, -90],
               [317, 175, 0], [439, 175, 0], [562, 175, 0], [663, 175, 0]];

  function stageHTML(id, inner, extra) {
    var b = BOX[id];
    return '<div class="o-stage' + (extra || '') + '" data-stage="' + id + '" data-tip="st-' + id + '" style="left:' + b[0] + 'px;top:' + b[1] +
      'px;width:' + b[2] + 'px;height:' + b[3] + 'px">' + inner + '</div>';
  }
  function slider(key, lbl) {
    return '<div class="row">' + (lbl ? '<label>' + lbl + '</label>' : '') +
      '<input type="range" tabindex="-1" data-key="' + key + '"><span class="val" data-val="' + key + '"></span></div>';
  }
  function chainHTML(toy, mi, ci) {
    var c = CH[ci], style = ' style="--ch:var(--' + c.hue + ');--ch-mid:var(--' + c.hue + '-mid)"';
    var wires = '<svg class="o-wires" viewBox="0 0 778 314">' + WIRES.map(function (d) { return '<path d="' + d + '"/>'; }).join('') +
      HEADS.map(function (h) { return '<path class="ah" d="M0 0L-7 -3.5V3.5Z" transform="translate(' + h[0] + ' ' + h[1] + ') rotate(' + h[2] + ')"/>'; }).join('') + '</svg>';
    var T = function (t) { return '<div class="t"><span>' + t + '</span><span class="num"></span></div>'; };
    var TC = function (t) { return '<div class="t"><span>' + t + '</span></div><span class="num"></span>'; };
    return '<div class="o-fold" data-fold="' + mi + '.' + ci + '" data-tip="fold"' + style + '>' +
        '<div class="r1"><span class="car">▸</span><span class="nm">' + c.name + '</span>' + (ci ? '<span class="mrg"></span>' : '') +
        '<span class="o-pips">' + 'IDSPCWEZO'.split('').map(function (l) { return '<span>' + l + '</span>'; }).join('') + '</span>' +
        '<span class="o-meter" style="flex:1"><i></i></span><span class="x">–</span><span class="xb">✕</span></div>' +
        '<div class="sum"></div></div>' +
      '<div class="o-chain" data-chain="' + mi + '.' + ci + '"' + style + '>' +
        '<span class="hd">Motor ' + mi + ' · ' + c.name + '</span><span class="o-btn rst" data-act="reset" data-tip="reset">Reset to defaults</span>' +
        '<span class="lab" style="left:196px">SOURCES</span><span class="lab" style="left:423px">WAKE</span><span class="lab" style="left:649px">SHAPING</span>' + wires +
        stageHTML('input', TC('Input') + '<div class="hint js-src"></div>', ' center') +
        stageHTML('depth', T('Depth') + slider('depth.gain')) +
        stageHTML('speed', T('Speed') + slider('speed.gain', 'In') + slider('speed.gain_out', 'Out')) +
        stageHTML('punch', T('Punch') + slider('punch.gain', 'In') + slider('punch.gain_out', 'Out')) +
        stageHTML('combine', TC('Combine') + '<span class="o-btn seg on js-op" style="height:22px;width:62px;margin-top:6px" data-act="op"></span>', ' center') +
        stageHTML('wake', TC('Wake') + '<div class="hint" data-sub="wake"></div>' + slider('wake.wake_threshold') + '<div class="o-act"><i></i><u></u></div>', ' center') +
        stageHTML('envelope', T('Envelope') + slider('smoothing.ms') + '<div class="hint" data-sub="envelope"></div>' +
          '<div class="row"><span class="o-sw" data-act="texture.enabled"></span><span>Texture</span></div>') +
        stageHTML('zerocut', TC('Zero cut') + '<div class="hint" data-sub="zerocut"></div><div class="row" style="justify-content:center"><span class="o-sw" data-act="zerocut.enabled"></span><span>Cut</span></div>', ' center') +
        stageHTML('output', TC('Output') + '<div class="hint" data-sub="output"></div>' + slider('output.gain'), ' center') +
        '<span class="o-meter omet"><i></i></span>' +
      '</div>';
  }
  function bodyHTML(toy) {
    var out = '';
    for (var mi = 0; mi < toy.motors; mi++) {
      if (toy.motors > 1) out += '<div style="font-weight:600;margin:' + (mi ? 12 : 0) + 'px 0 8px 2px">Motor ' + mi + '</div>';
      out += chainHTML(toy, mi, 0) +
        '<div class="o-merge" data-merge="' + mi + '" data-tip="merge"><b>Merge chains:</b>' +
        ['Add', 'Max', 'Multiply'].map(function (n) { return '<span class="o-btn seg" data-mergeop="' + n.toLowerCase() + '">' + n + '</span>'; }).join('') + '</div>' +
        chainHTML(toy, mi, 1);
    }
    return out;
  }

  // ── binding the stage cards to the real settings ─────────────────────────
  // The controls are the port's own table (OGPChain.CONTROLS): the same
  // config keys, ranges and readouts as the app's stage cards.
  var CONTROLS = {};
  ((Chain && Chain.CONTROLS) || []).forEach(function (c) { CONTROLS[c.id] = c; });
  function chainCfg(toyId, mi, ci) { return motors[toyId][mi].cfg.chains[ci]; }
  function refreshChain(toyEl, toyId, mi, ci) {
    if (!Chain) return;
    var cc = chainCfg(toyId, mi, ci), key = mi + '.' + ci;
    var block = $('.o-chain[data-chain="' + key + '"]', toyEl), fold = $('.o-fold[data-fold="' + key + '"]', toyEl);
    $$('input[data-key]', block).forEach(function (inp) {
      var id = inp.getAttribute('data-key'), c = CONTROLS[id];
      if (!c) return;
      var v = Chain.readControl(cc, id);
      inp.min = c.min; inp.max = c.max; inp.step = c.step; inp.value = v;
      setRange(inp);
      $('[data-val="' + id + '"]', block).textContent = c.format(v);
    });
    $('.js-op', block).textContent = CONTROLS.combine.format(Chain.readControl(cc, 'combine'));
    $$('.o-sw[data-act]', block).forEach(function (sw) { sw.classList.toggle('on', !!Chain.readControl(cc, sw.getAttribute('data-act'))); });
    $$('[data-sub]', block).forEach(function (h) { h.textContent = Chain.stageSummary(h.getAttribute('data-sub'), cc); });
    $('.js-src', block).textContent = S.sim.on ? 'sim' : 'avatar';
    $('.o-act u', block).style.left = Chain.readControl(cc, 'wake.wake_threshold') * 100 + '%';
    $('.sum', fold).textContent = Chain.summaryLine(cc, { zones: zonesOf(toyId) || 'none', self: false, others: true, params: [], sim: false });
    var merge = $('.o-merge[data-merge="' + mi + '"]', toyEl), op = motors[toyId][mi].cfg.merge;
    $$('.o-fold[data-fold^="' + mi + '."] .mrg', toyEl).forEach(function (m) { m.textContent = '⋁ ' + op; });
    $$('[data-mergeop]', merge).forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-mergeop') === op); });
  }
  function openToy(toyEl, open) {
    var id = toyEl.getAttribute('data-toy'), toy = TOYS.filter(function (t) { return t.id === id; })[0];
    if (!toy.on) return;
    var body = $('.o-toybody', toyEl);
    if (open && !body.firstChild) {
      body.innerHTML = bodyHTML(toy);
      for (var mi = 0; mi < toy.motors; mi++) { refreshChain(toyEl, id, mi, 0); refreshChain(toyEl, id, mi, 1); }
    }
    toyEl.classList.toggle('open', open);
    $('.o-caret', toyEl).textContent = open ? '▾' : '▸';
  }

  // ── interactions ──────────────────────────────────────────────────────────
  function go(page) {
    if (!$('.o-page[data-page="' + page + '"]')) return;
    S.page = page;
    $$('.o-page').forEach(function (p) { p.classList.toggle('on', p.getAttribute('data-page') === page); });
    $$('.o-nav .n').forEach(function (n) { n.classList.toggle('on', n.getAttribute('data-go') === page); });
    if (page === 'Statistics' && window.OGPDemoStats && !go.stats) {
      go.stats = true;
      var statsPage = $('.o-page[data-page="Statistics"]');
      statsPage.innerHTML = window.OGPDemoStats.HTML;
      window.OGPDemoStats.init(statsPage);
    }
  }
  function refreshZones() {
    $$('.o-toy').forEach(function (t) { $('.o-tzones', t).textContent = zoneLabel(t.getAttribute('data-toy')); });
    $$('.o-toy.open').forEach(function (t) {
      var id = t.getAttribute('data-toy');
      motors[id].forEach(function (_m, mi) { refreshChain(t, id, mi, 0); refreshChain(t, id, mi, 1); });
    });
  }
  function refreshSim() {
    $('.js-hz').textContent = S.sim.hz.toFixed(2) + ' Hz';
    $('.js-amp').textContent = S.sim.amp.toFixed(2);
    $('.js-shape').textContent = SHAPES[S.sim.shape];
    $('.js-play').textContent = S.sim.on ? '■ Stop' : '▸ Play';
    $('.js-gtarget').textContent = TOYS.filter(function (t) { return t.id === S.graphToy; })[0].name + ' · M' + S.graphMotor;
    $('.js-gchain').textContent = CH[S.graphChain].name;
    $$('.js-src').forEach(function (e) { e.textContent = S.sim.on ? 'sim' : 'avatar'; });
  }

  app.addEventListener('click', function (e) {
    var t = e.target, x;
    if ((x = t.closest('[data-go]'))) { go(x.getAttribute('data-go')); return; }
    if ((x = t.closest('[data-mode]'))) {
      S.mode = +x.getAttribute('data-mode');
      $$('[data-mode]').forEach(function (b) { b.classList.toggle('on', b === x); });
      refreshZones(); return;
    }
    if (t.closest('.js-off')) { S.off = !S.off; $('.js-off').classList.toggle('on', S.off); return; }
    if (t.closest('.js-sleep')) { S.sleep = !S.sleep; $('.js-sleep').classList.toggle('on', S.sleep); return; }
    if (t.closest('.js-testall')) { S.testUntil = S.t + 1.0; return; }
    if ((x = t.closest('[data-flip]'))) { x.classList.toggle('on'); return; }
    if ((x = t.closest('.js-uimode'))) { setMode(x.getAttribute('data-uimode')); return; }
    if ((x = t.closest('.o-swatch'))) { setHue(x.hasAttribute('data-hue') ? +x.getAttribute('data-hue') : null); return; }
    if (t.closest('.o-toolbar')) {
      var tools = $('.o-tools'); tools.classList.toggle('open');
      $('.o-toolbar .car').textContent = tools.classList.contains('open') ? '▾' : '▸';
      sizeGraph(); return;
    }
    if (t.closest('.js-play')) { S.sim.on = !S.sim.on; refreshSim(); return; }
    if (t.closest('.js-shape')) { S.sim.shape = (S.sim.shape + 1) % SHAPES.length; rebuildSim(); refreshSim(); return; }
    if ((x = t.closest('[data-spin] i'))) {
      var which = x.closest('[data-spin]').getAttribute('data-spin'), d = +x.getAttribute('data-d');
      if (which === 'hz') S.sim.hz = clamp(Math.round((S.sim.hz + d * 0.1) * 100) / 100, 0.1, 10);
      else S.sim.amp = clamp(Math.round((S.sim.amp + d * 0.05) * 100) / 100, 0.05, 1);
      rebuildSim(); refreshSim(); return;
    }
    if (t.closest('.js-graphsw')) {
      S.graph = !S.graph; $('.js-graphsw').classList.toggle('on', S.graph);
      $('.o-graph').style.display = S.graph ? '' : 'none';
      $('.o-toolbar .sum').textContent = S.graph ? 'Signal graph on' : 'Simulator · signal graph';
      sizeGraph(); return;
    }
    if (t.closest('.js-gtarget')) {
      var live = TOYS.filter(function (ty) { return ty.on; }), list = [];
      live.forEach(function (ty) { for (var i = 0; i < ty.motors; i++) list.push([ty.id, i]); });
      var at = 0; list.forEach(function (p, i) { if (p[0] === S.graphToy && p[1] === S.graphMotor) at = i; });
      var nx = list[(at + 1) % list.length]; S.graphToy = nx[0]; S.graphMotor = nx[1]; hist = {}; refreshSim(); return;
    }
    if (t.closest('.js-gchain')) { S.graphChain = 1 - S.graphChain; hist = {}; refreshSim(); return; }

    var toyEl = t.closest('.o-toy');
    if (!toyEl) return;
    var id = toyEl.getAttribute('data-toy');
    if ((x = t.closest('[data-act="mute"]'))) {
      var mu = !motors[id][0].muted; motors[id].forEach(function (m) { m.muted = mu; });
      x.classList.toggle('on', mu); x.classList.toggle('seg', mu); x.textContent = mu ? 'Unmute' : 'Mute'; return;
    }
    if (t.closest('[data-act="test"]')) { motors[id].forEach(function (m) { m.testUntil = S.t + 1.0; }); return; }
    if (t.closest('.o-toybar')) { openToy(toyEl, !toyEl.classList.contains('open')); return; }
    if ((x = t.closest('[data-mergeop]'))) {
      var mi0 = +x.closest('[data-merge]').getAttribute('data-merge');
      motors[id][mi0].cfg.merge = x.getAttribute('data-mergeop');
      refreshChain(toyEl, id, mi0, 0); return;
    }
    var block = t.closest('.o-chain'), fold = t.closest('.o-fold');
    if (fold) {
      var k = fold.getAttribute('data-fold'), blk = $('.o-chain[data-chain="' + k + '"]', toyEl);
      blk.classList.toggle('open'); $('.car', fold).textContent = blk.classList.contains('open') ? '▾' : '▸';
      return;
    }
    if (!block) return;
    var parts = block.getAttribute('data-chain').split('.'), mi = +parts[0], ci = +parts[1], cc = chainCfg(id, mi, ci);
    if (t.closest('[data-act="op"]')) {
      var ops = CONTROLS.combine.options;
      Chain.applyControl(cc, 'combine', ops[(ops.indexOf(Chain.readControl(cc, 'combine')) + 1) % ops.length]);
    } else if ((x = t.closest('.o-sw[data-act]'))) {
      Chain.applyControl(cc, x.getAttribute('data-act'), !Chain.readControl(cc, x.getAttribute('data-act')));
    } else if (t.closest('[data-act="reset"]')) {
      motors[id][mi].cfg.chains[ci] = Chain.defaults().chains[ci];      // the motor reads its config every tick
    } else return;
    refreshChain(toyEl, id, mi, ci);
  });

  app.addEventListener('input', function (e) {
    var inp = e.target;
    if (inp.classList.contains('js-strength')) {
      S.strength = inp.value / 100; $('.js-strval').textContent = inp.value + '%'; setRange(inp); return;
    }
    if (inp.classList.contains('js-hue')) { setHue(+inp.value, true); return; }
    var key = inp.getAttribute('data-key');
    if (!key || !CONTROLS[key]) return;
    var toyEl = inp.closest('.o-toy'), id = toyEl.getAttribute('data-toy');
    var parts = inp.closest('.o-chain').getAttribute('data-chain').split('.'), mi = +parts[0], ci = +parts[1];
    Chain.applyControl(chainCfg(id, mi, ci), key, +inp.value);
    refreshChain(toyEl, id, mi, ci);
  });
  setRange($('.js-strength'));
  $('.js-strval').textContent = Math.round(S.strength * 100) + '%';

  // ── Appearance: the app's own colour maths, on this page's tokens ────────
  var CHROME = ['bg', 'panel', 'card', 'well', 'hover', 'line', 'tint', 'accent', 'accent2', 'ink', 'txt', 'muted', 'dim'];
  var GREENS = ['green', 'green-mid', 'green-tint'];
  var PRESETS = [['Green (default)', null], ['Cyan', 'cyan'], ['Blue', 'blue'], ['Purple', 'purple'], ['Pink', 'pink'], ['Orange', 'orange'], ['Yellow', 'yellow']];
  var neonAccent = tok('--accent'), pickedHue = null, defaultHue = Accent ? Accent.hueOf(neonAccent) : 150;
  function baseTokens() {
    var names = CHROME.concat(GREENS), base = {};
    names.forEach(function (n) { root.style.removeProperty('--' + n); });
    names.forEach(function (n) { base[n] = tok('--' + n); });
    return base;
  }
  function applyColour() {
    if (!Accent) return;
    var base = baseTokens(), delta = Accent.deltaFor(pickedHue, neonAccent);
    if (delta) Object.keys(base).forEach(function (n) { root.style.setProperty('--' + n, Accent.shiftHex(base[n], delta)); });
    paintPicker(base);
    redrawAll();
  }
  function setHue(hue, fromSlider) {
    if (hue !== null && fromSlider && Math.round(hue) === Math.round(defaultHue)) hue = null;
    pickedHue = hue; applyColour();
  }
  function setMode(mode) {
    if (mode === 'midnight') root.setAttribute('data-theme', 'midnight'); else root.removeAttribute('data-theme');
    $$('.js-uimode').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-uimode') === mode); });
    applyColour();
  }
  function same(a, b) { return a === null || b === null ? a === b : Math.abs(((a - b + 180) % 360 + 360) % 360 - 180) < 0.5; }
  function paintPicker(base) {
    if (!Accent) return;
    var slider = $('.js-hue'), box = $('.js-presets');
    function at(hue) { return Accent.shiftHex(base.accent, Accent.deltaFor(hue, neonAccent)); }
    if (!box.firstChild) {
      box.innerHTML = PRESETS.map(function (p) {
        var hue = p[1] === null ? null : Accent.hueOf(tok('--' + p[1]));
        return '<span class="o-swatch" title="' + p[0] + '"' + (hue === null ? '' : ' data-hue="' + hue + '"') + '></span>';
      }).join('');
    }
    $$('.o-swatch', box).forEach(function (sw) {
      var hue = sw.hasAttribute('data-hue') ? +sw.getAttribute('data-hue') : null;
      sw.style.background = at(hue); sw.classList.toggle('on', same(hue, pickedHue));
    });
    var stops = [];
    for (var i = 0; i <= 12; i++) stops.push(at(i * 30) + ' ' + (i / 12 * 100).toFixed(2) + '%');
    slider.style.setProperty('--huetrack', 'linear-gradient(90deg,' + stops.join(',') + ')');
    if (document.activeElement !== slider || pickedHue === null) slider.value = Math.round(pickedHue === null ? defaultHue : pickedHue) % 360;
  }

  // ── the loop: contact -> chain -> meters ─────────────────────────────────
  var hist = {}, HIST_N = 270, frameAcc = 0, histAcc = 0, stepAcc = 0, listeners = [];
  // The signal graph's lines, in the app's trace hues.
  var TRACES = [
    { id: 'd_raw', hue: 'blue', label: 'Input' }, { id: 's_shaped', hue: 'amber', label: 'Speed' },
    { id: 'punch', hue: 'pink', label: 'Punch' }, { id: 'mixed', hue: 'purple', label: 'Combine' },
    { id: 'smoothed', hue: 'cyan', label: 'Envelope' }, { id: 'out', hue: 'accent', label: 'Output' }
  ];
  var LEVEL = (Chain && Chain.STAGE_LEVEL_TRACE) || {};
  var TRACE_IDS = ((Chain && Chain.TRACE_IDS) || []).filter(function (id) { return id !== 'wake_mode' && id !== 'wake_open'; });
  function pushHist(name, v) { var a = hist[name] || (hist[name] = []); a.push(v); if (a.length > HIST_N) a.shift(); }
  function meterFill(node, v) {
    node.style.width = (v * 100).toFixed(1) + '%';
    node.style.background = 'linear-gradient(90deg,var(--accent),color-mix(in srgb,var(--pink) ' + Math.round(v * 100) + '%,var(--accent)))';
  }
  function levelColor(v) { return 'color-mix(in srgb,var(--pink) ' + Math.round(clamp(v, 0, 1) * 100) + '%,var(--line))'; }

  function tick(dt) {
    S.t += dt;
    if (!Chain) return;
    var pen = contactNow(), ref = null;
    TOYS.forEach(function (toy) {
      if (!toy.on) return;
      var heard = hears(toy.id) ? pen : 0;
      motors[toy.id].forEach(function (mo, mi) {
        var res = mo.m.step(dt, { pen: heard, touch: 0 }, { strength: S.strength, off: S.off, sleep: S.sleep });
        var out = res.out;
        if (!S.off && (S.t < S.testUntil || S.t < mo.testUntil)) out = Math.max(out, mo.m.mapIntoOutputBand(TEST_LEVEL));
        if (mo.muted) out = 0;
        mo.out = out; mo.res = res;
        if (toy.id === S.graphToy && mi === S.graphMotor) ref = res;
      });
    });
    histAcc += dt;
    if (histAcc < 2 * ROUTER_DT - 1e-9) return;   // every second tick: the plots keep 6 s
    histAcc = 0;
    pushHist('pen', pen);
    if (ref) {
      var c = ref.chains[S.graphChain] || {};
      TRACE_IDS.forEach(function (id) { if (id !== 'out') pushHist(id, +c[id] || 0); });
      pushHist('out', motors[S.graphToy][S.graphMotor].out);
    }
    listeners.forEach(function (fn) { fn(S, motors); });
  }

  function paint() {
    $$('.o-toy').forEach(function (toyEl) {
      var id = toyEl.getAttribute('data-toy'), ms = motors[id];
      if (!ms || toyEl.classList.contains('offline')) return;
      $$('.o-toybar .o-meter i', toyEl).forEach(function (fill, i) { meterFill(fill, ms[i].out); });
      if (!toyEl.classList.contains('open')) return;
      ms.forEach(function (mo, mi) {
        if (!mo.res) return;
        [0, 1].forEach(function (ci) {
          var c = mo.res.chains[ci] || {}, key = mi + '.' + ci;
          var fold = $('.o-fold[data-fold="' + key + '"]', toyEl), block = $('.o-chain[data-chain="' + key + '"]', toyEl);
          var chainOut = +c.out || 0;
          meterFill($('.o-meter i', fold), clamp(chainOut, 0, 1));
          var pips = $$('.o-pips span', fold);
          STAGES.forEach(function (st, i) { pips[i].style.color = levelColor(+c[LEVEL[st]] || 0); });
          if (!block.classList.contains('open')) return;
          STAGES.forEach(function (st) {
            var card = $('[data-stage="' + st + '"]', block), v = +c[LEVEL[st]] || 0;
            card.style.borderColor = levelColor(v);
            $('.num', card).textContent = v > 0.004 ? v.toFixed(2) : '–';
          });
          var act = $('.o-act', block), wm = c.wake_meter || 0;
          $('i', act).style.width = clamp(wm, 0, 1) * 100 + '%';
          act.classList.toggle('open', !!c.wake_open);
          meterFill($('.omet i', block), clamp(chainOut, 0, 1));
        });
      });
    });
    if (S.graph && S.page === 'Home') drawGraph($('.o-graph canvas'), TRACES, true);
    pageCanvases.forEach(function (cv) { drawSpark(cv); });
  }

  // ── graphs ────────────────────────────────────────────────────────────────
  function prep(cv) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2), w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return null;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    var g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    return { g: g, w: w, h: h };
  }
  function line(g, arr, w, h, pad, col, width, top) {
    if (!arr || arr.length < 2) return;
    var n = arr.length, step = w / (HIST_N - 1);
    top = top || pad;
    g.beginPath();
    for (var i = 0; i < n; i++) {
      var x = w - (n - 1 - i) * step, y = top + (1 - clamp(arr[i], 0, 1)) * (h - top - pad);
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    }
    g.strokeStyle = col; g.lineWidth = width; g.lineJoin = 'round'; g.stroke();
  }
  function drawGraph(cv, traces, legend) {
    var p = prep(cv); if (!p) return;
    var g = p.g, w = p.w, h = p.h;
    g.strokeStyle = tok('--green-mid'); g.lineWidth = 1; g.globalAlpha = .5;
    for (var i = 1; i < 4; i++) { g.beginPath(); g.moveTo(0, Math.round(h * i / 4) + .5); g.lineTo(w, Math.round(h * i / 4) + .5); g.stroke(); }
    g.globalAlpha = 1;
    traces.forEach(function (tr) { line(g, hist[tr.id], w, h, 6, tok('--' + tr.hue), tr.id === 'out' ? 2.2 : 1.3, legend ? 22 : 6); });
    if (!hist.pen) return;
    if (!legend) return;
    g.font = '11px "Segoe UI", system-ui, sans-serif'; g.textBaseline = 'top';
    var x = 8;
    traces.forEach(function (tr) {
      g.fillStyle = tok('--' + tr.hue); g.fillRect(x, 9, 9, 3); x += 13;
      g.fillStyle = tok('--muted'); g.fillText(tr.label, x, 4); x += g.measureText(tr.label).width + 12;
    });
  }
  function sizeGraph() { /* the canvas follows its card; nothing to cache */ }
  // Canvases elsewhere on the page that show one trace of the same engine:
  // <canvas data-ogp-trace="smoothed" data-ogp-hue="cyan">
  var pageCanvases = [].slice.call(document.querySelectorAll('canvas[data-ogp-trace]'));
  function drawSpark(cv) {
    var r = cv.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) return;
    var p = prep(cv); if (!p) return;
    var ids = cv.getAttribute('data-ogp-trace').split(','), hues = (cv.getAttribute('data-ogp-hue') || 'accent').split(',');
    ids.forEach(function (id, i) { line(p.g, hist[id], p.w, p.h, 4, tok('--' + (hues[i] || hues[0])), i === ids.length - 1 ? 2 : 1.2); });
  }
  function redrawAll() {
    if (window.OGPDemoStats && go.stats) window.OGPDemoStats.redraw();
    paint();
  }

  // ── hover explanations: the app's own words, after the app's 0.7 s rest ──
  var TIPS = {
    mode: ['Modes', 'A mode is a <b>routing</b> \u2014 which parts of your avatar drive which toys. Click to make this one live. Your tuning, your toys and the strength stay the same whichever mode is on.<br><br><b>Right-click</b> to rename it or change its icon.'],
    strength: ['Total output strength', 'One multiplier on everything your toys receive \u2014 the knob for \u201Ca bit softer tonight\u201D. It never touches your tuning, so turning it back up restores exactly the feel you had.<br><br>From inside VRChat: the <b>OGP/Strength</b> radial.'],
    off: ['Off', 'Panic silence. Every toy stops instantly, whatever the strength says; press it again and your previous level comes straight back.<br><br>From inside VRChat: <b>OGP/Off</b>.'],
    sleep: ['Sleep', 'Makes your toys hard to wake: nothing plays until three full strokes land within six seconds, so a brush against a sleeping partner does nothing.<br><br>From inside VRChat: <b>OGP/Sleep</b>.'],
    test: ['Test all', 'Buzzes every connected toy at a low level for a moment, so you know they\u2019re all wired up.'],
    testone: ['Test', 'Buzzes this toy at a low level for a moment.'],
    mute: ['Mute', 'Silences this toy only. Everything else keeps playing, and its setup is untouched.'],
    toy: ['Your toys', 'Every connected toy with its live output and battery. Click one to open it right there and choose which zones drive it and how each motor responds.'],
    offline: ['Offline', 'Switched off or out of range. Everything you set up for it is kept, and it comes back to life the moment it reconnects.'],
    tools: ['Tuning tools', 'For when you are shaping how a toy responds: an input simulator to tune against without a partner, and a live graph of the signal. Folded away until you want them.'],
    vrc: ['VRChat OSC', 'The link to VRChat\u2019s OSC bus \u2014 where every avatar contact signal comes from. The app finds VRChat by itself and reconnects by itself.'],
    intiface: ['Intiface', 'The toy server. The built-in engine starts with the app, looks for your toys and reconnects if the link drops.'],
    fold: ['A chain', 'One chain per kind of contact. The letters are its nine stages \u2014 Input, Depth, Speed, Punch, Combine, Wake, Envelope, Zero cut, Output \u2014 each lit by its live level; the line below is its settings at a glance. Click to open it.'],
    merge: ['Merge chains', 'How this motor\u2019s chains become one output: added together, the larger of them, or multiplied.'],
    reset: ['Reset to defaults', 'Puts every stage of this chain back to how it shipped.'],
    'st-input': ['Input', 'What this motor listens to: zones on your avatar, sources you built, or any OSC parameter. With several, the strongest one counts.'],
    'st-depth': ['Depth', 'How far in, right now. The slider is its gain; the full card adds a curve.'],
    'st-speed': ['Speed', 'How fast the depth is changing. <b>In</b> scales the stroke going deeper, <b>Out</b> the stroke coming back.'],
    'st-punch': ['Punch', 'A short hit on top when a stroke is fast, which then rings out. <b>In</b> fires on the thrust, <b>Out</b> on the pull. Slow movement never triggers it.'],
    'st-combine': ['Combine', 'How Depth and Speed become one level: <b>Add</b>, <b>Max</b> (the larger one) or <b>Multiply</b>. Punch rides on top.'],
    'st-wake': ['Wake', 'The activity gate. A meter charges while there is real movement; below the mark the chain stays silent, so a contact that only rests against you does nothing. Sleep switches it to counting strokes.'],
    'st-envelope': ['Envelope', 'How the level moves over time: rise and fall times round it so the toy never clicks on or off. <b>Texture</b> adds a small wobble to a held level so it does not feel flat.'],
    'st-zerocut': ['Zero cut', 'When everything this motor listens to is back at zero, the output is silenced at once instead of fading.'],
    'st-output': ['Output', 'This chain\u2019s gain, then the range the toy can actually feel. The level is remapped into that range, not clipped.'],
    simhz: ['Simulator speed', 'How many strokes per second the simulated contact makes.'],
    simamp: ['Simulator depth', 'How deep each simulated stroke goes, 0 to 1.'],
    simshape: ['Simulator wave', 'The shape of the simulated stroke. Click to step through them.'],
    simsend: ['Send to toy', 'On: the simulated contact drives your real toys. Off: only the meters and graphs move.'],
    simplay: ['Play / Stop', 'Starts and stops the simulated contact.'],
    graph: ['Signal graph', 'Every stage of one chain drawn live, for the motor and chain picked beside the switch.'],
    uimode: ['Vibrant / Darker', '<b>Vibrant</b> draws every card, button and chip with an outline in your colour. <b>Darker</b> turns those outlines down to a faint hairline and deepens the blacks, so only what matters lights up. Same layout in both.<br><br>Switches as you click \u2014 nothing restarts.'],
    colour: ['Colour', 'Turns everything that is green \u2014 frames, buttons, highlights, even the faint tint of the background \u2014 to the colour you pick, as you pick it. Brightness and contrast stay as they are.<br><br>The colours that <i>mean</i> something keep theirs: each toy\u2019s own colour, pink for the live signal, amber for warnings, red for errors.']
  };
  var tip = el('<div class="tip" role="tooltip"></div>'), tipTimer = null, tipFor = null;
  document.body.appendChild(tip);
  function tipShow(target) {
    var t = TIPS[target.getAttribute('data-tip')]; if (!t) return;
    tip.innerHTML = '<b class="t">' + t[0] + '</b>' + t[1]; tip.classList.add('show');
    var r = target.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
    var x = clamp(r.left + r.width / 2 - tw / 2, 8, root.clientWidth - tw - 8), y = r.bottom + 8;
    if (y + th > window.innerHeight - 8) y = r.top - th - 8;
    tip.style.left = (x + window.scrollX) + 'px'; tip.style.top = (y + window.scrollY) + 'px'; tipFor = target;
  }
  function tipHide() { clearTimeout(tipTimer); tip.classList.remove('show'); tipFor = null; }
  app.addEventListener('pointerover', function (e) {
    if (e.pointerType === 'touch') return;
    var t = e.target.closest('[data-tip]');
    if (t === tipFor) return;
    tipHide(); if (t) tipTimer = setTimeout(function () { tipShow(t); }, 700);
  });
  app.addEventListener('pointerleave', tipHide);
  app.addEventListener('pointerdown', tipHide);
  window.addEventListener('scroll', function () { if (tipFor) tipHide(); }, { passive: true });

  // ── start ─────────────────────────────────────────────────────────────────
  refreshZones(); refreshSim();
  if (Accent) paintPicker(baseTokens());
  var prev, visible = true;
  function frameFn(ts) {
    if (!visible) return;
    if (prev === undefined) prev = ts;
    var dt = Math.min(0.1, (ts - prev) / 1000); prev = ts;
    stepAcc += dt;
    while (stepAcc >= ROUTER_DT) { stepAcc -= ROUTER_DT; tick(ROUTER_DT); }
    frameAcc += dt;
    if (frameAcc >= 1 / 40) { frameAcc = 0; paint(); }
    requestAnimationFrame(frameFn);
  }
  document.addEventListener('visibilitychange', function () {
    visible = !document.hidden; if (visible) { prev = undefined; requestAnimationFrame(frameFn); }
  });

  window.OGPDemo = {
    state: S, go: go, contact: contactNow,
    // The visitor as the contact: a depth 0..1, held for a moment after the last call.
    setManual: function (v) { S.manual = v === null ? null : clamp(+v, 0, 1); S.manualUntil = S.t + 1.2; },
    onTick: function (fn) { listeners.push(fn); },
    open: function (toyId, chain) {
      var toyEl = $('.o-toy[data-toy="' + toyId + '"]'); openToy(toyEl, true);
      if (chain !== undefined) { var b = $('.o-chain[data-chain="0.' + chain + '"]', toyEl); b.classList.add('open'); $('.o-fold[data-fold="0.' + chain + '"] .car', toyEl).textContent = '▾'; }
    },
    setHue: setHue, setMode: setMode,
    // Run the engine ahead without the clock (screenshots, reduced motion).
    advance: function (seconds) { for (var i = 0; i < seconds / ROUTER_DT; i++) tick(ROUTER_DT); paint(); }
  };

  // #demo=toy | chain | tools | settings | stats : open the window in a state.
  var want = (location.hash.match(/demo=([a-z]+)/) || [])[1];
  if (want === 'toy' || want === 'chain') window.OGPDemo.open('lush', want === 'chain' ? 0 : undefined);
  if (want === 'tools') { $('.o-toolbar').click(); $('.js-graphsw').click(); }
  if (want === 'settings') go('Settings');
  if (want === 'stats') go('Statistics');
  var wantMode = (location.hash.match(/mode=(midnight|neon)/) || [])[1], wantHue = (location.hash.match(/hue=(\d+)/) || [])[1];
  if (wantMode) setMode(wantMode);
  if (wantHue) setHue(+wantHue);

  window.OGPDemo.advance(6);                     // the meters and graphs start full
  if (!reduce) requestAnimationFrame(frameFn);
})();
