// OscGoesPurrr — one-click VRChat expression-menu installer.
//
// Drop this file anywhere inside Assets/ (e.g. Assets/OscGoesPurrr/Editor/),
// select your avatar in the Hierarchy, then run
//   Tools → OscGoesPurrr → Install VRChat Menu
//
// It adds the five OSC control parameters (OGP/Strength Float, OGP/Mode Int
// 0-3, OGP/Off Bool, OGP/Sleep Bool, OGP/Test Bool — all unsynced, i.e. ZERO
// sync bits) to the avatar's Expression Parameters, creates an "OscGoesPurrr"
// submenu asset (a strength radial, the Off / Sleep toggles, a momentary Test
// button and the four routing modes — exactly VRChat's 8-control limit), and
// links it into the avatar's root expressions menu. Everything is done through
// the VRC SDK's own API — no hand-rolled asset GUIDs — and re-running is
// idempotent (updates in place, never duplicates).
//
// Works with or without VRCFury: it edits the avatar descriptor's own
// menu/parameter assets, which VRCFury preserves and merges on top of at
// build time. See docs/VRCHAT_MENU.md for what the parameters do.

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
        private const string SubMenuControlName = "OscGoesPurrr";

        // Matches ModeManager.DEFAULT_STRENGTH.
        private const float DefaultStrength = 0.85f;

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
                AddOrUpdateParameter(parameters, StrengthParam,
                    VRCExpressionParameters.ValueType.Float, DefaultStrength);
                AddOrUpdateParameter(parameters, ModeParam,
                    VRCExpressionParameters.ValueType.Int, 0f);
                AddOrUpdateParameter(parameters, OffParam,
                    VRCExpressionParameters.ValueType.Bool, 0f);
                AddOrUpdateParameter(parameters, SleepParam,
                    VRCExpressionParameters.ValueType.Bool, 0f);
                AddOrUpdateParameter(parameters, TestParam,
                    VRCExpressionParameters.ValueType.Bool, 0f);
                EditorUtility.SetDirty(parameters);

                var subMenu = BuildSubMenu();
                var linked = LinkIntoRootMenu(descriptor, subMenu);

                AssetDatabase.SaveAssets();

                EditorUtility.DisplayDialog(
                    "OscGoesPurrr",
                    "Done!\n\n" +
                    "• OGP/Strength (Float), OGP/Mode (Int), OGP/Off, " +
                    "OGP/Sleep and OGP/Test (Bool) added — all unsynced, " +
                    "so they cost 0 sync bits.\n" +
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

        private static void AddOrUpdateParameter(
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
            // Unsynced: OSC reads/writes local values regardless, and the
            // desktop app re-asserts the mode after every avatar load, so
            // neither syncing nor saving buys anything — keep the cost at 0.
            existing.networkSynced = false;
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
            menu.controls.Clear();
            // Ordered by how often you reach for it. VRChat caps a menu at
            // 8 controls and this is exactly 8 — adding anything here means
            // dropping something or nesting another submenu.
            menu.controls.Add(new VRCExpressionsMenu.Control
            {
                // The one knob that decides how strong everything runs.
                name = "\U0001F4AA Strength",
                type = VRCExpressionsMenu.Control.ControlType.RadialPuppet,
                subParameters = new[]
                {
                    new VRCExpressionsMenu.Control.Parameter
                    { name = StrengthParam },
                },
            });
            menu.controls.Add(new VRCExpressionsMenu.Control
            {
                name = "\U0001F507 Off",
                type = VRCExpressionsMenu.Control.ControlType.Toggle,
                parameter = new VRCExpressionsMenu.Control.Parameter
                { name = OffParam },
                value = 1,
            });
            menu.controls.Add(new VRCExpressionsMenu.Control
            {
                name = "\U0001F319 Sleep",
                type = VRCExpressionsMenu.Control.ControlType.Toggle,
                parameter = new VRCExpressionsMenu.Control.Parameter
                { name = SleepParam },
                value = 1,
            });
            menu.controls.Add(new VRCExpressionsMenu.Control
            {
                // A Button (not Toggle) is momentary: the connectivity
                // pulse runs only while held.
                name = "\U0001F50D Test",
                type = VRCExpressionsMenu.Control.ControlType.Button,
                parameter = new VRCExpressionsMenu.Control.Parameter
                { name = TestParam },
                value = 1,
            });
            foreach (var (name, value) in Modes)
            {
                menu.controls.Add(new VRCExpressionsMenu.Control
                {
                    name = name,
                    type = VRCExpressionsMenu.Control.ControlType.Toggle,
                    parameter = new VRCExpressionsMenu.Control.Parameter
                    { name = ModeParam },
                    value = value,
                });
            }
            EditorUtility.SetDirty(menu);
            return menu;
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
