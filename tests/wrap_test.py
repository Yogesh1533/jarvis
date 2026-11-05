"""Offline test for the evening wrap data (wrap.get), task done_at and proactive state.

Run:  .venv/bin/python tests/wrap_test.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: {}".format(name)
    PASS.append(name)
    print("  ok - {}".format(name))


root = Path(tempfile.mkdtemp(prefix="jarvis-wrap-test-"))
gitcfg = root / "gitconfig"
gitcfg.write_text("[user]\n\temail = me@example.com\n\tname = Me\n", encoding="utf-8")
os.environ["GIT_CONFIG_GLOBAL"] = str(gitcfg)
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

config.DB_PATH = root / "old.db"
VDIR = root / "Brain"
VDIR.mkdir()
config.VAULT_DIR = VDIR

print("== done_at migration ==")
con = sqlite3.connect(str(config.DB_PATH))
con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
            "due TEXT, notes TEXT, done INTEGER NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))")
con.execute("INSERT INTO tasks (title, done) VALUES ('ancient chore', 1)")
con.commit()
con.close()

from jarvis.tools import db, gcal, gmail, projects, tasks, wrap  # noqa: E402

with db.connect() as c:
    cols = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
check("old-schema db gets done_at on open", "done_at" in cols)

config.DB_PATH = root / "jarvis.db"
tasks.add("Write the report")
tasks.add("Pay invoice", due=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
tasks.add("Old overdue", due="2020-01-01")
tasks.complete(1)
with db.connect() as c:
    r = c.execute("SELECT done_at FROM tasks WHERE id = 1").fetchone()
check("complete sets done_at", r["done_at"] and r["done_at"][:10] == datetime.now().strftime("%Y-%m-%d"))

print("== wrap.get ==")
repo = root / "repo"
repo.mkdir()
env = dict(os.environ)
for args in (["init", "-q"], ["commit", "--allow-empty", "-q", "-m", "ship the wrap feature"]):
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)
other = root / "other"
other.mkdir()
subprocess.run(["git", "-C", str(other), "init", "-q"], check=True, env=env, capture_output=True)
subprocess.run(["git", "-C", str(other), "-c", "user.email=someone@else.com", "-c", "user.name=X",
                "commit", "--allow-empty", "-q", "-m", "not mine"], check=True, env=env, capture_output=True)

(VDIR / "Projects.md").write_text(
    "| Project | Path | What |\n|---|---|---|\n"
    "| Demo | `{}` | demo |\n| Other | `{}` | other |\n| Plain | `{}` | no git |\n".format(
        repo, other, root), encoding="utf-8")

tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
today = datetime.now().strftime("%Y-%m-%d")
gcal.list_events = lambda days_ahead=7, query=None: (
    "id: a\ntitle: Standup today\nstart: {t}T09:00:00+00:00\nend: {t}T09:30:00+00:00\n\n"
    "id: b\ntitle: Dentist tomorrow\nstart: {m}T10:00:00+00:00\nend: {m}T11:00:00+00:00"
).format(t=today, m=tomorrow)
QUERIES = []


def fake_search(query, max_results=10):
    QUERIES.append((query, max_results))
    return "id: m1\nfrom: boss@x.com\nsubject: Need the numbers\ndate: today\nsnippet: please"


gmail.search = fake_search

out = wrap.get()
check("Done today section", "Done today" in out and "Write the report" in out)
check("ancient task ignored", "ancient chore" not in out)
check("Due tomorrow or overdue section", "Due tomorrow or overdue" in out and "Pay invoice" in out
      and "Old overdue" in out)
check("commit subject listed", "Commits today" in out and "ship the wrap feature" in out)
check("other author's commit excluded", "not mine" not in out)
check("calendar shows tomorrow only", "Dentist tomorrow" in out and "Standup today" not in out)
check("reply section with subject", "Might need a reply" in out and "Need the numbers" in out)
check("exact reply query", QUERIES == [(
    "is:unread newer_than:1d -category:promotions -category:social -category:updates", 8)])
check("section order", [out.index(s) for s in (
    "Done today", "Due tomorrow or overdue", "Commits today", "Tomorrow", "Might need a reply")]
    == sorted(out.index(s) for s in (
        "Done today", "Due tomorrow or overdue", "Commits today", "Tomorrow", "Might need a reply")))


def boom(*a, **k):
    raise RuntimeError("gmail exploded")


gmail.search = boom
out2 = wrap.get()
check("gmail failure skips only that section", "Done today" in out2 and "Commits today" in out2
      and "Might need a reply" not in out2)
check("no traceback text", "Traceback" not in out2 and "exploded" not in out2)

print("== proactive state ==")
from jarvis import proactive  # noqa: E402

p = proactive.Proactive.__new__(proactive.Proactive)
p._state_path = root / "proactive.json"
check("missing file loads None", p._load_state("wrap") is None)
p._state_path.write_text("{not json", encoding="utf-8")
check("corrupt file loads None", p._load_state("wrap") is None)
p._save_state("wrap", "2026-11-05")
p._save_state("briefing", "2026-11-05")
check("wrap survives a briefing write", p._load_state("wrap") == "2026-11-05")
check("briefing stored", p._load_state("briefing") == "2026-11-05"
      and p._last_briefing() == "2026-11-05")
check("no temp files left", [f.name for f in root.glob("proactive*")] == ["proactive.json"])

print("ALL {} CHECKS PASSED".format(len(PASS)))
