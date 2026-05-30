# Intiface toy simulator package — strictly stand-alone, never imported by the main app.
#
# Mirror image of the `sim/` package: where `sim/` impersonates VRChat so OGP
# routes real avatar params with the game closed, `toysim/` impersonates a
# haptic toy so OGP drives a real haptic output with no hardware powered on.
#
# It connects to Intiface Central's Device Websocket Server (the same path a
# DIY ESP32 toy uses) and speaks the Lovense wire protocol, so a fully virtual
# toy shows up in Intiface's device list and OGP commands it through its normal
# Buttplug path.
