"""macOS control: apps, volume, media, notifications, clipboard, Shortcuts
and (confirmation-gated) arbitrary AppleScript.

User- and model-supplied strings are always passed to osascript as argv,
never spliced into script source, so a song or app name can't inject code.
"""
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import ConfirmationRequired


def _require_mac():
    if sys.platform != "darwin":
        raise RuntimeError("Mac control is only available on macOS")


def _run(cmd, input_text=None, timeout=20):
    _require_mac()
    proc = subprocess.run(
        cmd, input=input_text, capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "command failed").strip())
    return proc.stdout.strip()


def osa(script, *args, timeout=20):
    """Run AppleScript. `script` is the body of an `on run argv` handler."""
    lines = ["on run argv"] + script.strip().splitlines() + ["end run"]
    cmd = ["osascript"]
    for line in lines:
        cmd += ["-e", line]
    return _run(cmd + [str(a) for a in args], timeout=timeout)


def open_app(name):
    _run(["open", "-a", name])
    return "Opened {}.".format(name)


def quit_app(name, _confirmed=False):
    if not _confirmed:
        raise ConfirmationRequired(
            "Quit {}? Any unsaved work there may be lost.".format(name)
        )
    osa("tell application (item 1 of argv) to quit", name)
    return "Quit {}.".format(name)


def open_url(url):
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Only http(s) URLs can be opened")
    _run(["open", url])
    return "Opened {}.".format(url)


def get_volume():
    # Polled by the HUD, so fail fast rather than tie up a worker.
    try:
        out = osa("return output volume of (get volume settings)", timeout=4)
        return int(out)
    except (ValueError, RuntimeError, subprocess.TimeoutExpired):
        return None


def set_volume(level):
    level = max(0, min(100, int(level)))
    osa("set volume output volume (item 1 of argv as integer)", level)
    return "Volume set to {}%.".format(level)


def _running(app):
    # pgrep, not AppleScript: referencing an app that isn't installed makes
    # osascript pop a "Where is <app>?" dialog and hang.
    _require_mac()
    return subprocess.run(["pgrep", "-xq", app], capture_output=True).returncode == 0


def _player(app=None):
    if app:
        return app
    for candidate in ("Spotify", "Music"):
        try:
            if _running(candidate):
                return candidate
        except RuntimeError:
            continue
    return "Music"


def media(action, app=None):
    commands = {
        "play": "play", "pause": "pause", "playpause": "playpause",
        "next": "next track", "previous": "previous track",
    }
    if action not in commands:
        raise ValueError("action must be one of {}".format(", ".join(commands)))
    player = _player(app)
    # The verb comes from the fixed table above, never from the model.
    osa("tell application (item 1 of argv) to {}".format(commands[action]), player)
    return "{}: {}.".format(player, action)


def now_playing_data():
    """{app, title, artist, playing} for the HUD's media widget, or None."""
    for app in ("Spotify", "Music"):
        try:
            if not _running(app):
                continue
            out = osa(
                "tell application (item 1 of argv)\n"
                "if player state is stopped then return \"\"\n"
                "return (name of current track) & \"\\n\" & (artist of current track) "
                "& \"\\n\" & (player state as text)\n"
                "end tell",
                app, timeout=4,
            )
        except (RuntimeError, subprocess.TimeoutExpired):
            continue
        parts = out.split("\n")
        if len(parts) >= 3:
            return {"app": app, "title": parts[0], "artist": parts[1], "playing": parts[2] == "playing"}
    return None


def now_playing():
    for app in ("Spotify", "Music"):
        try:
            if not _running(app):
                continue
            out = osa(
                "tell application (item 1 of argv)\n"
                "if player state is playing then\n"
                "return (name of current track) & \" by \" & (artist of current track)\n"
                "end if\n"
                "end tell\n"
                "return \"\"",
                app,
            )
            if out:
                return "{} is playing {}.".format(app, out)
        except RuntimeError:
            continue
    return "Nothing is playing."


def notify(message, title=None):
    osa(
        "display notification (item 2 of argv) with title (item 1 of argv)",
        title or "Jarvis", message,
    )
    return "Notification shown."


def screenshot():
    path = Path.home() / "Desktop" / "Jarvis screenshot {}.png".format(
        datetime.now().strftime("%Y-%m-%d at %H.%M.%S")
    )
    _run(["screencapture", "-x", str(path)])
    return "Screenshot saved to {}.".format(path)


def clipboard_read():
    text = _run(["pbpaste"])
    if not text:
        return "The clipboard is empty (or holds something other than text)."
    if len(text) > 4000:
        text = text[:4000] + "\n[truncated]"
    return text


def clipboard_write(text):
    _run(["pbcopy"], input_text=text)
    return "Copied to the clipboard."


def list_shortcuts():
    out = _run(["shortcuts", "list"])
    return out or "No Shortcuts found."


def run_shortcut(name, input=None):  # noqa: A002 — matches the tool schema
    cmd = ["shortcuts", "run", name]
    tmp = None
    if input:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(input)
            tmp = Path(f.name)
        cmd += ["--input-path", str(tmp)]
    try:
        out = _run(cmd, timeout=120)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    return "Shortcut '{}' ran.{}".format(name, " Output: " + out if out else "")


def run_applescript(script, purpose, _confirmed=False):
    if not _confirmed:
        preview = script.strip()
        if len(preview) > 600:
            preview = preview[:600] + "…"
        raise ConfirmationRequired(
            "Run an AppleScript to {}?\n\n{}".format(purpose.rstrip("."), preview)
        )
    out = _run(["osascript", "-e", script], timeout=60)
    return "Script ran.{}".format(" Output: " + out if out else "")
