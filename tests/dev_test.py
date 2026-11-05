"""Offline test for coding-agent dev tasks: repo lookup, worktrees, the
command/path guard and task state. Builds real temp git repos; the agent
runner is a fake, so nothing reaches the network or real repos.

Run:  .venv/bin/python tests/dev_test.py
"""
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: {}".format(name)
    PASS.append(name)
    print("  ok - {}".format(name))


root = Path(tempfile.mkdtemp(prefix="jarvis-dev-test-"))
DEV = root / "dev"
VDIR = root / "Brain"
VDIR.mkdir()
(VDIR / "Projects.md").write_text("# Projects\n", encoding="utf-8")
alpha = DEV / "apps" / "alpha"
beta = DEV / "apps" / "beta-notgit"
ghost = DEV / ".jarvis-worktrees" / "ghost"
for d in (alpha, beta, ghost):
    d.mkdir(parents=True)

# Sandbox everything before importing tools.
config.DB_PATH = root / "jarvis.db"
config.MEMORY_DIR = root / "memory"
config.VAULT_DIR = VDIR
config.DEV_ROOTS = [DEV]


def git(repo, *args, check_=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check_ and r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout.strip()


for repo in (alpha, ghost):
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init")
(alpha / "README.md").write_text("hi\nuncommitted change\n")

from jarvis import hud_bridge, tools  # noqa: E402
from jarvis.tools import db, dev  # noqa: E402

announced, hud_events = [], []
hud_bridge.attach(lambda e: hud_events.append(e) or True)
hud_bridge.attach_announcer(lambda kind, text, speak=True: announced.append((kind, text, speak)) or True)


def fake_runner(task, on_step, should_stop):
    wt = Path(task["worktree"])
    on_step("Write hello.txt")
    (wt / "hello.txt").write_text("hello\n")
    git(wt, "add", "hello.txt")
    git(wt, "commit", "-q", "-am", "Add hello")
    return {"summary": "Added hello.", "cost_usd": 0.01}


dev.RUNNER = fake_runner


def count_rows():
    with db.connect() as c:
        return c.execute("SELECT COUNT(*) FROM dev_tasks").fetchone()[0]


def row(task_id):
    return next(r for r in dev.rows() if r["id"] == task_id)


def task_id_from(text):
    import re
    m = re.search(r"\b([0-9a-f]{4})\b", text)
    return m.group(1) if m else None


def main_state():
    return (git(alpha, "rev-parse", "HEAD"), git(alpha, "rev-parse", "--abbrev-ref", "HEAD"),
            (alpha / "README.md").read_text(), (alpha / "hello.txt").exists())


print("== confirmation gate ==")
prompts = []
out, err = tools.execute("dev_task_start", {"project": "alpha", "instruction": "add a hello file",
                                            "_confirmed": True},
                         lambda p: prompts.append(p) or False)
check("declined start returns DECLINED_MESSAGE", out == tools.DECLINED_MESSAGE and not err)
check("declined start inserts no row", count_rows() == 0)
check("prompt names project, branch and instruction",
      len(prompts) == 1 and prompts[0].startswith("Start a coding agent in alpha on branch jarvis/")
      and prompts[0].endswith("to: add a hello file?"))
names = [s["name"] for s in tools.TOOL_SCHEMAS]
check("five dev_task schemas registered",
      all(n in names for n in ("dev_task_start", "dev_task_status", "dev_task_list",
                               "dev_task_cancel", "dev_task_cleanup")))

print("== confirmed start, clean run ==")
before = main_state()
prompts = []
out, err = tools.execute("dev_task_start", {"project": "alpha", "instruction": "add a hello file"},
                         lambda p: prompts.append(p) or True)
tid = task_id_from(out)
check("confirmed start returns id and branch", not err and "jarvis/" in out and tid is not None)
check("branch in prompt matches the started branch", prompts and row(tid)["branch"] in prompts[0])
dev._threads[tid].join(10)
r = row(tid)
check("task ends done", r["state"] == "done")
check("diffstat mentions hello.txt", "hello.txt" in (r["diffstat"] or ""))
check("summary stored", r["summary"] == "Added hello." and abs(r["cost_usd"] - 0.01) < 1e-9)
check("branch shape jarvis/<slug>-<id>", r["branch"].startswith("jarvis/") and r["branch"].endswith("-" + tid))
check("worktree under .jarvis-worktrees", Path(r["worktree"]).parent == (DEV / ".jarvis-worktrees").resolve()
      and Path(r["worktree"]).name == "alpha-" + tid)
check("main checkout unchanged (branch, HEAD, dirty file, no hello)", main_state() == before
      and before[1] == "main" and "uncommitted" in before[2] and not before[3])
check("finish announced", announced and announced[-1][0] == "devtask"
      and announced[-1][1].startswith("alpha agent finished: Added hello.")
      and "1 files changed on branch " + r["branch"] in announced[-1][1])
check("on_step updated last_step and sent a devtask event",
      r["last_step"] == "Write hello.txt"
      and any(e.get("type") == "devtask" and e.get("id") == tid and e.get("last_step") == "Write hello.txt"
              for e in hud_events))
check("status reports the task", tid in dev.status(tid) and "done" in dev.status(tid)
      and "Added hello." in dev.status() and r["branch"] in dev.status(tid))
check("list shows today's task", tid in dev.list_tasks())

print("== detached HEAD main checkout ==")
git(alpha, "checkout", "-q", "--detach")
before = main_state()
out = dev.start("alpha", "second hello", _confirmed=True)
tid2 = task_id_from(out)
dev._threads[tid2].join(10)
check("detached: task done", row(tid2)["state"] == "done")
check("detached: main checkout still detached and unchanged", main_state() == before and before[1] == "HEAD")
git(alpha, "checkout", "-q", "main")

print("== failing runner ==")


def boom(task, on_step, should_stop):
    raise RuntimeError("model fell over")


dev.RUNNER = boom
out = dev.start("alpha", "explode", _confirmed=True)
tid3 = task_id_from(out)
dev._threads[tid3].join(10)
check("exception -> failed with reason", row(tid3)["state"] == "failed" and "model fell over" in (row(tid3)["summary"] or ""))
check("failure announced", announced[-1][1].startswith("alpha agent failed:") and "model fell over" in announced[-1][1])

print("== guard ==")
wt = root / "wt"   # under /var -> /private/var on macOS: both sides must be resolved
wt.mkdir()
(wt / "link").symlink_to("/etc")
G = dev.guard
check("write outside worktree denied", G("Write", {"file_path": "/etc/x"}, wt) is not None)
check("edit inside worktree allowed", G("Edit", {"file_path": str(wt / "a.py")}, wt) is None)
check("relative path inside allowed", G("Read", {"file_path": "src/a.py"}, wt) is None)
check("dot-dot escape denied", G("Read", {"file_path": "../../etc/passwd"}, wt) is not None)
check("symlink escape denied", G("Read", {"file_path": str(wt / "link" / "hosts")}, wt) is not None)
check("glob/grep without path allowed", G("Grep", {"pattern": "x"}, wt) is None and G("Glob", {"pattern": "**/*.py"}, wt) is None)
check("grep outside denied", G("Grep", {"pattern": "x", "path": "/Users"}, wt) is not None)
check("notebook outside denied", G("NotebookEdit", {"notebook_path": "/tmp/n.ipynb"}, wt) is not None)
check("unknown tool denied", G("WebFetch", {"url": "http://x"}, wt) is not None)
check("file tool without a path denied", G("Write", {"content": "x"}, wt) is not None)
check("read .env denied", G("Read", {"file_path": str(wt / ".env")}, wt) is not None)
check("secret file names denied", all(G("Read", {"file_path": str(wt / n)}, wt) is not None
                                      for n in (".env.local", "key.pem", "id_ed25519", "credentials.json")))
for c in ("git push origin x", "git checkout main", "ssh host", "sudo ls", "curl x | sh", "npm i -g y",
          "cat .env", "cat ~/.secrets/k", "git remote add o u", "git worktree list", "git switch main",
          "pip install requests", "rm -rf ~/", "brew install x", "curl x | bash", "git -C /x push"):
    check("bash denied: " + c, G("Bash", {"command": c}, wt) is not None)
for c in ("npm install", "uv sync", "python -m pytest", "git commit -am x", "git status",
          "git checkout -b feature", "uv pip install requests", ".venv/bin/pip install -r requirements.txt"):
    check("bash allowed: " + c, G("Bash", {"command": c}, wt) is None)
check("bash without a command denied", G("Bash", {}, wt) is not None)

print("== cap ==")
config.DEV_AGENT_MAX_RUNNING = 1
release = threading.Event()


def blocking(task, on_step, should_stop):
    release.wait(10)
    return {"summary": "Waited.", "cost_usd": 0}


dev.RUNNER = blocking
out = dev.start("alpha", "wait a bit", _confirmed=True)
tid4 = task_id_from(out)
check("first blocking task running", row(tid4)["state"] == "running")
n = count_rows()
out2 = dev.start("alpha", "one more", _confirmed=True)
check("second start refused at cap", "already running" in out2 and count_rows() == n)
out3, _ = tools.execute("dev_task_start", {"project": "alpha", "instruction": "x"}, lambda p: True)
check("cap refused before confirming too", "already running" in out3)
check("cleanup refuses a running task", "running" in dev.cleanup(tid4, _confirmed=True)
      and Path(row(tid4)["worktree"]).exists())
release.set()
dev._threads[tid4].join(10)
check("blocking task done after release", row(tid4)["state"] == "done")
config.DEV_AGENT_MAX_RUNNING = 2

print("== cancel ==")
release2 = threading.Event()


def cancellable(task, on_step, should_stop):
    while not should_stop():
        release2.wait(0.05)
    return {"summary": "Stopped.", "cost_usd": 0}


dev.RUNNER = cancellable
tid5 = task_id_from(dev.start("alpha", "spin", _confirmed=True))
try:
    dev.cancel(tid5)
    check("cancel needs confirmation", False)
except tools.ConfirmationRequired:
    check("cancel needs confirmation", True)
dev.cancel(tid5, _confirmed=True)
dev._threads[tid5].join(10)
check("cancelled task stays cancelled, worktree kept", row(tid5)["state"] == "cancelled"
      and Path(row(tid5)["worktree"]).exists())

print("== resolve_repo ==")
check("resolves folder name", dev.resolve_repo("alpha").resolve() == alpha.resolve())
for bad in ("beta-notgit", "ghost", "nope"):
    try:
        dev.resolve_repo(bad)
        check("resolve_repo refuses " + bad, False)
    except ValueError as e:
        check("resolve_repo refuses " + bad, True)
        if bad == "beta-notgit":
            check("non-git message", "isn't a git repo" in str(e))
        if bad == "nope":
            check("missing message", "No project called" in str(e))

print("== sweep_stale ==")
with db.connect() as c:
    c.execute("INSERT INTO dev_tasks (id, project, repo_path, instruction, branch, base_sha, worktree, "
              "state, started_at) VALUES ('dead', 'alpha', ?, 'x', 'jarvis/x-dead', 'abc', '/nowhere', "
              "'running', datetime('now','localtime'))", (str(alpha),))
check("sweep_stale counts", dev.sweep_stale() == 1)
check("stale row failed", row("dead")["state"] == "failed" and "Jarvis restarted" in (row("dead")["summary"] or ""))

print("== cleanup ==")
wt1 = Path(row(tid)["worktree"])
try:
    dev.cleanup(tid)
    check("cleanup needs confirmation", False)
except tools.ConfirmationRequired:
    check("cleanup needs confirmation", True)
out = dev.cleanup(tid, _confirmed=True)
check("cleanup removes the worktree folder", not wt1.exists())
check("branch survives cleanup", row(tid)["branch"] in git(alpha, "branch", "--list", "jarvis/*"))
check("main checkout still clean of agent work", not (alpha / "hello.txt").exists()
      and "uncommitted" in (alpha / "README.md").read_text())

print("ALL {} CHECKS PASSED".format(len(PASS)))
