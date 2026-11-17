"""The log's stylesheet rules -- the Log page (ui/views/log_page.py) and the
"by person" rows it shares with the Friends page's log card
(ui/views/log_people.py) -- built with the rest of the sheet by
theme.build_qss.

A person is a well-coloured row; their shock count wears the shockers'
yellow (one colour per thing). The kind filter's chips are lit in the
accent while their kind is shown, a quiet outline while it's left out."""

from typing import Dict

from ui.theme import FRIEND_SHOCK_HUE


def log_qss(_mode_name: str, v: Dict[str, str]) -> str:
    shock, shock_mid, shock_tint = (v[FRIEND_SHOCK_HUE], v[f"{FRIEND_SHOCK_HUE}_mid"],
                                    v[f"{FRIEND_SHOCK_HUE}_tint"])
    return (
        f'QFrame#logPerson {{ background-color: {v["well"]}; border: 1px solid {v["well"]};'
        f' border-radius: {v["r_btn"]}px; }}\n'
        f'QFrame#logPerson:hover {{ border-color: {v["line"]}; }}\n'
        'QWidget#logPersonHead { background: transparent; }\n'
        f'QLabel#logCaret {{ color: {v["muted"]}; }}\n'
        f'QLabel#logPersonName {{ color: {v["txt"]}; font-weight: 700; }}\n'
        f'QLabel#logShocks {{ color: {shock}; background-color: {shock_tint};'
        f' border: 1px solid {shock_mid}; border-radius: 5px; padding: 0px 6px;'
        ' font-size: 11px; font-weight: 700; }\n'
        f'QLabel#logPersonBody {{ color: {v["txt"]}; padding: 2px 0px 2px 18px; }}\n'
        f'QPushButton[role="logKind"] {{ background-color: transparent; color: {v["muted"]};'
        f' border: 1px solid {v["line"]}; border-radius: 6px; padding: 2px 10px;'
        ' min-height: 20px; font-size: 12px; }\n'
        f'QPushButton[role="logKind"]:hover {{ background-color: {v["hover"]}; }}\n'
        f'QPushButton[role="logKind"]:checked {{ background-color: {v["ok_tint"]};'
        f' color: {v["accent"]}; border-color: {v["accent"]}; }}\n'
    )
