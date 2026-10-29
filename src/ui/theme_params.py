"""The Avatar Remote page's stylesheet rules (ui/views/params.py, the board
pieces in param_cards.py -- also a friend's board on the Friends page),
built with the rest of the sheet by theme.build_qss.

A category wears its colour like a toy does: a filled header bar and a
frame (Neon: the reference apps' bar pair where the hue has one -- the
orange category takes the yellow pair, which is an orange -- else the
hue's mid tone; Midnight: tint and mid). Inside, plain cards with a border
in the mid tone; a toggle is filled with the hue when ON, outlined when
OFF."""

from typing import Dict

import param_board as pb
from ui.theme import NEON_CAT_BARS, PALETTE, SUITS_HUE, normalize_mode

_BAR_OF = {"amber": "yellow", "yellow": None, "pink": None}


def _bar(hue: str, neon: bool):
    """(bar fill, frame border, bar text key or colour)."""
    vib, mid, tint = PALETTE[hue]
    if not neon:
        return tint, mid, vib
    pair = _BAR_OF.get(hue, hue)
    if pair is not None and pair in NEON_CAT_BARS:
        bar, frame = NEON_CAT_BARS[pair]
        return bar, frame, None
    return mid, mid, None


def params_qss(mode_name: str, v: Dict[str, str]) -> str:
    neon = normalize_mode(mode_name) == "neon"
    out = [
        f'QFrame#paramCat {{ background-color: transparent; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_card"]}px; }}\n',
        f'QWidget#paramCatHead {{ background-color: {v["catbar"]}; border-radius: {v["r_btn"]}px; }}\n',
        f'QLineEdit#paramCatName {{ background-color: transparent; border: none;'
        f' color: {v["catbar_text"]}; font-weight: 700; font-size: 14px; padding: 2px 4px; }}\n',
        f'QLineEdit#paramCatName:focus {{ background-color: {v["well"]};'
        f' border-radius: 6px; }}\n',
        f'QLabel#paramCatTitle {{ color: {v["catbar_text"]}; font-weight: 700; font-size: 14px;'
        ' padding: 2px 4px; }\n',
        'QToolButton#paramCatLock { border: none; background: transparent; font-size: 13px;'
        ' padding: 0px 4px; }\n',
        f'QLabel#paramCatGrip, QLabel#paramGrip {{ color: {v["muted"]}; font-size: 14px; }}\n',
        f'QLabel#paramCatHint {{ color: {v["dim"]}; border: 1px solid {v["dim"]};'
        f' border-radius: {v["r_btn"]}px; padding: 10px; }}\n',
        f'QFrame#paramCard {{ background-color: {v["well"]}; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_btn"]}px; }}\n',
        f'QLabel#paramLabel {{ color: {v["txt"]}; font-weight: 600; }}\n',
        f'QLabel#paramValue {{ color: {v["muted"]}; font-size: 11px; }}\n',
        f'QLabel#paramMark {{ color: {v["warn"]}; font-size: 13px; font-weight: 700; }}\n',
        f'QToolButton#paramMenu {{ border: none; background: transparent; color: {v["muted"]};'
        ' font-size: 16px; padding: 0px 4px; }\n',
        f'QToolButton#paramMenu:hover {{ color: {v["txt"]}; }}\n',
        f'QPushButton[role="paramSwitch"], QPushButton[role="paramHold"] {{'
        f' background-color: transparent; color: {v["muted"]}; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_btn"]}px; font-weight: 700; padding: 2px 8px; }}\n',
        f'QPushButton[role="paramSwitch"]:disabled, QPushButton[role="paramHold"]:disabled {{'
        f' color: {v["dim"]}; border-color: {v["dim"]}; background-color: transparent; }}\n',
        # the Avatar Remote page's own bits
        f'QPushButton[role="yolo"] {{ background-color: transparent; color: {v["warn"]};'
        f' border: 1px solid {v["warn_mid"]}; border-radius: {v["r_btn"]}px; padding: 3px 12px;'
        ' font-weight: 700; }\n',
        f'QPushButton[role="yolo"]:hover {{ background-color: {v["warn_tint"]}; }}\n',
        (f'QPushButton[role="yolo"]:checked {{ background-color: {v["warn"]}; color: {v["ink"]};'
         f' border-color: {v["warn"]}; }}\n') if neon else
        (f'QPushButton[role="yolo"]:checked {{ background-color: {v["warn_tint"]};'
         f' color: {v["warn"]}; border-color: {v["warn"]}; }}\n'),
        f'QLineEdit#paramAvatarName {{ font-size: 20px; font-weight: 700; color: {v["txt"]};'
        f' background-color: transparent; border: 1px solid transparent;'
        f' border-radius: {v["r_btn"]}px; padding: 2px 6px; }}\n',
        f'QLineEdit#paramAvatarName:hover {{ border-color: {v["line"]}; }}\n',
        f'QLineEdit#paramAvatarName:focus {{ border-color: {v["accent"]};'
        f' background-color: {v["well"]}; }}\n',
        f'QLabel#paramAvatarId {{ color: {v["dim"]}; font-size: 11px; padding-left: 8px; }}\n',
        f'QTreeWidget#paramTree {{ background-color: {v["well"]}; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_btn"]}px; alternate-background-color: {v["card"]}; }}\n',
        # the Shockers page's cards (pishock_cards.py): a name edited in
        # place, a limit's value in full, and the zones shockers are dropped on
        f'QLineEdit#cardName {{ background-color: transparent; border: 1px solid transparent;'
        f' color: {v["txt"]}; font-weight: 600; padding: 1px 4px;'
        f' border-radius: {v["r_btn"]}px; }}\n',
        f'QLineEdit#cardName:hover {{ border-color: {v["line"]}; }}\n',
        f'QLineEdit#cardName:focus {{ border-color: {v["accent"]};'
        f' background-color: {v["card"]}; }}\n',
        f'QLabel#cardValue {{ color: {v["txt"]}; font-weight: 700; }}\n',
        f'QLabel#cardHint {{ color: {v["muted"]}; font-size: 11px; }}\n',
        # a shocker that is shocking right now: the shockers' yellow, and a
        # resting one readable on the card's dark well (the dim grey isn't)
        f'QLabel[role="pill"][tone="shock"] {{ background-color: {PALETTE["yellow"][2]};'
        f' color: {PALETTE["yellow"][0]}; border-color: {PALETTE["yellow"][1]}; }}\n',
        f'QFrame#paramCard QLabel[role="pill"][tone="idle"] {{ color: {v["muted"]}; }}\n',
        f'QFrame#dropZone {{ background-color: transparent; border: 1px solid {v["dim"]};'
        f' border-radius: {v["r_btn"]}px; }}\n',
        f'QPushButton#dropAdd {{ background-color: transparent; border: none;'
        f' color: {v["muted"]}; padding: 3px 6px; text-align: left; }}\n',
        f'QPushButton#dropAdd:hover {{ color: {v["txt"]}; }}\n',
        f'QLabel#dropHint {{ color: {v["dim"]}; }}\n',
        # a shocker card held over a drop zone: it lights up in the shockers' hue
        f'QFrame#dropZone[hover="true"] {{ border-color: {PALETTE["yellow"][0]};'
        f' background-color: {PALETTE["yellow"][2]}; }}\n',
        # a friend's board: the section and its micro title in the accent
        f'QFrame#friendSection[hue="accent"] {{ border-color: {v["ok_mid"]}; }}\n',
        f'QLabel#friendsMicro[hue="accent"] {{ color: {v["accent"]}; }}\n',
        f'QCheckBox[hue="accent"]::indicator {{ border-color: {v["ok_mid"]}; }}\n',
        f'QCheckBox[hue="accent"]::indicator:checked {{ background-color: {v["accent"]};'
        f' border-color: {v["accent"]}; }}\n',
    ]
    # (and the orange: the Suits page's bHaptics frame and cards)
    for hue in pb.CATEGORY_HUES + (SUITS_HUE,):
        vib, mid, tint = PALETTE[hue]
        bar, frame, bar_text = _bar(hue, neon)
        text = bar_text or v["txt"]
        # ON / held: filled with the hue in Vibrant, the hue on its tint in
        # Darker (which keeps every surface dark)
        on_fill, on_text = (vib, v["ink"]) if neon else (tint, vib)
        out.append(
            f'QFrame#paramCat[hue="{hue}"] {{ border-color: {frame}; }}\n'
            f'QWidget#paramCatHead[hue="{hue}"] {{ background-color: {bar}; }}\n'
            f'QWidget#paramCatHead[hue="{hue}"] QLineEdit#paramCatName,'
            f' QWidget#paramCatHead[hue="{hue}"] QLabel#paramCatTitle {{ color: {text}; }}\n'
            f'QWidget#paramCatHead[hue="{hue}"] QLabel#paramCatGrip,'
            f' QWidget#paramCatHead[hue="{hue}"] QToolButton#paramMenu {{ color: {text}; }}\n'
            f'QLabel#paramCatHint[hue="{hue}"] {{ border-color: {mid}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] {{ border-color: {mid}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] QLabel#paramGrip,'
            f' QFrame#paramCard[hue="{hue}"] QToolButton#paramMenu {{ color: {vib}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] QPushButton[role="paramSwitch"] {{ border-color: {mid}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] QPushButton[role="paramSwitch"]:hover {{'
            f' background-color: {tint}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] QPushButton[role="paramSwitch"]:checked {{'
            f' background-color: {on_fill}; color: {on_text}; border-color: {vib}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] QPushButton[role="paramHold"] {{ color: {vib};'
            f' border-color: {mid}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] QPushButton[role="paramHold"]:hover {{'
            f' background-color: {tint}; }}\n'
            f'QFrame#paramCard[hue="{hue}"] QPushButton[role="paramHold"]:pressed {{'
            f' background-color: {on_fill}; color: {on_text}; border-color: {vib}; }}\n'
            f'QSlider[hue="{hue}"]::sub-page:horizontal {{ background: {vib}; }}\n'
            f'QSlider[hue="{hue}"]::handle:horizontal {{ background: {vib}; }}\n'
            f'QSlider[hue="{hue}"]::handle:horizontal:hover {{ background: {vib}; }}\n'
            f'QSpinBox[hue="{hue}"] {{ border-color: {mid}; }}\n'
        )
    # Look-only (a friend's locked category, or their STOP): greyed out
    # whatever the hue -- after the hue rules, which it must win against.
    out.append(
        # (the state on the label itself: Qt ignores one on an ancestor,
        # and the rule then greyed every label)
        f'QFrame#paramCard QLabel#paramLabel:disabled {{ color: {v["dim"]}; }}\n'
        f'QFrame#paramCard QPushButton[role="paramSwitch"]:checked:disabled {{'
        f' background-color: {v["well"]}; color: {v["dim"]}; border-color: {v["dim"]}; }}\n'
        f'QFrame#paramCard QSpinBox:disabled {{ color: {v["dim"]}; border-color: {v["dim"]}; }}\n'
        f'QFrame#paramCard QSlider::sub-page:horizontal:disabled {{ background: {v["dim"]}; }}\n'
        f'QFrame#paramCard QSlider::handle:horizontal:disabled {{ background: {v["dim"]}; }}\n'
        # a shocker switched off on its card (not in use): the frame greyed too
        # (grey's mid in both modes: Vibrant's `dim` is a green)
        f'QFrame#paramCard[off="true"] {{ border-color: {PALETTE["grey"][1]}; }}\n'
        f'QPushButton[role="seg"][hue="accent"]:checked {{ background-color: {v["ok_tint"]};'
        f' color: {v["accent"]}; border-color: {v["ok_mid"]}; }}\n'
    )
    return "".join(out)
