"""Now playing and playback control for whatever is playing on this Mac.

macOS keeps one "now playing" media session (the one behind the media keys
and Control Center). The `media-control` command line tool reads and
drives it, so this works for YouTube Music (the Chrome app or a browser
tab), Spotify, Apple Music, Safari, podcasts... without per-app scripting.

    brew install media-control

Without it, Spotify and Apple Music still work through AppleScript (mac.py).
"""
import base64
import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import mac

KNOWN_APPS = {
    "com.google.Chrome.app.cinhimbnkkaeohfgghhklpknlkffjgod": "YouTube Music",
    "com.spotify.client": "Spotify",
    "com.apple.Music": "Music",
    "com.apple.podcasts": "Podcasts",
    "com.apple.Safari": "Safari",
    "com.google.Chrome": "Chrome",
    "com.apple.TV": "TV",
}
COMMANDS = {
    "play": "play", "pause": "pause", "playpause": "toggle-play-pause",
    "next": "next-track", "previous": "previous-track",
    "forward": "skip-fifteen-seconds", "back": "go-back-fifteen-seconds",
}
_names = dict(KNOWN_APPS)


def binary():
    return shutil.which("media-control") or next(
        (p for p in ("/opt/homebrew/bin/media-control", "/usr/local/bin/media-control")
         if Path(p).exists()), None,
    )


def app_name(bundle):
    """"YouTube Music" for its Chrome app's bundle id, and so on."""
    if not bundle:
        return None
    if bundle not in _names:
        name = bundle.rsplit(".", 1)[-1]
        try:
            found = subprocess.run(
                ["mdfind", "kMDItemCFBundleIdentifier == '{}'".format(bundle.replace("'", ""))],
                capture_output=True, text=True, timeout=3,
            ).stdout.split("\n")[0]
            if found:
                name = Path(found).stem
        except (OSError, subprocess.TimeoutExpired):
            pass
        _names[bundle] = name
    return _names[bundle]


class NowPlaying:
    """Follows the media session live (`media-control stream`) and tells
    `on_change` whenever the track, play state or position changes."""

    def __init__(self):
        self.state = None        # see _parse(); None when nothing is loaded
        self.art = None          # (bytes, mime) of the current artwork
        self.on_change = None
        self.running = False
        self._proc = None
        self._lock = threading.Lock()

    @property
    def available(self):
        return binary() is not None

    def start(self, on_change=None):
        self.on_change = on_change
        if self.running or not self.available:
            return
        self.running = True
        threading.Thread(target=self._run, daemon=True, name="now-playing").start()

    def stop(self):
        self.running = False
        if self._proc is not None:
            self._proc.terminate()

    def _run(self):
        backoff = 1
        while self.running:
            started = time.monotonic()
            try:
                self._proc = subprocess.Popen(
                    [binary(), "stream", "--no-diff", "--debounce=150", "--micros"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                )
                for line in self._proc.stdout:
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("type") == "data":
                        self._update(msg.get("payload") or {})
                self._proc.wait()
            except OSError as exc:
                print("[media] media-control failed: {}".format(exc))
            if time.monotonic() - started > 30:
                backoff = 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _update(self, payload):
        art = payload.pop("artworkData", None)
        mime = payload.pop("artworkMimeType", None) or "image/jpeg"
        state = _parse(payload)
        with self._lock:
            if state and art:
                raw = base64.b64decode(art)
                state["art"] = "/api/media/art?v=" + hashlib.sha1(raw).hexdigest()[:12]
                self.art = (raw, mime)
            elif state and self.state and self.state.get("title") == state["title"]:
                state["art"] = self.state.get("art")   # artwork can arrive late
            changed = state != self.state
            self.state = state
        if changed and self.on_change:
            self.on_change(state)

    def snapshot(self):
        """The current state, with `elapsed` brought up to date."""
        with self._lock:
            if self.state is None:
                return None
            s = dict(self.state)
        if s["playing"] and s.get("at"):
            now = time.time()
            s["elapsed"] = s["elapsed"] + (now - s["at"]) * (s["rate"] or 1)
            s["at"] = now
            if s.get("duration"):
                s["elapsed"] = min(s["elapsed"], s["duration"])
        return s


def _parse(p):
    if not p.get("title"):
        return None
    return {
        "app": app_name(p.get("bundleIdentifier")),
        "bundle": p.get("bundleIdentifier"),
        "title": p.get("title"),
        "artist": p.get("artist") or "",
        "album": p.get("album") or "",
        "playing": bool(p.get("playing")),
        "rate": p.get("playbackRate") or 0,
        "duration": (p.get("durationMicros") or 0) / 1e6 or None,
        # elapsed was `elapsed` seconds at time `at` (epoch seconds)
        "elapsed": (p.get("elapsedTimeMicros") or 0) / 1e6,
        "at": (p.get("timestampEpochMicros") or 0) / 1e6 or time.time(),
        "art": None,
    }


watcher = NowPlaying()


def _once():
    """One read of the media session, when the live watcher isn't running."""
    out = subprocess.run(
        [binary(), "get", "--micros", "--no-artwork"],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    return _parse(json.loads(out)) if out and out != "null" else None


def current():
    """{app, title, artist, album, playing, duration, elapsed, ...} or None."""
    if watcher.running:
        return watcher.snapshot()
    if binary():
        try:
            return _once()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    old = mac.now_playing_data()   # Spotify / Apple Music via AppleScript
    return dict(old, elapsed=None, duration=None, art=None) if old else None


def control(action, position=None):
    """play, pause, playpause, next, previous, forward/back (15 s), seek."""
    exe = binary()
    if exe is None:
        if action in ("forward", "back", "seek"):
            raise RuntimeError("Seeking needs media-control: brew install media-control")
        return mac.media(action)
    if action == "seek":
        if position is None:
            raise ValueError("seek needs a position in seconds")
        args = ["seek", str(max(0.0, float(position)))]
    elif action in COMMANDS:
        args = [COMMANDS[action]]
    else:
        raise ValueError("action must be one of {}, seek".format(", ".join(COMMANDS)))
    subprocess.run([exe, *args], capture_output=True, timeout=5, check=True)
    now = current()
    name = now["app"] if now else "Media"
    return "{}: {}.".format(name, action if action != "seek" else "moved to {:.0f}s".format(float(position)))


def _clock(seconds):
    seconds = int(seconds or 0)
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


# -- assistant tools ------------------------------------------------------
def media_tool(action, app=None, position=None):
    if app in ("Spotify", "Music") and binary() is None:
        return mac.media(action, app)
    return control(action, position)


def now_playing_tool():
    now = current()
    if not now:
        return "Nothing is playing."
    text = "{} in {}: {}{}".format(
        "Playing" if now["playing"] else "Paused",
        now["app"] or "an app", now["title"], " by " + now["artist"] if now["artist"] else "",
    )
    if now.get("album"):
        text += ", from " + now["album"]
    if now.get("duration"):
        text += " ({} of {})".format(_clock(now.get("elapsed")), _clock(now["duration"]))
    return text + "."


def play_on_youtube_music(query):
    """Search YouTube Music for `query` in its app (or the browser)."""
    from urllib.parse import quote_plus

    url = "https://music.youtube.com/search?q=" + quote_plus(query)
    app = Path.home() / "Applications" / "Chrome Apps.localized" / "YouTube Music.app"
    if app.exists():
        subprocess.run(["open", "-a", str(app), url], check=True, timeout=10)
    else:
        subprocess.run(["open", url], check=True, timeout=10)
    return (
        "Opened a YouTube Music search for '{}'. The user may need to pick a "
        "result; YouTube Music doesn't let me start a specific song directly.".format(query)
    )
