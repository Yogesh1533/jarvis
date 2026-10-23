"""Conversation log (SQLite) so the HUD can show past exchanges after a restart."""
from .db import connect


def add(role, text):
    with connect() as conn:
        conn.execute("INSERT INTO conversation (role, text) VALUES (?, ?)", (role, text))


def recent(limit=60):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversation ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear():
    with connect() as conn:
        conn.execute("DELETE FROM conversation")
