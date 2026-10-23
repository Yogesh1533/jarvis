"""Local task store (SQLite)."""
from . import ConfirmationRequired
from .db import connect


def add(title, due=None, notes=None):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, due, notes) VALUES (?, ?, ?)",
            (title, due, notes),
        )
    return "Task {} added: {}{}".format(
        cur.lastrowid, title, " (due {})".format(due) if due else ""
    )


def list_tasks(include_done=False):
    with connect() as conn:
        if include_done:
            rows = conn.execute("SELECT * FROM tasks ORDER BY done, due IS NULL, due").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE done = 0 ORDER BY due IS NULL, due"
            ).fetchall()
    if not rows:
        return "No tasks."
    lines = []
    for r in rows:
        lines.append(
            "#{} [{}] {}{}{}".format(
                r["id"],
                "done" if r["done"] else "open",
                r["title"],
                " — due {}".format(r["due"]) if r["due"] else "",
                " — {}".format(r["notes"]) if r["notes"] else "",
            )
        )
    return "\n".join(lines)


def _get(conn, task_id):
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError("No task with id {}".format(task_id))
    return row


def complete(task_id):
    with connect() as conn:
        row = _get(conn, task_id)
        conn.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
    return "Task {} marked done: {}".format(task_id, row["title"])


def delete(task_id, _confirmed=False):
    with connect() as conn:
        row = _get(conn, task_id)
        if not _confirmed:
            raise ConfirmationRequired(
                "Delete task {} — {}?".format(task_id, row["title"])
            )
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return "Task {} deleted: {}".format(task_id, row["title"])
