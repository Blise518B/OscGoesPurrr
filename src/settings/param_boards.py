"""Parameter boards -- the Avatar Remote page's avatars and their boards.

  * ``avatars``     — {avatar_id: profile}, each in param_board's shape
    (the same as VRC Parameter Relay's ``avatars/*.json``): its name, its
    parameter list from when it was last worn, its presets.
  * ``last_avatar`` — the avatar open on the page last time.
  * ``yolo``        — friends get every parameter of the worn avatar, not
    only its board (and locks don't hold for them).

Every avatar you wear has its parameter list remembered, so its board can
be built while you wear something else. Those that are only that -- never
named, nothing on any board -- are kept for the SCRATCH_KEEP most recently
worn; a named avatar, or one with a control on a board, stays.

One file, so the settings backups carry the boards like everything else.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

import param_board as pb

from ._base import JsonSettingsManager
from ._paths import PARAM_BOARDS_FILE

SCRATCH_KEEP = 30
MAX_AVATARS = 400


def _is_scratch(profile: Dict[str, Any]) -> bool:
    """Only remembered from wearing it: no name of its own, no controls."""
    return (profile.get("name") == pb.short_avatar_name(profile.get("avatar_id"))
            and not any(p.get("controls") for p in profile.get("presets") or []))


class ParamBoardsSettingsManager(JsonSettingsManager):
    DEFAULTS = {
        "avatars": {},
        "last_avatar": "",
        "yolo": False,
    }
    FILE_PATH = PARAM_BOARDS_FILE

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        avatars = {}
        raw = self.settings.get("avatars")
        for aid, profile in (raw.items() if isinstance(raw, dict) else []):
            aid = str(aid).strip()
            if aid and isinstance(profile, dict):
                avatars[aid] = pb.normalize_profile(profile, aid)
        self.settings["avatars"] = avatars
        self.settings["last_avatar"] = str(self.settings.get("last_avatar") or "")
        self.settings["yolo"] = bool(self.settings.get("yolo"))
        # ■ STOP is gone (2026-10-27): a STOP left on must not block friends
        # forever with no button to lift it
        self.settings.pop("stop", None)

    # -- the store BoardBook reads and writes ----------------------------------

    def load(self, avatar_id: str) -> Optional[Dict[str, Any]]:
        """The avatar's profile itself (edits to it are saved by `save`)."""
        return self.settings["avatars"].get(str(avatar_id))

    def save(self, profile: Dict[str, Any]) -> None:
        aid = profile.get("avatar_id")
        if not aid:
            return
        profile["seen"] = round(time.time(), 3)
        self.settings["avatars"][aid] = profile
        self._prune(keep=aid)
        self._save()

    def _prune(self, keep: str) -> None:
        avatars = self.settings["avatars"]
        # the one just saved counts as the newest, and is never the one to go
        scratch = sorted((aid == keep, p.get("seen", 0), aid) for aid, p in avatars.items()
                         if _is_scratch(p))
        for _, _, aid in scratch[:max(0, len(scratch) - SCRATCH_KEEP)]:
            del avatars[aid]
        if len(avatars) > MAX_AVATARS:
            oldest = sorted((p.get("seen", 0), aid) for aid, p in avatars.items() if aid != keep)
            for _, aid in oldest[:len(avatars) - MAX_AVATARS]:
                del avatars[aid]

    def list_profiles(self) -> List[Dict[str, Any]]:
        """[{avatar_id, name, named}] by name."""
        out = []
        for aid, p in self.settings["avatars"].items():
            short = pb.short_avatar_name(aid)
            out.append({"avatar_id": aid,
                        "name": pb.display_name({**p, "avatar_id": aid}),
                        "named": (p.get("name") or short) != short})
        return sorted(out, key=lambda e: (e["name"].lower(), e["avatar_id"]))

    def has(self, avatar_id: str) -> bool:
        p = self.settings["avatars"].get(str(avatar_id))
        return p is not None and not _is_scratch(p)

    def import_profiles(self, profiles: List[Dict[str, Any]],
                        replace: bool = False) -> Tuple[int, int, int]:
        """Boards from VRC Parameter Relay. An avatar that already has a
        board here is kept unless `replace`. Returns (added, replaced,
        kept)."""
        added = replaced = kept = 0
        avatars = self.settings["avatars"]
        for p in profiles:
            aid = p["avatar_id"]
            if self.has(aid):
                if not replace:
                    kept += 1
                    continue
                replaced += 1
            else:
                added += 1
            p["seen"] = round(time.time(), 3)
            avatars[aid] = p
        if added or replaced:
            self._prune(keep="")
            self._save()
        return added, replaced, kept

    # -- the page's own settings -------------------------------------------------

    def get_last_avatar(self) -> str:
        return self.settings.get("last_avatar") or ""

    def set_last_avatar(self, avatar_id: str) -> None:
        if avatar_id and avatar_id != self.settings.get("last_avatar"):
            self.settings["last_avatar"] = str(avatar_id)
            self._save()

    def get_yolo(self) -> bool:
        return bool(self.settings.get("yolo"))

    def set_yolo(self, on: bool) -> None:
        self.settings["yolo"] = bool(on)
        self._save()
