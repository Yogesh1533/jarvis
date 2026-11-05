"""Background coding agents in git worktrees (dev_task_* tools).

Each task gets its own branch `jarvis/<slug>-<id>` and worktree under
`<first DEV_ROOT>/.jarvis-worktrees/<project>-<id>`, cut from the repo's
current HEAD with `git worktree add`, so the main checkout's files and branch
are never touched. Starting, cancelling and cleaning up always confirm.

`RUNNER` does the actual agent work (the Claude Agent SDK runner is set in a
later task; tests swap in a fake). `guard()` is the per-tool-call path and
command check the runner applies. It is best-effort string matching; the
confirmation gate and worktree isolation are the real boundary.

Config is read at call time.
"""
import re
import secrets as _rand
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .. import config, hud_bridge
from . import ConfirmationRequired, db, projects

WORKTREES = ".jarvis-worktrees"
_GIT_TIMEOUT = 60

_lock = threading.Lock()      # cap check + row insert are atomic under this
_threads = {}                 # task id -> worker thread (tests join these)
_stops = {}                   # task id -> threading.Event set by cancel()
_pending = {}                 # (repo, instruction) -> id shown in the confirm prompt


def _no_runner(task, on_step, should_stop):
    raise RuntimeError("the coding agent runner isn't set up")


RUNNER = _no_runner


# ── helpers ──────────────────────────────────────────────────────────

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _roots():
    out = []
    for r in config.DEV_ROOTS or []:
        try:
            out.append(Path(r).expanduser().resolve())
        except OSError:
            continue
    return out


def _worktrees_dir():
    roots = _roots()
    if not roots:
        raise ValueError("No dev folders are configured (DEV_ROOTS).")
    return roots[0] / WORKTREES


def _inside(p, parent):
    return p == parent or parent in p.parents


def _git(path, *args):
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                       timeout=_GIT_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError("git {} failed: {}".format(args[0], (r.stderr or r.stdout).strip()[:200]))
    return r.stdout


def _slug(text):
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    slug = "-".join(words[:4])[:24].strip("-")
    return slug or "task"


# ── repo lookup ──────────────────────────────────────────────────────

def _check_repo(name, path):
    info = projects.git_info(path)
    if info is None:
        raise ValueError("{} isn't a git repo.".format(name))
    if "error" in info:
        raise ValueError("I couldn't read git for {}: {}.".format(name, info["error"]))
    return path


def _usable(path, roots):
    """Inside a dev root, and not one of our own worktrees."""
    try:
        p = Path(path).expanduser().resolve()
    except OSError:
        return None
    if not any(_inside(p, r) for r in roots):
        return None
    if WORKTREES in p.parts:
        return None
    return p if p.is_dir() else None


def _resolve(project):
    """(display name, repo path) for a project name; raises ValueError."""
    q = str(project or "").strip()
    if not q:
        raise ValueError("Which project?")
    roots = _roots()
    row = projects.find(q)
    if row and row.get("path"):
        p = _usable(row["path"], roots)
        if p is not None:
            return row["name"], _check_repo(row["name"], p)
    found = []
    for r in roots:
        try:
            cands = sorted(r.glob("*/*"))
        except OSError:
            continue
        for d in cands:
            if WORKTREES in d.parts or d.name.startswith(".") or not d.is_dir():
                continue
            if d.name.lower() == q.lower():
                found.append(d)
    if found:
        p = _usable(found[0], roots)
        if p is not None:
            return found[0].name, _check_repo(found[0].name, p)
    raise ValueError("No project called {} in your dev folders.".format(q))


def resolve_repo(project):
    return _resolve(project)[1]


# ── guard ────────────────────────────────────────────────────────────

_PATH_KEYS = ("file_path", "path", "notebook_path")
_FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}
_SEARCH_TOOLS = {"Glob", "Grep"}

_SECRET_NAME = re.compile(r"^(\.env.*|.*\.pem|id_.*|credentials\.json)$", re.I)
_SECRET_IN_CMD = re.compile(
    r"(?<![\w.-])\.env[\w.-]*|\.pem\b|(?<![\w.-])id_[\w.-]*|credentials\.json|\.secrets\b", re.I)

_BASH_DENY = [
    (re.compile(r"\bgit\s+(push|remote|worktree)\b"), "git push/remote/worktree isn't allowed"),
    (re.compile(r"\bgit\s+(checkout|switch)\b(?!\s+-b)"), "switching branches isn't allowed"),
    (re.compile(r"\bgit\s+(-C|--git-dir|--work-tree)\b"), "git on another repo isn't allowed"),
    (re.compile(r"\b(ssh|scp|rsync|sudo|brew)\b"), "ssh/scp/rsync/sudo/brew aren't allowed"),
    (re.compile(r"\|\s*(sudo\s+)?(ba|z)?sh\b"), "piping into a shell isn't allowed"),
    (re.compile(r"\bnpm\s+(i|install)\s+(-g|--global)\b"), "global npm installs aren't allowed"),
    (re.compile(r"\brm\s+-(rf|fr)\s+(/|~|\$HOME)"), "rm -rf on / or ~ isn't allowed"),
]
_PIP = re.compile(r"\bpip3?\s+install\b")
_VENV_START = re.compile(r"\s*(uv\b|\.venv/bin/|python3?\s+-m\s+venv\b)")


def _secret_path(p, wt):
    if any(_SECRET_NAME.match(part) for part in p.relative_to(wt).parts):
        return True
    try:
        home_secrets = (Path.home() / ".secrets").resolve()
    except OSError:
        return True
    return _inside(p, home_secrets)


def _check_path(value, wt):
    if not isinstance(value, str) or not value.strip():
        return "missing or invalid path"
    raw = Path(value).expanduser()
    try:
        p = (raw if raw.is_absolute() else wt / raw).resolve()
    except (OSError, RuntimeError):
        return "path can't be resolved"
    if not _inside(p, wt):
        return "{} is outside the worktree".format(value)
    if _secret_path(p, wt):
        return "{} looks like a secret file".format(value)
    return None


def _guard_bash(cmd):
    if not isinstance(cmd, str) or not cmd.strip():
        return "missing command"
    for rx, why in _BASH_DENY:
        if rx.search(cmd):
            return why
    if _PIP.search(cmd) and not _VENV_START.match(cmd):
        return "pip installs only into the worktree's .venv (use uv or .venv/bin/pip)"
    if _SECRET_IN_CMD.search(cmd):
        return "commands touching secret files aren't allowed"
    return None


def guard(tool_name, tool_input, worktree):
    """Reason to deny this tool call, or None to allow it. Fails closed."""
    try:
        wt = Path(worktree).expanduser().resolve()
    except (OSError, RuntimeError, TypeError):
        return "worktree can't be resolved"
    args = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "Bash":
        return _guard_bash(args.get("command"))
    if tool_name not in _FILE_TOOLS and tool_name not in _SEARCH_TOOLS:
        return "{} isn't allowed for coding agents".format(tool_name)
    present = [k for k in _PATH_KEYS if k in args and args[k] is not None]
    if tool_name in _FILE_TOOLS and not present:
        return "{} needs a file path".format(tool_name)
    for k in present:
        why = _check_path(args[k], wt)
        if why:
            return why
    for k in ("pattern", "glob"):
        if tool_name == "Glob" or k == "glob":
            v = args.get(k)
            if isinstance(v, str) and (v.startswith(("/", "~")) or ".." in Path(v).parts):
                return "glob patterns must stay inside the worktree"
    return None


# ── state ────────────────────────────────────────────────────────────

def _update(task_id, **fields):
    if not fields:
        return
    cols = ", ".join("{} = ?".format(k) for k in fields)
    with db.connect() as c:
        c.execute("UPDATE dev_tasks SET {} WHERE id = ?".format(cols), (*fields.values(), task_id))


def _finish(task_id, **fields):
    """Move a running task to a final state; False if it already ended."""
    cols = ", ".join("{} = ?".format(k) for k in fields)
    with db.connect() as c:
        cur = c.execute("UPDATE dev_tasks SET {} WHERE id = ? AND state = 'running'".format(cols),
                        (*fields.values(), task_id))
        return cur.rowcount == 1


def _get(task_id):
    with db.connect() as c:
        r = c.execute("SELECT * FROM dev_tasks WHERE id = ?", (str(task_id),)).fetchone()
    return dict(r) if r else None


def _running_count(conn):
    return conn.execute("SELECT COUNT(*) FROM dev_tasks WHERE state = 'running'").fetchone()[0]


def rows(today_only=False):
    q = "SELECT * FROM dev_tasks"
    if today_only:
        q += " WHERE state = 'running' OR date(started_at) = date('now', 'localtime')"
    with db.connect() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY started_at DESC, rowid DESC")]


def sweep_stale():
    with db.connect() as c:
        cur = c.execute("UPDATE dev_tasks SET state = 'failed', summary = 'Jarvis restarted', "
                        "finished_at = ? WHERE state = 'running'", (_now(),))
        return cur.rowcount


def _cap_message():
    return ("{} coding agent{} already running, which is the limit. Wait for one to finish "
            "or cancel one.").format(config.DEV_AGENT_MAX_RUNNING,
                                     "" if config.DEV_AGENT_MAX_RUNNING == 1 else "s")


def _id_taken(task_id, repo, slug):
    if _get(task_id):
        return True
    if (_worktrees_dir() / "{}-{}".format(repo.name, task_id)).exists():
        return True
    try:
        return bool(_git(repo, "branch", "--list", "jarvis/{}-{}".format(slug, task_id)).strip())
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return True


def _new_id(repo, slug):
    for _ in range(50):
        tid = _rand.token_hex(2)
        if not _id_taken(tid, repo, slug):
            return tid
    raise RuntimeError("couldn't pick a free task id")


# ── worker ───────────────────────────────────────────────────────────

def _diffstat(task):
    out = _git(task["worktree"], "diff", "--stat", "{}..HEAD".format(task["base_sha"])).strip()
    m = re.search(r"(\d+) files? changed", out)
    return out, int(m.group(1)) if m else 0


def _work(task):
    tid = task["id"]
    stop = _stops[tid]

    def on_step(text):
        step = str(text)[:200]
        try:
            _update(tid, last_step=step)
        except Exception:  # noqa: BLE001 — progress must never kill the task
            pass
        hud_bridge.send({"type": "devtask", "id": tid, "state": "running", "last_step": step})

    ended = False
    try:
        result = RUNNER(dict(task), on_step, stop.is_set) or {}
        stat, n = _diffstat(task)
        if stop.is_set():
            _update(tid, diffstat=stat)
            ended = True
            return
        summary = str(result.get("summary") or "").strip()[:2000]
        ended = True
        if not _finish(tid, state="done", finished_at=_now(), summary=summary, diffstat=stat,
                       cost_usd=float(result.get("cost_usd") or 0)):
            _update(tid, diffstat=stat)   # cancelled meanwhile: keep that state
            return
        hud_bridge.send({"type": "devtask", "id": tid, "state": "done", "last_step": None})
        hud_bridge.announce("devtask", "{} agent finished: {} {} files changed on branch {}.".format(
            task["project"], summary, n, task["branch"]), speak=True)
    except Exception as exc:  # noqa: BLE001 — every failure ends the task as failed
        reason = str(exc)[:300] or exc.__class__.__name__
        if stop.is_set():
            ended = True
            return
        try:
            ended = True
            if not _finish(tid, state="failed", finished_at=_now(), summary=reason):
                return
        finally:
            hud_bridge.send({"type": "devtask", "id": tid, "state": "failed", "last_step": None})
            hud_bridge.announce("devtask", "{} agent failed: {}".format(task["project"], reason),
                                speak=True)
    finally:
        if not ended and not stop.is_set():
            try:
                _finish(tid, state="failed", finished_at=_now(), summary="agent ended unexpectedly")
            except Exception:  # noqa: BLE001
                pass


# ── tools ────────────────────────────────────────────────────────────

def start(project, instruction, _confirmed=False):
    instruction = str(instruction or "").strip()
    if not instruction:
        return "What should the agent do?"
    try:
        name, repo = _resolve(project)
    except ValueError as e:
        return str(e)
    with db.connect() as c:
        if _running_count(c) >= config.DEV_AGENT_MAX_RUNNING:
            return _cap_message()
    slug = _slug(instruction)
    key = (str(repo), instruction)

    if not _confirmed:
        tid = _new_id(repo, slug)
        _pending[key] = tid
        raise ConfirmationRequired("Start a coding agent in {} on branch jarvis/{}-{} to: {}?".format(
            name, slug, tid, instruction))

    tid = _pending.pop(key, None)
    if tid is None or _id_taken(tid, repo, slug):
        tid = _new_id(repo, slug)
    branch = "jarvis/{}-{}".format(slug, tid)
    wt = _worktrees_dir() / "{}-{}".format(repo.name, tid)
    try:
        base = _git(repo, "rev-parse", "HEAD").strip()
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return "I couldn't read {}'s HEAD: {}".format(name, e)

    with _lock:
        with db.connect() as c:
            if _running_count(c) >= config.DEV_AGENT_MAX_RUNNING:
                return _cap_message()
            c.execute("INSERT INTO dev_tasks (id, project, repo_path, instruction, branch, base_sha, "
                      "worktree, state, started_at, last_step) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)",
                      (tid, name, str(repo), instruction, branch, base, str(wt), _now(), "Creating worktree"))

    try:
        wt.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "-q", "-b", branch, str(wt), base)
    except Exception as e:  # noqa: BLE001
        reason = str(e)[:300]
        _update(tid, state="failed", finished_at=_now(), summary=reason)
        return "I couldn't create the worktree for {}: {}".format(name, reason)

    _update(tid, last_step="Starting agent")
    task = _get(tid)
    _stops[tid] = threading.Event()
    t = threading.Thread(target=_work, args=(task,), name="devtask-" + tid, daemon=True)
    _threads[tid] = t
    t.start()
    hud_bridge.send({"type": "devtask", "id": tid, "state": "running", "last_step": "Starting agent"})
    return "Started task {} in {} on branch {}. I'll tell you when it's done.".format(tid, name, branch)


def _elapsed(r):
    try:
        a = datetime.strptime(r["started_at"], "%Y-%m-%d %H:%M:%S")
        b = datetime.strptime(r["finished_at"], "%Y-%m-%d %H:%M:%S") if r["finished_at"] else datetime.now()
    except (TypeError, ValueError):
        return "unknown time"
    mins = int((b - a).total_seconds() // 60)
    return "{} min".format(mins) if mins else "under a minute"


def _describe(r):
    out = "Task {} ({}, branch {}): {}, {}.".format(r["id"], r["project"], r["branch"], r["state"],
                                                    _elapsed(r))
    if r["state"] == "running":
        if r["last_step"]:
            out += " Last step: {}.".format(r["last_step"])
    else:
        if r["summary"]:
            out += " " + r["summary"]
        if r["diffstat"]:
            out += "\n" + r["diffstat"]
    return out


def status(task_id=None):
    if task_id:
        r = _get(str(task_id).strip())
        return _describe(r) if r else "No coding task {}.".format(task_id)
    rs = rows()
    return _describe(rs[0]) if rs else "No coding tasks yet."


def list_tasks():
    rs = rows(today_only=True)
    if not rs:
        return "No coding tasks today."
    return "\n".join("{} {} ({}): {}{}".format(
        r["id"], r["project"], r["branch"], r["state"],
        " - " + r["last_step"] if r["state"] == "running" and r["last_step"] else "") for r in rs)


def cancel(task_id, _confirmed=False):
    r = _get(str(task_id).strip())
    if not r:
        return "No coding task {}.".format(task_id)
    if r["state"] != "running":
        return "Task {} isn't running ({}).".format(r["id"], r["state"])
    if not _confirmed:
        raise ConfirmationRequired("Stop the {} coding agent (task {})? Its worktree and branch are kept.".format(
            r["project"], r["id"]))
    ev = _stops.get(r["id"])
    if ev is not None:
        ev.set()
    if not _finish(r["id"], state="cancelled", finished_at=_now()):
        return "Task {} already finished.".format(r["id"])
    hud_bridge.send({"type": "devtask", "id": r["id"], "state": "cancelled", "last_step": None})
    return "Stopped task {}. The worktree and branch {} are kept.".format(r["id"], r["branch"])


def cleanup(task_id, _confirmed=False):
    r = _get(str(task_id).strip())
    if not r:
        return "No coding task {}.".format(task_id)
    if r["state"] == "running":
        return "Task {} is still running; cancel it first.".format(r["id"])
    wt = Path(r["worktree"] or "")
    try:
        wt_r = wt.resolve()
        base = _worktrees_dir().resolve()
    except (OSError, ValueError):
        return "I can't tell where task {}'s worktree is.".format(r["id"])
    if wt_r.parent != base:
        return "Task {}'s worktree isn't in {}, so I won't remove it.".format(r["id"], WORKTREES)
    if not wt_r.exists():
        return "Task {}'s worktree is already gone. Branch {} is kept.".format(r["id"], r["branch"])
    if not _confirmed:
        raise ConfirmationRequired("Remove the worktree folder for task {} ({})? Branch {} is kept.".format(
            r["id"], wt_r.name, r["branch"]))
    try:
        _git(r["repo_path"], "worktree", "remove", str(wt_r))
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return "I couldn't remove the worktree (it may have uncommitted changes): {}".format(e)
    _update(r["id"], last_step="Worktree removed")
    return "Removed task {}'s worktree. Branch {} is kept.".format(r["id"], r["branch"])
