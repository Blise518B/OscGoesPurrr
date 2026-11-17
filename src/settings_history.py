"""Ctrl+Z / Ctrl+Y: one history of your last five settings changes, for
the whole app (friends' reviews, 2026-11-14, Blise: "a control Z in the
entire app ... a history of the last 5 things you did", and Ctrl+Y "to get
back to the point").

Changes are recorded where settings are SAVED, not in each widget -- like
the app-wide wheel guard, a new setting gets undo without doing anything.
Every settings store reports its saves here (`saved`); the history keeps a
copy of what each store held at its last save (its *baseline*), and a save
that differs from it is a change: the paths that differ, each with its
value before and after. So a store only has to be tracked once
(`track`, at the end of its load) and to call `saved(self)` when it
writes its file -- settings/_base.py does both for every JSON settings
file, and the few stores with their own file code do it by hand.

* **A step** is what one Ctrl+Z takes back. Saves that follow each other
  within `COALESCE_S` -- a slider drag, a click that writes several keys,
  in one store or several -- are one step, until the user starts on
  another control (`boundary`). The newest `LIMIT` steps are kept; a new
  step after an undo drops what could still be redone.
* **Only your own changes.** A save counts only while `gate()` says the
  user just did something in the app (the UI's input tracker, on the GUI
  thread). A friend moving your strength, the avatar menu, a toy that
  connects, a migration at launch -- their saves move the baseline and
  are never a step. Each store also leaves out what is no setting
  (`history_ignore`): window places, folds, the page you're on, secrets,
  bookkeeping like a friend's last nickname.
* **Undo writes the old values back through the store** -- into its live
  settings, saved by its own save, then each `on_restored` hook (the
  controller facade that owns the store) puts it into effect and redraws.
  The UI may first try the control the step was made on (`replay`), which
  is how doing it by hand would do it; whatever that left undone is
  written to the store.
* **Nothing that already happened is undone**: a shock, a toy's level, a
  friend's drive, a sent message, the log, statistics -- none of them is
  a settings store.
* **Safety** (not to be loosened): a step that would arm shocks, switch a
  shocker, a Shock / Vibrate / Beep or the hub back on, widen what a
  friend may do, or raise a limit asks first, as by hand (each store's
  `history_asks`). Without a way to ask (`ask`), it isn't done, and the
  step stays where it is.
* **An action** (`action`) is a change that knows its own way back --
  dragging an Avatar Remote control back to the list (param_board.py's
  `take_control` / `put_back`). Its save is part of it, not a step of its
  own.

Pure Python, no Qt: ui/history_keys.py is the keyboard, the input tracker
and the asking."""

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

LIMIT = 5             # steps kept (Blise: "the last 5 things you did")
COALESCE_S = 0.8      # saves this close together are one step

# Results of undo() / redo()
DONE = "done"
NOTHING = "nothing"
ASKING = "asking"           # a question is up; the answer finishes it
BLOCKED = "blocked"         # it would need an ask nobody can give here
CANCELLED = "cancelled"     # asked, and the answer was no
FAILED = "failed"           # nothing of it could be applied


class _Missing:
    """A path that wasn't there (before an add, after a removal)."""
    _it = None

    def __new__(cls):
        if cls._it is None:
            cls._it = super().__new__(cls)
        return cls._it

    def __repr__(self) -> str:
        return "MISSING"

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        return (_Missing, ())


MISSING = _Missing()


@dataclass(frozen=True)
class ById:
    """A path step into a list of dicts that each carry a unique "id" (a
    friend, a group, a control): found by its id, wherever it sits now."""
    id: Any

    def __repr__(self) -> str:
        return f"#{self.id}"


class _Order:
    def __repr__(self) -> str:
        return "ORDER"


# A path's last step: the order of an id-keyed list (before / after are
# lists of ids).
ORDER = _Order()


@dataclass
class Change:
    """One path that changed in one store. `at_before` / `at_after`: where
    an element of an id-keyed list sat, for putting it back there."""
    path: Tuple[Any, ...]
    before: Any
    after: Any
    at_before: Optional[int] = None
    at_after: Optional[int] = None


@dataclass
class Ask:
    """A question a step needs answered before it is applied. `kind` is
    "arm" (Arm shocks' own question, in the switch's place) or "confirm"
    (Yes / No in the window); `text` says what it would do."""
    kind: str
    text: str


@dataclass
class Action:
    """A change that knows its own way back. `undo()` / `redo()` return
    True when they did it, or a text saying why they couldn't."""
    label: str
    undo: Callable[[], Any]
    redo: Callable[[], Any]
    key: Any = None             # what its maker knows it by (the Undo strip's)


@dataclass
class Step:
    changes: Dict[str, List[Change]] = field(default_factory=dict)  # store key -> changes
    label: str = ""             # what it did, for the status bar
    control: Any = None         # what the UI knows of the control it was made on
    action: Optional[Action] = None
    t_last: float = 0.0

    def stores(self) -> List[str]:
        return [k for k, v in self.changes.items() if v]

    def empty(self) -> bool:
        return self.action is None and not any(self.changes.values())


@dataclass
class Result:
    status: str
    text: str = ""
    step: Optional[Step] = None


# ---------------------------------------------------------------------------
# Diffing and patching plain JSON values
# ---------------------------------------------------------------------------

def snapshot(value: Any) -> Any:
    """A deep copy in JSON's own shapes (tuples become lists), so a live
    value and a saved one compare equal when the file would be the same."""
    return json.loads(json.dumps(value))


def _id_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    ids = []
    for e in value:
        if not isinstance(e, dict) or not isinstance(e.get("id"), (str, int)) \
                or isinstance(e.get("id"), bool):
            return False
        ids.append(e["id"])
    return len(set(ids)) == len(ids)


def diff(a: Any, b: Any, path: Tuple[Any, ...] = ()) -> List[Change]:
    """Every path where `b` differs from `a`: dicts key by key, lists of
    id'd dicts element by element (plus their order), anything else whole."""
    if a == b:
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        out: List[Change] = []
        for k in list(a) + [k for k in b if k not in a]:
            out += diff(a.get(k, MISSING), b.get(k, MISSING), path + (k,))
        return out
    if _id_list(a) and _id_list(b) and (a or b):
        ids_a = [e["id"] for e in a]
        ids_b = [e["id"] for e in b]
        in_b = set(ids_b)
        in_a = set(ids_a)
        out = []
        for i, e in enumerate(a):
            if e["id"] not in in_b:
                out.append(Change(path + (ById(e["id"]),), e, MISSING, at_before=i))
        for i, e in enumerate(b):
            if e["id"] not in in_a:
                out.append(Change(path + (ById(e["id"]),), MISSING, e, at_after=i))
        by_b = {e["id"]: e for e in b}
        for e in a:
            if e["id"] in in_b:
                out += diff(e, by_b[e["id"]], path + (ById(e["id"]),))
        common_a = [i for i in ids_a if i in in_b]
        common_b = [i for i in ids_b if i in in_a]
        if common_a != common_b:
            out.append(Change(path + (ORDER,), common_a, common_b))
        return out
    if (isinstance(a, list) and isinstance(b, list) and a and len(a) == len(b)
            and all(isinstance(x, dict) for x in a + b)):
        # a list of dicts that kept its length (the four modes, a rule
        # list where one rule changed): place by place
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, path + (i,))
        return out
    return [Change(path, a, b)]


def _find(lst: list, key: Any) -> int:
    for i, e in enumerate(lst):
        if isinstance(e, dict) and e.get("id") == key:
            return i
    return -1


def _key(node: dict, key: Any) -> Any:
    """`key` as the live dict holds it: a JSON copy turns int keys into
    strings, the live dict may still have the int."""
    if key not in node and isinstance(key, str):
        try:
            k = int(key)
        except ValueError:
            return key
        if k in node and str(k) == key:
            return k
    return key


def _index(step: Any) -> bool:
    return isinstance(step, int) and not isinstance(step, bool)


def lookup(root: Any, path: Iterable[Any]) -> Any:
    """The value at `path`, or MISSING."""
    node = root
    for step in path:
        if isinstance(step, ById):
            if not isinstance(node, list):
                return MISSING
            i = _find(node, step.id)
            if i < 0:
                return MISSING
            node = node[i]
        elif step is ORDER:
            if not isinstance(node, list):
                return MISSING
            return [e.get("id") for e in node if isinstance(e, dict)]
        elif _index(step) and isinstance(node, list):
            if not 0 <= step < len(node):
                return MISSING
            node = node[step]
        else:
            if not isinstance(node, dict):
                return MISSING
            step = _key(node, step)
            if step not in node:
                return MISSING
            node = node[step]
    return node


def put(root: Any, change: Change, want_before: bool) -> bool:
    """Write one side of `change` into `root`, in place. False when the
    place it goes is gone (its friend unfriended, its board deleted...)."""
    value = change.before if want_before else change.after
    at = change.at_before if want_before else change.at_after
    *parents, last = change.path
    node = root
    for step in parents:
        if isinstance(step, ById):
            if not isinstance(node, list):
                return False
            i = _find(node, step.id)
            if i < 0:
                return False
            node = node[i]
        elif _index(step) and isinstance(node, list):
            if not 0 <= step < len(node) or not isinstance(node[step], (dict, list)):
                return False
            node = node[step]
        else:
            if not isinstance(node, dict):
                return False
            step = _key(node, step)
            if not isinstance(node.get(step), (dict, list)):
                return False
            node = node[step]
    if last is ORDER:
        if not isinstance(node, list):
            return False
        rank = {fid: n for n, fid in enumerate(value or [])}
        named = sorted((e for e in node if isinstance(e, dict) and e.get("id") in rank),
                       key=lambda e: rank[e["id"]])
        slots = iter(named)
        node[:] = [next(slots) if isinstance(e, dict) and e.get("id") in rank else e
                   for e in node]
        return True
    if isinstance(last, ById):
        if not isinstance(node, list):
            return False
        i = _find(node, last.id)
        if value is MISSING:
            if i >= 0:
                del node[i]
            return True
        fresh = snapshot(value)
        if i >= 0:
            if isinstance(node[i], dict) and isinstance(fresh, dict):
                node[i].clear()             # the same dict: whoever holds it sees it
                node[i].update(fresh)
            else:
                node[i] = fresh
        else:
            node.insert(len(node) if at is None else max(0, min(at, len(node))), fresh)
        return True
    if _index(last) and isinstance(node, list):
        if not 0 <= last < len(node) or value is MISSING:
            return False
        node[last] = snapshot(value)
        return True
    if not isinstance(node, dict):
        return False
    last = _key(node, last)
    if value is MISSING:
        node.pop(last, None)
    else:
        node[last] = snapshot(value)
    return True


def apply_changes(root: Any, changes: List[Change], undo: bool) -> List[Change]:
    """Write a step's changes for one store; undo goes newest first. The
    changes that couldn't be placed come back."""
    failed = []
    for ch in (reversed(changes) if undo else changes):
        if not put(root, ch, want_before=undo):
            failed.append(ch)
    return failed


def humanize(key: Any) -> str:
    """A key as words: "toy_antistuck_enabled" -> "toy antistuck enabled"."""
    text = str(key.id if isinstance(key, ById) else key)
    return " ".join(text.replace("_", " ").split())


# ---------------------------------------------------------------------------
# One tracked store
# ---------------------------------------------------------------------------

class _Store:
    """How the history reads, writes and judges one settings store. The
    store object may define any of:

    * ``HISTORY_KEY`` / ``HISTORY_LABEL`` -- its name here, and in words;
    * ``history_state()`` -- what is saved, as plain JSON values (default:
      ``self.settings``);
    * ``history_live()`` -- the live values to write a change into (default:
      ``history_state()``), and ``history_commit(live)`` -- after writing:
      put it into effect in the store and save (default: its save);
    * ``history_ignore(path, before, after)`` -- True for what is no setting;
    * ``history_asks(current, target)`` -- the questions a step from
      `current` to `target` needs (see Ask);
    * ``history_describe(path)`` -- a setting's name in words."""

    def __init__(self, obj: Any):
        self.obj = obj
        cls = type(obj)
        self.key = getattr(obj, "HISTORY_KEY", None) or cls.__name__
        self.label = getattr(obj, "HISTORY_LABEL", None) or humanize(self.key)
        self.baseline: Any = snapshot(self.state())
        self.restored: List[Callable[[List[Change]], None]] = []

    def state(self) -> Any:
        fn = getattr(self.obj, "history_state", None)
        return fn() if callable(fn) else self.obj.settings

    def live(self) -> Any:
        fn = getattr(self.obj, "history_live", None)
        return fn() if callable(fn) else self.state()

    def commit(self, live: Any) -> None:
        fn = getattr(self.obj, "history_commit", None)
        if callable(fn):
            fn(live)
            return
        for name in ("_save", "save", "_save_settings"):
            save = getattr(self.obj, name, None)
            if callable(save):
                save()
                return

    def ignored(self, ch: Change) -> bool:
        fn = getattr(self.obj, "history_ignore", None)
        return bool(fn(ch.path, ch.before, ch.after)) if callable(fn) else False

    def asks(self, current: Any, target: Any) -> List[Ask]:
        fn = getattr(self.obj, "history_asks", None)
        return list(fn(current, target) or []) if callable(fn) else []

    def describe(self, path: Tuple[Any, ...]) -> str:
        fn = getattr(self.obj, "history_describe", None)
        name = fn(path) if callable(fn) else None
        if name:
            return name
        keys = [p for p in path if not isinstance(p, ById) and p is not ORDER]
        return humanize(keys[-1]) if keys else self.label


# ---------------------------------------------------------------------------
# The history
# ---------------------------------------------------------------------------

class SettingsHistory:
    """The app's one history. `gate()` -- did the user just do something --
    decides whether a save is a step; `context()` names the control a new
    step is made on ({"label": ..., "control": ...}, the UI's). Both
    default to "yes" / nothing, for tests and scripts."""

    def __init__(self, limit: int = LIMIT, coalesce_s: float = COALESCE_S,
                 clock: Callable[[], float] = time.monotonic,
                 gate: Optional[Callable[[], bool]] = None):
        self.limit = limit
        self.coalesce_s = coalesce_s
        self.clock = clock
        self.gate: Callable[[], bool] = gate or (lambda: True)
        self.context: Callable[[], Dict[str, Any]] = lambda: {}
        self._stores: Dict[int, _Store] = {}
        self._keys: Dict[str, _Store] = {}
        self._undo: List[Step] = []
        self._redo: List[Step] = []
        self._open: Optional[Step] = None
        self._boundary = False
        self._quiet = 0
        self._action: Optional[Step] = None
        self._lock = threading.RLock()
        self.listeners: List[Callable[[], None]] = []   # the stacks changed

    # -- stores ---------------------------------------------------------------

    def track(self, obj: Any) -> None:
        """Take a store in: what it holds now is its baseline. Again for the
        same object: its baseline is taken again (a reload)."""
        with self._lock:
            store = self._stores.get(id(obj))
            if store is None or store.obj is not obj:
                store = _Store(obj)
                old = self._keys.get(store.key)
                if old is not None and old.obj is not obj:
                    # a second store of the same kind (a reload made a new
                    # object): it takes over the name and its hooks
                    store.restored = old.restored
                    self._stores.pop(id(old.obj), None)
                self._stores[id(obj)] = store
                self._keys[store.key] = store
            else:
                store.baseline = snapshot(store.state())

    def store(self, key: str) -> Optional[_Store]:
        return self._keys.get(key)

    def on_restored(self, obj_or_key: Any, fn: Callable[[List[Change]], None]) -> None:
        """`fn(changes)` runs after an undo or redo wrote into that store:
        the facade puts it into effect and redraws."""
        with self._lock:
            store = (self._keys.get(obj_or_key) if isinstance(obj_or_key, str)
                     else self._stores.get(id(obj_or_key)))
            if store is None and not isinstance(obj_or_key, str):
                self.track(obj_or_key)
                store = self._stores[id(obj_or_key)]
            if store is not None and fn not in store.restored:
                store.restored.append(fn)

    def saved(self, obj: Any) -> None:
        """A store wrote its file. Called by the store, on any thread."""
        with self._lock:
            store = self._stores.get(id(obj))
            if store is None or store.obj is not obj:
                self.track(obj)
                return
            now = snapshot(store.state())
            changes = [ch for ch in diff(store.baseline, now) if not store.ignored(ch)]
            store.baseline = now
            if not changes or self._quiet:
                return
            if self._action is not None:
                return          # part of the action being made, which knows its way back
            if not self._user_did_it():
                return
            self._record(store, changes)

    def _user_did_it(self) -> bool:
        try:
            return bool(self.gate())
        except Exception:
            return False

    def _record(self, store: _Store, changes: List[Change]) -> None:
        t = self.clock()
        step = self._open
        if (step is None or self._boundary or not self._undo or self._undo[-1] is not step
                or step.action is not None or t - step.t_last > self.coalesce_s):
            step = Step(t_last=t)
            try:
                ctx = self.context() or {}
            except Exception:
                ctx = {}
            step.label = str(ctx.get("label") or "")
            step.control = ctx.get("control")
            self._push(step)
        mine = step.changes.setdefault(store.key, [])
        for ch in changes:
            same = next((c for c in mine if c.path == ch.path), None)
            if same is None:
                mine.append(ch)
            else:
                same.after, same.at_after = ch.after, ch.at_after
                if same.before == same.after:
                    mine.remove(same)
        step.t_last = t
        self._boundary = False
        if step.empty():
            self._undo.remove(step)
            self._open = None
        self._changed()

    def _push(self, step: Step) -> None:
        self._undo.append(step)
        del self._undo[:-self.limit]
        self._redo.clear()
        self._open = step

    def boundary(self) -> None:
        """The user started on another control: the next save is a new
        step, however soon it comes."""
        self._boundary = True

    @contextmanager
    def quiet(self):
        """Saves inside move baselines and are never steps (an undo being
        applied, a reload)."""
        with self._lock:
            self._quiet += 1
        try:
            yield
        finally:
            with self._lock:
                self._quiet -= 1

    # -- actions ----------------------------------------------------------------

    @contextmanager
    def action(self):
        """Make a change that knows its own way back:

            with history.action() as act:
                snap = book.take_control(cid)      # saves inside are its own
            act.done("removed Ears from the Avatar Remote", undo, redo)

        Nothing is recorded unless `done` is called (and the user did it)."""
        holder = _ActionHolder(self)
        with self._lock:
            outer = self._action
            self._action = Step()
        try:
            yield holder
        finally:
            with self._lock:
                self._action = outer

    def _record_action(self, act: Action) -> None:
        with self._lock:
            if self._quiet or not self._user_did_it():
                return
            step = Step(label=act.label, action=act, t_last=self.clock())
            self._push(step)
            self._open = None            # an action never takes more in
            self._changed()

    # -- reading ------------------------------------------------------------------

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def steps(self) -> List[Step]:
        return list(self._undo)

    def redoable(self) -> List[Step]:
        return list(self._redo)

    def label_of(self, step: Step) -> str:
        if step.label:
            return step.label
        for key, changes in step.changes.items():
            store = self._keys.get(key)
            if store is not None and changes:
                return f"changed {store.describe(changes[0].path)} ({store.label})"
        return "a change"

    def clear(self) -> None:
        with self._lock:
            self._undo.clear()
            self._redo.clear()
            self._open = None
            self._changed()

    def _changed(self) -> None:
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:
                pass

    # -- undo / redo ----------------------------------------------------------------

    def undo(self, ask: Optional[Callable] = None, replay: Optional[Callable] = None) -> Result:
        """Take back the newest step. `ask(asks, text, answer)` puts a
        question up and calls `answer(yes)` later -- returning False when it
        can't ask here; `replay(step, undo)` tries the step's own control
        first (the UI). Returns a Result; ASKING finishes on the answer."""
        return self._go(True, ask, replay)

    def redo(self, ask: Optional[Callable] = None, replay: Optional[Callable] = None) -> Result:
        return self._go(False, ask, replay)

    def _go(self, undo: bool, ask, replay) -> Result:
        with self._lock:
            stack = self._undo if undo else self._redo
            if not stack:
                return Result(NOTHING, "Nothing to undo" if undo else "Nothing to redo")
            step = stack[-1]
            self._open = None
            verb = "undo" if undo else "redo"
            label = self.label_of(step)
            if step.action is None:
                asks = self._asks(step, undo)
                if asks:
                    text = f"{'Undoing' if undo else 'Redoing'} “{label}” " + \
                        "; ".join(a.text for a in asks)
                    if ask is None:
                        return Result(BLOCKED, f"Didn't {verb}: it {_join(asks)} - "
                                      "that has to be asked first", step)

                    def answer(yes: bool, step=step, undo=undo) -> Result:
                        return self._answered(step, undo, yes, replay)
                    try:
                        asked = ask(asks, text, answer)
                    except Exception:
                        asked = False
                    if not asked:
                        return Result(BLOCKED, f"Didn't {verb}: it {_join(asks)}, and "
                                      "that can't be asked here", step)
                    return Result(ASKING, text, step)
            return self._apply(step, undo, replay if step.action is None else None)

    def _answered(self, step: Step, undo: bool, yes: bool, replay) -> Result:
        with self._lock:
            stack = self._undo if undo else self._redo
            if not stack or stack[-1] is not step:
                return Result(CANCELLED, "That change isn't next any more", step)
            if not yes:
                return Result(CANCELLED, f"Kept as it is: “{self.label_of(step)}”", step)
            # after Yes, written to the store: the control's own path would
            # only ask again
            return self._apply(step, undo, None)

    def _asks(self, step: Step, undo: bool) -> List[Ask]:
        out: List[Ask] = []
        for key in step.stores():
            store = self._keys.get(key)
            if store is None:
                continue
            current = snapshot(store.state())
            target = snapshot(current)
            apply_changes(target, step.changes[key], undo)
            out += store.asks(current, target)
        return out

    def _apply(self, step: Step, undo: bool, replay) -> Result:
        label = self.label_of(step)
        verb = "Undid" if undo else "Redid"
        with self.quiet():
            if step.action is not None:
                fn = step.action.undo if undo else step.action.redo
                try:
                    ok = fn()
                except Exception as e:
                    ok = f"it went wrong ({e})"
                if ok is not True:
                    why = ok if isinstance(ok, str) and ok else "it can't be done any more"
                    return Result(FAILED, f"Couldn't {'undo' if undo else 'redo'} "
                                  f"“{label}”: {why}", step)
                self._move(step, undo)
                self._rebase()
                return Result(DONE, f"{verb}: {label}", step)
            if replay is not None and step.control is not None:
                try:
                    replay(step, undo)
                except Exception:
                    pass
            missed = placed = 0
            for key in step.stores():
                store = self._keys.get(key)
                if store is None:
                    missed += len(step.changes[key])
                    continue
                state = store.state()
                want = [c for c in step.changes[key]
                        if snapshot_or_missing(lookup(state, c.path)) != snapshot_or_missing(
                            c.before if undo else c.after)]
                if not want:
                    placed += len(step.changes[key])
                    continue        # the control's own path did it all
                live = store.live()
                failed = apply_changes(live, want, undo)
                missed += len(failed)
                placed += len(step.changes[key]) - len(failed)
                try:
                    store.commit(live)
                except Exception as e:
                    print(f"[history] {store.key} save failed: {e}")
                for fn in list(store.restored):
                    try:
                        fn(want)
                    except Exception as e:
                        print(f"[history] {store.key} restore hook failed: {e}")
            self._rebase()
        if not placed:
            return Result(FAILED, f"Couldn't {'undo' if undo else 'redo'} “{label}”: "
                          "what it changed is gone", step)
        self._move(step, undo)
        text = f"{verb}: {label}"
        if missed:
            text += " (part of it is gone)"
        return Result(DONE, text, step)

    def _move(self, step: Step, undo: bool) -> None:
        src, dst = (self._undo, self._redo) if undo else (self._redo, self._undo)
        if src and src[-1] is step:
            src.pop()
        dst.append(step)
        del dst[:-self.limit]
        self._open = None
        self._changed()

    def _rebase(self) -> None:
        """Every store's baseline is what it holds now: a save that was
        still due (a debounced one) finds nothing new to record."""
        for store in self._keys.values():
            try:
                store.baseline = snapshot(store.state())
            except Exception:
                pass


class _ActionHolder:
    def __init__(self, history: SettingsHistory):
        self.history = history
        self.act: Optional[Action] = None

    def done(self, label: str, undo: Callable[[], Any], redo: Callable[[], Any],
             key: Any = None) -> None:
        """It happened: one step, inside the `with` or right after it."""
        self.act = Action(label, undo, redo, key)
        if self.history is not None:
            self.history._record_action(self.act)


def snapshot_or_missing(value: Any) -> Any:
    return value if value is MISSING else snapshot(value)


def _join(asks: List[Ask]) -> str:
    texts = list(dict.fromkeys(a.text for a in asks))
    return texts[0] if len(texts) == 1 else ", ".join(texts[:-1]) + " and " + texts[-1]


# ---------------------------------------------------------------------------
# The app's one history: stores report here (no history active: nothing)
# ---------------------------------------------------------------------------

_active: Optional[SettingsHistory] = None


def activate(history: Optional[SettingsHistory]) -> Optional[SettingsHistory]:
    """Make `history` the one stores report to (None: none). Returns the
    one it replaces."""
    global _active
    old, _active = _active, history
    return old


def active() -> Optional[SettingsHistory]:
    return _active


def track(obj: Any) -> None:
    h = _active
    if h is not None:
        try:
            h.track(obj)
        except Exception as e:
            print(f"[history] couldn't track {type(obj).__name__}: {e}")


def saved(obj: Any) -> None:
    h = _active
    if h is not None:
        try:
            h.saved(obj)
        except Exception as e:
            print(f"[history] {type(obj).__name__} save not recorded: {e}")


def on_restored(obj: Any, fn: Callable[[List[Change]], None]) -> None:
    h = _active
    if h is not None:
        h.on_restored(obj, fn)


@contextmanager
def action():
    """`SettingsHistory.action` on the active history, or a stand-in."""
    h = _active
    if h is None:
        yield _ActionHolder(None)       # done() is kept and ignored
        return
    with h.action() as holder:
        yield holder


@contextmanager
def quiet():
    h = _active
    if h is None:
        yield
        return
    with h.quiet():
        yield


# ---------------------------------------------------------------------------
# Helpers for the stores' safety questions (history_asks)
# ---------------------------------------------------------------------------

def turned_on(current: Any, target: Any, path: Iterable[Any], default: bool = False) -> bool:
    """A switch at `path` goes from off to on."""
    path = tuple(path)
    a, b = lookup(current, path), lookup(target, path)
    return bool(default if b is MISSING else b) and not bool(default if a is MISSING else a)


def raised(current: Any, target: Any, path: Iterable[Any], default: Any = None) -> bool:
    """A number at `path` goes up."""
    path = tuple(path)
    a, b = lookup(current, path), lookup(target, path)
    a = default if a is MISSING else a
    b = default if b is MISSING else b
    try:
        return float(b) > float(a)
    except (TypeError, ValueError):
        return False
