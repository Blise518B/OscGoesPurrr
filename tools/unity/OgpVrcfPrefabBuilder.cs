// OscGoesPurrr — builds the VRCFury prefabs and docs/unity/
// OscGoesPurrr-VRCFury.unitypackage. Not something avatar owners install.
//
// Three prefabs, one package: "OscGoesPurrr Menu" (your own controls and the
// Friends menu under one OscGoesPurrr submenu), "OscGoesPurrr Menu (Self)"
// and "OscGoesPurrr Menu (Friends)". They share the nested menus and the
// icons (docs/unity/icons/, drawn by tools/make_menu_icons.py).
//
// tools/build_vrcf_prefab.py copies this file, its .asmdef and
// docs/unity/OGP_MenuInstaller.cs (the menu and parameter definitions both
// share) into a throwaway Editor folder of a Unity project that has the
// VRChat SDK and VRCFury, runs BuildFromCommandLine in batch mode and takes
// the folder out again.
//
// Everything is made through the SDK's and VRCFury's own APIs, so no GUID or
// serialized field is written by hand. After exporting, the package itself is
// checked rather than the assets that went into it: the built folder is
// deleted, the .unitypackage imported, the prefab put on throwaway avatars
// and VRChat's upload preprocess run on them — the pipeline a real upload
// runs, VRCFury included — and the menu and parameters that come out are
// compared with what the app expects.

#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using com.vrcfury.api;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Avatars.ScriptableObjects;
using VRC.SDKBase.Editor.BuildPipeline;
using Object = UnityEngine.Object;

namespace OscGoesPurrr.Build
{
    public static class OgpVrcfPrefabBuilder
    {
        // Everything the package brings lands in its own top-level folder,
        // Assets/OGP — apart from Assets/OscGoesPurrr, where the one-click
        // installer writes, so importing it never touches the installer's
        // assets. Only the prefab sits at the top, where it is picked up;
        // the parts it uses are in Menu/.
        private const string Dir = "Assets/OGP";
        private const string PartsDir = Dir + "/Menu";
        private const string IconsDir = PartsDir + "/Icons";
        private const string IconPath = PartsDir + "/OGP_MenuIcon.png";

        // Per prefab: its parameters, its root controls, the one-control
        // menu VRCFury merges into the avatar's root, and the prefab. The
        // Both one keeps the paths (and so the pinned GUIDs) it always had,
        // so a newer package updates an avatar that has the older one.
        private static string Suffix(OgpMenuInstaller.MenuVariant v) =>
            v == OgpMenuInstaller.MenuVariant.Both ? "" : "_" + v;
        private static string ParamsPath(OgpMenuInstaller.MenuVariant v) =>
            PartsDir + "/OGP_VRCF_Parameters" + Suffix(v) + ".asset";
        private static string ControlsPath(OgpMenuInstaller.MenuVariant v) =>
            PartsDir + "/OGP_VRCF_Controls" + Suffix(v) + ".asset";
        private static string MenuPath(OgpMenuInstaller.MenuVariant v) =>
            PartsDir + "/OGP_VRCF_Menu" + Suffix(v) + ".asset";
        private static string PrefabName(OgpMenuInstaller.MenuVariant v) =>
            v == OgpMenuInstaller.MenuVariant.Both ? "OscGoesPurrr Menu"
                : "OscGoesPurrr Menu (" + v + ")";
        private static string PrefabPath(OgpMenuInstaller.MenuVariant v) =>
            Dir + "/" + PrefabName(v) + ".prefab";
        private static readonly OgpMenuInstaller.MenuVariant[] Variants =
        {
            OgpMenuInstaller.MenuVariant.Both, OgpMenuInstaller.MenuVariant.Self,
            OgpMenuInstaller.MenuVariant.Friends,
        };

        // Everything the app listens to is under OGP/. VRCFury renames any
        // parameter its Full Controller doesn't list as global, and OSC
        // addresses the name, so a renamed one would never reach the app.
        private const string GlobalParams = "OGP/*";

        // VRChat's limit on menu icons; the SDK warns about anything larger.
        private const int IconSize = 256;
        private const double TimeoutSeconds = 600;

        private static readonly List<string> Report = new List<string>();
        private static string _packagePath;
        private static string _reportPath;
        private static DateTime _started;
        private static bool _done;

        public static void BuildFromCommandLine()
        {
            _started = DateTime.Now;
            try
            {
                _packagePath = Path.GetFullPath(Arg("-ogpOut"));
                _reportPath = Path.GetFullPath(Arg("-ogpReport"));
                var iconSource = Path.GetFullPath(Arg("-ogpIcon"));
                var iconsSource = Path.GetFullPath(Arg("-ogpIcons"));
                if (AssetDatabase.IsValidFolder(Dir))
                    throw new Exception(Dir + " already exists in this " +
                                        "project; build in one without it.");

                Build(iconSource, iconsSource);
                PinIds();
                Directory.CreateDirectory(Path.GetDirectoryName(_packagePath));
                AssetDatabase.ExportPackage(Dir, _packagePath,
                    ExportPackageOptions.Recurse);
                Log("exported " + _packagePath + " (" +
                    new FileInfo(_packagePath).Length + " bytes)");

                AssetDatabase.DeleteAsset(Dir);
                AssetDatabase.importPackageCompleted += _ => Verify();
                AssetDatabase.importPackageFailed += (_, error) =>
                    Finish(false, "import failed: " + error);
                EditorApplication.update += Watchdog;
                AssetDatabase.ImportPackage(_packagePath, false);
                // Returns with the import queued; Unity keeps running in
                // batch mode until Finish() exits.
            }
            catch (Exception e)
            {
                Finish(false, e.ToString());
            }
        }

        private static Texture2D ImportIcon(string source, string path)
        {
            File.Copy(source, path);
            AssetDatabase.ImportAsset(path);
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            importer.textureType = TextureImporterType.Default;
            importer.alphaIsTransparency = true;
            importer.mipmapEnabled = false;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.maxTextureSize = IconSize;
            importer.textureCompression = TextureImporterCompression.Compressed;
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        private static void Build(string iconSource, string iconsSource)
        {
            AssetDatabase.CreateFolder("Assets", "OGP");
            AssetDatabase.CreateFolder(Dir, "Menu");
            AssetDatabase.CreateFolder(PartsDir, "Icons");

            var appIcon = ImportIcon(iconSource, IconPath);
            var icons = new Dictionary<string, Texture2D>();
            foreach (var png in Directory.GetFiles(iconsSource, "*.png").OrderBy(f => f))
            {
                var name = Path.GetFileNameWithoutExtension(png);
                icons[name] = ImportIcon(png, IconsDir + "/" + name + ".png");
            }
            Log("imported " + icons.Count + " menu icons");
            Texture2D Icon(string name)
            {
                if (!icons.TryGetValue(name, out var tex))
                    throw new Exception("no icon " + name + ".png in " + iconsSource);
                return tex;
            }

            // The nested menus (Modes, Friends, Toys, ...) are assets of
            // their own in Menu/, shared by every prefab that has them.
            var nested = new Dictionary<string, VRCExpressionsMenu>();
            VRCExpressionsMenu Nested(string key)
            {
                if (!nested.TryGetValue(key, out var sub))
                {
                    sub = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                    AssetDatabase.CreateAsset(sub, PartsDir + "/OGP_VRCF_" + key + ".asset");
                    nested[key] = sub;
                }
                return sub;
            }

            foreach (var variant in Variants)
            {
                var parameters = ScriptableObject.CreateInstance<VRCExpressionParameters>();
                parameters.parameters = new VRCExpressionParameters.Parameter[0];
                foreach (var (name, type, defaultValue) in OgpMenuInstaller.ParametersFor(variant))
                    OgpMenuInstaller.AddOrUpdateParameter(parameters, name, type, defaultValue);
                AssetDatabase.CreateAsset(parameters, ParamsPath(variant));

                var controls = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                OgpMenuInstaller.AddControls(controls, variant, Nested, Icon);
                AssetDatabase.CreateAsset(controls, ControlsPath(variant));

                // VRCFury merges this menu into the avatar's root, so its one
                // control — the submenu, with its icon — is what appears
                // there. Its Prefix field moves it into another submenu.
                var menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                menu.controls.Add(new VRCExpressionsMenu.Control
                {
                    name = OgpMenuInstaller.RootName(variant),
                    type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                    subMenu = controls,
                    icon = variant == OgpMenuInstaller.MenuVariant.Friends ? Icon("friends") : appIcon,
                });
                AssetDatabase.CreateAsset(menu, MenuPath(variant));

                var go = new GameObject(PrefabName(variant));
                var controller = FuryComponents.CreateFullController(go);
                controller.AddMenu(menu);
                controller.AddParams(parameters);
                controller.AddGlobalParam(GlobalParams);
                PrefabUtility.SaveAsPrefabAsset(go, PrefabPath(variant));
                Object.DestroyImmediate(go);
                Log("built " + PrefabPath(variant));
            }
            foreach (var sub in nested.Values)
                EditorUtility.SetDirty(sub);
            AssetDatabase.SaveAssets();
        }

        // Unity gives every new asset a random GUID and a new prefab random
        // object IDs. A package whose GUIDs changed lands next to the older
        // copy as duplicates ("OGP_VRCF_Menu 1.asset") instead of updating
        // it, so every ID is replaced with one derived from the file's path:
        // the same on every build. tests/test_vrcf_prefab.py checks them.
        private static void PinIds()
        {
            var files = Directory.GetFiles(Dir, "*", SearchOption.AllDirectories)
                .Select(f => f.Replace('\\', '/')).Append(Dir + ".meta").ToList();
            var guids = files.Where(f => f.EndsWith(".meta"))
                .Select(f => f.Substring(0, f.Length - ".meta".Length))
                .ToDictionary(a => AssetDatabase.AssetPathToGUID(a), a => StableGuid(a));
            var yaml = files.Where(f => f.EndsWith(".meta") || f.EndsWith(".asset")
                                        || f.EndsWith(".prefab"))
                .ToDictionary(f => f, f => File.ReadAllText(f));
            var binary = files.Where(f => !yaml.ContainsKey(f))
                .ToDictionary(f => f, f => File.ReadAllBytes(f));

            AssetDatabase.DeleteAsset(Dir);
            foreach (var entry in binary)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(entry.Key));
                File.WriteAllBytes(entry.Key, entry.Value);
            }
            foreach (var entry in yaml)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(entry.Key));
                var text = entry.Value;
                foreach (var guid in guids)
                    text = text.Replace(guid.Key, guid.Value);
                if (entry.Key.EndsWith(".prefab"))
                    text = PinLocalIds(text, entry.Key);
                File.WriteAllText(entry.Key, text);
            }
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            Log("pinned the GUIDs of " + guids.Count + " assets");
        }

        // The prefab's object anchors (&id) and VRCFury's managed-reference
        // ids (rid), numbered in file order.
        private static string PinLocalIds(string text, string path)
        {
            var ids = Regex.Matches(text, @"--- !u!\d+ &(\d+)")
                .Cast<Match>().Concat(Regex.Matches(text, @"\brid: (\d+)").Cast<Match>())
                .Select(m => m.Groups[1].Value).Distinct().ToList();
            var map = ids.Select((id, i) => (id, i)).ToDictionary(
                p => p.id, p => StableLong(path + "#" + p.i).ToString());
            return Regex.Replace(text, @"\b\d+\b",
                m => map.TryGetValue(m.Value, out var pinned) ? pinned : m.Value);
        }

        private static string StableGuid(string assetPath)
        {
            return string.Concat(Md5("OscGoesPurrr:" + assetPath)
                .Select(b => b.ToString("x2")));
        }

        private static long StableLong(string key)
        {
            // Positive and never 0: Unity reserves 0 and the negatives.
            return (BitConverter.ToInt64(Md5(key), 0) & 0x0FFFFFFFFFFFFFFF) | 1;
        }

        private static byte[] Md5(string text)
        {
            using (var md5 = MD5.Create())
                return md5.ComputeHash(Encoding.UTF8.GetBytes(text));
        }

        // --- Checking the imported package ------------------------------

        private static void Verify()
        {
            try
            {
                var prefabs = Variants.ToDictionary(v => v,
                    v => AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath(v)));
                foreach (var entry in prefabs.Where(e => e.Value == null))
                    throw new Exception("the imported package has no " + PrefabPath(entry.Key));
                Log("imported the package back");
                EditorSceneManager.NewScene(NewSceneSetup.EmptyScene);

                var ok = true;
                foreach (var variant in Variants)
                {
                    var prefab = prefabs[variant];
                    var name = PrefabName(variant);
                    ok &= Scenario(name + " on an avatar with no menu of its own", prefab, variant,
                        avatar => { });
                    ok &= Scenario(name + " on an avatar whose root menu is full", prefab, variant,
                        avatar => GiveMenu(avatar, 8, false));
                }
                var both = prefabs[OgpMenuInstaller.MenuVariant.Both];
                ok &= Scenario("avatar that already has the OGP parameters", both,
                    OgpMenuInstaller.MenuVariant.Both, avatar => GiveMenu(avatar, 3, true));
                // What VRCHAT_MENU.md tells someone switching over from the
                // one-click installer rests on this one; it is reported,
                // not checked.
                ok &= Scenario("avatar that still has the installer's submenu",
                    both, OgpMenuInstaller.MenuVariant.Both, avatar =>
                    {
                        GiveMenu(avatar, 3, true);
                        var old = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
                        OgpMenuInstaller.AddControls(old);
                        avatar.GetComponent<VRCAvatarDescriptor>().expressionsMenu.controls.Add(
                            new VRCExpressionsMenu.Control
                            {
                                name = OgpMenuInstaller.SubMenuControlName,
                                type = VRCExpressionsMenu.Control.ControlType.SubMenu,
                                subMenu = old,
                            });
                    }, reportOnly: true);
                AssetDatabase.DeleteAsset(Dir);
                Finish(ok, ok ? "all checks passed" : "some checks FAILED");
            }
            catch (Exception e)
            {
                Finish(false, e.ToString());
            }
        }

        private static bool Scenario(string title, GameObject prefab,
                                     OgpMenuInstaller.MenuVariant variant,
                                     Action<GameObject> setUp,
                                     bool reportOnly = false)
        {
            Log("");
            Log("== " + title);
            var avatar = new GameObject("OGP Test Avatar");
            avatar.AddComponent<Animator>();
            var descriptor = avatar.AddComponent<VRCAvatarDescriptor>();
            // The descriptor's inspector fills the layer slots; one added
            // from code has none, and VRCFury walks them.
            descriptor.baseAnimationLayers = DefaultLayers(
                VRCAvatarDescriptor.AnimLayerType.Base,
                VRCAvatarDescriptor.AnimLayerType.Additive,
                VRCAvatarDescriptor.AnimLayerType.Gesture,
                VRCAvatarDescriptor.AnimLayerType.Action,
                VRCAvatarDescriptor.AnimLayerType.FX);
            descriptor.specialAnimationLayers = DefaultLayers(
                VRCAvatarDescriptor.AnimLayerType.Sitting,
                VRCAvatarDescriptor.AnimLayerType.TPose,
                VRCAvatarDescriptor.AnimLayerType.IKPose);
            setUp(avatar);
            PrefabUtility.InstantiatePrefab(prefab, avatar.transform);
            // Like VRCFury's own "Build a test copy": preprocess a clone so
            // the original keeps its unbuilt state.
            var clone = Object.Instantiate(avatar);
            var ok = true;
            try
            {
                if (!VRCBuildPipelineCallbacks.OnPreprocessAvatar(clone))
                {
                    Log("FAIL: the upload preprocess refused the avatar " +
                        "(see the Unity log)");
                    return false;
                }
                var built = clone.GetComponent<VRCAvatarDescriptor>();
                if (reportOnly)
                {
                    DescribeMenu(built.expressionsMenu, "");
                    return true;
                }
                ok &= CheckParameters(built.expressionParameters, variant);
                ok &= CheckMenu(built.expressionsMenu, variant);
                return ok;
            }
            finally
            {
                Object.DestroyImmediate(clone);
                Object.DestroyImmediate(avatar);
            }
        }

        private static VRCAvatarDescriptor.CustomAnimLayer[] DefaultLayers(
            params VRCAvatarDescriptor.AnimLayerType[] types)
        {
            return types.Select(t => new VRCAvatarDescriptor.CustomAnimLayer
            {
                type = t,
                isDefault = true,
            }).ToArray();
        }

        // Gives the avatar its own root menu with `count` placeholder
        // toggles, and with `ogpParameters` the five OGP parameters as the
        // one-click installer would have left them.
        private static void GiveMenu(GameObject avatar, int count, bool ogpParameters)
        {
            var descriptor = avatar.GetComponent<VRCAvatarDescriptor>();
            var parameters = ScriptableObject.CreateInstance<VRCExpressionParameters>();
            var list = new List<VRCExpressionParameters.Parameter>();
            var menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
            for (var i = 0; i < count; i++)
            {
                list.Add(new VRCExpressionParameters.Parameter
                {
                    name = "Placeholder" + i,
                    valueType = VRCExpressionParameters.ValueType.Bool,
                    networkSynced = true,
                });
                menu.controls.Add(new VRCExpressionsMenu.Control
                {
                    name = "Placeholder " + i,
                    type = VRCExpressionsMenu.Control.ControlType.Toggle,
                    parameter = new VRCExpressionsMenu.Control.Parameter
                    { name = "Placeholder" + i },
                    value = 1,
                });
            }
            parameters.parameters = list.ToArray();
            if (ogpParameters)
                foreach (var (name, type, defaultValue) in OgpMenuInstaller.Parameters)
                    OgpMenuInstaller.AddOrUpdateParameter(parameters, name, type, defaultValue);
            descriptor.customExpressions = true;
            descriptor.expressionParameters = parameters;
            descriptor.expressionsMenu = menu;
        }

        private static bool CheckParameters(VRCExpressionParameters built,
                                            OgpMenuInstaller.MenuVariant variant)
        {
            var ok = true;
            var all = built.parameters ?? new VRCExpressionParameters.Parameter[0];
            var wanted = OgpMenuInstaller.ParametersFor(variant);
            foreach (var (name, type, defaultValue) in wanted)
            {
                var found = all.Where(p => p != null && p.name == name).ToList();
                if (found.Count != 1)
                {
                    ok = Fail(name + ": found " + found.Count + " times, wanted 1");
                    continue;
                }
                var p0 = found[0];
                if (p0.valueType != type || p0.networkSynced || p0.saved
                    || Math.Abs(p0.defaultValue - defaultValue) > 1e-6)
                    ok = Fail(name + ": " + p0.valueType + ", synced " +
                              p0.networkSynced + ", saved " + p0.saved +
                              ", default " + p0.defaultValue);
            }
            // A renamed copy (VRCFury prefixes the names it isn't told are
            // global) would mean the menu drives a parameter OSC never sees;
            // one from another prefab would mean this one brings too much.
            var extra = all.Where(p => p != null && p.name.Contains("OGP/")
                && wanted.All(q => q.name != p.name))
                .Select(p => p.name).ToList();
            if (extra.Count > 0)
                ok = Fail("renamed or extra parameters: " + string.Join(", ", extra));
            Log((ok ? "ok" : "FAIL") + ": the OGP parameters, unsynced, " +
                "unsaved, not renamed (" + built.CalcTotalCost() +
                " synced bits in all)");
            return ok;
        }

        private static bool CheckMenu(VRCExpressionsMenu root, OgpMenuInstaller.MenuVariant variant)
        {
            var expected = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
            OgpMenuInstaller.AddControls(expected, variant);
            var rootName = OgpMenuInstaller.RootName(variant);
            var found = new List<(VRCExpressionsMenu.Control control, string path)>();
            FindSubmenus(root, "", new HashSet<VRCExpressionsMenu>(), found, rootName);
            Log("root menu: " + string.Join(" | ",
                root.controls.Select(c => c.name + (c.subMenu != null
                    ? " [" + c.subMenu.controls.Count + "]" : ""))));
            if (found.Count != 1)
                return Fail("found " + found.Count + " \"" + rootName + "\" submenus, wanted 1");
            var (submenu, path) = found[0];
            var ok = true;
            if (submenu.icon == null)
                ok = Fail("the submenu has no icon");
            ok &= SameMenu(submenu.subMenu, expected, path);
            ok &= CheckIcons(submenu.subMenu, path, new HashSet<VRCExpressionsMenu>());
            return ok;
        }

        // Every control shows an icon -- but the routing modes, which are
        // named after the user's own modes.
        private static bool CheckIcons(VRCExpressionsMenu menu, string path,
                                       HashSet<VRCExpressionsMenu> seen)
        {
            if (menu == null || !seen.Add(menu)) return true;
            var ok = true;
            foreach (var c in menu.controls)
            {
                var isMode = c.parameter != null && c.parameter.name == "OGP/Mode";
                if (c.icon == null && !isMode)
                    ok = Fail(path + "/" + c.name + " has no icon");
                if (c.type == VRCExpressionsMenu.Control.ControlType.SubMenu)
                    ok &= CheckIcons(c.subMenu, path + "/" + c.name, seen);
            }
            return ok;
        }

        // The built menu against the expected one, nested menus included.
        private static bool SameMenu(VRCExpressionsMenu got, VRCExpressionsMenu expected,
                                     string path)
        {
            var ok = true;
            if (got == null)
                return Fail(path + " is missing");
            if (got.controls.Count != expected.controls.Count)
                ok = Fail(path + " has " + got.controls.Count + " controls, wanted " +
                          expected.controls.Count);
            for (var i = 0; i < Math.Min(got.controls.Count, expected.controls.Count); i++)
            {
                var g = got.controls[i];
                var e = expected.controls[i];
                if (Describe(g) != Describe(e))
                    ok = Fail(path + " control " + i + " is " + Describe(g) +
                              ", wanted " + Describe(e));
                else if (e.type == VRCExpressionsMenu.Control.ControlType.SubMenu)
                    ok &= SameMenu(g.subMenu, e.subMenu, path + "/" + e.name);
            }
            Log((ok ? "ok" : "FAIL") + ": " + path + " with " + got.controls.Count +
                " controls: " + string.Join(" | ", got.controls.Select(Describe)));
            return ok;
        }

        private static void FindSubmenus(
            VRCExpressionsMenu menu, string path, HashSet<VRCExpressionsMenu> seen,
            List<(VRCExpressionsMenu.Control, string)> found, string name)
        {
            if (menu == null || !seen.Add(menu)) return;
            foreach (var c in menu.controls)
            {
                if (c.type != VRCExpressionsMenu.Control.ControlType.SubMenu) continue;
                var here = path + "/" + c.name;
                if (c.name == name)
                    found.Add((c, here));
                else
                    FindSubmenus(c.subMenu, here, seen, found, name);
            }
        }

        private static void DescribeMenu(VRCExpressionsMenu menu, string path)
        {
            Log((path == "" ? "/" : path) + ": " + string.Join(" | ",
                menu.controls.Select(c => c.name)));
            foreach (var c in menu.controls)
                if (c.type == VRCExpressionsMenu.Control.ControlType.SubMenu
                    && c.subMenu != null)
                    DescribeMenu(c.subMenu, path + "/" + c.name);
        }

        private static string Describe(VRCExpressionsMenu.Control c)
        {
            var param = c.type == VRCExpressionsMenu.Control.ControlType.RadialPuppet
                ? c.subParameters?.FirstOrDefault()?.name
                : c.parameter?.name;
            return c.name + " " + c.type + " " + param + "=" + c.value;
        }

        // --- Plumbing ---------------------------------------------------

        private static void Watchdog()
        {
            if ((DateTime.Now - _started).TotalSeconds > TimeoutSeconds)
                Finish(false, "timed out waiting for the package import");
        }

        private static void Finish(bool ok, string message)
        {
            if (_done) return;
            _done = true;
            EditorApplication.update -= Watchdog;
            Log("");
            Log((ok ? "PASS: " : "FAIL: ") + message);
            try
            {
                if (_reportPath != null)
                    File.WriteAllLines(_reportPath, Report);
            }
            catch (Exception e)
            {
                Debug.LogException(e);
            }
            EditorApplication.Exit(ok ? 0 : 1);
        }

        private static bool Fail(string message)
        {
            Log("FAIL: " + message);
            return false;
        }

        private static void Log(string line)
        {
            Report.Add(line);
            Debug.Log("[OGP prefab] " + line);
        }

        private static string Arg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            var i = Array.IndexOf(args, name);
            if (i < 0 || i + 1 >= args.Length)
                throw new ArgumentException("missing " + name + " <path>");
            return args[i + 1];
        }
    }
}
#endif
