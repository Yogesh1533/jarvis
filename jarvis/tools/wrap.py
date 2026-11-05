"""Evening wrap: one call that gathers what got done today and what's next.
Each section fails soft (skipped when empty or broken), like briefing.py."""
import os
import subprocess
from datetime import datetime, timedelta

from . import dev, gcal, gmail, projects, tasks
from .db import connect

_GIT_TIMEOUT = 5
_MAX_COMMITS = 5
_REPLY_QUERY = "is:unread newer_than:1d -category:promotions -category:social -category:updates"


def _section(title, fn):
    try:
        body = fn()
    except Exception:  # noqa: BLE001 — skip a failing section, never leak a traceback
        return None
    return "## {}\n{}".format(title, body) if body else None


def _done_today():
    with connect() as conn:
        rows = conn.execute(
            "SELECT title FROM tasks WHERE done = 1 AND done_at IS NOT NULL "
            "AND date(done_at) = date('now', 'localtime') ORDER BY done_at, id").fetchall()
    return "\n".join("- {}".format(r["title"]) for r in rows)


def _due_soon():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    out = []
    for t in tasks.rows():
        due = (t.get("due") or "")[:10]
        if due and due <= tomorrow:
            out.append("- {} (due {})".format(t["title"], t["due"]))
    return "\n".join(out)


def _git(path, *args):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    r = subprocess.run(["git", *dev.SAFE_GIT, "-C", str(path), *args], capture_output=True,
                       text=True, timeout=_GIT_TIMEOUT, env=env)
    return r.stdout if r.returncode == 0 else ""


def _commits():
    try:
        email = _git(".", "config", "user.email").strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    if not email:
        return ""
    blocks = []
    for r in projects.rows():
        path = r["path"]
        try:
            if path is None or not path.exists():
                continue
            info = projects.git_info(path)
            if info is None or "error" in info:
                continue
            log = _git(path, "log", "--since=midnight", "--author=" + email, "--format=%s")
        except (OSError, subprocess.SubprocessError):
            continue
        subjects = [l.strip() for l in log.splitlines() if l.strip()][:_MAX_COMMITS]
        if subjects:
            blocks.append("{}:\n{}".format(r["name"], "\n".join("- " + s for s in subjects)))
    return "\n".join(blocks)


def _agents():
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for t in dev.rows(today_only=True):
        if t.get("state") != "running" and (t.get("finished_at") or "")[:10] == today:
            out.append("- {} [{}] {}{}".format(t["project"], t["state"], t["instruction"][:80],
                                              " — " + t["summary"][:120] if t.get("summary") else ""))
    return "\n".join(out)


def _tomorrow():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    text = gcal.list_events(days_ahead=2)
    keep = [b for b in text.split("\n\n") if "start: " + tomorrow in b]
    return "\n\n".join(keep)


def _replies():
    text = gmail.search(_REPLY_QUERY, max_results=8)
    return "" if text.startswith("No emails match") else text


def get():
    parts = [
        _section("Done today", _done_today),
        _section("Due tomorrow or overdue", _due_soon),
        _section("Commits today", _commits),
        _section("Coding agents", _agents),
        _section("Tomorrow", _tomorrow),
        _section("Might need a reply", _replies),
    ]
    parts = [p for p in parts if p]
    return "\n\n".join(parts) if parts else "Nothing to report for today."
