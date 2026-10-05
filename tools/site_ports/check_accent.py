"""Check the website's colour port (docs/assets/ogp-accent.js) against the
app's src/accent_shift.py.

Runs the real `shift_hex` / `hue_of` / `delta_for` over every 518 token and
a wide set of other colours and turns, writes the results to
`accent_reference.json`, then runs `node tools/site_ports/check_accent.js`,
which must reproduce every colour string exactly.

    venv\\Scripts\\python.exe tools\\site_ports\\check_accent.py
    venv\\Scripts\\python.exe tools\\site_ports\\check_accent.py --quick --out D:\\tmp\\ports

The reference is never written into the repo: it goes to --out, by default
a folder in the system temp dir. The home directory is pointed at a scratch
folder inside --out before any app module is imported, like
gen_reference.py does, so nothing here can touch the real profile.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__ in src/ or tools/

import argparse                   # noqa: E402
import json                       # noqa: E402
import math                       # noqa: E402
import os                         # noqa: E402
import random                     # noqa: E402
import subprocess                 # noqa: E402
import tempfile                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_OUT = os.path.join(tempfile.gettempdir(), "ogp-site-ports")
REFERENCE_NAME = "accent_reference.json"


def is_inside(path, parent):
    path = os.path.normcase(os.path.realpath(path))
    parent = os.path.normcase(os.path.realpath(parent))
    return path == parent or path.startswith(parent + os.sep)


def redirect_home(out_dir):
    home = os.path.join(out_dir, "_fakehome")
    os.makedirs(home, exist_ok=True)
    os.environ["USERPROFILE"] = home
    os.environ["HOME"] = home
    os.environ["APPDATA"] = os.path.join(home, "AppData", "Roaming")
    os.environ["LOCALAPPDATA"] = os.path.join(home, "AppData", "Local")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(home, ".config")   # Linux
    os.environ["OGP_UI_ACCENT"] = "default"
    return home


def build_reference(quick):
    src = os.path.join(REPO, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import accent_shift
    import theme_tokens

    # --- the core set: every NEON / MIDNIGHT token + PALETTE["green"]
    required_hexes = []
    for name, table in (("NEON", theme_tokens.NEON),
                        ("MIDNIGHT", theme_tokens.MIDNIGHT)):
        for key, value in table.items():
            required_hexes.append(("%s.%s" % (name, key), value))
    for i, value in enumerate(theme_tokens.PALETTE["green"]):
        required_hexes.append(("PALETTE.green[%d]" % i, value))
    required_deltas = list(range(0, 360, 37 if quick else 7))

    required = []
    for label, hx in required_hexes:
        for d in required_deltas:
            required.append([label, hx, d, accent_shift.shift_hex(hx, d)])

    # --- the extended set: the whole palette, the retired hexes, primaries,
    #     greys, upper-case and bare hexes; whole degrees plus awkward
    #     fractional / negative / >360 turns
    extra_hexes = []
    for _hue, tones in theme_tokens.PALETTE.items():
        extra_hexes.extend(tones)
    extra_hexes.extend(theme_tokens.RETIRED.keys())
    extra_hexes.extend([
        "#000000", "#ffffff", "#808080", "#010101", "#fefefe",
        "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#00ffff", "#ff00ff",
        "#31F272", "31f272", "#7f7f80", "#123456", "#fedcba", "#0a0c0a",
    ])
    extra_hexes.extend(h for _l, h in required_hexes)
    seen, uniq = set(), []
    for h in extra_hexes:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    odd_turns = [0.5, 33.3, 359.999, 1e-9, -45, -0.25, 720.25, 180.0,
                 123.456789]
    extra_deltas = (list(range(0, 360, 61)) if quick
                    else list(range(0, 360))) + odd_turns
    extended = []
    for hx in uniq:
        for d in extra_deltas:
            extended.append([hx, d, accent_shift.shift_hex(hx, d)])

    # random colours x random turns
    rng = random.Random(518)
    rand = []
    for _ in range(600 if quick else 20000):
        hx = "#{:06x}".format(rng.randrange(0x1000000))
        d = rng.choice([rng.randrange(1, 360), rng.uniform(-720.0, 720.0)])
        rand.append([hx, d, accent_shift.shift_hex(hx, d)])

    # --- hue_of / delta_for / to_oklch as doubles
    hues = [[hx, accent_shift.hue_of(hx)] for hx in uniq]
    oklch = [[hx, list(accent_shift.to_oklch(hx))] for hx in uniq]
    accent = theme_tokens.NEON["accent"]
    targets = [None, 0, 29.23, 90, 145.0, 200.5, 264.05, 300, 359.9, 400, -30]
    for _hue, tones in theme_tokens.PALETTE.items():
        targets.append(accent_shift.hue_of(tones[0]))
    deltas = []
    for ref_hex in (accent, theme_tokens.MIDNIGHT["accent"]):
        for t in targets:
            deltas.append([t, ref_hex, accent_shift.delta_for(t, ref_hex)])

    # the picker's real use: turn every token of a mode to each palette hue
    turned = []
    for mode_name, table in (("NEON", theme_tokens.NEON),
                             ("MIDNIGHT", theme_tokens.MIDNIGHT)):
        for hue_name, tones in theme_tokens.PALETTE.items():
            d = accent_shift.delta_for(accent_shift.hue_of(tones[0]),
                                       table["accent"])
            turned.append([mode_name, hue_name, d,
                           accent_shift.shift_tokens(table, d)])

    # --- the two pieces the port reimplements bit for bit
    n_vec = 600 if quick else 5000
    hyp = []
    for _ in range(n_vec):
        a = rng.uniform(-0.5, 0.5) * rng.choice([1.0, 1e-3, 1e-9, 1e6])
        b = rng.uniform(-0.5, 0.5) * rng.choice([1.0, 1e-3, 1e-9, 1e6])
        hyp.append([a, b, math.hypot(a, b)])
    rnd = []
    for _ in range(n_vec):
        x = rng.choice([rng.uniform(0.0, 1.0), rng.uniform(0.0, 360.0),
                        rng.randrange(0, 360 * 32) / 32.0,
                        rng.randrange(0, 64) / 64.0])
        rnd.append([x, round(x, 4), round(x, 3)])

    return {
        "quick": bool(quick),
        "tokens": {"NEON": theme_tokens.NEON,
                   "MIDNIGHT": theme_tokens.MIDNIGHT,
                   "PALETTE": {k: list(v)
                               for k, v in theme_tokens.PALETTE.items()}},
        "required": required,
        "required_hex_count": len(required_hexes),
        "required_delta_count": len(required_deltas),
        "extended": extended,
        "random": rand,
        "hues": hues,
        "oklch": oklch,
        "deltas": deltas,
        "turned": turned,
        "hypot": hyp,
        "round": rnd,
    }


def emit(text):
    """print() that survives a console that cannot show a character, and
    a windowless interpreter that has no stdout at all."""
    out = sys.stdout
    if out is None:
        return
    try:
        out.write(text)
    except UnicodeEncodeError:
        out.write(text.encode("ascii", "backslashreplace").decode("ascii"))
    out.flush()


def run_node(script, args):
    """Run a node script without popping a console window; relay its
    output. Returns the exit code (127 when node is missing)."""
    flags = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["node", script] + list(args), cwd=REPO,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, creationflags=flags)
    except FileNotFoundError:
        emit("node is not on PATH - reference written, check not run\n")
        return 127
    emit(proc.stdout.decode("utf-8", "replace"))
    return proc.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="folder for accent_reference.json (default: %(default)s)")
    ap.add_argument("--quick", action="store_true",
                    help="the small set the test suite uses")
    ap.add_argument("--no-check", action="store_true",
                    help="only write the reference, do not run check_accent.js")
    ap.add_argument("--js", default=None,
                    help="check this ogp-accent.js instead of docs/assets/")
    args = ap.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    js = os.path.abspath(args.js) if args.js else None
    if is_inside(out_dir, REPO):
        print("refusing to write the reference inside the repo: " + out_dir)
        return 2
    os.chdir(REPO)
    os.makedirs(out_dir, exist_ok=True)
    redirect_home(out_dir)

    ref = build_reference(args.quick)
    path = os.path.join(out_dir, REFERENCE_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ref, f, allow_nan=False)
    changed = sum(1 for r in ref["required"] if r[1] != r[3])
    print("python: %d token hexes x %d turns = %d cases (%d change the "
          "colour); extended %d, random %d" % (
              ref["required_hex_count"], ref["required_delta_count"],
              len(ref["required"]), changed, len(ref["extended"]),
              len(ref["random"])))
    print("wrote " + path)
    emit("")
    if args.no_check:
        return 0
    node_args = [path]
    if js:
        node_args += ["--js", js]
    return run_node(os.path.join(HERE, "check_accent.js"), node_args)


if __name__ == "__main__":
    sys.exit(main())
