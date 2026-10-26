"""Conversation log (SQLite) so the HUD can show past exchanges after a restart."""
from . import recall
from .db import connect


def add(role, text):
    """Log one message and return its row id. A reply also queues its exchange
    for the recall index (on a worker thread, so this never waits for the model)."""
    with connect() as conn:
        row_id = conn.execute(
            "INSERT INTO conversation (role, text) VALUES (?, ?)", (role, text)
        ).lastrowid
    if role == "jarvis":
        recall.index_turn(row_id)
    return row_id


def recent(limit=60):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversation ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear():
    """Forget the log and every vector built from it."""
    with connect() as conn:
        conn.execute("DELETE FROM conversation")
    recall.flush()   # a queued exchange mustn't be re-indexed after the purge
    recall.purge("turn")
