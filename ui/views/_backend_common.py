"""Shared scaffolding for the per-backend view mixins (PiShock / Coyote /
OWO / Handy / bHaptics): the non-blocking "Connect Now" flow, the
zone-combo populate every Source fold needs, and the zone-TYPE-change
behavior that must clear + repopulate the combo.

View-layer only — talks to controller facade methods, never to engines or
routers (Law of Demeter). Extracted because the four per-view copies had
already drifted apart: only bHaptics Cross-Routing repopulated its combo on
an Orf/Pen switch, so the other backends silently routed 0 after a type
change (the stale zone name resolved against the wrong list).
"""

from PySide6.QtWidgets import QComboBox


def run_connect_now(view, label: str, worker, refresh_status_only,
                    buttons, failed_hint: str = "") -> None:
    """Shared "Connect Now" flow for the backend views: run the blocking
    connect off the Qt thread (``run_ui_task`` disables `buttons` while
    pending so a double-click or config flip can't race the in-flight
    open), log the outcome, then refresh **status-only**.

    Status-only is load-bearing: the done-callback fires seconds after
    the click, when the user may be typing again — a full refresh here
    would clobber their edits (the exact bug the full/status-only split
    exists to prevent, and one the per-view copies of this handler had
    already regressed once).

    `view` is the composed UI object (provides ``run_ui_task`` /
    ``log_message``); `worker` is the controller's ``*_connect_now``;
    `failed_hint` is appended to the not-connected log line (e.g.
    bHaptics' "is the Player running?")."""
    def done(result):
        if isinstance(result, Exception):
            view.log_message(f"{label}: connect failed — {result}")
        elif result:
            view.log_message(f"{label}: connected")
        else:
            view.log_message(f"{label}: connect failed{failed_hint}")
        refresh_status_only()
    view.run_ui_task(worker, done, buttons=buttons)


def populate_zone_combo(controller, combo: QComboBox, zone_type: str,
                        keep_current: bool = True) -> None:
    """Fill an editable zone combo with the detected OGB zones plus the
    synthetic SPS sources for `zone_type` ('Orf' | 'Pen').

    Preserves the current edit text by default (appending it if it isn't in
    the fresh list, so a hand-typed or not-yet-detected name survives).
    Signals are blocked throughout — populating must never push config.
    """
    combo.blockSignals(True)
    try:
        current = combo.currentText() if keep_current else ""
        combo.clear()
        try:
            zones = controller.get_detected_zones() or {}
        except Exception:
            zones = {}
        key = {"Orf": "Orifices", "Pen": "Penetrators",
               "Touch": "Touch"}.get(zone_type, "Orifices")
        names = list(zones.get(key) or [])
        try:
            custom = controller.get_sps_source_names_by_type() or {}
        except Exception:
            custom = {}
        for nm in (custom.get(key) or []):
            if nm not in names:
                names.append(nm)
        combo.addItems(names)
        if current and combo.findText(current) < 0:
            combo.addItem(current)
        combo.setEditText(current)
    finally:
        combo.blockSignals(False)


def zone_signature(controller):
    """Cheap hashable snapshot of the selectable zone + source names. Open
    pages compare it each status tick and repopulate their combos when it
    changes, so zones detected mid-session become selectable without
    navigating away and back."""
    try:
        zones = controller.get_detected_zones() or {}
    except Exception:
        zones = {}
    try:
        custom = controller.get_sps_source_names_by_type() or {}
    except Exception:
        custom = {}
    return (
        tuple(zones.get("Orifices") or ()),
        tuple(zones.get("Penetrators") or ()),
        tuple(zones.get("Touch") or ()),
        tuple(custom.get("Orifices") or ()),
        tuple(custom.get("Penetrators") or ()),
    )


def on_zone_type_changed(controller, zone_combo: QComboBox, new_type: str,
                         push) -> None:
    """Zone-TYPE switch (Orf <-> Pen): the previous type's zone name cannot
    be valid for the new type, so clear the selection, repopulate the
    dropdown with the new type's zones, then push the (now blank-zone)
    config."""
    populate_zone_combo(controller, zone_combo, new_type, keep_current=False)
    push()
