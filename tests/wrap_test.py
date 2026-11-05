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

print("== wrap trigger ==")
from jarvis import settings  # noqa: E402

today = datetime.now().date().isoformat()


def at(h, m):
    return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)


check("due after the set time", proactive.wrap_due(at(20, 5), "20:00", None, 10))
check("not due before the set time", not proactive.wrap_due(at(19, 59), "20:00", None, 10))
check("not due twice a day", not proactive.wrap_due(at(20, 5), "20:00", today, 10))
check("off never fires", not proactive.wrap_due(at(20, 5), "off", None, 10))
check("not due when away", not proactive.wrap_due(at(20, 5), "20:00", None, 300))
check("not due with unknown idle", not proactive.wrap_due(at(20, 5), "20:00", None, None))
check("late evening still fires", proactive.wrap_due(at(23, 50), "20:00", None, 10))

config.DB_PATH = root / "set" / "jarvis.db"
settings._cache = None
check("wrap defaults off, vault on", settings.get()["wrap"] == "off" and settings.get()["wrap_to_vault"] is True)
check("wrap time is normalised", settings.update(wrap="8:30")["wrap"] == "08:30")
try:
    settings.update(wrap="25:00")
    bad = False
except ValueError as exc:
    bad = "wrap must be 'off' or a time like 20:00" in str(exc)
check("bad wrap time rejected", bad)
try:
    settings.update(briefing="25:00")
    bad = False
except ValueError as exc:
    bad = "briefing must be 'off' or a time like 07:30" in str(exc)
check("briefing error text unchanged", bad)


class FakeHub:
    def __init__(self):
        self.prompts = []

    def free(self):
        return True

    def brief(self, prompt, label=None):
        self.prompts.append((prompt, label))
        return True

    def announce(self, *a, **k):
        pass


settings.update(wrap="00:00", wrap_to_vault=False, briefing="off", nudges=False, meeting_alerts="off")
proactive.idle_seconds = lambda: 5
hub = FakeHub()
q = proactive.Proactive(hub)
q._state_path = root / "p2.json"
q.tick()
check("tick runs the wrap once", len(hub.prompts) == 1)
check("wrap prompt calls wrap_get and skips the vault",
      "wrap_get" in hub.prompts[0][0] and "Skip the vault_note step" in hub.prompts[0][0])
check("wrap label", hub.prompts[0][1] == "Your evening wrap")
q.tick()
check("second tick doesn't repeat", len(hub.prompts) == 1)
check("wrap date saved", q._load_state("wrap") == today)
settings.update(wrap_to_vault=True)
hub2 = FakeHub()
q2 = proactive.Proactive(hub2)
q2._state_path = root / "p3.json"
q2.tick()
check("vault on: no skip sentence", "Skip the vault_note step" not in hub2.prompts[0][0]
      and "vault_note" in hub2.prompts[0][0])

from jarvis import tools  # noqa: E402
check("wrap_get registered", "wrap_get" in tools._handlers() and any(t["name"] == "wrap_get" for t in tools.TOOL_SCHEMAS))

print("ALL {} CHECKS PASSED".format(len(PASS)))
