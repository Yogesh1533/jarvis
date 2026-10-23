"""Reminders (SQLite) plus the background scheduler that fires them."""
import threading
import time
from datetime import datetime

from .. import config
from . import ConfirmationRequired
from .db import connect

_FMT = "%Y-%m-%d %H:%M"


def set_reminder(message, due_at):
    try:
        parsed = datetime.strptime(due_at.strip(), _FMT)
    except ValueError:
        raise ValueError("due_at must be 'YYYY-MM-DD HH:MM', got {!r}".format(due_at))
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (message, due_at) VALUES (?, ?)",
            (message, parsed.strftime(_FMT)),
        )
    return "Reminder {} set for {}: {}".format(cur.lastrowid, due_at, message)


def list_reminders():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE fired = 0 ORDER BY due_at"
        ).fetchall()
    if not rows:
        return "No pending reminders."
    return "\n".join(
        "#{} at {}: {}".format(r["id"], r["due_at"], r["message"]) for r in rows
    )


def cancel(reminder_id, _confirmed=False):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ? AND fired = 0", (reminder_id,)
        ).fetchone()
        if row is None:
            raise ValueError("No pending reminder with id {}".format(reminder_id))
        if not _confirmed:
            raise ConfirmationRequired(
                "Cancel reminder {} — {} at {}?".format(
                    reminder_id, row["message"], row["due_at"]
                )
            )
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    return "Reminder {} cancelled.".format(reminder_id)


def _due_now():
    now = datetime.now().strftime(_FMT)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE fired = 0 AND due_at <= ?", (now,)
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (r["id"],))
    return [r["message"] for r in rows]


def start_scheduler(notify):
    """Poll for due reminders on a daemon thread; call notify(message) for each."""

    def loop():
        while True:
            try:
                for message in _due_now():
                    notify(message)
            except Exception as exc:  # noqa: BLE001 — keep the scheduler alive
                print("[reminder scheduler] {}".format(exc))
            time.sleep(config.REMINDER_POLL_SECONDS)

    t = threading.Thread(target=loop, daemon=True, name="reminder-scheduler")
    t.start()
    return t
