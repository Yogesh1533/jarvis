"""Launcher for the web UI that works from any working directory and any
Python (used by .claude/launch.json and handy for launchd/Task Scheduler).

If invoked with the system interpreter instead of the venv one, it puts the
venv's site-packages on sys.path itself, so the dependencies are found
without the venv activation shim.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if not sys.prefix.startswith(str(ROOT / ".venv")):
    for site_packages in sorted(ROOT.glob(".venv/lib/python3.*/site-packages")):
        if str(site_packages) not in sys.path:
            sys.path.insert(0, str(site_packages))

from jarvis import web  # noqa: E402

if __name__ == "__main__":
    web.run()
