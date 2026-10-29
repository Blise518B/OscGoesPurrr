// OscGoesPurrr — one-click VRChat expression-menu installer.
//
// Drop this file anywhere inside Assets/ (e.g. Assets/OscGoesPurrr/Editor/),
// select your avatar in the Hierarchy, then run
//   Tools → OscGoesPurrr → Install VRChat Menu
//
// It adds the OSC control parameters (OGP/Strength Float, OGP/Mode Int 0-3,
// OGP/Off, OGP/Sleep and OGP/Test Bool, and the OGP/Friend/* and OGP/Both/*
// sets — all unsynced, i.e. ZERO sync bits) to the avatar's Expression
// Parameters, creates an "OscGoesPurrr" submenu asset (a strength radial, the
// Off / Sleep toggles, a momentary Test button, a Modes submenu with the four
// routing modes and a Friends submenu -- Toys, Shockers, Both of us -- that
// drives the friends picked in the app), and links it into the avatar's root
// expressions menu. (No icons here; the VRCFury prefabs carry them.) Everything is done through
// the VRC SDK's own API — no hand-rolled asset GUIDs — and re-running is
// idempotent (updates in place, never duplicates).
//
// Works with or without VRCFury: it edits the avatar descriptor's own
// menu/parameter assets, which VRCFury preserves and merges on top of at
// build time. See docs/VRCHAT_MENU.md for what the parameters do.
//
// The VRCFury prefabs (OscGoesPurrr-VRCFury.unitypackage: Both, Self only,
// Friends only) are built from the same parameter tables and AddControls()
// by tools/unity/OgpVrcfPrefabBuilder.cs, with the icons from
// docs/unity/icons/ — change the menu here and rebuild it with
// tools/build_vrcf_prefab.py.

#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Avatars.ScriptableObjects;

namespace OscGoesPurrr
{
    public static class OgpMenuInstaller
    {
        private const string AssetDir = "Assets/OscGoesPurrr";
        private const string SubMenuPath = AssetDir + "/OGP_Menu.asset";
        private const string StrengthParam = "OGP/Strength";
        private const string ModeParam = "OGP/Mode";
        private const string OffParam = "OGP/Off";
        private const string SleepParam = "OGP/Sleep";
        private const string TestParam = "OGP/Test";
        // Friends: they act on the friend or group picked on the app's
        // Friends page. Toys ▸
        private const string FriendLevelParam = "OGP/Friend/Level";
        private const string FriendToy1Param = "OGP/Friend/Toy1";
        private const string FriendToy2Param = "OGP/Friend/Toy2";
        private const string FriendToy3Param = "OGP/Friend/Toy3";
        private const string FriendToy4Param = "OGP/Friend/Toy4";
        private const string FriendModeParam = "OGP/Friend/Mode";
        private const string FriendSpeedParam = "OGP/Friend/Speed";
        private const string FriendRangeParam = "OGP/Friend/Range";
        private const string FriendOverrideParam = "OGP/Friend/Override";
        private const string FriendStopToysParam = "OGP/Friend/StopToys";
        private const string FriendStrengthParam = "OGP/Friend/Strength";
        // Shockers ▸
        private const string FriendShockParam = "OGP/Friend/Shock";
        private const string FriendVibrateParam = "OGP/Friend/Vibrate";
        private const string FriendBeepParam = "OGP/Friend/Beep";
        private const string FriendStopShockParam = "OGP/Friend/StopShock";
        private const string FriendShockStrengthParam = "OGP/Friend/ShockStrength";
        private const string FriendShockLengthParam = "OGP/Friend/ShockLength";
        private const string FriendWarningParam = "OGP/Friend/Warning";
        private const string FriendShocker1Param = "OGP/Friend/Shocker1";
        private const string FriendShocker2Param = "OGP/Friend/Shocker2";
        private const string FriendShocker3Param = "OGP/Friend/Shocker3";
        private const string FriendShocker4Param = "OGP/Friend/Shocker4";
        // Both of us ▸ -- the picked friend and you at once
        private const string BothLevelParam = "OGP/Both/Level";
        private const string BothModeParam = "OGP/Both/Mode";
        private const string BothSpeedParam = "OGP/Both/Speed";
        private const string BothStopParam = "OGP/Both/Stop";
        private const string BothShockParam = "OGP/Both/Shock";
        private const string BothVibrateParam = "OGP/Both/Vibrate";
        private const string BothStrengthParam = "OGP/Both/Strength";
        private const string BothLengthParam = "OGP/Both/Length";
        internal const string SubMenuControlName = "OscGoesPurrr";
        internal const string FriendsMenuControlName = "OGP Friends";

        // Matches ModeManager.DEFAULT_STRENGTH.
        private const float DefaultStrength = 0.85f;

        // Which menu a prefab brings: your own controls, the Friends ones,
        // or both under one OscGoesPurrr submenu (the one-click installer's).
        public enum MenuVariant { Both, Self, Friends }

        private static readonly (string name,
            VRCExpressionParameters.ValueType type, float defaultValue)[]
            SelfParameters =
        {
            (StrengthParam, VRCExpressionParameters.ValueType.Float, DefaultStrength),
            (ModeParam, VRCExpressionParameters.ValueType.Int, 0f),
            (OffParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (SleepParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (TestParam, VRCExpressionParameters.ValueType.Bool, 0f),
        };

        private static readonly (string name,
            VRCExpressionParameters.ValueType type, float defaultValue)[]
            FriendParameters =
        {
            (FriendLevelParam, VRCExpressionParameters.ValueType.Float, 0f),
            // Which toys / Which shockers: all on, so the menu reaches
            // every toy and shocker until you narrow it down.
            (FriendToy1Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (FriendToy2Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (FriendToy3Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (FriendToy4Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (FriendModeParam, VRCExpressionParameters.ValueType.Int, 0f),
            (FriendSpeedParam, VRCExpressionParameters.ValueType.Float, 0.5f),
            (FriendRangeParam, VRCExpressionParameters.ValueType.Float, 1f),
            (FriendOverrideParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (FriendStopToysParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (FriendStrengthParam, VRCExpressionParameters.ValueType.Float, DefaultStrength),
            (FriendShockParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (FriendVibrateParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (FriendBeepParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (FriendStopShockParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (FriendShockStrengthParam, VRCExpressionParameters.ValueType.Float, 0.25f),
            (FriendShockLengthParam, VRCExpressionParameters.ValueType.Float, 0.1f),
            (FriendWarningParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (FriendShocker1Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (FriendShocker2Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (FriendShocker3Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (FriendShocker4Param, VRCExpressionParameters.ValueType.Bool, 1f),
            (BothLevelParam, VRCExpressionParameters.ValueType.Float, 0f),
            (BothModeParam, VRCExpressionParameters.ValueType.Int, 0f),
            (BothSpeedParam, VRCExpressionParameters.ValueType.Float, 0.5f),
            (BothStopParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (BothShockParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (BothVibrateParam, VRCExpressionParameters.ValueType.Bool, 0f),
            (BothStrengthParam, VRCExpressionParameters.ValueType.Float, 0.25f),
            (BothLengthParam, VRCExpressionParameters.ValueType.Float, 0.1f),
        };

        // The control parameters, all unsynced and unsaved: OSC
        // reads/writes local values regardless, and the desktop app
        // re-asserts its state after every avatar load, so neither syncing
        // nor saving buys anything — the cost stays at 0 sync bits.
        internal static readonly (string name,
            VRCExpressionParameters.ValueType type, float defaultValue)[]
            Parameters = SelfParameters.Concat(FriendParameters).ToArray();

        internal static (string name, VRCExpressionParameters.ValueType type, float defaultValue)[]
            ParametersFor(MenuVariant variant)
        {
            return variant == MenuVariant.Self ? SelfParameters
                : variant == MenuVariant.Friends ? FriendParameters : Parameters;
        }

        // The control that opens the variant's menu from the avatar's root.
        internal static string RootName(MenuVariant variant)
        {
            return variant == MenuVariant.Friends ? FriendsMenuControlName : SubMenuControlName;
        }

        // Slot order is the OSC contract with the desktop app — do not
        // reorder. Renaming modes in the app does not change the numbers.
        // A mode is a ROUTING (what drives what), not an intensity — that
        // is OGP/Strength.
        private static readonly (string name, int value)[] Modes =
        {
            ("\U0001F517 Combined", 0),
            ("\U0001F500 Separate", 1),
            ("\U0001F0CF Custom 1", 2),
            ("\U0001F3B2 Custom 2", 3),
        };

        // The auto modes, OGP/Friend/Mode and OGP/Both/Mode 1-8, in the
        // app's friend_patterns.WAVES order -- the same contract.
        private static readonly (string name, string icon)[] AutoModes =
        {
            ("Sine", "wave_sine"), ("Square", "wave_square"), ("Triangle", "wave_triangle"),
            ("Saw", "wave_saw"), ("Random", "wave_random"), ("Heartbeat", "wave_heart"),
            ("Build-up", "wave_build"), ("Oscillate", "wave_osc"),
        };

        [MenuItem("Tools/OscGoesPurrr/Install VRChat Menu")]
        public static void Install()
        {
            var go = Selection.activeGameObject;
            var descriptor = go != null ? go.GetComponent<VRCAvatarDescriptor>() : null;
            if (descriptor == null)
            {
                EditorUtility.DisplayDialog(
                    "OscGoesPurrr",
                    "Select your avatar (the object with the VRC Avatar " +
                    "Descriptor) in the Hierarchy first, then run this again.",
                    "OK");
                return;
            }

            try
            {
                EnsureAssetDir();
                var parameters = EnsureParameters(descriptor);
                foreach (var (name, type, defaultValue) in Parameters)
                    AddOrUpdateParameter(parameters, name, type, defaultValue);
                EditorUtility.SetDirty(parameters);

                var subMenu = BuildSubMenu();
                var linked = LinkIntoRootMenu(descriptor, subMenu);

                AssetDatabase.SaveAssets();

                EditorUtility.DisplayDialog(
                    "OscGoesPurrr",
                    "Done!\n\n" +
                    "• OGP/Strength (Float), OGP/Mode (Int), OGP/Off, " +
                    "OGP/Sleep, OGP/Test (Bool) and the OGP/Friend/* set " +
                    "added — all unsynced, so they cost 0 sync bits.\n" +
                    "• \"OscGoesPurrr\" submenu " +
                    (linked ? "linked into your expressions menu."
                            : "created, but your root menu already has 8 " +
                              "controls — add the submenu asset at\n  " +
                              SubMenuPath + "\nto any menu with a free slot.") +
                    "\n\nUpload the avatar. If the app doesn't react to the " +
                    "menu afterwards, delete the stale OSC config folder " +
                    "(see docs/VRCHAT_MENU.md → Troubleshooting).",
                    "OK");
            }
            catch (Exception e)
            {
                EditorUtility.DisplayDialog(
                    "OscGoesPurrr",
                    "Install failed: " + e.Message +
                    "\n\nNothing destructive was done. Full details are in " +
                    "the Console; the manual setup in docs/VRCHAT_MENU.md " +
                    "always works as a fallback.",
                    "OK");
                Debug.LogException(e);
            }
        }

        private static void EnsureAssetDir()
        {
            if (!AssetDatabase.IsValidFolder(AssetDir))
                AssetDatabase.CreateFolder("Assets", "OscGoesPurrr");
        }

        // The avatar may have no custom expressions yet, or share default
        // SDK assets. In both cases give it its own parameters asset under
        // Assets/OscGoesPurrr so we never mutate an SDK-shipped default.
        private static VRCExpressionParameters EnsureParameters(
            VRCAvatarDescriptor descriptor)
        {
            var current = descriptor.expressionParameters;
            if (current != null && IsEditable(current))
            {
                Undo.RecordObject(current, "OscGoesPurrr parameters");
                return current;
            }
            var fresh = ScriptableObject.CreateInstance<VRCExpressionParameters>();
            fresh.parameters = current != null && current.parameters != null
                ? current.parameters.Select(Clone).ToArray()
                : new VRCExpressionParameters.Parameter[0];
            AssetDatabase.CreateAsset(fresh, AssetDir + "/OGP_Parameters.asset");
            Undo.RecordObject(descriptor, "OscGoesPurrr parameters");
            descriptor.customExpressions = true;
            descriptor.expressionParameters = fresh;
            EditorUtility.SetDirty(descriptor);
            return fresh;
        }

        private static bool IsEditable(UnityEngine.Object asset)
        {
            var path = AssetDatabase.GetAssetPath(asset);
            // Immutable = ships inside a package (the SDK defaults) — clone
            // instead of mutating.
            return !string.IsNullOrEmpty(path) && path.StartsWith("Assets/");
        }

        private static VRCExpressionParameters.Parameter Clone(
            VRCExpressionParameters.Parameter p)
        {
            return new VRCExpressionParameters.Parameter
            {
                name = p.name,
                valueType = p.valueType,
                saved = p.saved,
                defaultValue = p.defaultValue,
                networkSynced = p.networkSynced,
            };
        }

        internal static void AddOrUpdateParameter(
            VRCExpressionParameters parameters, string name,
            VRCExpressionParameters.ValueType type, float defaultValue)
        {
            var list = (parameters.parameters
                        ?? new VRCExpressionParameters.Parameter[0]).ToList();
            var existing = list.FirstOrDefault(p => p != null && p.name == name);
            if (existing == null)
            {
                existing = new VRCExpressionParameters.Parameter { name = name };
                list.Add(existing);
            }
            existing.valueType = type;
            existing.defaultValue = defaultValue;
            existing.networkSynced = false;     // see Parameters
            existing.saved = false;
            parameters.parameters = list.ToArray();
        }

        private static VRCExpressionsMenu BuildSubMenu()
        {
            var menu = AssetDatabase.LoadAssetAtPath<VRCExpressionsMenu>(SubMenuPath);
            if (menu == null)
            {
                menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                AssetDatabase.CreateAsset(menu, SubMenuPath);
            }
            Undo.RecordObject(menu, "OscGoesPurrr submenu");
            AddControls(menu, MenuVariant.Both, SubMenuAsset, _ => null);
            EditorUtility.SetDirty(menu);
            return menu;
        }

        // The nested menus (Modes, Friends, ...) each live in an asset of
        // their own next to the submenu, updated in place on a re-run.
        private static VRCExpressionsMenu SubMenuAsset(string key)
        {
            var path = AssetDir + "/OGP_Menu_" + key + ".asset";
            var menu = AssetDatabase.LoadAssetAtPath<VRCExpressionsMenu>(path);
            if (menu == null)
            {
                menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                AssetDatabase.CreateAsset(menu, path);
            }
            Undo.RecordObject(menu, "OscGoesPurrr submenu");
            EditorUtility.SetDirty(menu);
            return menu;
        }

        // The submenu's controls, replacing whatever the menu held; nested
        // menus in memory (for comparing against a built avatar).
        internal static void AddControls(VRCExpressionsMenu menu)
        {
            AddControls(menu, MenuVariant.Both,
                _ => ScriptableObject.CreateInstance<VRCExpressionsMenu>(), _ => null);
        }

        internal static void AddControls(VRCExpressionsMenu menu, MenuVariant variant)
        {
            AddControls(menu, variant,
                _ => ScriptableObject.CreateInstance<VRCExpressionsMenu>(), _ => null);
        }

        // `subMenu(key)` hands back the (empty or stale) menu to fill for one
        // nested menu: "Modes", "Friends", "FriendToys", "FriendAuto",
        // "FriendWhichToys", "FriendShockers", "FriendWhichShockers",
        // "FriendBoth", "BothAuto". `icon(name)` the icon to show (one of
        // docs/unity/icons/*.png by file name), or null. VRChat caps every
        // menu at 8 controls.
        internal static void AddControls(VRCExpressionsMenu menu, MenuVariant variant,
                                         Func<string, VRCExpressionsMenu> subMenu,
                                         Func<string, Texture2D> icon)
        {
            menu.controls.Clear();
            if (variant == MenuVariant.Friends)
            {
                FillFriendsMenu(menu, subMenu, icon);
                return;
            }
            // Ordered by how often you reach for it.
            // The one knob that decides how strong everything runs.
            menu.controls.Add(Radial("Strength", StrengthParam, icon("strength")));
            menu.controls.Add(Toggle("Off", OffParam, 1, icon("off")));
            menu.controls.Add(Toggle("Sleep", SleepParam, 1, icon("sleep")));
            // A Button (not Toggle) is momentary: the connectivity pulse
            // runs only while held.
            menu.controls.Add(Button("Test", TestParam, icon("test")));
            var modes = subMenu("Modes");
            modes.controls.Clear();
            foreach (var (name, value) in Modes)
                modes.controls.Add(Toggle(name, ModeParam, value, null));
            menu.controls.Add(Folder("Modes", modes, icon("modes")));
            if (variant == MenuVariant.Both)
            {
                var friends = subMenu("Friends");
                FillFriendsMenu(friends, subMenu, icon);
                menu.controls.Add(Folder("Friends", friends, icon("friends")));
            }
        }

        // Everything here acts on the friend or group picked on the app's
        // Friends page, each friend within what they allow; Both of us on
        // you as well (see docs/VRCHAT_MENU.md).
        private static void FillFriendsMenu(VRCExpressionsMenu friends,
                                            Func<string, VRCExpressionsMenu> subMenu,
                                            Func<string, Texture2D> icon)
        {
            friends.controls.Clear();

            var toys = subMenu("FriendToys");
            toys.controls.Clear();
            // Level is direct control: moving it ends an auto mode (apart
            // from Oscillate, which swings around it).
            toys.controls.Add(Radial("Level", FriendLevelParam, icon("level")));
            toys.controls.Add(Folder("Auto mode", AutoMenu(subMenu("FriendAuto"), FriendModeParam, icon),
                                     icon("auto")));
            toys.controls.Add(Radial("Speed", FriendSpeedParam, icon("speed")));
            toys.controls.Add(Radial("Range", FriendRangeParam, icon("range")));
            toys.controls.Add(Toggle("Override", FriendOverrideParam, 1, icon("override")));
            var which = subMenu("FriendWhichToys");
            which.controls.Clear();
            foreach (var (n, param) in new[]
                     {
                         (1, FriendToy1Param), (2, FriendToy2Param),
                         (3, FriendToy3Param), (4, FriendToy4Param),
                     })
                which.controls.Add(Toggle("Toy " + n, param, 1, icon("toy" + n)));
            toys.controls.Add(Folder("Which toys", which, icon("which_toys")));
            toys.controls.Add(Button("Stop toys", FriendStopToysParam, icon("stop_toys")));
            friends.controls.Add(Folder("Toys", toys, icon("toys")));

            var shockers = subMenu("FriendShockers");
            shockers.controls.Clear();
            // Buttons: one operation per press, however long it is held.
            shockers.controls.Add(Button("Shock", FriendShockParam, icon("shock")));
            // "Shocker vibrate", not "Vibrate": in a menu full of toys it reads as
            // the toys' (Blise's call, 2026-10-28)
            shockers.controls.Add(Button("Shocker vibrate", FriendVibrateParam, icon("vibrate")));
            shockers.controls.Add(Button("Beep", FriendBeepParam, icon("beep")));
            shockers.controls.Add(Button("Stop", FriendStopShockParam, icon("stop")));
            shockers.controls.Add(Radial("Strength", FriendShockStrengthParam, icon("shock_strength")));
            shockers.controls.Add(Radial("Length", FriendShockLengthParam, icon("length")));
            shockers.controls.Add(Toggle("Warning", FriendWarningParam, 1, icon("warning")));
            var whichShockers = subMenu("FriendWhichShockers");
            whichShockers.controls.Clear();
            foreach (var (n, param) in new[]
                     {
                         (1, FriendShocker1Param), (2, FriendShocker2Param),
                         (3, FriendShocker3Param), (4, FriendShocker4Param),
                     })
                whichShockers.controls.Add(Toggle("Shocker " + n, param, 1, icon("shocker" + n)));
            shockers.controls.Add(Folder("Which shockers", whichShockers, icon("which_shockers")));
            friends.controls.Add(Folder("Shockers", shockers, icon("shockers")));

            var both = subMenu("FriendBoth");
            both.controls.Clear();
            both.controls.Add(Radial("Level", BothLevelParam, icon("level")));
            both.controls.Add(Folder("Auto mode", AutoMenu(subMenu("BothAuto"), BothModeParam, icon),
                                     icon("auto")));
            both.controls.Add(Radial("Speed", BothSpeedParam, icon("speed")));
            both.controls.Add(Button("Stop", BothStopParam, icon("stop_toys")));
            both.controls.Add(Button("Shock", BothShockParam, icon("shock")));
            both.controls.Add(Button("Shocker vibrate", BothVibrateParam, icon("vibrate")));
            both.controls.Add(Radial("Strength", BothStrengthParam, icon("shock_strength")));
            both.controls.Add(Radial("Length", BothLengthParam, icon("length")));
            friends.controls.Add(Folder("Both of us", both, icon("both")));

            friends.controls.Add(Radial("Their strength", FriendStrengthParam, icon("their_strength")));
        }

        private static VRCExpressionsMenu AutoMenu(VRCExpressionsMenu auto, string param,
                                                   Func<string, Texture2D> icon)
        {
            auto.controls.Clear();
            for (var i = 0; i < AutoModes.Length; i++)
                auto.controls.Add(Toggle(AutoModes[i].name, param, i + 1, icon(AutoModes[i].icon)));
            return auto;
        }

        private static VRCExpressionsMenu.Control Toggle(string name, string param, int value,
                                                         Texture2D icon)
        {
            return new VRCExpressionsMenu.Control
            {
                name = name,
                icon = icon,
                type = VRCExpressionsMenu.Control.ControlType.Toggle,
                parameter = new VRCExpressionsMenu.Control.Parameter { name = param },
                value = value,
            };
        }

        private static VRCExpressionsMenu.Control Button(string name, string param, Texture2D icon)
        {
            return new VRCExpressionsMenu.Control
            {
                name = name,
                icon = icon,
                type = VRCExpressionsMenu.Control.ControlType.Button,
                parameter = new VRCExpressionsMenu.Control.Parameter { name = param },
                value = 1,
            };
        }

        private static VRCExpressionsMenu.Control Radial(string name, string param, Texture2D icon)
        {
            return new VRCExpressionsMenu.Control
            {
                name = name,
                icon = icon,
                type = VRCExpressionsMenu.Control.ControlType.RadialPuppet,
                subParameters = new[] { new VRCExpressionsMenu.Control.Parameter { name = param } },
            };
        }

        private static VRCExpressionsMenu.Control Folder(string name, VRCExpressionsMenu menu,
                                                         Texture2D icon)
        {
            return new VRCExpressionsMenu.Control
            {
                name = name,
                icon = icon,
                type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                subMenu = menu,
            };
        }

        private static bool LinkIntoRootMenu(
            VRCAvatarDescriptor descriptor, VRCExpressionsMenu subMenu)
        {
            var root = descriptor.expressionsMenu;
            if (root == null || !IsEditable(root))
            {
                var fresh = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                if (root != null)
                    fresh.controls.AddRange(root.controls);
                AssetDatabase.CreateAsset(fresh, AssetDir + "/OGP_RootMenu.asset");
                Undo.RecordObject(descriptor, "OscGoesPurrr root menu");
                descriptor.customExpressions = true;
                descriptor.expressionsMenu = fresh;
                EditorUtility.SetDirty(descriptor);
                root = fresh;
            }
            else
            {
                Undo.RecordObject(root, "OscGoesPurrr root menu");
            }

            if (root.controls.Any(c =>
                    c.type == VRCExpressionsMenu.Control.ControlType.SubMenu
                    && c.subMenu == subMenu))
                return true;    // already linked — idempotent re-run
            if (root.controls.Count >= 8)
                return false;   // no free slot; the caller explains
            root.controls.Add(new VRCExpressionsMenu.Control
            {
                name = SubMenuControlName,
                type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                subMenu = subMenu,
            });
            EditorUtility.SetDirty(root);
            return true;
        }
    }
}
#endif
