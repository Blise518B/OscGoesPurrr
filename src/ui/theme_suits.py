"""The Suits page's stylesheet rules (ui/views/suits.py, suits_cards.py),
built with the rest of the sheet by theme.build_qss.

Its frames and cards are Avatar Remote's (theme_params styles them in the
orange too). What's the page's own: each suit's tag on its inspector card,
and the chips and segmented switches in the suit's hue -- bHaptics orange,
OWO purple, Vive trackers blue."""

from typing import Dict

from ui.theme import BHAPTICS_HUE, OWO_HUE, PALETTE, TRACKERS_HUE


def suits_qss(_mode_name: str, v: Dict[str, str]) -> str:
    out = []
    for hue in (BHAPTICS_HUE, OWO_HUE, TRACKERS_HUE):
        vib, mid, tint = PALETTE[hue]
        out.append(
            f'QLabel#suitTag[hue="{hue}"] {{ color: {vib}; border: 1px solid {mid};'
            f' border-radius: 8px; padding: 0px 6px; font-size: 11px; }}\n'
            f'QPushButton[role="seg"][hue="{hue}"]:checked {{ background-color: {tint};'
            f' color: {vib}; border-color: {mid}; }}\n'
            f'QPushButton[role="chip"][hue="{hue}"] {{ color: {v["txt"]}; border-color: {mid}; }}\n'
            f'QPushButton[role="chip"][hue="{hue}"]:checked {{ background-color: {tint};'
            f' color: {vib}; border-color: {vib}; }}\n'
        )
    return "".join(out)
