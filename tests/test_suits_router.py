"""SuitsRouter reads the avatar once and feeds both suits. Pinned here:
contacts reach the right bHaptics dots and OWO muscles, the strength
scales both, Off and VRChat going quiet silence both (once), the page's
test holds play while VRChat is quiet but never while Off, and a suit
that's switched off or not connected gets nothing."""

import pytest

import body_map
from parameter_store import ParameterStore
from settings.suits import SuitsSettingsManager
from suits_router import SuitsRouter, owo_intensity


class FakeBh:
    def __init__(self, positions=("VestFront", "VestBack")):
        self.is_connected = True
        self._positions = set(positions)
        self.frames = {}
        self.ends = 0

    def connected_positions(self):
        return set(self._positions)

    def submit_frame(self, position, dots):
        self.frames[position] = list(dots)

    def end_all(self):
        self.ends += 1


class FakeOwo:
    def __init__(self):
        self.is_connected = True
        self.active = None
        self.freq = None
        self.ends = 0

    def set_active(self, muscles, frequency):
        self.active = dict(muscles)
        self.freq = frequency

    def end_all(self):
        self.ends += 1


class Stale:
    def __init__(self):
        self.value = False

    def is_stale(self):
        return self.value


class Clock:
    def __init__(self):
        self.t = 10.0

    def __call__(self):
        return self.t


@pytest.fixture
def rig():
    store = ParameterStore()
    bh, owo = FakeBh(), FakeOwo()
    scale = {"v": 1.0}
    clock = Clock()
    r = SuitsRouter(bh, owo, get_master_scale=lambda: scale["v"], clock=clock,
                    param_store=store)
    r._stale = Stale()
    cfg = SuitsSettingsManager().snapshot()
    r.configure(cfg, bhaptics_on=True, owo_on=True)
    return r, store, bh, owo, scale, cfg, clock


def test_a_contact_reaches_both_suits(rig):
    r, store, bh, owo, _scale, _cfg, _clock = rig
    pos, cells = body_map.OWO_REGIONS["Pectoral_L"]
    store.update_parameter(f"bOSC/v2/{pos}/{cells[0]}/others", True)
    r.tick()
    assert bh.frames["VestFront"][cells[0]] == 100
    assert sum(bh.frames["VestFront"]) == 100
    assert bh.frames["VestBack"] == [0] * 20
    assert owo.active == {"Pectoral_L": 100}
    assert owo.freq == 50
    assert r.live()["owo"]["Pectoral_L"] == 1.0


def test_strength_scales_both(rig):
    r, store, bh, owo, scale, _cfg, _clock = rig
    store.update_parameter("owo_suit_Arm_R", 1.0)
    store.update_parameter("bOSC/v2/VestBack/0/self", True)
    scale["v"] = 0.5
    r.tick()
    assert bh.frames["VestBack"][0] == 50
    # The back dot sits in Dorsal_L's patch, so OWO feels it too.
    assert owo.active == {"Arm_R": 50, "Dorsal_L": 50}


def test_owo_follows_its_muscle_top(rig):
    r, store, _bh, owo, _scale, cfg, _clock = rig
    cfg["owo"]["muscles"]["Arm_R"]["max"] = 40
    r.configure(cfg, True, True)
    store.update_parameter("owo_suit_Arm_R", 0.5)
    r.tick()
    assert owo.active == {"Arm_R": 20}


def test_off_silences_both_once(rig):
    r, store, bh, owo, scale, _cfg, _clock = rig
    store.update_parameter("owo_suit_Arm_R", 1.0)
    r.tick()
    scale["v"] = 0.0
    r.tick()
    r.tick()
    assert bh.ends == 1 and owo.ends == 1
    assert owo.active == {}
    assert all(v == 0 for frame in bh.frames.values() for v in frame)


def test_vrchat_going_quiet_silences_both(rig):
    r, store, bh, owo, _scale, _cfg, _clock = rig
    store.update_parameter("bOSC/v2/VestFront/1/others", True)
    r.tick()
    r._stale.value = True
    r.tick()
    assert bh.ends == 1 and owo.ends == 1
    assert bh.frames["VestFront"] == [0] * 20
    r._stale.value = False
    r.tick()
    assert bh.frames["VestFront"][1] == 100


def test_test_holds_play_while_quiet_but_not_while_off(rig):
    r, _store, bh, _owo, scale, _cfg, clock = rig
    r._stale.value = True
    r.hold_dot("VestBack", 3, 1.0)
    r.tick()
    assert bh.frames["VestBack"][3] == 30
    clock.t += 2.0
    r.tick()
    assert bh.frames["VestBack"][3] == 0
    r.hold_position("VestFront", 1.0)
    scale["v"] = 0.0
    r.tick()
    assert bh.frames["VestFront"] == [0] * 20


# Settings → Toy Safety's defaults, which the suits share.
TOY_SAFETY = {"enabled": True, "active_s": 1, "peaked_s": 10}


def test_a_stuck_mid_range_contact_is_cut_after_a_second(rig):
    r, store, bh, owo, _scale, _cfg, clock = rig
    r._get_antistuck = lambda: TOY_SAFETY
    store.update_parameter("bOSC_v1_VestBack_19", 0.5)
    store.update_parameter("owo_suit_Arm_R", 0.5)
    r.tick()
    assert bh.frames["VestBack"][19] == 50 and owo.active["Arm_R"] == 50
    clock.t += 0.9
    r.tick()
    assert bh.frames["VestBack"][19] == 50
    clock.t += 0.2
    r.tick()
    assert bh.frames["VestBack"] == [0] * 20
    assert owo.active == {}                        # EMS too
    store.update_parameter("bOSC_v1_VestBack_19", 0.52)    # a new value: back at once
    r.tick()
    assert bh.frames["VestBack"][19] == 52


def test_a_held_full_contact_gets_ten_seconds_then_fades(rig):
    r, store, bh, _owo, _scale, _cfg, clock = rig
    r._get_antistuck = lambda: TOY_SAFETY
    store.update_parameter("bOSC/v2/VestBack/0/others", True)
    r.tick()
    clock.t += 9.9
    r.tick()
    assert bh.frames["VestBack"][0] == 100
    clock.t += 1.6                                 # halfway down the 3 s fade
    r.tick()
    assert bh.frames["VestBack"][0] == 50
    clock.t += 2.0
    r.tick()
    assert bh.frames["VestBack"][0] == 0


def test_a_frozen_contact_doesnt_silence_a_live_one_under_it(rig):
    r, store, bh, _owo, _scale, _cfg, clock = rig
    r._get_antistuck = lambda: TOY_SAFETY
    pos, cells = body_map.OWO_REGIONS["Dorsal_L"]
    node = cells[0]
    store.update_parameter(f"bOSC_v1_{pos}_{node}", 0.6)      # frozen
    for step in range(12):                                    # OWO's, moving
        store.update_parameter("owo_suit_Dorsal_L", 0.30 + 0.01 * (step % 2))
        r.tick()
        clock.t += 0.1
    assert bh.frames[pos][node] in (30, 31)


def test_toy_safety_off_holds_and_turning_it_on_starts_the_fuse(rig):
    r, store, bh, _owo, _scale, _cfg, clock = rig
    safety = dict(TOY_SAFETY, enabled=False)
    r._get_antistuck = lambda: safety
    store.update_parameter("bOSC_v1_VestFront_3", 0.5)
    r.hold_dot("VestBack", 3, 30.0)
    r.tick()
    clock.t += 20.0
    r.tick()
    assert bh.frames["VestFront"][3] == 50
    safety["enabled"] = True
    r.tick()
    assert bh.frames["VestFront"][3] == 50         # not cut on the spot
    clock.t += 1.0
    r.tick()
    assert bh.frames["VestFront"][3] == 0
    assert bh.frames["VestBack"][3] == 30          # the page's test hold is never cut


def test_a_switched_off_or_unconnected_suit_gets_nothing(rig):
    r, store, bh, owo, _scale, cfg, _clock = rig
    store.update_parameter("owo_suit_Lumbar_L", 1.0)
    r.configure(cfg, bhaptics_on=False, owo_on=True)
    r.tick()
    assert bh.frames == {}
    assert owo.active == {"Lumbar_L": 100}
    owo.is_connected = False
    owo.active = None
    r.tick()
    assert owo.active is None


def test_only_connected_positions_are_submitted(rig):
    r, store, bh, _owo, _scale, _cfg, _clock = rig
    store.update_parameter("bOSC/v2/ForearmL/0/others", True)
    r.tick()
    assert "ForearmL" not in bh.frames
    bh._positions.add("ForearmL")
    r.tick()
    assert bh.frames["ForearmL"][0] == 100


def test_sharing_switches_are_honoured(rig):
    r, store, bh, owo, _scale, cfg, _clock = rig
    cfg["bhaptics"]["follow_owo"] = False
    cfg["owo"]["follow_bhaptics"] = False
    r.configure(cfg, True, True)
    store.update_parameter("owo_suit_Pectoral_R", 1.0)
    pos, cells = body_map.OWO_REGIONS["Dorsal_L"]
    store.update_parameter(f"bOSC/v2/{pos}/{cells[0]}/others", True)
    r.tick()
    assert sum(bh.frames["VestFront"]) == 0
    assert owo.active == {"Pectoral_R": 100}


def test_notify_wakes_only_for_body_keys(rig):
    r = rig[0]
    r._wake.clear()
    r.notify("SomethingElse")
    assert not r._wake.is_set()
    r.notify("/avatar/parameters/owo_suit_Arm_L")
    assert r._wake.is_set()
    r._wake.clear()
    r.notify("OGB/Orf/Mouth/PenOthers")
    assert r._wake.is_set()


def test_owo_intensity_edges():
    cfg = {"enabled": True, "max": 80}
    assert owo_intensity(1.0, cfg, 1.0) == 80
    assert owo_intensity(0.01, cfg, 1.0) == 0          # dead zone
    assert owo_intensity(float("nan"), cfg, 1.0) == 0
    assert owo_intensity(1.0, {"enabled": False, "max": 80}, 1.0) == 0
    assert owo_intensity(5.0, cfg, 3.0) == 80
    assert owo_intensity(1.0, cfg, 0.0) == 0
