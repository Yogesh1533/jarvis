"""Things Jarvis brings up without being asked.

Meeting alerts: a heads-up a few minutes before each event on your Google
Calendar ("meeting_alerts" setting: off / 5 / 10 / 15 minutes). It's
spoken only if you've used the Mac in the last ten minutes; otherwise it
just appears on screen (no "Wake Up starts in 5 minutes" to an empty room).

Morning briefing: once a day, after the "briefing" time, the first time
you're at your Mac (you've touched the keyboard or mouse in the last
minute) and Jarvis is free, it reads you your day. Mornings only, so
coming back at 3 pm doesn't get you a stale "good morning".
"""
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

from . import config, settings

POLL_SECONDS = 20
CALENDAR_REFRESH = 300      # re-read the calendar every 5 minutes
PRESENT_IDLE = 60           # seconds since the last keypress / mouse move
NEARBY_IDLE = 600           # meeting alerts are only spoken if you were here recently
BRIEFING_UNTIL = 12         # no morning briefing after noon
BRIEFING_PROMPT = (
    "(Automatic morning briefing: the user has just sat down at their Mac. "
    "Use briefing_get, then give a short spoken rundown of their day: the "
    "weather, their first meetings, anything due, and only the emails that "
    "look important. About thirty seconds; skip empty sections.)"
)


def idle_seconds():
    """Seconds since the user last touched the keyboard, mouse or trackpad."""
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        m = re.search(r'"HIDIdleTime" = (\d+)', out)
        return int(m.group(1)) / 1e9 if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def alert_text(event, now):
    minutes = max(1, round((event["start"] - now).total_seconds() / 60))
    text = "Heads up: {} starts in {} minute{}".format(
        event["title"], minutes, "" if minutes == 1 else "s"
    )
    if event.get("link"):
        text += ", on Google Meet"
    elif event.get("location"):
        text += ", at " + event["location"].split(",")[0]
    return text + "."


def briefing_due(now, setting, last_date, idle):
    """Should the morning briefing play now?"""
    if setting == "off" or last_date == now.date().isoformat():
        return False
    hour, minute = map(int, setting.split(":"))
    if now < now.replace(hour=hour, minute=minute, second=0, microsecond=0):
        return False
    if now.hour >= BRIEFING_UNTIL:
        return False
    return idle is not None and idle < PRESENT_IDLE


class Proactive:
    """Polls the calendar and the clock on a daemon thread. `hub` provides
    announce(kind, text, speak), brief(prompt) -> bool and free() -> bool."""

    def __init__(self, hub):
        self.hub = hub
        self.events = []
        self.fetched = 0.0
        self.alerted = set()     # (event id, start) already announced
        self._state_path = config.DB_PATH.parent / "proactive.json"

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="proactive").start()

    def _loop(self):
        while True:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 — keep the thread alive
                print("[proactive] {}".format(exc))
            time.sleep(POLL_SECONDS)

    def tick(self):
        prefs = settings.get()
        if prefs["meeting_alerts"] != "off" and config.GOOGLE_TOKEN_PATH.exists():
            self._meetings(int(prefs["meeting_alerts"]))
        if prefs["briefing"] != "off":
            self._briefing(prefs["briefing"])

    # -- meeting alerts --------------------------------------------------
    def _meetings(self, lead_minutes):
        from .tools import gcal

        if time.time() - self.fetched > CALENDAR_REFRESH:
            self.events = gcal.upcoming(hours=3)
            self.fetched = time.time()
        now = datetime.now(timezone.utc)
        for event in self.events:
            key = (event["id"], event["start"].isoformat())
            until = event["start"] - now
            if key in self.alerted or until <= timedelta(0):
                continue
            if until <= timedelta(minutes=lead_minutes):
                self.alerted.add(key)
                idle = idle_seconds()
                nearby = idle is None or idle < NEARBY_IDLE
                self.hub.announce("meeting", alert_text(event, now), speak=nearby)

    # -- morning briefing ------------------------------------------------
    def _last_briefing(self):
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8")).get("briefing")
        except (OSError, ValueError):
            return None

    def _briefing(self, setting):
        now = datetime.now()
        if not briefing_due(now, setting, self._last_briefing(), idle_seconds()):
            return
        if not self.hub.free() or not self.hub.brief(BRIEFING_PROMPT):
            return   # busy or nobody's window is open; try again shortly
        self._state_path.write_text(
            json.dumps({"briefing": now.date().isoformat()}), encoding="utf-8"
        )

