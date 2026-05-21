// OscGoesPurrr SteamVR toy driver — trampoline that exposes the user's
// connected toys as virtual tracked devices. Talks to the OscGoesPurrr
// Python app over a localhost TCP socket. See ../README.md for the
// architecture and protocol.

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "openvr_driver.h"

#pragma comment(lib, "Ws2_32.lib")

using namespace vr;

// ---- Logging --------------------------------------------------------------

static void DriverLog(const char* fmt, ...) {
    if (!VRDriverLog()) return;
    char buf[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    VRDriverLog()->Log(buf);
}

// ---- A single virtual toy device ------------------------------------------

class ToyDevice : public ITrackedDeviceServerDriver {
public:
    ToyDevice(const std::string& serial,
              const std::string& displayName,
              const std::string& iconKey,
              const std::string& iconPath,
              float battery)
        : m_serial(serial),
          m_name(displayName),
          m_iconKey(iconKey),
          m_iconPath(iconPath),
          m_battery(battery),
          m_objectId(k_unTrackedDeviceIndexInvalid),
          m_propertyContainer(k_ulInvalidPropertyContainer) {}

    // ITrackedDeviceServerDriver -------------------------------------------

    EVRInitError Activate(uint32_t unObjectId) override {
        m_objectId = unObjectId;
        m_propertyContainer = VRProperties()->TrackedDeviceToPropertyContainer(m_objectId);

        VRProperties()->SetStringProperty(m_propertyContainer, Prop_SerialNumber_String, m_serial.c_str());
        // CRITICAL: Prop_ModelNumber_String is what SteamVR matches against
        // the keys in driver.vrresources' statusicons map. So this MUST be
        // the icon-key string (e.g. "edge_2", "hush_2") — not the toy's
        // user-visible name. With the wrong value here, SteamVR can't find
        // our per-toy icon set and falls back to a generic silhouette.
        // Verified via Valve's openvr docs:
        //   "keys matching the value in Prop_ModelNumber_String are
        //    considered first for model-specific icons"
        const std::string& modelKey = m_iconKey.empty() ? m_name : m_iconKey;
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_ModelNumber_String, modelKey.c_str());
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_ManufacturerName_String, "OscGoesPurrr");
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_TrackingSystemName_String, "oscgoespurrr_toys");
        // Masquerade as a Vive tracker so SteamVR's Status window strip
        // accepts us. Verified pattern via SlimeVR-OpenVR-Driver — the strip
        // hardcodes its filter to known controller-type/render-model combos,
        // so we hand it the canonical HTC Vive tracker references. Without
        // these two strings the device is registered but invisible in the
        // strip (still queryable via the OpenVR API).
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_RenderModelName_String,
            "{htc}/rendermodels/vr_tracker_vive_1_0");
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_InputProfilePath_String,
            "{htc}/input/vive_tracker_profile.json");
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_ControllerType_String, "vive_tracker");

        // Dynamically assign a tracker role for this device. This is what
        // SlimeVR's TrackerDevice::Activate does. Without it, SteamVR's
        // Status window strip silently filters our devices out.
        //
        // Role ordering: Waist (Hips slot) goes first because it's the
        // most reliably-visible body-tracker slot in the strip — perfect
        // for A/B testing whether role binding works at all. After that,
        // we rotate through body-part roles the user is unlikely to have
        // real trackers in (shoulders, elbows, ankles, chest). Wrists are
        // intentionally avoided because Quest hand-tracking can claim
        // those slots.
        static const char* kRoles[] = {
            "TrackerRole_Waist",         // Hips — first toy lands here
            "TrackerRole_Chest",
            "TrackerRole_LeftShoulder",  "TrackerRole_RightShoulder",
            "TrackerRole_LeftElbow",     "TrackerRole_RightElbow",
            "TrackerRole_LeftAnkle",     "TrackerRole_RightAnkle",
            "TrackerRole_Camera",        "TrackerRole_Keyboard",
        };
        // Round-robin over m_objectId so multiple toys spread across slots.
        const char* role = kRoles[m_objectId % (sizeof(kRoles) / sizeof(kRoles[0]))];
        std::string devicePath = "/devices/oscgoespurrr/" + m_serial;
        EVRSettingsError settingsErr = VRSettingsError_None;
        VRSettings()->SetString(k_pch_Trackers_Section,
                                devicePath.c_str(),
                                role,
                                &settingsErr);
        if (settingsErr != VRSettingsError_None) {
            DriverLog("[ogp] SetString(trackers,%s,%s) failed: err=%d",
                      devicePath.c_str(), role, (int)settingsErr);
        } else {
            DriverLog("[ogp] Assigned %s -> %s", devicePath.c_str(), role);
        }

        // Device icons — these are what SteamVR renders in the device strip.
        // We supply the same PNG for every state because toys don't have a
        // real "searching / standby / alert" lifecycle.
        if (!m_iconPath.empty()) {
            const char* p = m_iconPath.c_str();
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceOff_String,             p);
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceSearching_String,      p);
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceSearchingAlert_String, p);
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceReady_String,           p);
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceReadyAlert_String,     p);
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceNotReady_String,        p);
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceStandby_String,         p);
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceAlertLow_String,        p);
        }

        // Battery — SteamVR shows this as a percentage in the dashboard tooltip.
        VRProperties()->SetBoolProperty(m_propertyContainer, Prop_DeviceProvidesBatteryStatus_Bool, true);
        VRProperties()->SetFloatProperty(m_propertyContainer, Prop_DeviceBatteryPercentage_Float, m_battery);
        VRProperties()->SetBoolProperty(m_propertyContainer, Prop_DeviceIsCharging_Bool, false);
        VRProperties()->SetBoolProperty(m_propertyContainer, Prop_DeviceIsWireless_Bool, true);
        VRProperties()->SetBoolProperty(m_propertyContainer, Prop_DeviceCanPowerOff_Bool, false);
        // NOTE: Prop_NeverTracked_Bool MUST be false for the SteamVR Status
        // window strip to honor our custom Prop_NamedIconPath* values. With
        // NeverTracked=true the strip falls back to a generic silhouette
        // even though the icon file loads and caches correctly. We report
        // a stationary "tracked at origin" pose to keep the lie consistent.
        VRProperties()->SetBoolProperty(m_propertyContainer, Prop_NeverTracked_Bool, false);
        // NOTE: do NOT set Prop_DeviceClass_Int32 here — that's owned by
        // SteamVR via the class passed to TrackedDeviceAdded() and setting
        // it on the property container causes the device to be silently
        // omitted from the public device list on some SteamVR builds.

        DriverLog("[ogp] Activated toy device: %s (%s) icon='%s'",
                  m_serial.c_str(), m_name.c_str(),
                  m_iconPath.empty() ? "(none)" : m_iconPath.c_str());
        return VRInitError_None;
    }

    void Deactivate() override {
        m_objectId = k_unTrackedDeviceIndexInvalid;
        m_propertyContainer = k_ulInvalidPropertyContainer;
    }

    void EnterStandby() override {}
    void* GetComponent(const char* /*pchComponentNameAndVersion*/) override { return nullptr; }
    void DebugRequest(const char* /*pchRequest*/, char* pchResponseBuffer, uint32_t unResponseBufferSize) override {
        if (unResponseBufferSize >= 1) pchResponseBuffer[0] = '\0';
    }

    DriverPose_t GetPose() override {
        return MakeIdentityPose();
    }

    static DriverPose_t MakeIdentityPose() {
        DriverPose_t pose{};
        pose.poseIsValid = true;
        pose.result = TrackingResult_Running_OK;
        pose.deviceIsConnected = true;
        pose.qWorldFromDriverRotation = { 1, 0, 0, 0 };
        pose.qDriverFromHeadRotation  = { 1, 0, 0, 0 };
        pose.qRotation = { 1, 0, 0, 0 };
        // Position 0,0,0 — these aren't real trackers in space; the strip
        // just needs us to look "alive" via periodic pose updates.
        return pose;
    }

    TrackedDeviceIndex_t ObjectId() const { return m_objectId; }

    // Hot-update from incoming IPC messages -------------------------------

    void UpdateBattery(float battery) {
        m_battery = battery;
        if (m_propertyContainer != k_ulInvalidPropertyContainer) {
            VRProperties()->SetFloatProperty(m_propertyContainer, Prop_DeviceBatteryPercentage_Float, m_battery);
        }
    }

    void UpdateName(const std::string& displayName) {
        m_name = displayName;
        if (m_propertyContainer != k_ulInvalidPropertyContainer) {
            VRProperties()->SetStringProperty(m_propertyContainer, Prop_ModelNumber_String, m_name.c_str());
        }
    }

    void UpdateIcon(const std::string& iconPath) {
        m_iconPath = iconPath;
        if (m_propertyContainer == k_ulInvalidPropertyContainer || m_iconPath.empty()) return;
        const char* p = m_iconPath.c_str();
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceOff_String,             p);
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceSearching_String,      p);
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceSearchingAlert_String, p);
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceReady_String,           p);
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceReadyAlert_String,     p);
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceNotReady_String,        p);
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceStandby_String,         p);
        VRProperties()->SetStringProperty(m_propertyContainer, Prop_NamedIconPathDeviceAlertLow_String,        p);
    }

    const std::string& Serial() const { return m_serial; }
    const std::string& IconPath() const { return m_iconPath; }
    const std::string& IconKey() const { return m_iconKey; }
    const std::string& Name() const { return m_name; }
    float Battery() const { return m_battery; }

private:
    std::string m_serial;
    std::string m_name;
    std::string m_iconKey;       // matches a key in driver.vrresources statusicons
    std::string m_iconPath;      // fallback {oscgoespurrr}/icons/<key>.png
    float m_battery;
    TrackedDeviceIndex_t m_objectId;
    PropertyContainerHandle_t m_propertyContainer;
};

// ---- Provider that owns the device list and the IPC thread ---------------

class ToyProvider : public IServerTrackedDeviceProvider {
public:
    EVRInitError Init(IVRDriverContext* pDriverContext) override {
        VR_INIT_SERVER_DRIVER_CONTEXT(pDriverContext);
        DriverLog("[ogp] ToyProvider::Init");

        // Spin up the IPC listener thread. Driver-side is server, Python-side
        // connects in. Devices get added dynamically when Python's first
        // set_devices message arrives.
        m_stop.store(false);
        m_ipcThread = std::thread(&ToyProvider::IpcThreadMain, this);
        return VRInitError_None;
    }

    void Cleanup() override {
        DriverLog("[ogp] ToyProvider::Cleanup");
        m_stop.store(true);
        if (m_listenSock != INVALID_SOCKET) {
            closesocket(m_listenSock);
            m_listenSock = INVALID_SOCKET;
        }
        if (m_clientSock != INVALID_SOCKET) {
            closesocket(m_clientSock);
            m_clientSock = INVALID_SOCKET;
        }
        if (m_ipcThread.joinable()) m_ipcThread.join();
        WSACleanup();

        std::lock_guard<std::mutex> lock(m_devicesMu);
        m_devices.clear();
        VR_CLEANUP_SERVER_DRIVER_CONTEXT();
    }

    const char* const* GetInterfaceVersions() override {
        return k_InterfaceVersions;
    }

    void RunFrame() override {
        // SteamVR polls this on every server frame. We use it to publish a
        // pose update for each virtual toy so the Status window strip
        // considers us "actively tracking" and renders our custom icons.
        // Without these updates, a device with NeverTracked=false but no
        // pose traffic gets filtered out as asleep.
        std::lock_guard<std::mutex> lock(m_devicesMu);
        for (auto& kv : m_devices) {
            auto& dev = kv.second;
            TrackedDeviceIndex_t id = dev->ObjectId();
            if (id == k_unTrackedDeviceIndexInvalid) continue;
            DriverPose_t pose = ToyDevice::MakeIdentityPose();
            VRServerDriverHost()->TrackedDevicePoseUpdated(id, pose, sizeof(pose));
        }
    }

    bool ShouldBlockStandbyMode() override { return false; }
    void EnterStandby() override {}
    void LeaveStandby() override {}

private:
    // Per-serial map. We hold devices by shared_ptr because SteamVR keeps a
    // pointer reference after TrackedDeviceAdded; we never delete a device
    // ourselves once SteamVR has accepted it (Deactivate is the lifecycle
    // SteamVR drives on its own).
    std::mutex m_devicesMu;
    std::unordered_map<std::string, std::shared_ptr<ToyDevice>> m_devices;

    std::thread m_ipcThread;
    std::atomic<bool> m_stop{false};
    SOCKET m_listenSock{INVALID_SOCKET};
    SOCKET m_clientSock{INVALID_SOCKET};


    static constexpr uint16_t IPC_PORT = 24855;

    // ---- IPC thread ------------------------------------------------------

    void IpcThreadMain() {
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
            DriverLog("[ogp] WSAStartup failed");
            return;
        }

        while (!m_stop.load()) {
            if (!StartListener()) {
                // Bind failure (port already in use, etc.) — back off and retry.
                std::this_thread::sleep_for(std::chrono::seconds(2));
                continue;
            }

            // Accept exactly one client at a time. If the Python app reconnects
            // we'll come back around and re-accept.
            SOCKET client = AcceptOne();
            if (client == INVALID_SOCKET) continue;

            m_clientSock = client;
            DriverLog("[ogp] Python client connected");
            HandleClient(client);
            DriverLog("[ogp] Python client disconnected");

            // Wipe device list when the controlling app goes away.
            ReplaceDevices({});
            m_clientSock = INVALID_SOCKET;
            closesocket(client);
        }

        if (m_listenSock != INVALID_SOCKET) {
            closesocket(m_listenSock);
            m_listenSock = INVALID_SOCKET;
        }
    }

    bool StartListener() {
        m_listenSock = socket(AF_INET, SOCK_STREAM, 0);
        if (m_listenSock == INVALID_SOCKET) return false;

        BOOL reuse = TRUE;
        setsockopt(m_listenSock, SOL_SOCKET, SO_REUSEADDR, (const char*)&reuse, sizeof(reuse));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(IPC_PORT);
        inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

        if (bind(m_listenSock, (sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
            DriverLog("[ogp] bind() failed: %d", WSAGetLastError());
            closesocket(m_listenSock);
            m_listenSock = INVALID_SOCKET;
            return false;
        }
        if (listen(m_listenSock, 1) == SOCKET_ERROR) {
            closesocket(m_listenSock);
            m_listenSock = INVALID_SOCKET;
            return false;
        }
        DriverLog("[ogp] Listening on 127.0.0.1:%u", (unsigned)IPC_PORT);
        return true;
    }

    SOCKET AcceptOne() {
        // accept() with a non-blocking-ish wait loop so Cleanup() can shut us down.
        while (!m_stop.load()) {
            fd_set rs;
            FD_ZERO(&rs);
            FD_SET(m_listenSock, &rs);
            timeval tv{1, 0};
            int sel = select(0, &rs, nullptr, nullptr, &tv);
            if (sel > 0 && FD_ISSET(m_listenSock, &rs)) {
                sockaddr_in src{};
                int srclen = sizeof(src);
                SOCKET s = accept(m_listenSock, (sockaddr*)&src, &srclen);
                return s;
            }
        }
        return INVALID_SOCKET;
    }

    void HandleClient(SOCKET s) {
        std::string buffer;
        char chunk[2048];
        while (!m_stop.load()) {
            int n = recv(s, chunk, sizeof(chunk), 0);
            if (n <= 0) return;
            buffer.append(chunk, chunk + n);
            // Process line-delimited JSON.
            for (;;) {
                size_t nl = buffer.find('\n');
                if (nl == std::string::npos) break;
                std::string line = buffer.substr(0, nl);
                buffer.erase(0, nl + 1);
                if (!line.empty()) HandleMessage(line);
            }
            // Guard against a malicious / runaway client.
            if (buffer.size() > (1 << 20)) buffer.clear();
        }
    }

    // ---- Tiny JSON-ish parser ------------------------------------------
    // We don't want to vendor a JSON library for the driver, and the wire
    // schema is intentionally rigid: messages are flat objects of strings
    // / numbers / one nested array of flat objects. This parser handles
    // exactly that shape; anything richer is ignored.

    struct Field {
        std::string key;
        std::string svalue;  // raw string content
        double nvalue = 0.0;
        bool isString = false;
        bool isNumber = false;
    };

    static void SkipWs(const std::string& s, size_t& i) {
        while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) ++i;
    }

    static bool ParseString(const std::string& s, size_t& i, std::string& out) {
        out.clear();
        if (i >= s.size() || s[i] != '"') return false;
        ++i;
        while (i < s.size()) {
            char c = s[i++];
            if (c == '"') return true;
            if (c == '\\' && i < s.size()) {
                char esc = s[i++];
                switch (esc) {
                    case 'n': out.push_back('\n'); break;
                    case 't': out.push_back('\t'); break;
                    case 'r': out.push_back('\r'); break;
                    case '"': out.push_back('"');  break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    default: out.push_back(esc); break;
                }
            } else {
                out.push_back(c);
            }
        }
        return false;
    }

    static bool ParseNumber(const std::string& s, size_t& i, double& out) {
        size_t start = i;
        if (i < s.size() && (s[i] == '-' || s[i] == '+')) ++i;
        while (i < s.size() && ((s[i] >= '0' && s[i] <= '9') || s[i] == '.' || s[i] == 'e' || s[i] == 'E' || s[i] == '+' || s[i] == '-')) ++i;
        if (i == start) return false;
        try { out = std::stod(s.substr(start, i - start)); } catch (...) { return false; }
        return true;
    }

    // Parse the value at s[i] into `f`. Recognises "string", number, or
    // a nested array (in which case we just record the slice).
    static bool ParseValue(const std::string& s, size_t& i, Field& f, std::string* arraySlice) {
        SkipWs(s, i);
        if (i >= s.size()) return false;
        char c = s[i];
        if (c == '"') {
            if (!ParseString(s, i, f.svalue)) return false;
            f.isString = true;
            return true;
        }
        if (c == '[') {
            // Slice out the array (balanced brackets, respecting strings).
            int depth = 0;
            size_t start = i;
            bool inStr = false;
            while (i < s.size()) {
                char ch = s[i++];
                if (inStr) {
                    if (ch == '\\' && i < s.size()) { ++i; continue; }
                    if (ch == '"') inStr = false;
                    continue;
                }
                if (ch == '"') inStr = true;
                else if (ch == '[') ++depth;
                else if (ch == ']') { --depth; if (depth == 0) break; }
            }
            if (arraySlice) *arraySlice = s.substr(start, i - start);
            return true;
        }
        if (c == 't' || c == 'f' || c == 'n') {
            // booleans / null — skip the word
            while (i < s.size() && isalpha((unsigned char)s[i])) ++i;
            return true;
        }
        if (ParseNumber(s, i, f.nvalue)) {
            f.isNumber = true;
            return true;
        }
        return false;
    }

    // Parse a single flat object starting at s[i] == '{'. Records primitive
    // fields into `out`. If a `devices` array is present, returns its slice
    // via `devicesSlice`.
    static bool ParseObject(const std::string& s, size_t& i,
                            std::vector<Field>& out,
                            std::string* devicesSlice = nullptr) {
        SkipWs(s, i);
        if (i >= s.size() || s[i] != '{') return false;
        ++i;
        for (;;) {
            SkipWs(s, i);
            if (i >= s.size()) return false;
            if (s[i] == '}') { ++i; return true; }
            Field f;
            if (!ParseString(s, i, f.key)) return false;
            SkipWs(s, i);
            if (i >= s.size() || s[i] != ':') return false;
            ++i;
            std::string slice;
            if (!ParseValue(s, i, f, &slice)) return false;
            if (!slice.empty() && f.key == "devices" && devicesSlice) {
                *devicesSlice = slice;
            }
            if (f.isString || f.isNumber) out.push_back(std::move(f));
            SkipWs(s, i);
            if (i < s.size() && s[i] == ',') { ++i; continue; }
            if (i < s.size() && s[i] == '}') { ++i; return true; }
        }
    }

    // ---- Message handling -----------------------------------------------

    void HandleMessage(const std::string& line) {
        size_t i = 0;
        std::vector<Field> fields;
        std::string devicesSlice;
        if (!ParseObject(line, i, fields, &devicesSlice)) {
            DriverLog("[ogp] parse error on message");
            return;
        }
        std::string type;
        for (auto& f : fields) {
            if (f.key == "type" && f.isString) type = f.svalue;
        }
        if (type == "hello") {
            DriverLog("[ogp] hello from client");
            return;
        }
        if (type == "set_devices") {
            std::vector<std::shared_ptr<ToyDevice>> incoming;
            ParseDeviceArray(devicesSlice, incoming);
            ReplaceDevices(incoming);
            return;
        }
        if (type == "battery_update") {
            std::string serial;
            float battery = 0.0f;
            for (auto& f : fields) {
                if (f.key == "serial" && f.isString) serial = f.svalue;
                else if (f.key == "battery" && f.isNumber) battery = (float)f.nvalue;
            }
            if (!serial.empty()) {
                std::lock_guard<std::mutex> lock(m_devicesMu);
                auto it = m_devices.find(serial);
                if (it != m_devices.end()) it->second->UpdateBattery(battery);
            }
            return;
        }
    }

    void ParseDeviceArray(const std::string& slice,
                          std::vector<std::shared_ptr<ToyDevice>>& out) {
        // slice begins with '[' and ends with ']'. Walk past the opening
        // bracket and parse a sequence of objects.
        if (slice.size() < 2 || slice.front() != '[') return;
        size_t i = 1;
        for (;;) {
            SkipWs(slice, i);
            if (i >= slice.size() || slice[i] == ']') return;
            std::vector<Field> fields;
            if (!ParseObject(slice, i, fields)) return;
            std::string serial, name, icon, iconKey;
            float battery = -1.0f;
            for (auto& f : fields) {
                if      (f.key == "serial"   && f.isString) serial   = f.svalue;
                else if (f.key == "name"     && f.isString) name     = f.svalue;
                else if (f.key == "icon"     && f.isString) icon     = f.svalue;
                else if (f.key == "icon_key" && f.isString) iconKey  = f.svalue;
                else if (f.key == "battery"  && f.isNumber) battery  = (float)f.nvalue;
            }
            if (!serial.empty()) {
                out.push_back(std::make_shared<ToyDevice>(
                    serial, name, iconKey, icon, battery < 0 ? 1.0f : battery));
            }
            SkipWs(slice, i);
            if (i < slice.size() && slice[i] == ',') { ++i; continue; }
        }
    }

    void ReplaceDevices(const std::vector<std::shared_ptr<ToyDevice>>& incoming) {
        std::lock_guard<std::mutex> lock(m_devicesMu);

        std::unordered_map<std::string, std::shared_ptr<ToyDevice>> incomingMap;
        for (auto& d : incoming) incomingMap[d->Serial()] = d;

        // Add brand-new serials. SteamVR holds the pointer indefinitely after
        // TrackedDeviceAdded, so we keep our shared_ptr alive in m_devices.
        // Existing serials get their battery / icon updated in place via
        // UpdateBattery / UpdateIcon (no churn — SteamVR has no public
        // RemoveDevice anyway).
        for (auto& kv : incomingMap) {
            auto existing = m_devices.find(kv.first);
            if (existing != m_devices.end()) {
                existing->second->UpdateBattery(kv.second->Battery());
                existing->second->UpdateIcon(kv.second->IconPath());
                continue;
            }
            m_devices[kv.first] = kv.second;
            VRServerDriverHost()->TrackedDeviceAdded(
                kv.first.c_str(),
                TrackedDeviceClass_GenericTracker,
                kv.second.get());
            DriverLog("[ogp] Added toy '%s' (icon_key='%s')",
                      kv.second->Serial().c_str(),
                      kv.second->IconKey().c_str());
        }
    }
};

// ---- Factory ---------------------------------------------------------------

static ToyProvider g_provider;

extern "C" __declspec(dllexport)
void* HmdDriverFactory(const char* pInterfaceName, int* pReturnCode) {
    if (0 == std::strcmp(IServerTrackedDeviceProvider_Version, pInterfaceName)) {
        return &g_provider;
    }
    if (pReturnCode) *pReturnCode = VRInitError_Init_InterfaceNotFound;
    return nullptr;
}
