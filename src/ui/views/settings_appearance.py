"""Settings -> Appearance: the mode (Vibrant / Darker), the colour, and
Other colours -- the colours that mean something, each automatic (moving
out of the colour's way when it lands too close) or set by hand. Every
change applies while the app runs (ui/live_theme.py) and is saved once the
control rests. Part of SettingsMixin (settings.py)."""

from typing import Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QSlider, QWidget

from ui import theme as _theme
from ui.layout_helpers import vbox as _vbox, hbox as _hbox


class AppearanceMixin:

    # ----------------------------------------------------------
    # Appearance: the mode and the colour picker
    # ----------------------------------------------------------

    # "Mode:" and "Colour:" share a column, so what follows them lines up.
    _APPEARANCE_LABEL_W = 52

    _UI_MODE_TIP = (
        "<b>Vibrant</b> draws every card, button and chip with an outline "
        "in your colour. <b>Darker</b> turns those outlines down to a "
        "faint hairline and deepens the blacks, so only what matters "
        "lights up. Same layout in both.<br><br>"
        "Switches as you click — nothing restarts."
    )

    def _build_ui_mode_row(self) -> QWidget:
        """Mode: one button per mode, the one in use lit."""
        host = QWidget()
        row = _hbox(0, 8)
        host.setLayout(row)
        label = QLabel("Mode:")
        label.setFixedWidth(self._APPEARANCE_LABEL_W)
        row.addWidget(label)
        self._ui_mode_buttons = {}
        for key in _theme.MODE_ORDER:
            btn = QPushButton(_theme.MODE_LABELS.get(key, key))
            btn.setProperty(
                "role", "segActive" if key == _theme.MODE else "segIdle")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._set_ui_mode(k))
            row.addWidget(btn)
            self._ui_mode_buttons[key] = btn
        self._explain(row, "Vibrant / Darker", self._UI_MODE_TIP)
        row.addStretch(1)
        return host

    def _set_ui_mode(self, key: str) -> None:
        """Switch between the two modes, now: the page in view first, the
        rest of the app right behind it (the same sweep as a colour)."""
        key = _theme.normalize_mode(key)
        live = getattr(self, "live_theme", None)
        if live is None or not live.set_mode(key):
            return
        self.controller.set_app_setting("ui_mode", key)
        for k, btn in self._ui_mode_buttons.items():
            btn.setProperty("role", "segActive" if k == key else "segIdle")
            self._repolish(btn)
        # The picker shows this mode's version of every colour.
        self._paint_accent_picker()

    _ACCENT_TIP = (
        "Turns everything that is green — frames, buttons, highlights, "
        "even the faint tint of the background — to the colour you pick, "
        "as you pick it. Brightness and contrast stay as they are, so "
        "every colour reads as well as the green does.<br><br>"
        "The colours that <i>mean</i> something keep theirs — each toy's "
        "own colour, pink for the live signal, amber for warnings, red "
        "for errors — unless your colour lands right on one of them: "
        "that one then moves out of its way (pick Pink, and the pink "
        "turns green). <b>Other colours</b> below shows them all and lets "
        "you set any of them yourself.<br><br>"
        "Nothing restarts: what you are looking at changes first and the "
        "rest of the app follows a moment later. <b>Green</b> brings the "
        "original back."
    )

    # The slider reports every pixel of a drag; the app follows at most
    # this often. One step re-styles what is on screen (two or three
    # sections), so this is also the frame rate of the live preview.
    _ACCENT_LIVE_MS = 40
    # The choice is written to disk once the picker has been still this long.
    _ACCENT_SAVE_MS = 600

    def _build_accent_picker(self) -> QWidget:
        """Colour: presets and a hue slider. The whole app is the preview:
        a choice is applied as it is made (ui/live_theme.py sweeps it
        through the app in slices) and saved once the picker rests."""
        host = QWidget()
        lay = _vbox(0, 8)
        host.setLayout(lay)

        self._accent_pick = _theme.ACCENT_HUE

        # ---- presets ----
        row = _hbox(0, 8)
        colour_label = QLabel("Colour:")
        colour_label.setFixedWidth(self._APPEARANCE_LABEL_W)
        row.addWidget(colour_label)
        self._accent_preset_buttons = []
        for name, hue in _theme.ACCENT_PRESETS:
            btn = QPushButton("")
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(name)
            # Shows a colour that is not the current one, on purpose.
            btn.setProperty("noRetint", True)
            btn.clicked.connect(lambda _=False, h=hue: self._set_accent_pick(h))
            row.addWidget(btn)
            self._accent_preset_buttons.append((btn, hue))
        row.addStretch(1)
        lay.addLayout(row)

        # ---- hue slider: its track is the colours it leads to ----
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 359)
        slider.setPageStep(15)
        slider.setFixedHeight(24)
        slider.setMaximumWidth(420)
        slider.setCursor(Qt.PointingHandCursor)
        slider.setProperty("noRetint", True)
        self._accent_slider = slider
        slider.valueChanged.connect(
            lambda v: self._set_accent_pick(float(v), from_slider=True))
        lay.addWidget(slider)

        self._accent_note = self._muted_label(
            "Mode and colour change as you pick — no restart.")
        lay.addWidget(self._accent_note)

        # Coalesce a drag into steps the app can keep up with, and save
        # once it stops.
        self._accent_live_timer = QTimer(host)
        self._accent_live_timer.setSingleShot(True)
        self._accent_live_timer.setInterval(self._ACCENT_LIVE_MS)
        self._accent_live_timer.timeout.connect(self._apply_accent_pick)
        self._accent_save_timer = QTimer(host)
        self._accent_save_timer.setSingleShot(True)
        self._accent_save_timer.setInterval(self._ACCENT_SAVE_MS)
        self._accent_save_timer.timeout.connect(self._save_accent_pick)

        self._explain(lay, "Colour", self._ACCENT_TIP)
        self._paint_accent_picker()
        return host

    def _set_accent_pick(self, hue, from_slider: bool = False) -> None:
        """Take a choice (None = the house green) from a preset or the
        slider. A preset applies at once; a drag is coalesced."""
        default = _theme.DEFAULT_ACCENT_HUE
        if from_slider and hue is not None and round(hue) == round(default):
            hue = None                    # the green's own spot on the track
        self._accent_pick = hue
        if from_slider:
            if not self._accent_live_timer.isActive():
                self._accent_live_timer.start()
        else:
            self._accent_live_timer.stop()
            self._apply_accent_pick()

    def _apply_accent_pick(self) -> None:
        """Turn the app to the picked colour, now."""
        hue = self._accent_pick
        live = getattr(self, "live_theme", None)
        if live is not None:
            live.set_hue(hue)
        self._paint_accent_picker()
        self._accent_save_timer.start()

    def _save_accent_pick(self) -> None:
        hue = self._accent_pick
        self.controller.set_app_setting(
            "ui_accent_hue", None if hue is None else round(float(hue), 1))

    def _paint_accent_picker(self) -> None:
        """Repaint the picker around the current choice: the slider's
        position, its handle and track, and the ring on the chosen preset."""
        hue = self._accent_pick
        now = _theme.CHROME
        accent = _theme.accent_preview(hue)["accent"]

        slider = self._accent_slider
        want = int(round(_theme.DEFAULT_ACCENT_HUE if hue is None else hue)) % 360
        if slider.value() != want and not slider.isSliderDown():
            slider.blockSignals(True)
            slider.setValue(want)
            slider.blockSignals(False)
        stops = ", ".join(
            f"stop:{i / 12:.4f} {_theme.accent_preview(i * 30.0)['accent']}"
            for i in range(13))
        slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 10px; "
            f"border: 1px solid {now['line']}; border-radius: 6px; "
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops}); }}"
            "QSlider::sub-page:horizontal { background: transparent; }"
            "QSlider::handle:horizontal { width: 14px; height: 14px; "
            "margin: -4px 0; border-radius: 9px; "
            f"background: {accent}; border: 2px solid {now['txt']}; }}")

        for btn, preset in self._accent_preset_buttons:
            chosen = _theme.same_accent(preset, hue)
            fill = _theme.accent_preview(preset)["accent"]
            ring = now["txt"] if chosen else now["panel"]
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {fill}; "
                f"border: 2px solid {ring}; border-radius: 12px; padding: 0; }}"
                f"QPushButton:hover {{ background-color: {fill}; "
                f"border-color: {now['txt']}; }}")
        # what moved out of the colour's way
        if getattr(self, "_identity_rows", None):
            self._paint_identity_colours()

    # ----------------------------------------------------------
    # Other colours: the identity colours
    # ----------------------------------------------------------

    _IDENTITY_TIP = (
        "The colours that <i>mean</i> something: the live signal, errors, "
        "warnings, shockers, each toy's own colour.<br><br>"
        "<b>Auto</b> (the default): a colour keeps its own hue — unless "
        "your colour above lands too close to it, then it moves out of its "
        "way, to where it stands out most.<br>"
        "<b>Drag a slider</b> to set that colour yourself; it then stays "
        "where you put it, whatever your colour. <b>Auto</b> hands it back."
    )

    def _build_identity_colours(self) -> QWidget:
        """Other colours ▸ -- folded until asked for."""
        host = QWidget()
        lay = _vbox(0, 6)
        host.setLayout(lay)
        self._identity_pick: Dict[str, float] = dict(_theme.identity_chosen())

        toggle = QPushButton("Other colours ▸")
        toggle.setProperty("role", "ghost")
        toggle.setCursor(Qt.PointingHandCursor)
        row = _hbox(0, 8)
        row.addWidget(toggle)
        row.addStretch(1)
        lay.addLayout(row)
        self._explain(toggle, "Other colours", self._IDENTITY_TIP)

        body = QWidget()
        bl = _vbox(0, 4)
        body.setLayout(bl)
        bl.addWidget(self._muted_label(
            "A colour that comes too close to yours moves out of its way by "
            "itself. Drag one to set it yourself; Auto hands it back."))
        self._identity_rows = {}
        for name, label, what in _theme.IDENTITY_ROLES:
            bl.addWidget(self._identity_row(name, label, what))
        body.setVisible(False)
        lay.addWidget(body)

        def fold() -> None:
            body.setVisible(not body.isVisible())
            toggle.setText("Other colours ▾" if body.isVisible() else "Other colours ▸")
        toggle.clicked.connect(lambda _=False: fold())
        self._identity_body = body

        self._identity_live_timer = QTimer(host)
        self._identity_live_timer.setSingleShot(True)
        self._identity_live_timer.setInterval(self._ACCENT_LIVE_MS)
        self._identity_live_timer.timeout.connect(self._apply_identity_pick)
        self._identity_save_timer = QTimer(host)
        self._identity_save_timer.setSingleShot(True)
        self._identity_save_timer.setInterval(self._ACCENT_SAVE_MS)
        self._identity_save_timer.timeout.connect(self._save_identity_pick)
        self._paint_identity_colours()
        return host

    def _identity_row(self, name: str, label: str, what: str) -> QWidget:
        """One colour: a swatch, its name, a hue slider whose track is the
        colours it leads to, what it marks, and Auto."""
        row_w = QWidget()
        row = _hbox(0, 8)
        row_w.setLayout(row)
        swatch = QLabel("")
        swatch.setFixedSize(16, 16)
        swatch.setProperty("noRetint", True)     # painted from the state, every change
        row.addWidget(swatch)
        name_lbl = QLabel(label)
        name_lbl.setFixedWidth(52)
        row.addWidget(name_lbl)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 359)
        slider.setPageStep(15)
        slider.setFixedHeight(20)
        slider.setFixedWidth(220)
        slider.setFocusPolicy(Qt.StrongFocus)
        slider.setCursor(Qt.PointingHandCursor)
        slider.setProperty("noRetint", True)
        slider.valueChanged.connect(lambda v, n=name: self._set_identity_pick(n, float(v)))
        row.addWidget(slider)
        auto = QPushButton("Auto")
        auto.setProperty("role", "ghost")
        auto.setCursor(Qt.PointingHandCursor)
        auto.setToolTip("Back to automatic: its own colour, or out of your colour's way")
        auto.clicked.connect(lambda _=False, n=name: self._set_identity_pick(n, None))
        keep = auto.sizePolicy()
        keep.setRetainSizeWhenHidden(True)        # the rows stay lined up
        auto.setSizePolicy(keep)
        row.addWidget(auto)
        note = QLabel(what)
        note.setProperty("muted", "true")
        row.addWidget(note, 1)
        self._identity_rows[name] = {"swatch": swatch, "slider": slider, "auto": auto,
                                     "note": note, "what": what}
        return row_w

    def _set_identity_pick(self, name: str, hue) -> None:
        """A slider moved (a hue) or Auto was pressed (None)."""
        if hue is None:
            self._identity_pick.pop(name, None)
            self._identity_live_timer.stop()
            self._apply_identity_pick()
            return
        self._identity_pick[name] = hue
        if not self._identity_live_timer.isActive():
            self._identity_live_timer.start()

    def _apply_identity_pick(self) -> None:
        live = getattr(self, "live_theme", None)
        if live is not None:
            live.set_identity(self._identity_pick)
        self._paint_identity_colours()
        self._identity_save_timer.start()

    def _save_identity_pick(self) -> None:
        self.controller.set_app_setting(
            "ui_identity_hues", {n: round(h, 1) for n, h in self._identity_pick.items()})

    def _paint_identity_colours(self) -> None:
        """Each row as things stand: its colour now, the slider there, a
        word on why, Auto only when it was set by hand."""
        now = _theme.CHROME
        state = _theme.identity_state()
        for name, w in self._identity_rows.items():
            st = state[name]
            colour = _theme.identity_preview(name, st["hue"])
            w["swatch"].setStyleSheet(
                f"background-color: {colour}; border-radius: 8px; border: 1px solid {now['line']};")
            slider = w["slider"]
            want = int(round(st["hue"])) % 360
            if slider.value() != want and not slider.isSliderDown():
                slider.blockSignals(True)
                slider.setValue(want)
                slider.blockSignals(False)
            stops = ", ".join(
                f"stop:{i / 12:.4f} {_theme.identity_preview(name, i * 30.0)}" for i in range(13))
            slider.setStyleSheet(
                "QSlider::groove:horizontal { height: 8px; "
                f"border: 1px solid {now['line']}; border-radius: 5px; "
                f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops}); }}"
                "QSlider::sub-page:horizontal { background: transparent; }"
                "QSlider::handle:horizontal { width: 12px; height: 12px; "
                "margin: -3px 0; border-radius: 8px; "
                f"background: {colour}; border: 2px solid {now['txt']}; }}")
            why = (" · set by you" if st["chosen"]
                   else " · moved out of your colour's way" if st["moved"] else "")
            text = w["what"] + why
            if w["note"].text() != text:
                w["note"].setText(text)
            w["auto"].setVisible(bool(st["chosen"]))     # only what you set has an Auto
