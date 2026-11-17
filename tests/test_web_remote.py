"""The web remote's page must speak the Friends protocol the way an OGP
friend does.

`docs/assets/remote-proto.js` builds what docs/remote.html sends (cmd, shk,
stp, pw, pst, ph) and reads what it gets (st, pnl, pbd, pv); it also plays
the auto modes for the toy card's graph. These tests run it in node and
hold it against the Python: what the page builds must read back through
remote_protocol / remote_params exactly as the app's own messages do, and
what the app sends must read the same on both sides. Skipped when `node`
is not on PATH.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import friend_patterns
import remote_params as rp
import remote_protocol as proto

REPO = Path(__file__).resolve().parent.parent
PROTO_JS = REPO / "docs" / "assets" / "remote-proto.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")


def js(expr: str):
    """Evaluate `expr` with the page's protocol module as P; its JSON."""
    script = (f"const P = require({json.dumps(str(PROTO_JS))});\n"
              f"process.stdout.write(JSON.stringify({expr}));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True,
                         encoding="utf-8", cwd=str(PROTO_JS.parent))
    return json.loads(out.stdout)


def j(value) -> str:
    return json.dumps(value)


def test_a_cmd_reads_back_like_the_apps():
    args = ({proto.ALL_TOYS: 0.5, "Edge": 0.25, "Lush": 0.0}, [123, 0.8], ["Edge"],
            {"Edge": ["sine", 2.0, 0.2, 0.8], proto.ALL_TOYS: ["osc", 300, -1, 2]},
            {"0": ["shock", 0.5], "5": ["shock", 1.0], "1": ["nope", 1.0]}, 4)
    page = js(f"P.makeCmd({', '.join(j(a) for a in args)})")
    app = proto.make_cmd(args[0], tuple(args[1]), args[2],
                         {k: tuple(v) for k, v in args[3].items()},
                         {0: ("shock", 0.5)}, syn=4)
    for msg in (page, app):
        msg.pop("ts", None)
    assert proto.read_cmd(page) == proto.read_cmd(app)
    assert proto.read_cmd_more(page) == proto.read_cmd_more(app)
    assert proto.read_syn(page) == proto.read_syn(app) == 4
    assert proto.drives(page) and js("P.drives(P.makeCmd({}, null, [], {}, {}, null))") is False


def test_shocks_and_stops_read_back_like_the_apps():
    page = js('P.makeShock("abcd", [2, 0, 9, 0], 0.333333, 1.5, "vibrate", "vibrate", 0.7, 20000)')
    app = proto.make_shock("abcd", [2, 0, 9, 0], 0.333333, 1.5, "vibrate", "vibrate", 0.7, 20000)
    assert proto.read_shock(page) == proto.read_shock(app)
    plain = js('P.makeShock("x1", [1], 1, 0, "shock", "", 0, 0)')
    assert proto.read_shock(plain) == proto.read_shock(proto.make_shock("x1", [1], 1, 0))
    assert proto.read_stop(js('P.makeStop("s9", [3, 1, 7])')) == \
        proto.read_stop(proto.make_stop("s9", [3, 1, 7]))
    assert js("P.shockValues(0.5, 0.5, 40, 2000)") == list(proto.shock_values(0.5, 0.5, 40, 2000))


def test_the_avatar_messages_are_the_apps():
    assert js('P.makeWatch("v1", true, 7)') == rp.make_watch("v1", True, 7)
    assert js('P.makeWatch("", false, 0)') == rp.make_watch("", False, 0)
    assert js("P.WATCH_OFF") == rp.WATCH_OFF
    assert js('P.makeSet(5, 0.12345, "c1")') == rp.make_set(5, 0.12345, control="c1")
    assert js('P.makeSet(6, true, "", "Hoodie")') == rp.make_set(6, True, param="Hoodie")
    assert js('P.makeSet(7, 3, "c2")') == rp.make_set(7, 3, control="c2")
    assert js('P.makeHolds(["b", "a"])') == rp.make_holds(["b", "a"])


def test_their_status_reads_the_same():
    st = proto.make_status([("Edge", 2), ("Lush", 1)], {"Edge": 0.43, "Lush": 1.0}, 0.8, False,
                           True, True, True, ["Collar", "Thigh"], True, 40, 2000, 60, 5.0,
                           prm=rp.make_prm("abc123", True, False, "d04401a1"),
                           batteries={"Edge": 0.55}, shocker_caps=[(40, 60, 2000), (10, 60, 500)])
    page = js(f"P.readStatus({j(st)})")
    app = proto.read_status(st)
    assert [tuple(t) for t in page["toys"]] == app["toys"]
    assert page["outputs"] == app["outputs"] and page["strength"] == app["strength"]
    assert (page["off"], page["paused"], page["allowToys"], page["allowShock"], page["armed"]) == \
        (app["off"], app["paused"], app["allow_toys"], app["allow_shock"], app["armed"])
    assert page["shockers"] == app["shockers"]
    assert (page["maxIntensity"], page["maxPulseMs"], page["maxVibrate"], page["maxHoldS"]) == \
        (app["max_intensity"], app["max_pulse_ms"], app["max_vibrate"], app["max_hold_s"])
    assert [tuple(c) for c in page["shockerCaps"]] == app["shocker_caps"]
    assert page["batteries"] == app["batteries"]
    assert page["prm"] == rp.read_prm(app["prm"])
    for slot in (0, 1):
        assert js(f"P.shockerCaps(P.readStatus({j(st)}), {slot})") == \
            list(proto.shocker_caps(app, slot))


def test_not_in_their_instance_reads_the_same():
    """Only friends in their instance, and you aren't in it: paused, and
    ``nh`` says why -- a copy from before it just shows paused."""
    st = proto.make_status([("Edge", 1)], {}, 1.0, False, True, True, False, [], False,
                           0, 0, not_here=True)
    page = js(f"P.readStatus({j(st)})")
    app = proto.read_status(st)
    assert (page["paused"], page["notHere"]) == (app["paused"], app["not_here"]) == (True, True)
    plain = proto.make_status([], {}, 1.0, False, True, True, False, [], False, 0, 0)
    assert "nh" not in plain
    assert js(f"P.readStatus({j(plain)}).notHere") is False
    assert proto.read_status(plain)["not_here"] is False


def test_what_they_may_send_reads_the_same():
    """What each of their shockers lets through (``sop``) reads the same in
    the page as in the app -- and a copy from before it allows everything. A
    test build's per-friend share bits (``fw``, ``nc``) are read by neither."""
    st = proto.make_status([], {}, 1.0, False, False, True, True, ["Collar", "Thigh"], True,
                           25, 800, 25, 5.0, shocker_caps=[(25, 25, 800), (10, 25, 500)],
                           shocker_ops=[proto.ops_mask(["shock", "beep"]), 2])
    st = {**st, "fw": 1, "nc": 1}
    page = js(f"P.readStatus({j(st)})")
    app = proto.read_status(st)
    assert page["shockerOps"] == app["shocker_ops"] == [["shock", "beep"], ["vibrate"]]
    assert "warnFirst" not in page and "holdsOk" not in page
    assert "warn_first" not in app and "holds_ok" not in app
    for slot in (0, 1, 3):
        assert js(f"P.shockerOps(P.readStatus({j(st)}), {slot})") == proto.shocker_ops(app, slot)
    assert js("P.OP_BITS") == proto.OP_BITS
    old = proto.make_status([], {}, 1.0, False, False, True, True, ["Collar"], False, 40, 2000)
    page = js(f"P.readStatus({j(old)})")
    assert page["shockerOps"] == []
    assert js(f"P.shockerOps(P.readStatus({j(old)}), 0)") == proto.shocker_ops(proto.read_status(old), 0)
    for bad in ([7], [7, "x"], [True, 7]):
        msg = {**old, "shk": ["a", "b"], "sop": bad}
        assert js(f"P.readStatus({j(msg)}).shockerOps") == proto.read_status(msg)["shocker_ops"]


def test_a_greyed_button_says_why_the_same():
    """The line a greyed button says (Blise's call: the sender sees why) is
    the app's, word for word -- their switch, arming, or (an older OGP's)
    anything else."""
    cases = []
    for off in ([], ["shock"], ["vibrate"], ["vibrate", "beep"], ["beep"]):
        for allowed in (["shock", "vibrate", "beep"], ["vibrate"], []):
            for armed in (True, False):
                for fw in (True, False):        # a test build's share bit: ignored
                    st = proto.make_status(
                        [], {}, 1.0, False, False, True, True, ["Collar"], armed, 40, 2000,
                        shocker_ops=[proto.ops_mask(allowed)],
                        shocker_off=[proto.ops_mask(off)])
                    cases.append({**st, "fw": 1} if fw else st)
    page = js("[" + ",".join(f"[\"shock\", \"vibrate\", \"beep\"].map((o) => "
                             f"P.shockerWhy(P.readStatus({j(st)}), 0, o))" for st in cases) + "]")
    for st, got in zip(cases, page):
        app = proto.read_status(st)
        assert got == [proto.shocker_why(app, 0, op) for op in proto.OPS], st
    assert "Shock is switched off on their side" in {w for row in page for w in row}
    warn = js("[" + ",".join(f"P.canWarn(P.readStatus({j(st)}), 0)" for st in cases) + "]")
    assert warn == [proto.can_warn(proto.read_status(st), 0) for st in cases]
    assert False in warn and True in warn
    assert js("P.WARN_OFF_WHY") == proto.WARN_OFF_WHY


def test_the_shared_panel_reads_the_same():
    msg = proto.make_panel(9, {proto.ALL_TOYS: 0.3, "Edge": 0.7}, {"Edge"},
                           {"Lush": ("heart", 1.0, 0.1, 0.9)})
    seq, levels, override, patterns = proto.read_panel(msg)
    page = js(f"P.readPanel({j(msg)})")
    assert page[0] == seq and page[1] == levels and set(page[2]) == override
    assert {k: tuple(v) for k, v in page[3].items()} == patterns



def test_how_the_owner_has_sync_with_others_reads_the_same():
    """Their call (Blise's, 2026-11-17): one bit in their ``st``; an OGP
    from before says nothing, which is synced."""
    st = proto.make_status([("Edge", 1)], {}, 1.0, False, False, True, False, [], False, 40, 2000)
    for msg in (st, proto.mark_separate(st, True), proto.mark_separate(st, False),
                {**st, "sep": 0}, {**st, "sep": "x"}):
        assert js(f"P.readSeparate({j(msg)})") == proto.read_separate(msg)
    assert proto.read_separate(proto.mark_separate(st, True)) is True
    assert proto.read_separate(st) is False


def test_a_board_and_its_values_read_the_same():
    board = rp.with_version({
        "t": "pbd", "name": "Fox", "a": "d04401a1",
        "cats": [{"id": "c1", "name": "Clothes", "color": "pink", "locked": False},
                 {"id": "c2", "name": "Secret", "color": "nope", "locked": True}],
        "ctl": [{"id": "a", "param": "Hoodie", "ptype": "Bool", "kind": "toggle", "label": "Hoodie",
                 "cat": "c1", "invert": True},
                {"id": "b", "param": "Outfit", "ptype": "Int", "kind": "toggle", "label": "Outfit 2",
                 "cat": "c1", "on": 2, "off": 0},
                {"id": "c", "param": "Bright", "ptype": "Float", "kind": "slider", "label": "",
                 "cat": "c2", "min": 0, "max": 1},
                {"id": "d", "param": "Bad", "ptype": "Float", "kind": "toggle", "label": "x",
                 "cat": "c1"}],
        "keys": ["Hoodie", "Outfit", "Bright", "Extra"], "nb": 3,
        "all": [["Extra", "Int"], ["Odd", "Text"]]})
    app = rp.read_board(board)
    page = js(f"P.readBoard({j(board)})")
    assert page["ver"] == app["ver"] and page["name"] == app["name"] and page["avatar"] == app["avatar"]
    assert page["categories"] == app["categories"]
    assert page["controls"] == app["controls"]
    assert page["keys"] == app["keys"]
    assert [tuple(a) for a in page["all"]] == app["all"]
    for msg in rp.make_values(app["ver"], 1, [True, 2, 0.4567, 7]):
        assert js(f"P.readValues({j(msg)}, P.readBoard({j(board)}))") == rp.read_values(msg, app)
    import param_board as pb
    for c in app["controls"]:
        for v in (None, 0, 1, 2, True, False):
            assert js(f"P.showsOn({j(c)}, {j(v)})") is pb.shows_on(c, v), (c["id"], v)


def test_the_height_box_reads_and_sends_the_same():
    """Their Height box (avatar_height.py): the board's ``ht``, the height
    on ``pv``, the ``pht`` the page sends, the log slider and its numbers --
    the page's port is the app's, number for number."""
    import avatar_height as ah
    box = rp.make_height_box(0.3, 12.0, locked=True, forbidden=False)
    board = rp.with_version({"t": "pbd", "name": "Fox", "cats": [], "ctl": [], "keys": [],
                             "nb": 0, "ht": box})
    assert js(f"P.readBoard({j(board)}).height") == rp.read_board(board)["height"]
    assert js(f"P.readBoard({j(rp.with_version({'t': 'pbd', 'cats': []}))}).height") is None
    for raw in (None, {"lo": 5, "hi": 1}, {"lo": "x", "hi": 2},
                {"lo": 0.001, "hi": 900, "no": 1}, {"lo": 0.2, "hi": 5, "lk": 1}):
        assert js(f"P.readHeightBox({j(raw)})") == rp.read_height_box(raw), raw
    for msg in ({"t": "pv", "h": 1.62}, {"t": "pv"}, {"t": "pv", "h": -1},
                {"t": "pv", "h": 500}, {"t": "pv", "h": "x"}):
        assert js(f"P.readHeight({j(msg)})") == rp.read_height(msg), msg
    for args in ((5, "grow", 1.8), (6, "now", 0.4567), (7, "reset", None)):
        page = js(f"P.makeHeightSet({args[0]}, {j(args[1])}, {j(args[2])})")
        assert page == rp.make_height_set(*args)
        assert rp.read_height_set(page) == rp.read_height_set(rp.make_height_set(*args))
    assert js("P.HEIGHT_MODES") == list(ah.MODES)
    for lo, hi in ((0.2, 5.0), (0.1, 100.0)):
        for x in (0, 0.25, 0.5, 0.731, 1):
            assert abs(js(f"P.sliderToHeight({x}, {lo}, {hi})") - ah.from_slider(x, lo, hi)) < 1e-9
        for h in (0.05, 0.2, 1.62, 4.99, 300):
            assert abs(js(f"P.heightToSlider({h}, {lo}, {hi})") - ah.to_slider(h, lo, hi)) < 1e-9
    assert js("P.heightToSlider(null, 0.2, 5)") is None
    for h in (None, 0.1, 1.625, 1.6249, 9.995, 10.0, 42.25, 99.95):
        assert js(f"P.fmtHeight({j(h)})") == ah.fmt(h), h


def test_the_auto_modes_play_the_same_shapes():
    cases = [(w, phase, t, period) for w in friend_patterns.WAVES
             for phase in (0.0, 0.1, 0.37, 0.5, 0.93, 0.95, 1.21, 2.75)
             for t, period in ((0.3, 2.0), (4.7, 1.5), (61.0, 30.0))]
    page = js("[" + ",".join(f"P.shape({j(w)}, {p}, {t}, {d})" for w, p, t, d in cases) + "]")
    for (w, p, t, d), got in zip(cases, page):
        assert abs(got - friend_patterns.shape(w, p, t, d)) < 1e-9, (w, p, t, d)
    raw = [("sine", 0.1, 0.2, 0.8), ("osc", 500, 1.3, -0.4), ("nope", 1, 0, 1), ("saw", 2, 0.9, 0.1)]
    assert js("[" + ",".join(f"P.cleanPattern({', '.join(j(x) for x in r)})" for r in raw) + "]") == \
        [list(friend_patterns.clean(*r)) if friend_patterns.clean(*r) else None for r in raw]


def test_the_speed_slider_maps_like_the_cards():
    from ui.views.card_parts import fmt_period, period_to_slider, slider_to_period
    for period in (0.25, 0.4, 1.0, 2.0, 7.5, 30.0, 120.0):
        assert js(f"P.periodToSlider({period})") == period_to_slider(period)
        assert js(f"P.fmtPeriod({period})") == fmt_period(period)
    for x in (0, 1, 250, 500, 999, 1000):
        assert abs(js(f"P.sliderToPeriod({x})") - slider_to_period(x)) < 1e-9


@pytest.mark.parametrize("nick", ["Blise", "Mika.Chan ✨", "a(b) c's"])
def test_the_page_reads_the_copied_link_even_joined_with_its_note(nick):
    """What Copy web remote link puts on the clipboard, pasted into a
    browser's address bar: the browser joins the two lines -- with nothing
    or a space between them -- and percent-encodes the spaces. The page
    takes the ID, the code and the nickname, never the note."""
    import friend_links
    pid, code = "ab" * 32, "0123456789abcdef"
    msg = friend_links.remote_message(pid, code, nick)
    want = {"id": pid, "code": code, "nick": proto.clean_nick(nick)}
    for glue in ("", " "):
        pasted = glue.join(msg.split("\n"))
        frag = "#" + pasted.split("#", 1)[1].replace(" ", "%20")
        assert js(f"P.parseLink({j(frag)})") == want
    assert js(f"P.parseLink({j('#' + pid + '.' + code[:-1] + '.x')})") is None


def test_the_shocker_buttons_layouts_are_the_apps():
    """The web remote's "Shocker buttons" switch and OpenShock's card
    (remote-openshock.js) on the app's numbers: the layouts and the default,
    OpenShock's controls, and the maths from a dial or the Live pad to what
    a message carries."""
    import shocker_layout as layout
    assert js("P.LAYOUTS") == list(layout.LAYOUTS) and js("P.LAYOUT_DEFAULT") == layout.DEFAULT
    for v in (None, "", "pishock", "openshock", "OpenShock", 3):
        assert js(f"P.cleanLayout({j(v)})") == layout.clean(v), v
    assert js("P.OS") == {
        "INTENSITY_DEFAULT": layout.INTENSITY_DEFAULT, "DURATION_DEFAULT_MS": layout.DURATION_DEFAULT_MS,
        "DURATION_MIN_MS": layout.DURATION_MIN_MS, "DURATION_STEP_MS": layout.DURATION_STEP_MS,
        "OPS": list(layout.OS_OPS), "OP_NAMES": layout.OP_NAMES,
        "LIVE_DEFAULT_OP": layout.LIVE_DEFAULT_OP, "LIVE_STEP": layout.LIVE_STEP}
    assert js("['HOLDS_OFF_WHY' in P, 'FORCED_WARN_MS' in P]") == [False, False]   # the share's
    caps = (1, 2, 25, 40, 60, 100)
    cases = [(v, c) for c in caps for v in range(1, c + 1, max(1, c // 9))]
    page = js("[" + ",".join(f"P.toFraction({v}, {c})" for v, c in cases) + "]")
    assert page == [layout.to_fraction(v, c) for v, c in cases]
    lengths = [(ms, top) for top in (100, 300, 800, 5000, 15000) for ms in (100, 300, 450, 1000, 9999)]
    page = js("[" + ",".join(f"[P.lengthFraction({m}, {t}), P.durationRange({t}), "
                             f"P.snapDuration({m}, {t})]" for m, t in lengths) + "]")
    for (ms, top), (frac, rng, snap) in zip(lengths, page):
        assert frac == pytest.approx(layout.length_fraction(ms, top), abs=1e-12)
        assert tuple(rng) == layout.duration_range(top) and snap == layout.snap_duration(ms, top)
    pads = [(y, c) for c in (1, 25, 40, 60, 100) for y in (-1, 0, 0.1, 0.25, 0.333, 0.5, 0.98, 1, 2)]
    page = js("[" + ",".join(f"P.liveStrength({y}, {c})" for y, c in pads) + "]")
    assert page == [layout.live_strength(y, c) for y, c in pads]


def test_openshocks_card_on_the_page_is_the_apps():
    """remote-openshock.js is the app's openshock_card.py, 1-to-1: the same
    calls the panel makes of either card, and the same words on hover."""
    import re

    from ui.views import openshock_card as oc
    from ui.views.friends_shockers import LAYOUT_TITLE
    page = (REPO / "docs" / "assets" / "remote-openshock.js").read_text("utf-8")
    pishock = (REPO / "docs" / "assets" / "remote-shockers.js").read_text("utf-8")
    remote = (REPO / "docs" / "assets" / "remote.js").read_text("utf-8")
    for method in ("setCaps", "setRules", "setBlocked", "stop", "release", "settings", "restore"):
        assert re.search(rf"^  {method}\(", page, re.M), method
        assert re.search(rf"^  {method}\(", pishock, re.M), method
    joined = re.sub(r'"\s*\+\s*"', "", page)        # long strings are split over lines
    for text in [*oc._TIPS.values(), *oc._LIVE_TIPS.values(), oc._RUNNING_TIP, oc._LIVE_TIP]:
        assert text in joined, text
    assert LAYOUT_TITLE in remote and "new ShockParty(" in remote and "{ Card }" in remote
