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
  // Who a toy hears, per mode: Touch / Penetration x Self / Others
  // (contact_filters.py: off / on / off / on by default). The demo's contact
  // is a partner's penetration, so Penetration · Others is the one it needs.
  var PAIRS = [['ts', 'Touch', 'Self', 'Touch from yourself', 'your own hands and body touching your avatar’s zones'],
               ['to', 'Touch', 'Others', 'Touch from others', 'other players’ hands and bodies touching your avatar’s zones'],
               ['ps', 'Penetration', 'Self', 'Penetration from yourself', 'your own plug in your own sockets'],
               ['po', 'Penetration', 'Others', 'Penetration from others', 'other players penetrating you, or you them']];
  var heard = {};
  function hearOf(toyId) {
    var k = S.mode + ':' + toyId;
    return heard[k] || (heard[k] = { ts: false, to: true, ps: false, po: true });
  }
  function hears(toyId) {
    var z = zonesOf(toyId);
    return (z === 'All SPS' || z.split(', ').indexOf(CONTACT_ZONE) >= 0) && hearOf(toyId).po;
  }
  function zoneLabel(toyId) {
    var z = zonesOf(toyId), n = z ? z.split(', ').length : 0;
    return z === 'All SPS' ? z : n === 0 ? 'No zones' : n === 1 ? z : n + ' zones';
  }
  var STAGES = ['input', 'depth', 'speed', 'punch', 'combine', 'wake', 'envelope', 'zerocut', 'output'];
  // Pages built in their own files (demo-friends.js, demo-shockers.js,
  // demo-avatar.js, demo-suits.js, demo-log.js): the window keeps a scrolling
  // frame for each.
  var BUILT = ['Friends', 'My Avatar Remote', 'Shockers', 'Suits', 'Log'];
  var SPS_NOTE = 'Builds a zone out of your avatar’s own contact receivers, for avatars whose contacts are not standard SPS / OGB sockets and plugs. A source you make here can be picked for any toy, under its Input.';
  var NOTES = {
    'PSVR2': 'Your PlayStation VR2 headset’s rumble motor, from a contact on your avatar, through PSVR2Toolkit (its experimental build, on a jailbroken headset; Windows only): connect it, set its rumble band and test it.',
    'OSC Inspector': 'A live table of every parameter your avatar sends over OSC, with search — for finding the contact you want, or checking that one moves at all.',
    'OSC Diagnostics': 'Shows whether VRChat is reaching the app: the port in use, packets per second, when the last one arrived, and buttons to reconnect by hand.',
    'System Log': 'What the app did and when: toys connecting and dropping, the link to VRChat, updates, errors.',
    'Help': 'The app’s own manual: what each page is for and how the signal chain works. <b>Take the tour</b> walks you through the app one real step at a time — your toy, its zones, the chips, Test and strength, then what you use — and never changes a setting by itself. Every control also explains itself when you rest the pointer on it.'
  };

  var S = {
    mode: 0, strength: 0.85, off: false, sleep: false, page: 'Home',
    // each toy's own Sleep and Anti-stuck (its bar's chips; toy id -> bool,
    // anti-stuck on unless false) and the toys' anti-stuck (the Toys page)
    toySleep: {}, toyAs: {}, as: { enabled: true, active_s: 1, peaked_s: 10 },
    sim: { on: true, hz: 1.0, amp: 1.0, shape: 0 }, manual: null, manualUntil: 0,
    graph: false, graphToy: 'lush', graphMotor: 0, graphChain: 0,
    testUntil: 0, t: 0, scanAt: 24,
    // a friend driving these toys: toy id -> [level 0..1, override]
    drive: {},
    // the shocker hub on Home and the Shockers page (demo-shockers.js);
    // asking: Arm shocks' question is up (until when)
    shock: { armed: true, share: true, on: true, asking: 0 },
    // the PSVR2 headset's row on Home (shown while its feature is on)
    psvr2: { on: true },
    // Settings -> Features: a switched-off one hides its page. The demo's PC is
    // set up as someone with the hardware has it: the shockers, Avatar Remote
    // and a bHaptics vest switched on (all three start off in a new install);
    // OWO, the trackers and the headset off, their switches there to try
    // (demo-suits.js)
    features: { intiface: true, inspector: true, statistics: true, pishock: true, bhaptics: true, owo: false,
                trackers: false, psvr2: false, friends: true, params: true }
  };
  var ICONS = window.OGPDemoIcons || {};
  // The sidebar's pages: name, icon (ui/icons.py), its colour token ('' = the
  // nav text's), the feature switch that hides it ('a|b': shown while either is on)
  // (the app's order: Home, Friends, then the devices as Home lists them)
  var NAV = [['Friends', 'friends', 'cyan', 'friends'], ['Toys', 'toys', 'pink', 'intiface'],
             ['Shockers', 'shock', 'yellow', 'pishock'], ['Suits', 'suits', 'orange', 'bhaptics|owo|trackers'],
             ['PSVR2', 'psvr2', 'blue', 'psvr2'],
             ['My Avatar Remote', 'params', 'accent', 'params'],
             ['Statistics', 'stats', '', 'statistics'], ['Log', 'activity', '', 'friends|pishock']];
  var NAV_TOOLS = [['OSC Inspector', 'inspector', '', 'inspector'],
                   ['OSC Diagnostics', 'diagnostics'], ['System Log', 'log']];

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
    function nav(name, icon, hue, feature) {
      return '<span class="n" data-go="' + name + '"' + (feature ? ' data-feature="' + feature + '"' : '') + '>' +
        '<i class="ic"' + (hue ? ' style="color:var(--' + hue + ')"' : '') + '>' + (ICONS[icon] || '') + '</i>' + name + '</span>';
    }
    function navs(list) { return list.map(function (n) { return nav(n[0], n[1], n[2], n[3]); }).join(''); }
    return '<div class="o-side o-scroll">' +
      '<div class="o-brand" data-go="Home">OscGoesPurrr</div><div class="o-build"><span class="ver-tag"></span>&nbsp;</div>' +
      '<div class="o-grid o-modes">' + modes + '</div>' +
      '<div class="o-strrow" data-tip="strength"><span>Total output strength</span><b class="js-strval">85%</b></div>' +
      '<input type="range" class="big js-strength" min="0" max="100" value="85" tabindex="-1" data-tip="strength">' +
      '<div class="o-grid o-offrow"><span class="o-btn o-mode warn js-off" data-tip="off">Off</span><span class="o-btn o-mode js-sleep" data-tip="sleep">Sleep</span></div>' +
      '<div class="o-nav">' +
        '<span class="n home on" data-go="Home">' + HOME_SVG + 'Home</span>' + navs(NAV) +
        '<span class="grp">TOOLS</span>' + navs(NAV_TOOLS) +
        '<span class="gap"></span>' + nav('Settings', 'settings') + nav('Help', 'help') +
      '</div>' +
      '<div class="o-links"><div class="l" data-tip="vrc"><span>VRChat</span><span class="o-pill ok">CONNECTED</span></div>' +
      '<div class="l" data-tip="intiface"><span>Intiface</span><span class="o-pill ok">CONNECTED</span></div></div>' +
      '</div>';
  }

  // Who a toy hears, after its zones: Touch [Self][Others] Penetration [Self][Others]
  function chipsHTML() {
    var out = '', cap = '';
    PAIRS.forEach(function (p) {
      if (p[1] !== cap) { cap = p[1]; out += '<span class="o-ccap">' + cap + '</span>'; }
      out += '<span class="o-cchip" data-pair="' + p[0] + '" data-tip="chip-' + p[0] + '">' + p[2] + '</span>';
    });
    return out;
  }
  // A toy's own Sleep over its Anti-stuck, beside the contact chips
  // (device_frame._build_safety_chips); refreshSafety paints them
  function safetyHTML() {
    return '<span class="o-cchip" data-safe="sleep" data-tip="toysleep">Sleep</span>' +
      '<span class="o-cchip on" data-safe="as" data-tip="toyas">Anti-stuck</span>';
  }
  // One toy, in two places (device_frame._build_toy_bar): its row on Home,
  // which opens its card on the Toys page, and that card, open on its
  // motors' folded chains. At this width the bar is one line, all of it
  // centred on it: the name and zones, the chips as two rows -- Touch above
  // Penetration, the captions in a column -- with Sleep over Anti-stuck
  // beside them, then the battery, meters, Mute and Test (the app drops to
  // two lines only in a narrower window).
  function toyHTML(toy, where) {
    var style = toy.hue ? ' style="--hue:var(--' + toy.hue + ');--hue-mid:var(--' + toy.hue + '-mid)"' : '';
    // its place among the connected toys, in its corner (the app's ToyFrame)
    var num = toy.on ? '<span class="o-tnum">' + (TOYS.filter(function (t) { return t.on; }).indexOf(toy) + 1) + '</span>' : '';
    var meters = '';
    for (var i = 0; i < toy.motors; i++) meters += '<span class="o-meter"><i></i></span>';
    var right = toy.on
      ? '<span class="o-batt">' + BATT_SVG + toy.batt + '%</span><span class="o-meters">' + meters + '</span>' +
        '<span class="o-btn small" data-act="mute" data-tip="mute">Mute</span><span class="o-btn small" data-act="test" data-tip="testone">Test</span>'
      : '<span class="o-pill idle">OFFLINE</span>';
    var caret = '<span class="o-caret">' + (where === 'home' ? '›' : '▸') + '</span>';
    var head = '<span class="o-ticon"><img src="assets/demo/' + toy.icon + '.png" alt=""></span><span class="o-dot"></span>' +
      '<span class="o-tname">' + toy.name + '</span>';
    var sub = '<span class="o-tzones"></span><span class="o-chips">' + chipsHTML() + '</span>' +
      '<span class="o-schips">' + safetyHTML() + '</span>';
    var tip = toy.on ? (where === 'home' ? 'toyrow' : 'toy') : 'offline';
    var bar = '<div class="o-toybar wide" data-tip="' + tip + '">' + head + sub +
      '<span class="o-tspace"></span>' + right + caret + '</div>';
    return '<div class="o-toy' + (toy.on ? '' : ' offline') + '" data-toy="' + toy.id + '" data-where="' + where + '"' + style + '>' + num +
      bar + (where === 'home' ? '' : '<div class="o-toybody"></div>') + '</div>';
  }

  // The shocker hub, in the device list under the connected toys
  // (home_devices.py): Arm shocks (it asks first, in its own place) with the
  // red words that say which it is, Share with friends, On
  function shockRowHTML() {
    return '<div class="o-toy o-dev" data-dev="shock" style="--hue:var(--yellow);--hue-mid:var(--yellow-mid)">' +
      '<div class="o-toybar" data-tip="shockrow"><span class="o-ticon o-devicon">' + (ICONS.shock || '') + '</span>' +
      '<span class="o-dot"></span><span class="o-tname">Shockers</span><span class="o-tzones js-sum">PiShock · Collar, Thigh</span>' +
      '<span class="o-tspace"></span>' + armHTML() +
      '<span class="o-sw on js-share" data-tip="shockshare"></span><span class="o-swl">Share with friends</span>' +
      '<span class="o-sw on js-shockon" data-tip="shockon"></span><span class="o-swl js-shockonl">On</span>' +
      '<span class="o-caret">›</span></div></div>';
  }
  // Arm shocks (shocker_switches.ArmSwitch): the switch, or "Arm shocks? Yes /
  // No" in its place for five seconds; the red words from the setting
  function armHTML() {
    return '<span class="o-arm js-arm"><span class="o-armsw"><span class="o-sw js-armsw" data-tip="arm"></span>' +
      '<span class="o-swl">Arm shocks</span></span>' +
      '<span class="o-armask" data-tip="armask"><span class="o-swl">Arm shocks?</span><span class="o-btn small danger" data-arm="yes">Yes</span>' +
      '<span class="o-btn small" data-arm="no">No</span></span>' +
      '<b class="o-armw js-armw" data-tip="armw">Shocks armed</b></span>';
  }
  // The PSVR2 headset (home_devices.psvr2_row), while its feature is on
  function psvr2RowHTML() {
    return '<div class="o-toy o-dev" data-dev="psvr2" style="--hue:var(--blue);--hue-mid:var(--blue-mid)">' +
      '<div class="o-toybar" data-tip="psvr2row"><span class="o-ticon o-devicon">' + (ICONS.psvr2 || '') + '</span>' +
      '<span class="o-dot"></span><span class="o-tname">PSVR2</span><span class="o-tzones">Connected through PSVR2Toolkit</span>' +
      '<span class="o-tspace"></span>' +
      '<span class="o-sw on js-devon" data-tip="psvr2on"></span><span class="o-swl js-devonl">On</span>' +
      '<span class="o-caret">›</span></div></div>';
  }
  // A haptic suit, under the shocker hub (home_devices.py bhaptics_row /
  // owo_row); demo-suits.js says how it stands and runs its two switches
  function suitRowHTML(dev, name, share) {
    return '<div class="o-toy o-dev" data-dev="' + dev + '" style="--hue:var(--orange);--hue-mid:var(--orange-mid)">' +
      '<div class="o-toybar" data-tip="' + dev + 'row"><span class="o-ticon o-devicon">' + (ICONS.suits || '') + '</span>' +
      '<span class="o-dot"></span><span class="o-tname">' + name + '</span><span class="o-tzones js-sum"></span>' +
      '<span class="o-tspace"></span><span class="o-pill idle js-pill">OFFLINE</span>' +
      '<span class="o-sw js-share" data-tip="' + dev + 'share"></span><span class="o-swl js-sharel">' + share + '</span>' +
      '<span class="o-sw on js-devon" data-tip="' + dev + 'on"></span><span class="o-swl js-devonl">On</span>' +
      '<span class="o-caret">›</span></div></div>';
  }

  function rows(where, on) {
    return TOYS.filter(function (t) { return t.on === on; }).map(function (t) { return toyHTML(t, where); }).join('');
  }
  // Home: everything at a glance, each row opening its own page (home.py)
  function homeHTML() {
    return '<div class="o-page on" data-page="Home"><div class="o-home">' +
      '<div class="o-setup" data-tip="setup"><span class="o-ok"></span>Toy on<span class="o-ok"></span>VRChat connected' +
        '<span class="o-ok"></span>Avatar has SPS<span class="o-ok" data-tip="menu"></span>Avatar menu' +
        '<span class="o-setupr">Getting started</span></div>' +
      '<div class="o-homehead"><h4 data-tip="devices">Devices</h4><span class="o-tspace"></span>' +
        '<span class="o-btn js-testall" data-tip="test">Test all</span></div>' +
      '<div class="o-toysoff o-muted">Toy communication is off — switch it back on in Settings, under Features.</div>' +
      '<div class="o-toys o-scroll">' + rows('home', true) + shockRowHTML() +
        suitRowHTML('bhaptics', 'bHaptics', 'Also feel OWO’s contacts') +
        suitRowHTML('owo', 'OWO', 'Also feel bHaptics’ contacts') + psvr2RowHTML() +
        rows('home', false) + '</div>' +
      '</div></div>';
  }

  // The toys' anti-stuck timers: the app's ValueSlider, logarithmic
  var AS_MAX = 600, AS_STEPS = 1000;
  function asX(s) { return Math.round(AS_STEPS * Math.log(Math.max(1, s)) / Math.log(AS_MAX)); }
  function asS(x) { return clamp(Math.round(Math.exp(x / AS_STEPS * Math.log(AS_MAX))), 1, AS_MAX); }
  function secText(s) { return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min' + (s % 60 ? ' ' + (s % 60) + ' s' : ''); }
  function asSlider(key, label) {
    return '<div class="o-asrow"><div class="h"><span>' + label + '</span><b class="js-asv" data-as="' + key + '"></b></div>' +
      '<input type="range" class="js-asr" data-as="' + key + '" min="0" max="' + AS_STEPS + '" tabindex="-1"></div>';
  }
  // Toys: each toy's card with its chains, the toy server, SPS Sources and
  // the tuning tools (toys.py)
  function toysHTML() {
    return '<div class="o-page" data-page="Toys"><div class="o-home">' +
      '<div class="o-homehead"><h4 data-tip="toyspage">Toys</h4><span class="o-btn js-scan" data-tip="scan">Scan now</span>' +
        '<span class="o-muted js-nextscan"></span></div>' +
      '<div class="o-server" data-tip="server"><b>Toy server</b><span class="o-pill ok">CONNECTED</span>' +
        '<span class="o-srvok">✓ Built in, on this PC</span><span class="o-tspace"></span>' +
        '<span class="o-btn" data-go="Settings" data-tip="intisettings">Intiface settings</span></div>' +
      // the toys' anti-stuck (toys.py _build_toys_antistuck_card): the switch,
      // then its two times while it is on, on a log scale from 1 s to 10 min
      '<div class="o-asbox" data-tip="toysas"><div class="line"><span class="o-sw on js-tas"></span><span>Anti-stuck</span></div>' +
        '<div class="o-astimes js-astimes">' + asSlider('active_s', 'Frozen part-way: stop after') +
          asSlider('peaked_s', 'Held at 100%: ease off after') + '</div></div>' +
      '<div class="o-toys o-cards o-scroll">' + rows('card', true) + rows('card', false) + '</div>' +
      '<div class="o-tools o-sps"><div class="o-toolbar" data-tip="sps"><span class="car">▸</span><b>SPS Sources</b><span class="sum">Your own zones from any contact</span></div>' +
      '<div class="o-toolbody"><div class="o-card o-simcard"><p class="o-muted" style="margin:0 0 4px">' + SPS_NOTE + '</p>' +
        '<p class="o-muted" style="margin:0;color:var(--dim)">This part is not rebuilt in the website’s demo.</p></div></div></div>' +
      '<div class="o-tools o-tune"><div class="o-toolbar" data-tip="tools"><span class="car">▸</span><b>Tuning tools</b><span class="sum">Simulator · signal graph</span></div>' +
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
    // each with its page's icon, as "What are you here for?" (interests.FEATURE_ICONS)
    function feat(key, text, icon, hue) {
      return '<div class="line"><i class="o-fic"' + (hue ? ' style="color:var(--' + hue + ')"' : '') + '>' + (ICONS[icon] || '') + '</i>' +
        '<span class="o-sw on" data-feat="' + key + '" data-tip="feature"></span><span>' + text + '</span></div>';
    }
    return '<div class="o-page" data-page="Settings"><div class="o-viewtitle">Application Settings</div>' +
      '<div class="o-tabs"><span class="on">General</span><span>Sessions</span></div>' +
      '<div class="o-setscroll o-scroll">' +
      '<div class="o-card o-set"><div class="o-sect">Features</div>' +
        '<p>Turn off features you don’t need. Disabled features hide their sidebar entry and stop their background threads to save resources.</p>' +
        '<div class="line"><span class="o-btn" data-tip="interests">Choose what you use…</span></div>' +
        feat('intiface', 'Intiface toy communication (Buttplug.io)', 'toys', 'pink') +
        feat('inspector', 'OSC Inspector (debug view)', 'inspector') +
        feat('statistics', 'Usage statistics', 'stats') +
        '<div class="line" style="padding-left:68px"><span class="o-btn danger" data-tip="delstats">Delete statistics…</span></div>' +
        feat('pishock', 'Shockers — PiShock / OpenShock (USB)', 'shock', 'yellow') +
        feat('bhaptics', 'bHaptics — suit and sleeves over Bluetooth', 'suits', 'orange') +
        feat('owo', 'OWO — EMS suit through the My OWO app', 'suits', 'orange') +
        feat('trackers', 'Trackers — vibrating trackers through SteamVR', 'suits', 'orange') +
        feat('psvr2', 'PSVR2 — the headset’s rumble, through PSVR2Toolkit', 'psvr2', 'blue') +
        feat('friends', 'Friends — control each other over the internet', 'friends', 'cyan') +
        feat('params', 'Avatar Remote — avatar boards friends can use too', 'params', 'accent') + '</div>' +
      // the avatar's menu: the demo's avatar wears it (its OGP/* parameters
      // are in My Avatar Remote's list); the buttons are the real downloads
      '<div class="o-card o-set"><div class="o-sect">VRChat menu</div>' +
        '<p>OGP’s controls can be in your avatar’s own menu too, so you never leave VRChat: drag one VRCFury prefab onto your avatar — your own controls, the Friends submenu, or both — and upload. Your avatar’s own menu files aren’t touched, and the parameters are unsynced (0 sync bits).</p>' +
        '<div class="line"><span class="o-tick">✓</span><span><b>Your own controls</b> — Strength, Off, Sleep, Test and the modes · <i>on the avatar you’re wearing</i></span></div>' +
        '<div class="line"><span class="o-tick">✓</span><span><b>Friends submenu</b> — drives whoever you picked on the Friends page · <i>on the avatar you’re wearing</i></span></div>' +
        '<div class="line"><span class="o-tick">✓</span><span><b>Avatar Remote submenu</b> — seven toggles and seven radials for the controls you give its slots on My Avatar Remote · <i>on the avatar you’re wearing</i></span></div>' +
        '<div class="line"><a class="o-btn" data-tip="getmenu" target="_blank" rel="noopener" href="https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-VRCFury.unitypackage">Get the menu prefabs</a>' +
        '<a class="o-btn" data-tip="howmenu" target="_blank" rel="noopener" href="https://github.com/Blise518B/OscGoesPurrr/blob/main/docs/VRCHAT_MENU.md">How to add it</a></div></div>' +
      '<div class="o-card o-set"><div class="o-sect">Connection Settings</div>' +
        line(1, 'Auto Refresh Devices') + line(1, 'Auto Connect (Intiface)') + line(1, 'Auto Connect (VRChat OSC)') +
        line(1, 'Sound when a toy connects or disconnects') +
        '<div class="line"><span class="o-sw on" data-flip="1"></span><span>Tell VRChat while any toy is connected</span><span class="o-in" style="flex:1">OGP/ToyConnected</span><span class="o-btn">Pick...</span></div>' +
        line(0, 'Send thrust counters to VRChat') + '</div>' +
      // Safety (Toy Safety until 2026-11-17): where each anti-stuck lives now
      '<div class="o-card o-set"><div class="o-sect">Safety</div>' +
        '<div class="line" data-tip="aswhere"><p style="flex:1;margin:0">Anti-stuck, which stops a toy, a suit or the headset when a contact freezes, has its own switch and timers on each device’s page:</p>' +
          '<span class="o-btn" data-go="Toys">Toys</span><span class="o-btn" data-go="Suits">Suits</span><span class="o-btn" data-go="PSVR2">PSVR2</span></div>' +
        // Off while you're away (away_facade): a held Off, never your own switch
        '<p style="margin-top:10px">While VRChat says you’re AFK, everything is off — toys, shockers, suits, trackers and friends’ drives — and it all comes back by itself when you’re back. Your own Off switch isn’t touched. On by default.</p>' +
        '<div class="line"><span class="o-sw on" data-flip="1" data-tip="away"></span><span>Off while you’re away</span></div>' +
        '<div class="line" style="padding-left:44px"><span class="o-sw on" data-flip="1" data-tip="afk"></span><span>VRChat’s AFK</span></div>' +
        '<div class="line" style="padding-left:44px"><span class="o-sw on" data-flip="1" data-tip="goafk"></span><span>GoGo Loco’s AFK button</span></div>' +
        '<div class="line" style="padding-left:44px"><span>Also off while</span></div>' +
        '<p style="padding-left:44px;color:var(--dim)">None yet.</p>' +
        '<div class="line" style="padding-left:44px"><span class="o-btn" data-tip="awayparam">+ Add parameter…</span></div></div>' +
      '<div class="o-card o-set js-appearance"><div class="o-sect">Appearance</div>' +
        '<div class="line"><span class="o-lbl">Mode:</span><span class="o-btn seg js-uimode on" data-uimode="neon" data-tip="uimode">Vibrant</span><span class="o-btn seg js-uimode" data-uimode="midnight" data-tip="uimode">Darker</span></div>' +
        '<div class="line"><span class="o-lbl">Colour:</span><span class="js-presets" style="display:flex;gap:8px"></span></div>' +
        '<div class="line"><input type="range" class="o-hue js-hue" min="0" max="359" value="150" tabindex="-1" data-tip="colour"></div>' +
        '<p style="margin-top:4px">Mode and colour change as you pick — no restart.</p>' +
        '<div class="line"><span class="o-btn small ghost js-idfold" data-tip="idcolours">Other colours ▸</span></div>' +
        '<div class="js-idbody" style="display:none"><p>A colour that comes too close to yours moves out of its way by itself. Drag one to set it yourself; Auto hands it back.</p>' +
        '<div class="js-idrows"></div></div></div>' +
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
    '<div class="o-main">' + homeHTML() + toysHTML() +
      '<div class="o-page" data-page="Statistics"></div>' + settingsHTML() +
      BUILT.map(function (n) { return '<div class="o-page o-built" data-page="' + n + '"><div class="o-pgscroll o-scroll rpanel"></div></div>'; }).join('') +
      Object.keys(NOTES).map(noteHTML).join('') + '</div>' +
    // the name and the version link to the repository, Blise518B to his
    // profile (theme.status_tag_html)
    '<div class="o-status"><span><a class="o-help" href="guide/" target="_blank" rel="noopener">Guide&nbsp;↗</a> ' +
    '<span class="o-help">?&nbsp; Show me around</span></span>' +
    '<span><a class="o-dimlink" href="https://github.com/Blise518B/OscGoesPurrr" target="_blank" rel="noopener">OscGoesPurrr</a> ' +
    '<a class="o-dimlink" href="https://github.com/Blise518B/OscGoesPurrr" target="_blank" rel="noopener"><span class="ver-tag"></span></a> · made by ' +
    '<a href="https://github.com/Blise518B" target="_blank" rel="noopener"><b>Blise518B</b></a></span></div>' +
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
    return out + footHTML(toy);
  }
  // A card's last line, after every motor's chains (device_frame._build_toy_foot):
  // Avatar parameters folded, saying how many are on, and Delete device as
  // words at its end
  function footHTML(toy) {
    function row(on, label, name) {
      return '<div class="o-trow"><span class="o-sw' + (on ? ' on' : '') + '" data-flip="1" data-tip="avparams"></span>' +
        '<span class="o-trowl">' + label + '</span><span class="o-in o-tname-in">' +
        (name || '<i>Avatar parameter name (e.g. TailW…</i>') + '</span><span class="o-btn small">Pick…</span></div>';
    }
    var rows = '';
    for (var mi = 0; mi < toy.motors; mi++)
      rows += row(false, toy.motors > 1 ? 'Mirror motor ' + mi + ' to VRChat parameter' : 'Mirror to VRChat parameter', '');
    rows += row(true, 'Tell VRChat while this toy is connected', 'OGP/' + toy.name.replace(/[^A-Za-z0-9]/g, '') + 'Connected');
    return '<div class="o-tfoot"><span class="o-btn ghost small js-pfold" data-tip="avparams">▸&nbsp; Avatar parameters</span>' +
      '<span class="o-muted js-pcount"></span><span class="o-tspace"></span>' +
      '<span class="o-dangertext" data-tip="deltoy">Delete device</span></div>' +
      '<div class="o-tparams">' + rows + '</div>';
  }
  function countParams(toyEl) {
    var n = $$('.o-tparams .o-sw.on', toyEl).length;
    $('.js-pcount', toyEl).textContent = n ? n + ' on' : 'none on';
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
    var h = hearOf(toyId), pen = CH[ci].name === 'Penetration';      // a typed chain hears its own kind
    $('.sum', fold).textContent = Chain.summaryLine(cc, { zones: zonesOf(toyId) || 'none', self: pen ? h.ps : h.ts,
                                                          others: pen ? h.po : h.to, params: [], sim: false });
    var merge = $('.o-merge[data-merge="' + mi + '"]', toyEl), op = motors[toyId][mi].cfg.merge;
    $$('.o-fold[data-fold^="' + mi + '."] .mrg', toyEl).forEach(function (m) { m.textContent = '⋁ ' + op; });
    $$('[data-mergeop]', merge).forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-mergeop') === op); });
  }
  // The merge picker shows only beside an open chain; folded, the chains'
  // bars carry its tag (MotorChainListWidget._rebuild)
  function syncMerge(toyEl) {
    $$('.o-merge', toyEl).forEach(function (m) {
      var mi = m.getAttribute('data-merge');
      m.style.display = $('.o-chain.open[data-chain^="' + mi + '."]', toyEl) ? '' : 'none';
    });
  }
  function openToy(toyEl, open) {
    var id = toyEl.getAttribute('data-toy'), toy = TOYS.filter(function (t) { return t.id === id; })[0];
    if (!toy.on) return;
    var body = $('.o-toybody', toyEl);
    if (open && !body.firstChild) {
      body.innerHTML = bodyHTML(toy);
      for (var mi = 0; mi < toy.motors; mi++) { refreshChain(toyEl, id, mi, 0); refreshChain(toyEl, id, mi, 1); }
      syncMerge(toyEl);
      countParams(toyEl);
    }
    toyEl.classList.toggle('open', open);
    $('.o-caret', toyEl).textContent = open ? '▾' : '▸';
  }
  function cardOf(toyId) { return $('.o-toy[data-toy="' + toyId + '"][data-where="card"]'); }
  // A toy's row on Home: the Toys page, its card open at the top of the list
  // (toys.open_toy_card)
  function openCard(toyId) {
    go('Toys');
    openToy(cardOf(toyId), true);
    scrollToCard(toyId);
  }
  function scrollToCard(toyId) {
    var card = cardOf(toyId), list = $('.o-cards');
    list.scrollTop = card.offsetTop - list.offsetTop;
  }

  // ── interactions ──────────────────────────────────────────────────────────
  // What the pages in their own files listen to: 'shock' (the hub's
  // switches), 'features', 'page', 'strength'.
  var handlers = {};
  function on(name, fn) { (handlers[name] = handlers[name] || []).push(fn); }
  function emit(name) { (handlers[name] || []).forEach(function (fn) { fn(S); }); }

  // Arm shocks, wherever it shows (Home's row, the Shockers page's hub): one
  // setting; the question stands in the switch's place until answered or
  // ARM_ASK_S runs out
  var ARM_ASK_S = 5;
  function refreshArm() {
    var st = S.shock, asking = st.asking > 0;
    $$('.js-arm').forEach(function (a) {
      a.classList.toggle('asking', asking);
      $('.js-armsw', a).classList.toggle('on', st.armed);
      var w = $('.js-armw', a), text = st.armed ? 'Shocks armed' : 'Shocks not armed';
      if (w.textContent !== text) { w.textContent = text; w.classList.toggle('not', !st.armed); }
    });
  }
  // what: "flip" (the switch), "yes" or "no" (its question)
  function arm(what) {
    var st = S.shock;
    if (what !== 'flip') { if (what === 'yes') st.armed = true; st.asking = 0; }
    else if (st.armed) st.armed = false;          // switching off never asks
    else {
      var ask = st.asking = performance.now();
      setTimeout(function () { if (st.asking === ask) { st.asking = 0; emit('shock'); } }, ARM_ASK_S * 1000);
    }
    emit('shock');
  }
  function refreshShockRow() {
    var row = $('.o-dev[data-dev="shock"]'), up = S.shock.on;
    $('.js-share', row).classList.toggle('on', S.shock.share);
    $('.js-shockon', row).classList.toggle('on', up);
    $('.js-shockonl', row).textContent = up ? 'On' : 'Off';
    row.classList.toggle('down', !up);
    refreshArm();
  }
  on('shock', refreshShockRow);
  function refreshPsvr2Row() {
    var row = $('.o-dev[data-dev="psvr2"]'), up = S.psvr2.on;
    $('.js-devon', row).classList.toggle('on', up);
    $('.js-devonl', row).textContent = up ? 'On' : 'Off';
    row.classList.toggle('down', !up);
  }
  function applyFeatures() {
    $$('.o-nav [data-feature]').forEach(function (n) {
      var on = n.getAttribute('data-feature').split('|').some(function (k) { return S.features[k]; });
      n.style.display = on ? '' : 'none';
    });
    $$('[data-feat]').forEach(function (sw) { sw.classList.toggle('on', !!S.features[sw.getAttribute('data-feat')]); });
    $('.o-dev[data-dev="shock"]').style.display = S.features.pishock ? '' : 'none';
    $('.o-dev[data-dev="bhaptics"]').style.display = S.features.bhaptics ? '' : 'none';
    $('.o-dev[data-dev="owo"]').style.display = S.features.owo ? '' : 'none';
    $('.o-dev[data-dev="psvr2"]').style.display = S.features.psvr2 ? '' : 'none';
    // toy communication off: Home keeps its other devices, the toys go
    // (and with them the Toys page)
    $$('.o-page[data-page="Home"] .o-toy[data-toy]').forEach(function (t) { t.style.display = S.features.intiface ? '' : 'none'; });
    $('.o-toysoff').style.display = S.features.intiface ? 'none' : '';
    if (!S.features.intiface && S.page === 'Toys') go('Home');
  }
  function setFeature(key, value) { S.features[key] = value; applyFeatures(); emit('features'); }
  function setStrength(v) {
    S.strength = clamp(v, 0, 1);
    var inp = $('.js-strength');
    inp.value = Math.round(S.strength * 100); setRange(inp);
    $('.js-strval').textContent = Math.round(S.strength * 100) + '%';
    emit('strength');
  }

  function go(page) {
    if (!$('.o-page[data-page="' + page + '"]')) return;
    var entry = $('.o-nav [data-go="' + page + '"]');
    if (entry && entry.style.display === 'none') return;     // its feature is switched off
    S.page = page;
    $$('.o-page').forEach(function (p) { p.classList.toggle('on', p.getAttribute('data-page') === page); });
    $$('.o-nav .n').forEach(function (n) { n.classList.toggle('on', n.getAttribute('data-go') === page); });
    if (page === 'Statistics' && window.OGPDemoStats && !go.stats) {
      go.stats = true;
      var statsPage = $('.o-page[data-page="Statistics"]');
      statsPage.innerHTML = window.OGPDemoStats.HTML;
      window.OGPDemoStats.init(statsPage);
    }
    emit('page');
  }
  // Each toy's Sleep and Anti-stuck chips, both bars, and the Toys page's
  // anti-stuck: Sleep lit while it sleeps, lit and greyed ("held") while the
  // sidebar's Sleep has every toy asleep; Anti-stuck greyed while the toys'
  // anti-stuck is off (device_frame._safety_looks)
  function refreshSafety() {
    $$('.o-toy[data-toy]').forEach(function (t) {
      var id = t.getAttribute('data-toy'), sl = $('[data-safe="sleep"]', t), as = $('[data-safe="as"]', t);
      if (!sl) return;
      sl.classList.toggle('held', S.sleep);
      sl.classList.toggle('on', !S.sleep && !!S.toySleep[id]);
      as.classList.toggle('dis', !S.as.enabled);
      as.classList.toggle('on', S.as.enabled && S.toyAs[id] !== false);
    });
    var sw = $('.js-tas');
    if (!sw) return;
    sw.classList.toggle('on', S.as.enabled);
    $('.js-astimes').hidden = !S.as.enabled;
    $$('.js-asr').forEach(function (r) {
      var k = r.getAttribute('data-as');
      if (document.activeElement !== r) r.value = asX(S.as[k]);
      setRange(r);
    });
    $$('.js-asv').forEach(function (v) { v.textContent = secText(S.as[v.getAttribute('data-as')]); });
  }
  function refreshZones() {
    $$('.o-toy[data-toy]').forEach(function (t) {
      var id = t.getAttribute('data-toy'), h = hearOf(id);
      $('.o-tzones', t).textContent = zoneLabel(id);
      $$('.o-cchip', t).forEach(function (c) { c.classList.toggle('on', h[c.getAttribute('data-pair')]); });
    });
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
    if (t.closest('.js-sleep')) { S.sleep = !S.sleep; $('.js-sleep').classList.toggle('on', S.sleep); refreshSafety(); return; }
    if (t.closest('.js-tas')) { S.as.enabled = !S.as.enabled; refreshSafety(); return; }
    if (t.closest('.js-testall')) { S.testUntil = S.t + 1.0; return; }
    if ((x = t.closest('.js-pfold'))) {
      var tf = x.closest('.o-toy'), pOpen = !tf.classList.contains('params');
      tf.classList.toggle('params', pOpen); x.innerHTML = (pOpen ? '▾' : '▸') + '&nbsp; Avatar parameters'; return;
    }
    if ((x = t.closest('.o-tparams [data-flip]'))) { x.classList.toggle('on'); countParams(x.closest('.o-toy')); return; }
    if (t.closest('.o-dangertext')) return;               // the demo keeps its toys
    if ((x = t.closest('[data-flip]'))) { x.classList.toggle('on'); return; }
    if ((x = t.closest('[data-feat]'))) { setFeature(x.getAttribute('data-feat'), !x.classList.contains('on')); return; }
    if (t.closest('.js-scan')) { S.scanAt = 30; return; }      // it looks now; with a toy connected the next is 30 s on
    if ((x = t.closest('.js-armsw, [data-arm]'))) { arm(x.getAttribute('data-arm') || 'flip'); return; }
    if (t.closest('.js-arm')) return;                          // the question's own space, never the row's
    var dev = t.closest('.o-dev');
    if (dev) {
      var kind = dev.getAttribute('data-dev');
      if (kind === 'psvr2') {
        if (t.closest('.js-devon')) { S.psvr2.on = !S.psvr2.on; refreshPsvr2Row(); return; }
        go('PSVR2'); return;
      }
      // a suit's switches are demo-suits.js's; the rest of its row opens Suits
      if (kind !== 'shock') { if (!t.closest('.o-sw')) go('Suits'); return; }
      if (t.closest('.js-share')) { S.shock.share = !S.shock.share; emit('shock'); return; }
      if (t.closest('.js-shockon')) { S.shock.on = !S.shock.on; emit('shock'); return; }
      go('Shockers'); return;
    }
    if (t.closest('.o-tools')) {
      var tools = t.closest('.o-tools');
      if (t.closest('.o-toolbar')) {
        tools.classList.toggle('open');
        $('.o-toolbar .car', tools).textContent = tools.classList.contains('open') ? '▾' : '▸';
        sizeGraph(); return;
      }
    }
    if ((x = t.closest('.js-uimode'))) { setMode(x.getAttribute('data-uimode')); return; }
    if ((x = t.closest('.o-swatch'))) { setHue(x.hasAttribute('data-hue') ? +x.getAttribute('data-hue') : null); return; }
    if ((x = t.closest('.js-idfold'))) {
      var body = $('.js-idbody'), open = body.style.display === 'none';
      body.style.display = open ? '' : 'none'; x.textContent = open ? 'Other colours ▾' : 'Other colours ▸'; return;
    }
    if ((x = t.closest('.js-idauto'))) { delete chosenHues[x.closest('.o-idrow').getAttribute('data-id')]; applyColour(); return; }
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
      $('.o-tune .o-toolbar .sum').textContent = S.graph ? 'Signal graph on' : 'Simulator · signal graph';
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
    if ((x = t.closest('[data-safe]'))) {
      // the toy's own Sleep or Anti-stuck, the same on Home's row and the card
      if (x.classList.contains('held') || x.classList.contains('dis')) return;
      if (x.getAttribute('data-safe') === 'sleep') S.toySleep[id] = !S.toySleep[id];
      else S.toyAs[id] = S.toyAs[id] === false;
      refreshSafety(); return;
    }
    if ((x = t.closest('.o-cchip'))) {
      // its pair on every chain of the toy that hears that kind, in the
      // active mode -- the same on Home's row and the card
      var hr = hearOf(id), pair = x.getAttribute('data-pair');
      hr[pair] = !hr[pair]; refreshZones(); return;
    }
    if ((x = t.closest('[data-act="mute"]'))) {
      var mu = !motors[id][0].muted; motors[id].forEach(function (m) { m.muted = mu; });
      $$('.o-toy[data-toy="' + id + '"] [data-act="mute"]').forEach(function (b) {
        b.classList.toggle('on', mu); b.classList.toggle('seg', mu); b.textContent = mu ? 'Unmute' : 'Mute';
      });
      return;
    }
    if (t.closest('[data-act="test"]')) { motors[id].forEach(function (m) { m.testUntil = S.t + 1.0; }); return; }
    if (toyEl.getAttribute('data-where') === 'home') {
      if (t.closest('.o-toybar')) openCard(id);
      return;
    }
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
      syncMerge(toyEl);
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
    if (inp.classList.contains('js-strength')) { setStrength(inp.value / 100); return; }
    if (inp.classList.contains('js-hue')) { setHue(+inp.value, true); return; }
    if (inp.classList.contains('js-asr')) { S.as[inp.getAttribute('data-as')] = asS(+inp.value); refreshSafety(); return; }
    if (inp.classList.contains('js-idhue')) { chosenHues[inp.closest('.o-idrow').getAttribute('data-id')] = +inp.value; applyColour(); return; }
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
  // The colours that mean something: each moves out of the accent's way
  // when it lands too close (Accent.identityHues), or is set by hand under
  // Other colours -- as in the app (constants.IDENTITY_HUES).
  var IDENT = [['pink', 'Pink', 'the live signal, penetration, friends\u2019 toys'], ['red', 'Red', 'errors and Stop'],
    ['amber', 'Amber', 'touch contact and warnings'], ['yellow', 'Yellow', 'shockers'],
    ['cyan', 'Cyan', 'your first toy, friends, things running'], ['blue', 'Blue', 'your second toy'], ['purple', 'Purple', 'your third toy'],
    ['orange', 'Orange', 'the haptic suits']];
  var IDTONES = [];
  IDENT.forEach(function (r) { IDTONES.push(r[0], r[0] + '-mid', r[0] + '-tint'); });
  var neonAccent = tok('--accent'), pickedHue = null, defaultHue = Accent ? Accent.hueOf(neonAccent) : 150;
  var chosenHues = {};
  function baseTokens() {
    var names = CHROME.concat(GREENS, IDTONES), base = {};
    names.forEach(function (n) { root.style.removeProperty('--' + n); });
    names.forEach(function (n) { base[n] = tok('--' + n); });
    return base;
  }
  function turn(d) { return ((d % 360) + 360) % 360; }
  function applyColour() {
    if (!Accent) return;
    var base = baseTokens(), delta = Accent.deltaFor(pickedHue, neonAccent);
    if (delta) CHROME.concat(GREENS).forEach(function (n) { root.style.setProperty('--' + n, Accent.shiftHex(base[n], delta)); });
    var own = {};
    IDENT.forEach(function (r) { own[r[0]] = Accent.hueOf(base[r[0]]); });
    var moves = Accent.identityHues(pickedHue, own, Accent.hueOf(base.green), chosenHues);
    Object.keys(moves).forEach(function (n) {
      var d = turn(moves[n] - own[n]);
      if (Accent.hueDistance(moves[n], own[n]) < 0.5) return;
      [n, n + '-mid', n + '-tint'].forEach(function (t) { root.style.setProperty('--' + t, Accent.shiftHex(base[t], d)); });
    });
    paintPicker(base);
    paintIdentity(base, own, moves);
    redrawAll();
  }
  function paintIdentity(base, own, moves) {
    var box = $('.js-idrows');
    if (!box) return;
    if (!box.firstChild) {
      box.innerHTML = IDENT.map(function (r) {
        return '<div class="line o-idrow" data-id="' + r[0] + '"><span class="o-idsw"></span><span class="o-lbl">' + r[1] + '</span>' +
          '<input type="range" class="o-hue sm js-idhue" min="0" max="359" tabindex="-1">' +
          '<span class="o-btn small ghost js-idauto">Auto</span><span class="o-idnote"></span></div>';
      }).join('');
    }
    IDENT.forEach(function (r) {
      var n = r[0], row = $('.o-idrow[data-id="' + n + '"]', box), hue = n in moves ? moves[n] : own[n];
      var colour = Accent.shiftHex(base[n], turn(hue - own[n]));
      $('.o-idsw', row).style.background = colour;
      var stops = [];
      for (var i = 0; i <= 12; i++) stops.push(Accent.shiftHex(base[n], turn(i * 30 - own[n])) + ' ' + (i / 12 * 100).toFixed(2) + '%');
      var sl = $('.js-idhue', row);
      sl.style.setProperty('--huetrack', 'linear-gradient(90deg,' + stops.join(',') + ')');
      sl.style.setProperty('--huethumb', colour);
      if (document.activeElement !== sl) sl.value = Math.round(hue) % 360;
      var chosen = n in chosenHues;
      $('.js-idauto', row).style.visibility = chosen ? 'visible' : 'hidden';
      $('.o-idnote', row).textContent = r[2] + (chosen ? ' \u00b7 set by you' : n in moves ? ' \u00b7 moved out of your colour\u2019s way' : '');
    });
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
    S.scanAt -= dt;
    if (S.scanAt <= 0) S.scanAt += 30;
    if (!Chain) return;
    var pen = contactNow(), ref = null;
    TOYS.forEach(function (toy) {
      if (!toy.on) return;
      var heard = hears(toy.id) ? pen : 0, drive = S.drive[toy.id];
      motors[toy.id].forEach(function (mo, mi) {
        var res = mo.m.step(dt, { pen: heard, touch: 0 }, {
          strength: S.strength, off: S.off, sleep: S.sleep || !!S.toySleep[toy.id],
          antistuck: (S.as.enabled && S.toyAs[toy.id] !== false) ? S.as : null });
        var out = res.out;
        // A friend's level joins at the end, as in the app (motor_router
        // _apply_friend_drive): scaled by your strength (none while Off),
        // into this motor's output band; the higher wins, or with Override
        // theirs replaces it.
        if (drive) {
          if (drive[0] > 0) {
            var theirs = mo.m.mapIntoOutputBand(Math.min(1, drive[0]) * (S.off ? 0 : S.strength));
            out = drive[1] ? theirs : Math.max(out, theirs);
          } else if (drive[1]) out = 0;
        }
        if (!S.features.intiface) out = 0;
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
    var scan = 'Next scan in ' + Math.max(1, Math.ceil(S.scanAt)) + ' s', ns = $('.js-nextscan');
    if (ns.textContent !== scan) ns.textContent = scan;
    $$('.o-toy[data-toy]').forEach(function (toyEl) {
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
    if (S.graph && S.page === 'Toys') drawGraph($('.o-graph canvas'), TRACES, true);
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
  // How the shocker switches stack: the same paragraph under each of them
  // (shocker_switches.STACK)
  var STACK = '<br><br><b>How the shocker switches stack</b>, from everyone to one friend:<br><b>On</b> (the hub) → ' +
    '<b>Arm shocks</b> (real shocks) → <b>Share with friends</b> (friends at all) → each friend’s own <b>Shockers</b> ' +
    'switch on the Friends page (and the web remote’s).<br>Off stops everything, whatever the rest say. Unarmed, every shock - ' +
    'yours or a friend’s - is a vibrate. Not shared, no friend sees your shockers. Home’s shocker row and the Shockers page show the same switches.';
  var TIPS = {
    mode: ['Modes', 'A mode is a <b>routing</b> \u2014 which parts of your avatar drive which toys. Click to make this one live. Your tuning, your toys and the strength stay the same whichever mode is on.<br><br><b>Right-click</b> to rename it or change its icon.'],
    strength: ['Total output strength', 'One multiplier on everything your toys receive \u2014 the knob for \u201Ca bit softer tonight\u201D. It never touches your tuning, so turning it back up restores exactly the feel you had.<br><br>From inside VRChat: the <b>OGP/Strength</b> radial.'],
    off: ['Off', 'Panic silence. Every toy stops instantly, whatever the strength says; press it again and your previous level comes straight back.<br><br>From inside VRChat: <b>OGP/Off</b>.'],
    sleep: ['Sleep', 'Makes your toys hard to wake: nothing plays until three full strokes land within six seconds, so a brush against a sleeping partner does nothing.<br><br>From inside VRChat: <b>OGP/Sleep</b>.'],
    test: ['Test all', 'Buzzes every connected toy at a low level for a moment, so you know they\u2019re all wired up.'],
    testone: ['Test', 'Buzzes this toy at a low level for a moment.'],
    toysleep: ['Sleep (this toy)', 'Puts just this toy to sleep: nothing from your avatar’s contacts plays on it until three full strokes land within six seconds, so a brush against a sleeping partner does nothing. After 45 seconds without a stroke it sleeps again.<br><br><b>Lit</b> while it sleeps. <b>Lit and greyed</b> while the sidebar’s <b>Sleep</b> has every toy asleep. Not remembered when you restart OGP, like Mute. Friends’ drives still reach it.'],
    toyas: ['Anti-stuck (this toy)', 'Whether anti-stuck watches this toy. On by default: a contact that freezes (you swap avatar, your partner leaves, the link drops) stops it instead of keeping it going. Switch it off for a toy that should keep playing a value that sits still.<br><br><b>Greyed</b> while anti-stuck is off for every toy (on the Toys page, under Toy server, with its timers). Remembered, the same in every mode.'],
    toysas: ['Toys’ anti-stuck', 'VRChat only sends a value when it changes. If a contact stops updating - you swap avatar, your partner leaves, the link drops - its last value would keep a toy going. Anti-stuck notices a value that has frozen and stops it.<br><br>A value frozen <b>part-way</b> is cut quickly (1 s by default); one held at <b>100%</b> gets the longer wait, then eases off over 3 s. A new value brings it back at once. Each kind of device has its own: the toys here, each suit and the trackers on the Suits page, the headset on its page. Each toy’s bar has an <b>Anti-stuck</b> of its own too, to leave one toy out.'],
    aswhere: ['Anti-stuck', 'Each kind of device has its own anti-stuck, with its own timers: the toys on the Toys page (and each toy on its bar), the bHaptics suit, the OWO suit and the haptic trackers on the Suits page, the headset on the PSVR2 page.'],
    mute: ['Mute', 'Silences this toy only. Everything else keeps playing, and its setup is untouched.'],
    toy: ['Toys', 'Every toy you have connected, plus the ones you’ve used before that are switched off right now (grey). The bar shows what drives the toy in the active mode, who it hears, its battery and a live meter per motor - the same as its row on Home.<br><br>Under it, each motor’s <b>signal chains</b>, folded - click one to set it up (Input → Depth/Speed/Punch → Combine → Wake → Envelope → Zero cut → Output). A click on the bar folds the toy away. <b>Mute</b> silences the toy without touching its setup; <b>Test</b> gives it a short buzz.'],
    avparams: ['Avatar parameters', 'What this toy tells your avatar - for a light, an icon or a meter on it. <b>Mirror to VRChat parameter</b> sends each motor’s level as a Float; <b>Tell VRChat while this toy is connected</b> sends a Bool. Says how many are on; click to open or close.'],
    deltoy: ['Delete device', 'Forgets this toy and everything set up for it, in every mode. If you switch it on again later it comes back as a new toy with default settings. (The demo keeps its toys.)'],
    toyspage: ['Toys', 'Every toy you have connected, plus the ones you’ve used before that are switched off right now (grey). Each card is open on its motors’ signal chains, folded: click one to set it up.'],
    toyrow: ['Devices', 'Everything you have, at a glance. <b>Click a row</b> to open it on its own page - a toy opens at its card on the Toys page, where its signal chains are. The switches on a row work right here: a toy’s Touch / Penetration chips, Mute and Test; the shockers’ Arm shocks, Share with friends and On / Off.'],
    devices: ['Devices', 'Everything you have, at a glance: every toy you have connected (the ones you’ve used before stay listed, grey while they’re off), and your shocker hub, suits and headset while they’re switched on in Settings → Features.<br><br><b>Click a row</b> to open it on its own page - a toy opens at its card on the Toys page, where its signal chains are. The switches on a row work right here: a toy’s Touch / Penetration chips, Mute and Test; the shockers’ Arm shocks, Share with friends and On / Off.'],
    server: ['Toy server', 'The Buttplug.io server that talks to your Bluetooth toys. OGP runs its own copy, so there is nothing else to start, and it connects and reconnects by itself. With the built-in engine switched off, this says where your own Intiface Central is - on this PC or a phone - and whether it was found.'],
    intisettings: ['Intiface settings', 'Opens Settings → Intiface Engine: the built-in toy server, or your own Intiface Central, on this PC or on a phone on the same network.'],
    sps: ['SPS Sources', 'Your own zones, built from raw VRChat contact receivers - for spots the standard SPS zones don’t cover, or an avatar without them. Each source becomes a zone you can pick in any toy’s Input stage, like the ones your avatar’s SPS provides. Click to open or close.'],
    arm: ['Arm shocks', 'Until this is on, every shock - a behaviour’s, a friend’s, a test - goes out as a vibrate instead. Switching it on here asks first, in the switch’s place: Yes arms. The red words beside it say which it is now: Shocks armed or Shocks not armed. It stays as you leave it, across restarts too.' + STACK],
    armask: ['Arm shocks?', 'Yes arms your shocks: from then on every shock is real - your behaviours’, your avatar menu’s, and your friends’ where you share your shockers with them. No, or a few seconds without an answer, leaves them unarmed. Armed, they stay armed until you switch it off, even after a restart.'],
    armw: ['Shocks armed or not', 'Whether your shocks are real right now: Shocks armed, or Shocks not armed - then every shock goes out as a vibrate. It follows the one Arm shocks setting, so Home’s shocker row and the Shockers page always say the same.'],
    psvr2row: ['PSVR2', 'Your PlayStation VR2 headset’s rumble motor, through PSVR2Toolkit. Click the bar to open the page where you connect it, set its rumble band and test it.'],
    psvr2on: ['On / Off', 'Your headset’s motor for everyone. Off stops it now and keeps it still until you switch it on again, even after a restart. It stays connected, and its other settings stay as they are.'],
    away: ['Off while you’re away', 'Holds everything off while you’re AFK in VRChat: your toys, shockers, suits and haptic trackers, and every friend’s drive (their shocks are held back and logged). It’s the same Off as the sidebar’s Off button and <b>OGP/Off</b>, held for you — that switch isn’t pressed, so when you’re back everything is exactly as it was. Closing VRChat lets go too: it only holds while VRChat is running and says you’re away.<br><br>The status bar says why while it holds (“AFK: everything off”). Pick below what counts as away.'],
    afk: ['VRChat’s AFK', 'Off while VRChat’s own AFK parameter is on. VRChat sets it when you take the headset off, or press End on desktop, and clears it when you’re back. Every avatar has it.'],
    goafk: ['GoGo Loco’s AFK button', 'Off while GoGo Loco’s AFK pose is on. GoGo Loco’s Locomotion menu has an AFK button that sets <b>VRCEmote</b> to 101, so OGP reads that. Avatars without GoGo Loco never send it.'],
    awayparam: ['Also off while', 'Parameters of your choosing that switch everything off while they’re on — a Bool that is true, or a number above zero. Put a toggle of your own in your avatar’s menu and pick it here, and it’s your own Off switch; any one of them is enough.'],
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
    colour: ['Colour', 'Turns everything that is green \u2014 frames, buttons, highlights, even the faint tint of the background \u2014 to the colour you pick, as you pick it. Brightness and contrast stay as they are.<br><br>The colours that <i>mean</i> something keep theirs \u2014 each toy\u2019s own colour, pink for the live signal, amber for warnings, red for errors \u2014 unless your colour lands right on one of them: that one then moves out of its way (pick Pink, and the pink turns green). <b>Other colours</b> below shows them all and lets you set any of them yourself.'],
    setup: ['Getting started', 'The three things that have to be true for your toys to feel your avatar: a toy connected, VRChat talking to the app over OSC, and an avatar with SPS / OGB contacts. Click to open the steps again.'],
    scan: ['Scan now', 'Look for toys right now - for a toy you just switched on. The app also looks by itself: every few seconds while no toy is connected (Settings → Connection Settings sets how often), every 30 seconds while one is.'],
    shockrow: ['Shockers', 'Your shocker hub and the shockers it reports. Click the bar to open the Shockers page, where you connect and set the limits. The red words say whether shocks are armed; unarmed, they go out as vibrates.'],
    shockshare: ['Share with friends', 'Sharing only, for all your friends at once: off, your friends don’t see your shockers at all and nothing they send reaches them, whatever their own Shockers switch on the Friends page says. Your own rules and the Shockers page still work.' + STACK],
    shockon: ['On / Off', 'Your shockers, all of it. Off ends whatever they are doing now and keeps them quiet - your rules, friends, tests - until you switch them on again, even after a restart; friends don’t see them meanwhile. The hub stays connected, and who may use them stays as you set it. The same as Stop all / Resume on the Shockers page.' + STACK],
    bhapticsrow: ['bHaptics', 'Your bHaptics suit. Click to open the Suits page, where you connect it and set what it feels.'],
    bhapticsshare: ['Also feel OWO’s contacts', 'The bHaptics suit also plays the touches that reach the OWO suit’s places on the body — the same switch as on the Suits page.'],
    bhapticson: ['On / Off', 'Your bHaptics suit for everyone. Off sets it to zero now and keeps it there until you switch it on again, even after a restart. It stays connected, and its other settings stay as they are.'],
    oworow: ['OWO', 'Your OWO suit. Click to open the Suits page, where you connect it and set what it feels.'],
    owoshare: ['Also feel bHaptics’ contacts', 'The OWO suit also plays the touches that reach the bHaptics suit’s places on the body — the same switch as on the Suits page.'],
    owoon: ['On / Off', 'Your OWO suit for everyone. Off sets it to zero now and keeps it there until you switch it on again, even after a restart. It stays connected, and its other settings stay as they are.'],
    menu: ['Avatar menu', 'Optional — Strength, Off, Sleep, the modes and a Friends submenu, right in VRChat: drag one VRCFury prefab onto your avatar and upload. Settings → VRChat menu has the prefab and the guide.'],
    getmenu: ['Get the menu prefabs', 'Downloads OscGoesPurrr-VRCFury.unitypackage from the newest release. Import it into your avatar’s Unity project (it needs VRCFury), drag one of its three prefabs onto your avatar and upload.'],
    howmenu: ['How to add it', 'The setup guide: the prefabs, a one-click installer for avatars without VRCFury, the manual way, and every parameter.'],
    feature: ['Features', 'Switch a feature off and its page leaves the sidebar and its background work stops. Nothing you set up for it is lost.'],
    interests: ['Choose what you use', 'Asks again what you have and want — toys, a shocker, friends — and switches the features to match.'],
    delstats: ['Delete statistics', 'Deletes everything recorded. Asks first. Works whether statistics are on or off.'],
    idcolours: ['Other colours', 'The colours that <i>mean</i> something: the live signal, errors, warnings, shockers, each toy\u2019s own colour.<br><br><b>Auto</b> (the default): a colour keeps its own hue \u2014 unless your colour above lands too close to it, then it moves out of its way, to where it stands out most.<br><b>Drag a slider</b> to set that colour yourself; it then stays where you put it, whatever your colour. <b>Auto</b> hands it back.']
  };
  PAIRS.forEach(function (p) {
    TIPS['chip-' + p[0]] = [p[3], 'Whether this toy feels ' + p[4] + '. One click sets it on every ' +
      (p[1] === 'Touch' ? 'Touch and Custom' : 'Penetration and Custom') + ' chain of the toy, in the active mode.<br><br>' +
      '<b>Half lit</b> while those chains disagree; a click then turns it on for all of them. <b>Greyed</b> when no chain of ' +
      'the toy hears this kind of contact. Each chain has the same four switches in its <b>Input</b> stage.'];
  });
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
  refreshZones(); refreshSim(); refreshSafety();
  if (Accent) applyColour();
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

  applyFeatures(); refreshShockRow(); refreshPsvr2Row();
  // the Toys page's cards start open, on their motors' folded chains
  TOYS.forEach(function (t) { if (t.on) openToy(cardOf(t.id), true); });
  window.OGPDemo = {
    state: S, go: go, contact: contactNow, on: on, emit: emit, icons: ICONS,
    // the pages in their own files: their frame, and what they drive
    page: function (name) { return $('.o-page[data-page="' + name + '"] .o-pgscroll'); },
    toys: TOYS,
    // toy id -> [level, override], as a friend drives them (the Me row)
    setDrive: function (map) { S.drive = map || {}; },
    // what each connected toy is sent now (its strongest motor)
    outputs: function () {
      var o = {};
      TOYS.forEach(function (t) { if (t.on && motors[t.id]) o[t.id] = Math.max.apply(null, motors[t.id].map(function (m) { return m.out; })); });
      return o;
    },
    setStrength: setStrength, setFeature: setFeature,
    // The visitor as the contact: a depth 0..1, held for a moment after the last call.
    setManual: function (v) { S.manual = v === null ? null : clamp(+v, 0, 1); S.manualUntil = S.t + 1.2; },
    onTick: function (fn) { listeners.push(fn); },
    // a toy's card on the Toys page, opened (and one of its chains)
    open: function (toyId, chain) {
      openCard(toyId);
      var toyEl = cardOf(toyId);
      if (chain !== undefined) { var b = $('.o-chain[data-chain="0.' + chain + '"]', toyEl); b.classList.add('open'); $('.o-fold[data-fold="0.' + chain + '"] .car', toyEl).textContent = '▾'; syncMerge(toyEl); scrollToCard(toyId); }
    },
    // Arm shocks for the Shockers page's hub card: the same switch, words and question
    arm: arm,
    setHue: setHue, setMode: setMode,
    // Run the engine ahead without the clock (screenshots, reduced motion).
    advance: function (seconds) { for (var i = 0; i < seconds / ROUTER_DT; i++) tick(ROUTER_DT); paint(); }
  };

  // #demo=toy | chain | toys | tools | settings | stats : open the window in a
  // state (#demo=suits is demo-suits.js's: both suits on, their page open).
  var want = (location.hash.match(/demo=([a-z]+)/) || [])[1];
  if (want === 'toy' || want === 'chain') window.OGPDemo.open('lush', want === 'chain' ? 0 : undefined);
  if (want === 'toys') go('Toys');
  if (want === 'tools') { go('Toys'); $('.o-tune .o-toolbar').click(); $('.js-graphsw').click(); }
  if (want === 'settings') go('Settings');
  if (want === 'stats') go('Statistics');
  var wantMode = (location.hash.match(/mode=(midnight|neon)/) || [])[1], wantHue = (location.hash.match(/hue=(\d+)/) || [])[1];
  if (wantMode) setMode(wantMode);
  if (wantHue) setHue(+wantHue);

  window.OGPDemo.advance(6);                     // the meters and graphs start full
  if (!reduce) requestAnimationFrame(frameFn);
})();
