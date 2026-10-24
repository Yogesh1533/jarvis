"""What the user is looking at: a look at the screen (for Claude's vision)
and the app / web page in front.

Screenshots need macOS's Screen Recording permission for whichever app
runs the server (Jarvis.app, or your terminal). Without it, macOS hands
back only the desktop wallpaper.
"""
import base64
import re
import subprocess
import tempfile
from pathlib import Path

from . import ToolImage
from .mac import _run, osa

MAX_SIDE = 1568   # Claude's vision works best at or below this
SELF = {"Jarvis", "Electron"}
BROWSERS = {
    "com.google.Chrome": ("Google Chrome", "active tab of front window", "title", "URL"),
    "com.google.Chrome.beta": ("Google Chrome Beta", "active tab of front window", "title", "URL"),
    "com.brave.Browser": ("Brave Browser", "active tab of front window", "title", "URL"),
    "com.microsoft.edgemac": ("Microsoft Edge", "active tab of front window", "title", "URL"),
    "company.thebrowser.Browser": ("Arc", "active tab of front window", "title", "URL"),
    "com.apple.Safari": ("Safari", "current tab of front window", "name", "URL"),
}


def look(question=None):
    """Screenshot the main display, scaled down, for the model to see."""
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "screen.png"
        small = Path(tmp) / "screen.jpg"
        _run(["screencapture", "-x", "-m", "-t", "png", str(shot)])
        _run([
            "sips", "-Z", str(MAX_SIDE), "-s", "format", "jpeg",
            "-s", "formatOptions", "70", str(shot), "--out", str(small),
        ])
        data = base64.b64encode(small.read_bytes()).decode("ascii")
    front = front_app()
    caption = "Screenshot of the user's main display, taken just now"
    if front:
        caption += " (frontmost app: {})".format(front["name"])
    caption += (
        ". If it shows only a desktop wallpaper with no windows, macOS Screen "
        "Recording permission is missing: tell the user to allow Jarvis in System "
        "Settings > Privacy & Security > Screen Recording, then restart Jarvis."
    )
    if question:
        caption += " The user asked: " + question
    return ToolImage(caption, data, "image/jpeg")


def _apps_front_to_back():
    out = _run(["lsappinfo", "visibleProcessList"])
    return re.findall(r'(ASN:[0-9a-fx-]+-)"([^"]*)"', out)


def front_app():
    """The app the user was last using (not Jarvis itself): {name, bundle}."""
    try:
        apps = _apps_front_to_back()
    except (RuntimeError, OSError):
        return None
    for asn, name in apps:
        name = name.replace("_", " ").strip("‎ ")
        if name in SELF:
            continue
        info = _run(["lsappinfo", "info", "-only", "bundleid", asn])
        m = re.search(r'bundleID="([^"]+)"', info)
        return {"name": name, "bundle": m.group(1) if m else None}
    return None


def context():
    """Frontmost app, its window title, and the browser tab if it's a browser."""
    front = front_app()
    if not front:
        return "I couldn't tell which app is in front."
    lines = ["Frontmost app: {}".format(front["name"])]
    browser = BROWSERS.get(front["bundle"] or "")
    if browser:
        app, tab, title, url = browser
        try:
            out = osa(
                'tell application "{}"\nset t to {}\nreturn ({} of t) & linefeed & ({} of t)\nend tell'
                .format(app, tab, title, url),
                timeout=6,
            )
            page_title, _, page_url = out.partition("\n")
            lines.append("Page: {}".format(page_title))
            lines.append("URL: {}".format(page_url))
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            lines.append("(Couldn't read the tab: {}. macOS may need Jarvis allowed "
                         "to control {} under Privacy & Security > Automation.)".format(exc, app))
    else:
        try:
            title = osa(
                'tell application "System Events" to tell (first process whose name is '
                '(item 1 of argv)) to return name of front window',
                front["name"], timeout=4,
            )
            if title:
                lines.append("Window: {}".format(title))
        except (RuntimeError, subprocess.TimeoutExpired):
            pass   # window titles need Accessibility permission; the app name is enough
    return "\n".join(lines)
