# hardware_monitor.py
# Polls system hardware (CPU / RAM / GPU / VRAM) on a background thread and
# pushes the values to VRChat over OSC. Pure engine — owns its state, talks
# to the outside world via a config-getter and an OSC-send callback.
#
# Architecture parallels steamvr_router / bhaptics_engine: cheap stateless
# poll loop, debounced output so we don't flood VRChat with unchanged
# values. The UI reads `snapshot()` for live display.

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Any

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    psutil = None  # type: ignore
    _HAS_PSUTIL = False

# NVIDIA GPU via NVML. Optional — if absent we just report GPU as N/A.
try:
    import pynvml  # type: ignore
    _HAS_NVML = True
except Exception:
    try:
        # The "nvidia-ml-py" pip distribution exposes the same module.
        import pynvml  # type: ignore
        _HAS_NVML = True
    except Exception:
        pynvml = None  # type: ignore
        _HAS_NVML = False


_BYTES_PER_GB = 1024.0 ** 3


@dataclass
class HardwareStats:
    """Latest poll snapshot. Values are None when unavailable."""
    cpu_percent: Optional[float] = None       # 0..100
    ram_used_gb: Optional[float] = None
    ram_total_gb: Optional[float] = None
    gpu_percent: Optional[float] = None       # 0..100
    vram_used_gb: Optional[float] = None
    vram_total_gb: Optional[float] = None
    gpu_name: Optional[str] = None
    gpu_backend: str = "none"                 # "nvml" | "none"
    last_update: float = 0.0
    error: Optional[str] = None
    # last_sent_values tracks the actual OSC payload per stat key so the UI
    # can display what was last transmitted.  Keyed by stat name
    # (cpu_percent, ram_used_gb, …).
    last_sent_values: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cpu_percent": self.cpu_percent,
            "ram_used_gb": self.ram_used_gb,
            "ram_total_gb": self.ram_total_gb,
            "gpu_percent": self.gpu_percent,
            "vram_used_gb": self.vram_used_gb,
            "vram_total_gb": self.vram_total_gb,
            "gpu_name": self.gpu_name,
            "gpu_backend": self.gpu_backend,
            "last_update": self.last_update,
            "error": self.error,
            "has_psutil": _HAS_PSUTIL,
            "has_nvml": _HAS_NVML,
            "last_sent_values": dict(self.last_sent_values),
        }


# VRChat avatar parameters always live under /avatar/parameters/, so we hide
# that prefix from the user — they only see/edit the parameter name. The
# prefix is added back at send time.
OSC_PARAM_PREFIX = "/avatar/parameters/"

# Default short parameter names (what the user sees in the UI).
DEFAULT_ADDRESSES: Dict[str, str] = {
    "cpu_percent":   "HW_CPU",
    "ram_used_gb":   "HW_RAM_Used",
    "ram_total_gb":  "HW_RAM_Total",
    "gpu_percent":   "HW_GPU",
    "vram_used_gb":  "HW_VRAM_Used",
    "vram_total_gb": "HW_VRAM_Total",
}


def _full_osc_address(name: str) -> str:
    """Translate a user-facing parameter name into the actual OSC address.
    Accepts already-prefixed addresses for forward compatibility with old
    configs that stored the full path."""
    n = (name or "").strip()
    if not n:
        return ""
    if n.startswith("/"):
        return n
    return OSC_PARAM_PREFIX + n.lstrip("/")


class HardwareMonitorEngine:
    """Background poller. Reads CPU/RAM via psutil and (optionally) NVIDIA GPU
    metrics via NVML. Pushes values to VRChat through an injected `send_osc`
    callback. The UI reads `snapshot()` for live display."""

    def __init__(
        self,
        get_config: Callable[[], Dict[str, Any]],
        send_osc: Callable[[str, float], None],
    ):
        self._get_config = get_config
        self._send_osc = send_osc

        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stats = HardwareStats()
        self._last_sent: Dict[str, float] = {}

        # NVML handle is opened lazily on first GPU poll so we don't pay the
        # init cost when the user disables GPU monitoring.
        self._nvml_inited = False
        self._nvml_handle = None

    # -------- Lifecycle --------

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="HardwareMonitor"
        )
        self._thread.start()

    def stop(self):
        self._stop_evt.set()
        self._shutdown_nvml()

    # -------- Public read-side --------

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._stats.as_dict()

    # -------- Internals --------

    def _run(self):
        # Prime psutil's per-CPU counters so the first read returns a useful
        # delta instead of 0.0.
        if _HAS_PSUTIL:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

        while not self._stop_evt.is_set():
            cfg = {}
            try:
                cfg = self._get_config() or {}
            except Exception:
                cfg = {}
            poll_rate = float(cfg.get("poll_rate_s", 2.0))
            if poll_rate < 0.25:
                poll_rate = 0.25

            if bool(cfg.get("enabled", True)):
                try:
                    self._poll_once(cfg)
                except Exception as e:
                    with self._lock:
                        self._stats.error = f"poll: {e}"

            # Sleep in small slices so stop() is responsive.
            slept = 0.0
            while slept < poll_rate and not self._stop_evt.is_set():
                step = min(0.1, poll_rate - slept)
                time.sleep(step)
                slept += step

    def _poll_once(self, cfg: Dict[str, Any]):
        s = HardwareStats()
        s.last_update = time.time()

        if _HAS_PSUTIL:
            try:
                s.cpu_percent = float(psutil.cpu_percent(interval=None))
            except Exception as e:
                s.error = f"cpu: {e}"
            try:
                vm = psutil.virtual_memory()
                s.ram_used_gb = float(vm.used) / _BYTES_PER_GB
                s.ram_total_gb = float(vm.total) / _BYTES_PER_GB
            except Exception as e:
                s.error = (s.error or "") + f" ram: {e}"
        else:
            s.error = "psutil not installed"

        gpu_enabled = bool(cfg.get("gpu_enabled", True))
        if gpu_enabled and _HAS_NVML:
            try:
                self._read_nvml(s)
                s.gpu_backend = "nvml"
            except Exception as e:
                s.error = (s.error or "") + f" gpu: {e}"
                s.gpu_backend = "none"

        # Preserve last_sent_values from the previous snapshot so the UI can
        # still display the last transmitted value even when a stat is
        # toggled off this cycle.
        with self._lock:
            s.last_sent_values = dict(self._stats.last_sent_values)

        # Publish snapshot
        with self._lock:
            self._stats = s

        # Send OSC. Each value gets its own configured address; only send
        # when the value actually changed (debounce noise off the wire).
        if not bool(cfg.get("send_osc", True)):
            return

        addresses: Dict[str, str] = dict(DEFAULT_ADDRESSES)
        addresses.update({k: v for k, v in (cfg.get("addresses") or {}).items() if v})
        # Expand short names → full /avatar/parameters/<name> at send time.
        addresses = {k: _full_osc_address(v) for k, v in addresses.items()}

        toggles: Dict[str, bool] = cfg.get("send_toggles") or {}

        def _maybe_send(key: str, value: Optional[float], scale_0_1: bool = False):
            if value is None:
                return
            if not toggles.get(key, True):
                return
            addr = addresses.get(key)
            if not addr:
                return
            try:
                out = float(value) / 100.0 if scale_0_1 else float(value)
            except (TypeError, ValueError):
                return
            prev = self._last_sent.get(addr)
            if prev is not None and abs(prev - out) < 1e-4:
                return
            try:
                self._send_osc(addr, out)
                self._last_sent[addr] = out
                # Track the transmitted value (keyed by stat name) for the UI.
                s.last_sent_values[key] = out
            except Exception as e:
                with self._lock:
                    self._stats.error = f"osc: {e}"

        _maybe_send("cpu_percent",   s.cpu_percent,  scale_0_1=True)
        _maybe_send("ram_used_gb",   s.ram_used_gb)
        _maybe_send("ram_total_gb",  s.ram_total_gb)
        _maybe_send("gpu_percent",   s.gpu_percent,  scale_0_1=True)
        _maybe_send("vram_used_gb",  s.vram_used_gb)
        _maybe_send("vram_total_gb", s.vram_total_gb)

    # -------- NVML --------

    def _ensure_nvml(self):
        if self._nvml_inited:
            return
        pynvml.nvmlInit()
        self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        self._nvml_inited = True

    def _shutdown_nvml(self):
        if not self._nvml_inited:
            return
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
        self._nvml_inited = False
        self._nvml_handle = None

    def _read_nvml(self, s: HardwareStats):
        self._ensure_nvml()
        h = self._nvml_handle
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            s.gpu_percent = float(util.gpu)
        except Exception:
            pass
        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            s.vram_used_gb = float(mem.used) / _BYTES_PER_GB
            s.vram_total_gb = float(mem.total) / _BYTES_PER_GB
        except Exception:
            pass
        try:
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")
            s.gpu_name = str(name)
        except Exception:
            pass
