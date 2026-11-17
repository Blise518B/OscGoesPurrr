"""The Add Variable picker's groups of well-known parameters
(param_filters.py). The names pinned here were read off real avatars' OSC
configs (VRChat's OSC/<user>/Avatars/*.json, 328 avatars) and checked
against the projects that generate them -- see the module docstring."""

import pytest

import param_filters as pf
import remote_params as rp


# --- the groups, on real names ---------------------------------------------------

REAL = {
    pf.VRCHAT: [
        "AFK", "Viseme", "Voice", "GestureLeft", "GestureRightWeight", "VelocityX",
        "VelocityMagnitude", "AngularY", "Upright", "Grounded", "Seated", "TrackingType",
        "VRMode", "MuteSelf", "InStation", "Earmuffs", "IsOnFriendsList", "ScaleModified",
        "ScaleFactor", "ScaleFactorInverse", "EyeHeightAsMeters", "EyeHeightAsPercent",
        "AvatarVersion", "IsLocal", "PreviewMode", "IsAnimatorEnabled",
    ],
    pf.GOGO: [
        "Go/Locomotion", "Go/Stationary", "Go/Float", "Go/Height", "Go/PoseRadial",
        "Go/Jump&Fall", "Go/JSRF/ReadyToGrind", "Go/SVRB/Grounded", "Go/Station/Chair",
        "Go/Dash/Right/FistWeight", "Go/VRCEmote",
        "VF12_Go/Locomotion",                     # GoGo Loco inside a VRCFury prefab
    ],
    pf.FACE: [
        # VRCFaceTracking v2, its usual FT/ prefix and the older bare v2/
        "FT/v2/EyeLeftX", "FT/v2/EyeY", "FT/v2/JawOpen", "FT/v2/PupilDilation",
        "v2/EyeLidLeft", "v2/BrowPinchLeft1",
        # binary bits
        "FT/v2/EyeSquintLeft1", "FT/v2/EyeSquintLeft4", "FT/v2/JawForward1",
        "v2/CheekPuffSuckLeftNegative",
        # a prefab's own prefix in front of v2/ (VRCFT accepts any)
        "EchoFT/v2/EyeLeftX", "EchoFT/v2/PupilDilation2",
        # OSCmooth
        "OSCm/Binary/EchoFT/v2/TongueX1", "OSCm/Binary/EchoFT/v2/TongueXNegative",
        "OSCm/Proxy/EchoFT/v2/PupilDilation", "OSCm/Binary/1",
        # its status Bools
        "EyeTrackingActive", "LipTrackingActive", "ExpressionTrackingActive",
        "EyebrowTrackingActive",
        # v1 (SRanipal) names, and their bits
        "EyesY", "LeftEyeX", "JawOpen", "LeftEyeLid", "SmileSadRight", "CheekPuffLeft",
        "MouthApeShape", "MouthApeShape1", "MouthApeShape16", "TongueSteps2",
        "TongueStepsNegative", "TongueLongStep1", "EyesDilation4",
        # Jerry's VRCFT templates
        "VisemesEnable", "EyeDilationEnable", "FacialExpressionsDisabled",
        "State/TrackingActive",
        # behind VRCFury's renaming
        "VF12_EyeTrackingActive",
    ],
    pf.VRCFURY: [
        # AddDebugParamService's "VF " + part
        "VF 2022.3.22f1", "VF 1.1426.0", "VF 3.10.4", "VF N", "VF DN", "VF W",
        # the tracking conflict resolver
        "VF73_TC_current_trackingEyes", "VF73_TC_VRC Avatar Descriptor_trackingHip",
        "VF73_TC_FullControllerBuilder.Apply on GogoLoco Beyond (VRCFury)_trackingHead",
        # the Parameter Compressor
        "VF56_SyncPointer", "VF56_SyncDataNum", "VF57_SyncDataNum0", "VF57_SyncDataBool12",
        "VF57_SyncIndex1", "VF57_SyncData", "VF56_Go/Float/LastSynced",
        "VF56_Go/VRCEmote/Current", "VF56_BrushColor/LastSynced",
        # world-scale detection, the security lock
        "VF31_WSD - Pussy - Rcv", "VF4_SecurityInput",
    ],
    pf.PHYSICS: [
        "MPB_PB", "MPB_PB_Normal", "MPB_Clipping", "MPB_Interaction", "MPB_L_Squish1",
        "MPB_R_Scale", "MPB_Breast_Contacts", "VF57_MPB_Clipping",
    ],
    pf.PHYSBONES: [
        "MPB_L_IsGrabbed", "MPB_R_Angle", "MPB_L_Gravity_Stretch", "Cheek_L_Squish",
        "Cheek_R_IsPosed", "BoopPop_Stretch", "VF5_Tail_IsGrabbed",
    ],
    pf.SHOCKOSC: [
        # ShockOSC's inputs, PhysBones, feedback and config (shockosc.py) --
        # a PhysBone suffix under ShockOsc/ is ShockOSC's, not a state
        "ShockOsc/Collar", "ShockOsc/Collar_IShock", "ShockOsc/_All_CVibrate",
        "ShockOsc/Tail_Stretch", "ShockOsc/Tail_IsGrabbed", "ShockOsc/Collar_Active",
        "ShockOsc/_Any_Cooldown", "ShockOsc/_Config/_All/Paused",
    ],
    pf.OGP: [
        "OGP/ToyConnected", "OGP/Friend/Level", "OGP/Remote/Toggle1", "OGP/Off",
    ],
    pf.SPS: [
        "OGB/Orf/Pussy/PenOthersNewRoot", "OGB/Pen/Dick/TouchSelf", "OGB/Orf",
        "OGB/Socket/Pussy/DepthOthers_CollisionTag_TPS_Pen_Penetrating", "OGB/Enabled",
        "VFH/Version/10", "VFH/Beacon", "TPS_Internal/Pen/Dick/RootRoot", "OGB_ENABLED",
    ],
    pf.VF_TOGGLES: [
        "VF10_Pussy/Self/Contact/Root", "VF201_Hue", "VF194_Outfit ", "VF134_518_bHapticState",
        "VF10_SFFix BakedSpsSocket - Rcv", "VF9_spsll_SPSLL_Socket_Hole_self",
    ],
    None: [
        # an avatar's own -- never in a group
        "VRCEmote", "BoobSize", "Hat", "PantiesOff", "518H_PussyOutput", "SPS_P_Select",
        "bOSC_v1_VestFront_0", "NightMode/Hue", "WH_SFX_On",
        # look-alikes that aren't
        "Goggles", "GoGo", "FT", "v2", "Eyes", "JawOpenness", "MyAngle", "Tail_Angled",
        "EyeTracking", "VF", "VFX_On", "VF_Toggle", "OGPlus", "OGBX/Thing", "MPB",
        "ShockOscX", "MyShockOsc/Collar",
    ],
}


@pytest.mark.parametrize("group, name", [(g, n) for g, names in REAL.items() for n in names])
def test_a_real_name_lands_in_its_group(group, name):
    assert pf.group_of(name) == group


def test_every_builtin_is_vrchats_own():
    assert all(pf.group_of(n) == pf.VRCHAT for n in pf.BUILTINS)


def test_the_groups_and_their_order():
    assert pf.GROUP_KEYS == (pf.VRCHAT, pf.GOGO, pf.FACE, pf.VRCFURY, pf.PHYSICS,
                             pf.PHYSBONES, pf.SHOCKOSC, pf.OGP, pf.SPS, pf.VF_TOGGLES)
    assert sorted(pf.MATCH_ORDER) == sorted(pf.GROUP_KEYS)
    assert pf.MATCH_ORDER[-1] == pf.VF_TOGGLES           # the catch-all goes last
    labels = [g.label for g in pf.GROUPS]
    assert len(set(labels)) == len(labels)
    assert pf.BY_KEY[pf.FACE].label == "Face tracking"
    assert pf.BY_KEY[pf.VF_TOGGLES].label == "VRCFury toggles"


def test_every_tip_starts_with_a_sentence_that_stands_alone():
    for g in pf.GROUPS:
        first = g.tip.split(". ")[0].split(": ")[0]
        assert len(first) > 10 and g.tip.rstrip().endswith(".")


# --- defaults and the remembered setting -----------------------------------------

def test_everything_but_vrcfury_toggles_is_hidden_by_default():
    assert pf.default_hidden() == frozenset(pf.GROUP_KEYS) - {pf.VF_TOGGLES}


@pytest.mark.parametrize("saved", [None, {}, [], "face", {"face": "yes", "nope": True}])
def test_a_missing_or_broken_setting_means_the_defaults(saved):
    assert pf.hidden_from_setting(saved) == pf.default_hidden()


def test_the_setting_overrides_each_group_it_names():
    got = pf.hidden_from_setting({pf.VF_TOGGLES: True, pf.FACE: False})
    assert got == (pf.default_hidden() | {pf.VF_TOGGLES}) - {pf.FACE}


def test_the_setting_names_every_group_and_comes_back():
    hidden = {pf.GOGO, pf.SPS}
    saved = pf.setting_from_hidden(hidden)
    assert set(saved) == set(pf.GROUP_KEYS)
    assert pf.hidden_from_setting(saved) == hidden


def test_the_app_setting_exists_with_the_defaults():
    from settings.app import DEFAULT_APP_SETTINGS
    assert DEFAULT_APP_SETTINGS[pf.SETTING_KEY] == {}


# --- sorting a picker's list ----------------------------------------------------

AVATAR = ["AFK", "Go/Float", "FT/v2/JawOpen", "MPB_L_IsGrabbed", "Cheek_L_Angle",
          "OGB/Orf/Pussy/PenSelfNewRoot", "VF10_Outfit", "Hat", "TailWag"]


def test_the_filters_hide_their_groups():
    s = pf.split(AVATAR, pf.default_hidden())
    assert s.shown == ["Hat", "TailWag", "VF10_Outfit"]
    assert s.hidden == []                     # not listed without a search
    assert s.counts[pf.PHYSBONES] == 2 and s.counts[pf.VF_TOGGLES] == 1
    assert sum(s.counts.values()) == 7        # Hat and TailWag are in none


def test_nothing_hidden_shows_everything():
    assert pf.split(AVATAR, ()).shown == sorted(AVATAR)


def test_a_mapped_parameter_is_never_hidden():
    s = pf.split(AVATAR, pf.default_hidden(), mapped=["MPB_L_IsGrabbed", "/avatar/parameters/AFK"])
    assert "MPB_L_IsGrabbed" in s.shown and "AFK" in s.shown
    assert "Cheek_L_Angle" not in s.shown


def test_a_mapped_glob_keeps_what_it_matches():
    s = pf.split(AVATAR, pf.default_hidden(), mapped=["ogb/orf/*"])
    assert "OGB/Orf/Pussy/PenSelfNewRoot" in s.shown


def test_a_search_finds_hidden_parameters_too():
    s = pf.split(AVATAR, pf.default_hidden(), query="  a ")
    assert s.shown == ["Hat", "TailWag"]
    assert s.hidden == ["AFK", "Cheek_L_Angle", "FT/v2/JawOpen", "Go/Float",
                        "MPB_L_IsGrabbed"]
    assert s.counts[pf.FACE] == 1             # counts don't follow the search


def test_a_kept_group_stays_whatever_the_chips_say():
    s = pf.split(AVATAR, pf.default_hidden(), keep=[pf.PHYSBONES])
    assert {"MPB_L_IsGrabbed", "Cheek_L_Angle"} <= set(s.shown)


SHOCKOSC_AVATAR = AVATAR + ["ShockOsc/Collar", "ShockOsc/Collar_IShock",
                            "ShockOsc/Tail_Stretch", "ShockOsc/_Any_Active"]


def test_shockosc_is_hidden_from_the_toys_pickers():
    s = pf.split(SHOCKOSC_AVATAR, pf.default_hidden())
    assert not any(n.startswith("ShockOsc/") for n in s.shown)
    assert s.counts[pf.SHOCKOSC] == 4 and s.first == []


def test_a_first_group_comes_before_everything_else_whatever_the_chips_say():
    s = pf.split(SHOCKOSC_AVATAR, pf.default_hidden() | {pf.SHOCKOSC},
                 keep=[pf.PHYSBONES], first=[pf.SHOCKOSC])
    assert s.first == [(pf.SHOCKOSC, ["ShockOsc/Collar", "ShockOsc/Collar_IShock",
                                      "ShockOsc/Tail_Stretch", "ShockOsc/_Any_Active"])]
    assert not any(n.startswith("ShockOsc/") for n in s.shown + s.hidden)
    assert {"MPB_L_IsGrabbed", "Hat"} <= set(s.shown)
    # a search narrows it like the rest; a group with no name left isn't listed
    s = pf.split(SHOCKOSC_AVATAR, pf.default_hidden(), first=[pf.SHOCKOSC], query="collar")
    assert s.first == [(pf.SHOCKOSC, ["ShockOsc/Collar", "ShockOsc/Collar_IShock"])]
    assert pf.split(SHOCKOSC_AVATAR, (), first=[pf.SHOCKOSC], query="hat").first == []


# --- the friend's YOLO list keeps its rules (BUILTINS moved here) ----------------

def test_builtins_moved_and_settable_is_unchanged():
    assert rp.BUILTINS is pf.BUILTINS
    assert len(pf.BUILTINS) == 30
    for name in pf.BUILTINS:
        assert not rp.settable(name)
    assert not rp.settable("OGB/Orf/x/PenSelf")
    # everything else stays settable, filtered groups included
    for name in ("Hue", "Go/Float", "FT/v2/JawOpen", "MPB_PB", "VF10_Outfit", "OGP/Off",
                 "VFH/Version/10", "VRCEmote"):
        assert rp.settable(name)
