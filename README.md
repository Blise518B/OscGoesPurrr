# OscGoesPurrr 🐾
The ultimate, lightning-fast haptic feedback router for VRChat.

OscGoesPurrr listens to your VRChat avatar's interactions (like touching, petting, or penetration) and perfectly translates them into smooth vibrations for your Bluetooth toys. Built with a modern, dark-mode UI and a bulletproof "Shadow State" routing engine, it guarantees zero lag, no stuck vibrations, and effortless multi-zone routing.

## ✨ Features
* **Auto-Discovery:** Automatically finds VRChat via mDNS—no typing IP addresses or ports.
* **Shadow State Engine:** Downloads your avatar's exact parameter list to ensure flawless, stutter-free routing.
* **Multi-Zone Support:** Bind a single toy to multiple body parts (e.g., Head, Ears, and Tail) simultaneously using an intuitive checkbox menu.
* **Intiface Integration:** Supports nearly every Bluetooth vibrator on the market via Buttplug.io.
* **Real-Time Debugger:** See exactly what OSC data your avatar is sending live in the app.

## 🚀 Installation

**Prerequisites:**
1. Install [Python 3.10+](https://www.python.org/downloads/).
2. Install [Intiface Central](https://intiface.com/central/) (required to connect your toys to your PC).

**Setup:**
1. Clone or download this repository.
2. Open a terminal in the folder and install the dependencies:
   ```bash
   pip install -r requirements.txt
   