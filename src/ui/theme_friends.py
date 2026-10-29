"""The Friends page's stylesheet rules (ui/views/friends*.py and the
cards), built with the rest of the sheet by theme.build_qss."""

from typing import Dict

from ui.theme import (
    FRIEND_HUES, FRIEND_SHOCK_HUE, FRIEND_TOYS_HUE, NEON_CAT_BARS, PALETTE, normalize_mode,
)


def friends_qss(mode_name: str, v: Dict[str, str]) -> str:
    """The Friends page: a row per friend or group (picked = filled with
    its hue and outlined), the panel wearing the picked friend's hue, and
    sliders / boxes / labels in the hue of what they drive."""
    neon = normalize_mode(mode_name) == "neon"
    out = [
        'QPushButton[role="friendRow"] {'
        ' background-color: transparent; border: 1px solid transparent;'
        f' border-radius: {v["r_btn"]}px; padding: 2px 6px; text-align: left;'
        f' color: {v["muted"]}; }}\n',
        f'QPushButton[role="friendRow"]:hover {{ background-color: {v["hover"]}; }}\n',
        # a group with a friend dragged over it
        f'QPushButton[role="friendRow"][drop="true"] {{ background-color: {v["tint"]};'
        f' border: 1px solid {v["accent"]}; }}\n',
        f'QPushButton[role="friendRow"][active="true"] {{ background-color: {v["tint"]};'
        f' border-color: {v["accent"]}; }}\n',
        f'QPushButton[role="friendRow"][active="true"] QLabel#friendName {{'
        f' color: {v["accent"]}; font-weight: 700; }}\n',
        'QLabel#friendAvatar { border-radius: 11px; font-size: 11px; font-weight: 700;'
        f' background-color: {v["tint"]}; color: {v["accent"]};'
        f' border: 1px solid {v["accent"]}; }}\n',
        f'QLabel#friendsMicro {{ color: {v["dim"]}; font-size: 10px; font-weight: 700;'
        ' letter-spacing: 1px; }\n',
        f'QLabel[low="true"] {{ color: {v["warn"]}; }}\n',      # a toy's battery, low
        # Add a friend: a header with its +/- box, the fold its child -- one
        # card while open, the header's frame running on round the fold
        f'QPushButton[role="addHead"] {{ text-align: left; padding: 0; }}\n',
        f'QPushButton[role="addHead"][open="true"] {{ border-color: {v["accent"]};'
        f' background-color: {v["tint"]}; border-bottom-left-radius: 0;'
        ' border-bottom-right-radius: 0; }\n',
        f'QLabel#addTitle {{ color: {v["txt"]}; background: transparent; }}\n',
        f'QLabel#addSign {{ color: {v["accent"]}; border: 1px solid {v["line"]};'
        f' border-radius: 6px; background-color: {v["well"]};'
        ' font-size: 16px; font-weight: 700; padding-bottom: 2px; }\n',
        f'QLabel#addSign[open="true"] {{ border-color: {v["accent"]}; }}\n',
        f'QFrame#addFold {{ border: 1px solid {v["accent"]}; border-top: none;'
        f' border-bottom-left-radius: {v["r_btn"]}px;'
        f' border-bottom-right-radius: {v["r_btn"]}px; background-color: transparent; }}\n',
    ]
    for hue in FRIEND_HUES:
        vib, mid, tint = PALETTE[hue]
        bar, frame = (NEON_CAT_BARS[hue] if neon else (tint, mid))
        bar_text = v["txt"] if neon else vib
        out.append(
            f'QPushButton[role="friendRow"][hue="{hue}"][active="true"] {{'
            f' background-color: {tint}; border-color: {vib}; }}\n'
            f'QPushButton[role="friendRow"][hue="{hue}"][active="true"] QLabel#friendName {{'
            f' color: {vib}; }}\n'
            f'QPushButton[role="friendRow"][hue="{hue}"] QLabel#friendAvatar {{'
            f' background-color: {tint}; color: {vib}; border-color: {mid}; }}\n'
            f'QPushButton[role="friendRow"][hue="{hue}"][active="true"] QLabel#friendAvatar {{'
            f' background-color: {vib}; color: {v["ink"]}; border-color: {vib}; }}\n'
            f'QFrame#card[hue="{hue}"] {{ border-color: {frame}; }}\n'
            f'QLabel#sectionTitle[hue="{hue}"] {{ background-color: {bar}; color: {bar_text}; }}\n'
        )
    for hue in (FRIEND_TOYS_HUE, FRIEND_SHOCK_HUE):
        vib, mid, tint = PALETTE[hue]
        out.append(
            f'QSlider[hue="{hue}"]::sub-page:horizontal {{ background: {vib}; }}\n'
            f'QSlider[hue="{hue}"]::handle:horizontal {{ background: {vib}; }}\n'
            f'QSlider[hue="{hue}"]::handle:horizontal:hover {{ background: {vib}; }}\n'
            f'QCheckBox[hue="{hue}"]::indicator {{ border-color: {mid}; }}\n'
            f'QCheckBox[hue="{hue}"]::indicator:checked {{ background-color: {vib};'
            f' border-color: {vib}; }}\n'
            f'QLabel#friendsMicro[hue="{hue}"] {{ color: {vib}; }}\n'
        )
    # The toy and shocker cards (ui/views/toy_card.py, shocker_card.py): a section frame
    # in the hue of what it drives, plain cards inside it, small segmented
    # switches, auto-mode chips, operate tiles and mini buttons.
    # a friend's OGP is newer than yours: as loud as the open-twice banner,
    # in the warning amber -- out of date is not an error (red is only for those)
    out.append(
        f'QFrame#friendUpdateBanner {{ background-color: {v["warn_tint"]};'
        f' border: 2px solid {v["warn"]}; border-radius: {v["r_btn"]}px; }}\n'
        f'QFrame#friendUpdateBanner QLabel {{ color: {v["warn"]}; font-size: 14px;'
        ' font-weight: 700; background: transparent; }\n'
        f'QLabel#friendUpdateHead {{ background-color: {v["warn_tint"]}; color: {v["warn"]};'
        f' border: 2px solid {v["warn"]}; border-radius: {v["r_btn"]}px; padding: 10px;'
        ' font-size: 15px; font-weight: 700; }\n')
    out.append(
        f'QFrame#friendSection {{ background-color: transparent; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_card"]}px; }}\n'
        f'QFrame#friendCard {{ background-color: {v["well"]}; border: 1px solid {v["well"]};'
        f' border-radius: {v["r_btn"]}px; }}\n'
        f'QLabel#friendCardName {{ color: {v["txt"]}; font-weight: 700; }}\n'
        f'QPushButton[role="seg"] {{ background-color: transparent; color: {v["muted"]};'
        f' border: 1px solid {v["line"]}; border-radius: 0px; padding: 1px 8px;'
        ' min-height: 18px; font-size: 11px; }\n'
        'QPushButton[role="seg"][pos="first"] { border-top-left-radius: 6px;'
        ' border-bottom-left-radius: 6px; }\n'
        'QPushButton[role="seg"][pos="mid"] { border-left-width: 0px; }\n'
        'QPushButton[role="seg"][pos="last"] { border-left-width: 0px;'
        ' border-top-right-radius: 6px; border-bottom-right-radius: 6px; }\n'
        f'QPushButton[role="chip"] {{ background-color: transparent; color: {v["muted"]};'
        f' border: 1px solid {v["line"]}; border-radius: 5px; padding: 2px 4px;'
        ' min-height: 18px; font-size: 11px; }\n'
        f'QPushButton[role="mini"] {{ background-color: transparent; color: {v["muted"]};'
        f' border: 1px solid {v["line"]}; border-radius: 5px; padding: 0px;'
        ' min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; }\n'
        'QPushButton[role="mini"][wide="true"] { max-width: 90px; padding: 0px 6px; }\n'
        'QPushButton[role="chip"][row="main"] { min-height: 24px; padding: 3px 10px;'
        ' font-size: 12px; }\n'
        f'QPushButton[role="control"] {{ background-color: transparent; color: {v["cyan"]};'
        f' border: 1px solid {v["cyan_mid"]}; border-radius: {v["r_btn"]}px; padding: 3px 12px;'
        ' font-weight: 700; }\n'
        f'QPushButton[role="control"]:hover {{ background-color: {v["cyan_tint"]};'
        f' border-color: {v["cyan"]}; }}\n'
        'QPushButton[role="control"][big="true"] { min-height: 36px; font-size: 15px;'
        ' padding: 4px 16px; }\n'
        f'QPushButton[role="seg"]:hover, QPushButton[role="chip"]:hover,'
        f' QPushButton[role="mini"]:hover {{ background-color: {v["hover"]}; }}\n'
        'QPushButton[role="danger"][size="small"] { padding: 1px 10px; min-height: 18px;'
        ' font-size: 11px; }\n'
    )
    # a shocker card's Shock / Vibrate blocks and its big Shock button; and
    # control mode's larger everything (big="true", for VR)
    out.append(
        f'QFrame#opBlock {{ background-color: transparent; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_btn"]}px; }}\n'
        'QFrame#friendCard[big="true"] QPushButton[role="fire"] { min-height: 56px; font-size: 20px; }\n'
        'QFrame#friendCard[big="true"] QPushButton[role="tile"] { min-height: 40px; font-size: 16px; }\n'
        'QPushButton[role="seg"][big="true"] { min-height: 32px; font-size: 14px;'
        ' padding: 4px 14px; }\n'
        'QPushButton[role="chip"][big="true"] { min-height: 36px; padding: 4px 8px;'
        ' font-size: 14px; }\n'
        'QPushButton[role="mini"][big="true"] { min-width: 36px; max-width: 36px;'
        ' min-height: 36px; max-height: 36px; font-size: 16px; }\n'
        'QPushButton[role="mini"][big="true"][wide="true"] { max-width: 150px;'
        ' padding: 0px 10px; }\n'
        'QPushButton[role="danger"][big="true"] { min-height: 36px; font-size: 15px;'
        ' padding: 4px 18px; }\n'
        'QLabel[big="true"], QCheckBox[big="true"] { font-size: 15px; }\n'
        'QLabel#friendCardName[big="true"] { font-size: 18px; }\n'
        'QSlider[big="true"] { min-height: 32px; }\n'
        'QSlider[big="true"]::groove:horizontal { height: 12px; border-radius: 6px; }\n'
        'QSlider[big="true"]::handle:horizontal { width: 28px; height: 28px;'
        ' margin: -9px 0; border-radius: 14px; }\n'
        'QFrame#card[big="true"] QLabel#sectionTitle { font-size: 20px; }\n'
        'QLabel#friendsMicro[big="true"] { font-size: 13px; }\n'
    )
    # PiShock's shocker panel (shocker_card.py, shocker_parts.py): tiles with
    # an icon, a value and a caption; the plain middle ones (Use Mode, Beep),
    # STOP in the error red (it stops things); the round pickers; vertical
    # sliders; and the state strip over the cards (armed: the warning amber
    # behind it -- state on the background). Resting (they paused you, a
    # mode that has no use for it): a solid grey outline, like everything
    # that is there but can't be used now -- never brighter than a live one
    # (Darker's hairline is already the quiet grey).
    rest = v["dim"] if neon else v["line"]
    out.append(
        f'QPushButton[role="opTile"] {{ background-color: transparent; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_btn"]}px; padding: 0px; }}\n'
        f'QPushButton[role="opTile"]:hover {{ background-color: {v["hover"]}; }}\n'
        'QPushButton[role="opTile"] QLabel { background: transparent; }\n'
        f'QPushButton[role="opTile"] QLabel#tileValue {{ color: {v["txt"]}; font-size: 15px;'
        ' font-weight: 700; }\n'
        f'QPushButton[role="opTile"] QLabel#tileCaption {{ color: {v["muted"]}; font-size: 10px; }}\n'
        'QPushButton[role="opTile"][big="true"] QLabel#tileValue { font-size: 22px; }\n'
        'QPushButton[role="opTile"][big="true"] QLabel#tileCaption { font-size: 14px; }\n'
        'QPushButton[role="opTile"] QLabel#tileValue[small="true"] { font-size: 10px; }\n'
        'QPushButton[role="opTile"][big="true"] QLabel#tileValue[small="true"] { font-size: 16px; }\n'
        f'QPushButton[role="opTile"]:disabled {{ border-color: {rest}; background-color: transparent; }}\n'
        f'QPushButton[role="opTile"] QLabel#tileValue:disabled,'
        f' QPushButton[role="opTile"] QLabel#tileCaption:disabled {{ color: {v["dim"]}; }}\n'
        f'QPushButton[role="opTile"][hue="stop"] {{ background-color: {v["err_tint"]};'
        f' border-color: {v["err_mid"]}; }}\n'
        f'QPushButton[role="opTile"][hue="stop"]:hover {{ border-color: {v["err"]}; }}\n'
        f'QPushButton[role="opTile"][hue="stop"]:pressed {{ background-color: {v["err_mid"]}; }}\n'
        f'QPushButton[role="opTile"][hue="stop"] QLabel#tileCaption {{ color: {v["err"]};'
        ' font-size: 12px; font-weight: 700; }\n'
        'QPushButton[role="opTile"][hue="stop"][big="true"] QLabel#tileCaption { font-size: 16px; }\n'
        f'QFrame#picker {{ background-color: {v["panel"]}; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_card"]}px; }}\n'
        f'QPushButton[role="pick"] {{ background-color: {v["well"]}; color: {v["txt"]};'
        f' border: 1px solid {v["line"]}; border-radius: 18px; min-width: 36px; max-width: 36px;'
        ' min-height: 36px; max-height: 36px; padding: 0px; font-size: 13px; font-weight: 700; }\n'
        'QPushButton[role="pick"][wide="true"] { border-radius: 10px; min-width: 130px;'
        ' max-width: 16777215px; min-height: 22px; max-height: 22px; padding: 4px 14px; }\n'
        'QPushButton[role="pick"][big="true"] { border-radius: 28px; min-width: 56px;'
        ' max-width: 56px; min-height: 56px; max-height: 56px; font-size: 18px; }\n'
        'QPushButton[role="pick"][big="true"][wide="true"] { border-radius: 10px;'
        ' min-width: 200px; max-width: 16777215px; min-height: 36px; max-height: 36px;'
        ' font-size: 16px; }\n'
        f'QPushButton[role="pick"]:hover {{ background-color: {v["hover"]}; border-color: {v["accent"]}; }}\n'
        f'QPushButton[role="pick"]:checked {{ background-color: {v["tint"]}; color: {v["accent"]};'
        f' border-color: {v["accent"]}; }}\n'
        f'QPushButton[role="pick"]:disabled {{ background-color: transparent; color: {v["dim"]};'
        f' border-color: {rest}; }}\n'
        f'QFrame#shockState {{ background-color: transparent; border: 1px solid {v["line"]};'
        f' border-radius: {v["r_btn"]}px; }}\n'
        f'QFrame#shockState[tone="armed"] {{ background-color: {v["warn_tint"]};'
        f' border-color: {v["warn_mid"]}; }}\n'
        f'QFrame#shockState QLabel {{ color: {v["muted"]}; background: transparent; }}\n'
        f'QFrame#shockState QLabel#stateHead {{ color: {v["txt"]}; font-weight: 700; }}\n'
        f'QFrame#shockState[tone="armed"] QLabel#stateHead {{ color: {v["warn"]}; }}\n'
        'QFrame#shockState[big="true"] QLabel { font-size: 15px; }\n'
        'QSlider::groove:vertical { width: 6px; border-radius: 4px;'
        f' background: {v["well"]}; border: 1px solid {v["line"]}; }}\n'
        'QSlider::sub-page:vertical { background: transparent; }\n'
        'QSlider::handle:vertical { width: 14px; height: 14px; margin: 0px -4px;'
        ' border-radius: 7px; border: none; }\n'
        'QSlider[big="true"]::groove:vertical { width: 12px; border-radius: 6px; }\n'
        'QSlider[big="true"]::handle:vertical { width: 28px; height: 28px; margin: 0px -9px;'
        ' border-radius: 14px; }\n'
        'QSlider:vertical { min-width: 22px; }\n'
        'QSlider[big="true"]:vertical { min-width: 34px; }\n'
        f'QSlider::add-page:vertical:disabled {{ background: {v["dim"]}; }}\n'
    )
    for hue in (FRIEND_TOYS_HUE, FRIEND_SHOCK_HUE):
        vib, mid, tint = PALETTE[hue]
        # The big Shock button: filled with the hue in Vibrant; Darker keeps
        # it dark like everything else there -- the hue as text and frame.
        fill, text, edge = (vib, v["ink"], vib) if neon else (tint, vib, mid)
        out.append(
            f'QFrame#opBlock[hue="{hue}"] {{ background-color: {tint}; border-color: {mid}; }}\n'
            f'QPushButton[role="fire"][hue="{hue}"] {{ background-color: {fill}; color: {text};'
            f' border: 2px solid {edge}; border-radius: {v["r_btn"]}px; min-height: 34px;'
            ' padding: 4px 12px; font-size: 15px; font-weight: 700; }\n'
            f'QPushButton[role="fire"][hue="{hue}"]:hover {{ border-color: {v["txt"] if neon else vib}; }}\n'
            f'QPushButton[role="fire"][hue="{hue}"]:pressed {{ background-color: {mid};'
            f' color: {vib}; }}\n'
            f'QFrame#friendSection[hue="{hue}"] {{ border-color: {mid}; }}\n'
            f'QPushButton[role="seg"][hue="{hue}"]:checked {{ background-color: {tint};'
            f' color: {vib}; border-color: {mid}; }}\n'
            f'QPushButton[role="chip"][hue="{hue}"]:checked {{ background-color: {tint};'
            f' color: {vib}; border-color: {vib}; }}\n'
            f'QPushButton[role="mini"][hue="{hue}"]:checked {{ background-color: {tint};'
            f' border-color: {vib}; }}\n'
            f'QPushButton[role="tile"][hue="{hue}"] {{ background-color: transparent;'
            f' color: {vib}; border: 1px solid {vib}; border-radius: {v["r_btn"]}px;'
            ' padding: 2px 8px; min-height: 22px; font-weight: 700; }\n'
            f'QPushButton[role="tile"][hue="{hue}"]:hover {{ background-color: {tint}; }}\n'
            f'QPushButton[role="tile"][hue="{hue}"]:pressed {{ background-color: {mid}; }}\n'
            # PiShock's tiles: Operate filled like the old Shock button,
            # Duration / Warning outlined in the hue
            f'QPushButton[role="opTile"][hue="{hue}"] {{ border-color: {mid}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"]:hover {{ background-color: {tint};'
            f' border-color: {vib}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"]:pressed {{ background-color: {mid}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"] QLabel#tileValue {{ color: {vib}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"][filled="true"] {{ background-color: {fill};'
            f' border: 2px solid {edge}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"][filled="true"]:hover {{'
            f' border-color: {v["txt"] if neon else vib}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"][filled="true"]:pressed {{'
            f' background-color: {mid}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"][filled="true"] QLabel#tileValue,'
            f' QPushButton[role="opTile"][hue="{hue}"][filled="true"] QLabel#tileCaption'
            f' {{ color: {text}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"]:disabled {{ border-color: {rest}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"][filled="true"]:disabled {{'
            f' background-color: transparent; border: 1px solid {rest}; }}\n'
            f'QPushButton[role="opTile"][hue="{hue}"] QLabel#tileValue:disabled,'
            f' QPushButton[role="opTile"][hue="{hue}"] QLabel#tileCaption:disabled'
            f' {{ color: {v["dim"]}; }}\n'
            f'QPushButton[role="pick"][hue="{hue}"]:checked {{ background-color: {vib};'
            f' color: {v["ink"]}; border-color: {vib}; }}\n'
            f'QPushButton[role="pick"][hue="{hue}"]:hover {{ border-color: {vib}; }}\n'
            f'QPushButton[role="pick"][hue="{hue}"]:disabled {{ border-color: {rest}; }}\n'
            f'QFrame#picker[hue="{hue}"] {{ border-color: {mid}; }}\n'
            f'QSlider[hue="{hue}"]::add-page:vertical {{ background: {vib}; border-radius: 3px;'
            ' margin: 1px; }\n'
            f'QSlider[hue="{hue}"]::handle:vertical {{ background: {vib}; }}\n'
        )
    return "".join(out)
