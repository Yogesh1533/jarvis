"""Machine vitals for the HUD gauges and the system_status tool."""
import os
import subprocess
import sys
import time

_last_net = {"t": None, "sent": 0, "recv": 0}


def data():
    import psutil

    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.expanduser("~"))
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    net = psutil.net_io_counters()
    now = time.time()
    up_kbs = down_kbs = 0.0
    if _last_net["t"] is not None:
        dt = max(now - _last_net["t"], 0.001)
        up_kbs = (net.bytes_sent - _last_net["sent"]) / dt / 1024
        down_kbs = (net.bytes_recv - _last_net["recv"]) / dt / 1024
    _last_net.update(t=now, sent=net.bytes_sent, recv=net.bytes_recv)

    volume = None
    if sys.platform == "darwin":
        try:
            from .mac import get_volume

            volume = get_volume()
        except Exception:  # noqa: BLE001 — volume is a nice-to-have
            volume = None

    return {
        "cpu": psutil.cpu_percent(interval=None),
        "memory": vm.percent,
        "disk": disk.percent,
        "battery": round(battery.percent) if battery else None,
        "charging": bool(battery.power_plugged) if battery else None,
        "uptime_hours": round((now - psutil.boot_time()) / 3600, 1),
        "net_up_kbs": round(up_kbs, 1),
        "net_down_kbs": round(down_kbs, 1),
        "volume": volume,
        "host": os.uname().nodename.split(".")[0],
    }


def status():
    try:
        d = data()
    except ImportError:
        if sys.platform == "darwin":
            return subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
        raise
    parts = [
        "CPU {}%".format(d["cpu"]),
        "memory {}% used".format(d["memory"]),
        "disk {}% full".format(d["disk"]),
    ]
    if d["battery"] is not None:
        parts.append("battery {}%{}".format(d["battery"], ", charging" if d["charging"] else ""))
    if d["volume"] is not None:
        parts.append("volume {}%".format(d["volume"]))
    parts.append("up {} hours".format(d["uptime_hours"]))
    return ", ".join(parts) + "."
