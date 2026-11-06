"""Background coding agents in standalone git clones (dev_task_* tools).

Each task gets its own branch `jarvis/<slug>-<id>` in its own clone at
`<first DEV_ROOT>/.jarvis-worktrees/<project>-<id>` (the DB still calls it
`worktree`): `git clone --shared --no-checkout`, `origin` removed, then the
branch is checked out at the repo's current HEAD. The clone borrows the
repo's objects read-only through alternates and has its own .git, so the
main checkout's files, branch, refs, config and object store are never
written by the agent. Starting, cancelling and cleaning up always confirm.

`RUNNER` does the agent work: `sdk_runner` drives the Claude Agent SDK
(tests swap in a fake). Its Bash runs in the OS sandbox with writes limited
to the clone (minus its .claude/ and .git/config and hooks) and reads of
secrets denied. `guard()` is the per-tool-call path and command check,
enforced through a PreToolUse hook (which also fires for auto-approved
calls) and again in `can_use_tool`. It is best-effort string matching:
command substitution, variables, scripts and `subprocess` get around it.
The confirmation, the clone and the sandbox are the real boundary.

When the agent ends (done, failed or cancelled), Jarvis brings its branch
into the main repo itself: it copies the clone's objects and branch ref
into a private snapshot git dir that it writes (never trusting the clone's
.git config, commondir or hooks) and fetches from that. Every git call
Jarvis makes passes `-c core.fsmonitor=false -c core.hooksPath=/dev/null`.

Config is read at call time.
"""
import os
import re
import shutil
import warnings
import secrets as _rand
import shlex
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .. import config, hud_bridge
from . import ConfirmationRequired, db, projects

WORKTREES = ".jarvis-worktrees"
_GIT_TIMEOUT = 60
# Never let a repo's config run programs when Jarvis itself calls git.
SAFE_GIT = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")
# Extra overrides for git calls that read agent-written content (the clone's
# work tree, index or objects through a snapshot). With these plus
# _git_env(strict=True) no global or system config is read, so no filter,
# textconv, diff driver or include can be defined except by Jarvis, and git
# never recurses into a nested repo, whose own .git/config the agent writes.
STRICT_GIT = SAFE_GIT + (
    "-c", "core.attributesFile=/dev/null", "-c", "submodule.recurse=false",
    "-c", "diff.ignoreSubmodules=all", "-c", "status.submoduleSummary=false",
    "-c", "core.untrackedCache=false", "-c", "core.splitIndex=false",
    "-c", "protocol.allow=never",
)
_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

# The PreToolUse hook is the real gate, so can_use_tool being shadowed by
# allowed_tools is expected.
warnings.filterwarnings("ignore", message=r"can_use_tool will not be invoked")

_lock = threading.Lock()      # cap check + row insert are atomic under this
_threads = {}                 # task id -> worker thread (tests join these)
_stops = {}                   # task id -> threading.Event set by cancel()
_pending = {}                 # (repo, instruction) -> id shown in the confirm prompt



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


def _git(path, *args, git_dir=None, work_tree=None, strict=False):
    """Run git; strict=True for anything that reads agent-written content."""
    cmd = ["git", *(STRICT_GIT if strict else SAFE_GIT)]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir), "--work-tree", str(work_tree or path)]
    r = subprocess.run(cmd + ["-C", str(path), *args], capture_output=True, text=True,
                       timeout=_GIT_TIMEOUT, env=_git_env(strict))
    if r.returncode != 0:
        raise RuntimeError("git {} failed: {}".format(_subcommand(args), _git_error(r)))
    return r.stdout


def _subcommand(args):
    """The git subcommand in args, skipping options and `-c` values."""
    it = iter(args)
    for a in it:
        if a == "-c":
            next(it, None)
        elif not a.startswith("-"):
            return a
    return "command"


def _git_error(r):
    """git's own reason, minus `From <url>` and hint lines."""
    lines = [l.strip() for l in (r.stderr or r.stdout or "").splitlines()]
    keep = [l for l in lines if l and not l.startswith(("From ", "hint:"))]
    return "; ".join(keep)[:300] or "exit {}".format(r.returncode)


def _git_env(strict=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    if strict:
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_ATTR_NOSYSTEM"] = "1"
    return env


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

# `git` plus any global options (-c k=v, -C dir, --no-pager, --git-dir=x, -p ...)
# before the subcommand, so options can't hide the subcommand from the rules.
_GIT = r"\bgit\b(?:\s+(?:-[cC]\s+\S+|--?[\w-]+(?:=\S+)?))*\s+"
_SEG = r"[^;&|\n]*?"   # the rest of one simple command

_BASH_DENY = [
    (re.compile(r"\bgit\b(?:\s+(?:-c\s+\S+|--?[\w-]+(?:=\S+)?))*\s+(-C\b|--git-dir\b|--work-tree\b)"),
     "git on another repo isn't allowed"),
    (re.compile(r"\bgit\b" + _SEG + r"\s(--git-dir|--work-tree)\b"), "git on another repo isn't allowed"),
    (re.compile(r"\bGIT_(DIR|WORK_TREE|INDEX_FILE|COMMON_DIR|OBJECT_DIRECTORY|CONFIG\w*)\s*="),
     "redirecting git with environment variables isn't allowed"),
    (re.compile(_GIT + r"(push|remote|worktree|update-ref|symbolic-ref|send-pack|http-push|"
                r"filter-branch|replace)\b"),
     "that git command could change the main repo or a remote"),
    (re.compile(_GIT + r"(checkout|switch)\b(?!\s+-b\b)"), "switching branches isn't allowed"),
    (re.compile(_GIT + r"config\b(?!\s+(--get|--get-all|--get-regexp|--list|-l)\b)"),
     "changing git config isn't allowed (it's shared with the main repo)"),
    (re.compile(_GIT + r"config\b" + _SEG + r"\s(--global|--system|--unset\S*|--add|--replace-all|"
                r"--rename-section|--remove-section|--edit|-e)\b"),
     "changing git config isn't allowed (it's shared with the main repo)"),
    (re.compile(_GIT + r"branch\b" + _SEG + r"\s(-(?!-)[a-zA-Z]*[dDfmMcC][a-zA-Z]*|"
                r"--(delete|force|move|copy))\b"),
     "deleting, moving or forcing branches isn't allowed"),
    (re.compile(_GIT + r"stash\s+(drop|clear)\b"), "dropping stashes isn't allowed"),
    (re.compile(_GIT + r"tag\b" + _SEG + r"\s(-d|--delete)\b"), "deleting tags isn't allowed"),
    (re.compile(_GIT + r"reflog\s+(expire|delete)\b"), "rewriting the reflog isn't allowed"),
    (re.compile(_GIT + r"gc\b" + _SEG + r"--prune"), "pruning objects isn't allowed"),
    (re.compile(r"\bgh\b"), "the GitHub CLI isn't allowed"),
    (re.compile(r"\b(ssh|scp|rsync|sudo|brew)\b"), "ssh/scp/rsync/sudo/brew aren't allowed"),
    (re.compile(r"\|\s*(sudo\s+)?(ba|z)?sh\b"), "piping into a shell isn't allowed"),
    (re.compile(r"\bnpm\s+(i|install)\s+(-g|--global)\b"), "global npm installs aren't allowed"),
    (re.compile(r"\brm\b" + _SEG + r"\s(/|~/?|\$HOME/?|\$\{HOME\}/?)(?=\s|$|[;&|)])"),
     "rm on / or ~ isn't allowed"),
    (re.compile(r"\$\{?HOME\b"), "commands using $HOME aren't allowed"),
]
_PIP = re.compile(r"\bpip3?\s+install\b")
_VENV_START = re.compile(r"\s*(uv\b|\.venv/bin/|python3?\s+-m\s+venv\b)")

# Paths outside the worktree a command may name: devices, scratch space
# (checked after resolving symlinks) and system bin dirs (by prefix only,
# since e.g. Homebrew's bin entries are symlinks into its Cellar).
_DEV_FILES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}
_BIN_DIRS = ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin")
_TMP_DIRS = ("/tmp", "/private/tmp")
_SHELL_PUNCT = set(";&|()<>")


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
    if ".git" in p.relative_to(wt).parts:
        return "the worktree's .git is off limits"
    if _secret_path(p, wt):
        return "{} looks like a secret file".format(value)
    return None


def _rel_parts(value, wt):
    raw = Path(value).expanduser()
    try:
        return (raw if raw.is_absolute() else wt / raw).resolve().relative_to(wt).parts
    except (OSError, RuntimeError, ValueError):
        return ()


def _allowed_outside(tok):
    norm = os.path.normpath(tok)
    if norm in _DEV_FILES:
        return True
    if any(norm == d or norm.startswith(d + "/") for d in _BIN_DIRS):
        return True
    try:
        p = Path(norm).resolve()
        tmps = [Path(d).resolve() for d in _TMP_DIRS]
    except (OSError, RuntimeError):
        return False
    return any(_inside(p, t) for t in tmps)


def _check_token_path(tok, wt):
    if tok.startswith("/") and _allowed_outside(tok):
        return None
    return _check_path(tok, wt)


def _pathish(tok):
    return tok.startswith(("/", "~")) or ".." in tok.split("/") or tok == ".git" or tok.startswith(".git/")


def _tokens(cmd):
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def _guard_bash(cmd, wt, depth=0):
    if not isinstance(cmd, str) or not cmd.strip():
        return "missing command"
    if depth > 3:
        return "too deeply nested"
    for rx, why in _BASH_DENY:
        if rx.search(cmd):
            return why
    if _PIP.search(cmd) and not _VENV_START.match(cmd):
        return "pip installs only into the worktree's .venv (use uv or .venv/bin/pip)"
    if _SECRET_IN_CMD.search(cmd):
        return "commands touching secret files aren't allowed"
    try:
        toks = _tokens(cmd)
    except ValueError:
        return "I can't parse that command"
    for i, tok in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if tok in ("cd", "pushd"):
            if nxt is None or nxt[0] in _SHELL_PUNCT or nxt == "-":
                return "cd must name a folder inside the worktree"
            why = _check_path(nxt, wt)
            if why:
                return why
        if tok in ("sh", "bash", "zsh") and nxt == "-c" and i + 2 < len(toks):
            why = _guard_bash(toks[i + 2], wt, depth + 1)
            if why:
                return why
        if tok == "eval":
            rest = []
            for t in toks[i + 1:]:
                if t and t[0] in _SHELL_PUNCT:
                    break
                rest.append(t)
            why = _guard_bash(" ".join(rest), wt, depth + 1)
            if why:
                return why
        cands = [tok]
        if "=" in tok:
            cands.append(tok.split("=", 1)[1])
        for c in cands:
            if c and _pathish(c):
                why = _check_token_path(c, wt)
                if why:
                    return why
    return None


def guard(tool_name, tool_input, worktree):
    """Reason to deny this tool call, or None to allow it. Fails closed."""
    try:
        wt = Path(worktree).expanduser().resolve()
    except (OSError, RuntimeError, TypeError):
        return "worktree can't be resolved"
    args = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "Bash":
        return _guard_bash(args.get("command"), wt)
    if tool_name not in _FILE_TOOLS and tool_name not in _SEARCH_TOOLS:
        return "{} isn't allowed for coding agents".format(tool_name)
    present = [k for k in _PATH_KEYS if k in args and args[k] is not None]
    if tool_name in _FILE_TOOLS and not present:
        return "{} needs a file path".format(tool_name)
    for k in present:
        why = _check_path(args[k], wt)
        if why:
            return why
        if tool_name != "Read" and ".claude" in _rel_parts(args[k], wt):
            return "the repo's .claude settings are off limits"
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


def _alive(task_id):
    t = _threads.get(task_id)
    return t is not None and t.is_alive()


def _running_count(conn):
    """Running rows plus agents whose thread hasn't exited yet (a cancelled
    agent keeps running until it notices the stop)."""
    ids = {r[0] for r in conn.execute("SELECT id FROM dev_tasks WHERE state = 'running'")}
    ids |= {tid for tid in list(_threads) if _alive(tid)}
    return len(ids)


def _send(event):
    try:
        hud_bridge.send(event)
    except Exception:  # noqa: BLE001 — a broken HUD must never break a task
        pass


def _nearby():
    """Speak only if Yogesh touched the Mac recently (unknown counts as near)."""
    try:
        from .. import proactive
        idle = proactive.idle_seconds()
        return idle is None or idle < proactive.NEARBY_IDLE
    except Exception:  # noqa: BLE001
        return True


def _announce(text):
    try:
        hud_bridge.announce("devtask", text, speak=_nearby())
    except Exception:  # noqa: BLE001
        pass


def _fail(task, reason):
    """Mark a running task failed and tell the user; quiet if it already ended."""
    try:
        changed = _finish(task["id"], state="failed", finished_at=_now(), summary=reason)
    except Exception:  # noqa: BLE001 — db trouble: still tell the user
        changed = True
    if changed:
        _send({"type": "devtask", "id": task["id"], "state": "failed", "last_step": None})
        _announce("{} agent failed: {}".format(task["project"], reason))
    return changed


def rows(today_only=False):
    q = "SELECT * FROM dev_tasks"
    if today_only:
        q += " WHERE state = 'running' OR date(started_at) = date('now', 'localtime')"
    with db.connect() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY started_at DESC, rowid DESC")]


def sweep_stale():
    """Tasks still `running` died with the last Jarvis: bring back what they
    committed (best effort), then mark them failed."""
    with db.connect() as c:
        stale = [dict(r) for r in c.execute("SELECT * FROM dev_tasks WHERE state = 'running'")]
    for t in stale:
        try:
            stat, _n, commits = _import(t)
            _update(t["id"], diffstat=stat, commits=commits)
        except Exception:  # noqa: BLE001 — best effort
            pass
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

def _clone_git_dir(clone):
    """The clone's .git, only if it's a real directory (not a symlink or a
    `gitdir:` file the agent swapped in)."""
    g = Path(clone) / ".git"
    try:
        if g.is_symlink() or not g.is_dir():
            return None
    except OSError:
        return None
    return g


def _read_ref(git_dir, branch):
    """sha of refs/heads/<branch> read straight from the files; None if absent."""
    ref = "refs/heads/" + branch
    f = git_dir / ref
    try:
        if f.is_file() and not f.is_symlink():
            sha = f.read_text(encoding="ascii", errors="replace").strip()
            return sha if _SHA.match(sha) else None
        packed = git_dir / "packed-refs"
        if packed.is_file() and not packed.is_symlink():
            for line in packed.read_text(encoding="ascii", errors="replace").splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1].strip() == ref and _SHA.match(parts[0]):
                    return parts[0]
    except OSError:
        return None
    return None


def _snapshot(task):
    """Copy the clone's objects into a fresh git dir Jarvis writes
    itself, with its own config and the repo's objects as alternates.
    Returns (snapshot dir, branch sha or None). Nothing from the clone's
    config, hooks, commondir or info/ is carried over."""
    clone = Path(task["worktree"])
    gd = _clone_git_dir(clone)
    if gd is None:
        raise RuntimeError("the agent's clone has no usable .git")
    snap = _worktrees_dir() / ".snapshot-{}".format(task["id"])
    shutil.rmtree(snap, ignore_errors=True)
    _git(_worktrees_dir(), "init", "-q", "--bare", "--object-format",
         _git(task["repo_path"], "rev-parse", "--show-object-format").strip(), str(snap),
         strict=True)
    src = gd / "objects"
    # os.walk lists a symlinked top dir anyway; never copy from outside the clone.
    if src.is_symlink() or not src.is_dir():
        raise RuntimeError("the agent's clone has a bad .git/objects")
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel = Path(dirpath).relative_to(src)
        if rel.parts and rel.parts[0] == "info":
            continue
        (snap / "objects" / rel).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            f = Path(dirpath) / name
            if f.is_symlink() or not f.is_file():
                continue
            shutil.copyfile(f, snap / "objects" / rel / name)
    main_objects = Path(_git(task["repo_path"], "rev-parse", "--path-format=absolute",
                             "--git-common-dir").strip()) / "objects"
    (snap / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (snap / "objects" / "info" / "alternates").write_text(str(main_objects) + "\n")
    sha = _read_ref(gd, task["branch"])
    if sha:
        _git(snap, "update-ref", "refs/heads/" + task["branch"], sha, strict=True)
    return snap, sha


def _main_sha(task):
    try:
        return _git(task["repo_path"], "rev-parse", "--verify", "-q",
                    "refs/heads/{}^{{commit}}".format(task["branch"])).strip() or None
    except RuntimeError:
        return None


def _diffstat(task):
    """(diffstat, files changed, commit list) of the branch in the main repo."""
    if not _main_sha(task):
        return "", 0, ""
    base, br = task["base_sha"], "refs/heads/" + task["branch"]
    # Tree-to-tree in the main repo, so the agent's .gitattributes aren't read
    # and no submodule is entered; gitlinks still count as changed files.
    out = _git(task["repo_path"], "diff", "--stat", "--no-textconv", "--no-ext-diff",
               "{}...{}".format(base, br)).strip()
    commits = _git(task["repo_path"], "log", "--oneline", "{}..{}".format(base, br)).strip()
    m = re.search(r"(\d+) files? changed", out)
    return out, int(m.group(1)) if m else 0, commits[:4000]


def _import(task):
    """Bring the agent's branch into the main repo (never forced), then
    -> (diffstat, files changed, commit list)."""
    snap, sha = _snapshot(task)
    try:
        if sha and _main_sha(task) != sha:
            ref = "refs/heads/" + task["branch"]
            _git(task["repo_path"], "-c", "protocol.file.allow=always", "-c", "submodule.recurse=false",
                 "fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                 str(snap), "{0}:{0}".format(ref))
    finally:
        shutil.rmtree(snap, ignore_errors=True)
    return _diffstat(task)


def _work(task):
    tid = task["id"]
    stop = _stops[tid]

    def on_step(text):
        step = str(text)[:200]
        try:
            _update(tid, last_step=step)
        except Exception:  # noqa: BLE001 — progress must never kill the task
            pass
        _send({"type": "devtask", "id": tid, "state": "running", "last_step": step})

    result, error = None, None
    try:
        result = RUNNER(dict(task), on_step, stop.is_set) or {}
    except BaseException as exc:  # noqa: BLE001 — incl. asyncio.CancelledError from timeouts
        error = exc
    try:
        # Whatever happened, bring back what the agent committed.
        try:
            stat, n, commits = _import(task)
            import_err = None
        except Exception as exc:  # noqa: BLE001
            stat, n, commits, import_err = "", 0, "", str(exc)[:200] or exc.__class__.__name__
        try:
            if stat or commits:
                _update(tid, diffstat=stat, commits=commits)
        except Exception:  # noqa: BLE001
            pass
        if stop.is_set():
            return                      # cancelled: cancel() already set the state
        if error is not None:
            _fail(task, str(error)[:300] or error.__class__.__name__)
        elif import_err:
            _fail(task, "I couldn't bring the branch back: " + import_err)
        else:
            summary = str(result.get("summary") or "").strip()[:2000]
            cost = float(result.get("cost_usd") or 0)
            if _finish(tid, state="done", finished_at=_now(), summary=summary, diffstat=stat,
                       commits=commits, cost_usd=cost):
                _send({"type": "devtask", "id": tid, "state": "done", "last_step": None})
                _announce("{} agent finished: {} {} files changed on branch {}.".format(
                    task["project"], summary, n, task["branch"]))
    except BaseException as exc:  # noqa: BLE001 — never leave the row running
        if not stop.is_set():
            _fail(task, "agent ended unexpectedly: {}".format(exc)[:300])
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        raise error


# ── Claude Agent SDK runner ──────────────────────────────────────────

AGENT_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]
# Hosts sandboxed Bash may reach, so the agent can install a project's
# dependencies into the worktree. Anything else is blocked by the sandbox.
REGISTRY_DOMAINS = [
    "registry.npmjs.org", "registry.yarnpkg.com", "pypi.org", "files.pythonhosted.org",
    "github.com", "codeload.github.com", "objects.githubusercontent.com",
    "raw.githubusercontent.com",
]
# Env vars blanked for the agent (Jarvis's own .env keys, any OAuth token),
# so `env` in a Bash call can't read them.
_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?)(_PATH)?$", re.I)
_KEEP_ENV = set()   # the CLI logs in from the keychain; no token needs passing

AGENT_PROMPT = (
    "You're working in a throwaway worktree on branch {branch}. Make the change, run the "
    "project's tests if there are any, commit on this branch with a clear message, and end "
    "with a 2–3 sentence summary. Never push. Some commands are blocked by a guard; if one "
    "is denied, work around it inside the worktree or say so in your summary."
)


def _step_text(block):
    args = block.input if isinstance(getattr(block, "input", None), dict) else {}
    detail = next((args[k] for k in ("file_path", "path", "notebook_path", "command", "pattern")
                   if isinstance(args.get(k), str) and args[k].strip()), "")
    return "{} {}".format(block.name, " ".join(detail.split())).strip()[:200]


def _agent_env():
    return {k: "" for k in os.environ if _SECRET_ENV.search(k) and k not in _KEEP_ENV}


def _deny_reads(task):
    """Paths sandboxed Bash may not read: Yogesh's keys and Jarvis's secrets,
    the main repo's own .env files, and his private data (iCloud Drive incl.
    the vault, Google Drive, ~/Media, Mail, Messages, browser profiles and
    Claude session transcripts). ~/.claude itself stays readable: Bash
    sources the CLI's shell snapshot from there."""
    home = Path.home()
    lib = home / "Library"
    support = lib / "Application Support"
    out = [home / ".secrets", home / ".ssh", lib / "Keychains", home / ".aws",
           home / ".config" / "gh", home / ".gnupg", home / ".netrc",
           config.ROOT / ".env", config.ROOT / "credentials.json", config.ROOT / "data",
           lib / "Mobile Documents", lib / "CloudStorage", home / "Media",
           lib / "Messages", lib / "Mail", lib / "Cookies", lib / "Safari",
           support / "Google" / "Chrome", support / "Firefox", support / "BraveSoftware",
           support / "Arc", home / ".claude" / "projects"]
    if config.VAULT_DIR:
        out.append(Path(config.VAULT_DIR).expanduser())
    try:
        out += [p for p in Path(task["repo_path"]).glob(".env*")]
    except OSError:
        pass
    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(str(p))
    return uniq


def sandbox_settings(task):
    clone = Path(task["worktree"])
    return {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        "network": {"allowedDomains": list(REGISTRY_DOMAINS)},
        "filesystem": {
            "allowWrite": [str(clone)],
            "denyWrite": [str(clone / ".claude"), str(clone / ".git" / "config"),
                          str(clone / ".git" / "hooks")],
            "denyRead": _deny_reads(task),
        },
    }


def _deny_output(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def agent_options(task, sdk):
    """ClaudeAgentOptions for one task. The guard runs in a PreToolUse hook,
    which fires for every tool call (acceptEdits and allowed_tools auto-approve
    calls without ever reaching can_use_tool); can_use_tool repeats it for
    anything that does reach a permission prompt."""
    wt = str(task["worktree"])

    def check(name, args):
        try:
            return guard(name, args, wt)
        except Exception as exc:  # noqa: BLE001 — fail closed
            return "guard error: {}".format(exc)[:200]

    async def pre_tool_use(hook_input, tool_use_id, context):
        data = hook_input if isinstance(hook_input, dict) else {}
        why = check(data.get("tool_name"), data.get("tool_input"))
        return _deny_output(why) if why else {}

    async def can_use_tool(name, args, context):
        why = check(name, args)
        if why:
            return sdk.PermissionResultDeny(message=why)
        return sdk.PermissionResultAllow()

    return sdk.ClaudeAgentOptions(
        cwd=wt,
        model=config.DEV_AGENT_MODEL,
        max_turns=int(config.DEV_AGENT_MAX_TURNS),
        permission_mode="acceptEdits",
        tools=list(AGENT_TOOLS),
        allowed_tools=list(AGENT_TOOLS),
        setting_sources=["project"],
        skills=[],
        plugins=[],
        mcp_servers={},
        strict_mcp_config=True,
        system_prompt={"type": "preset", "preset": "claude_code",
                       "append": AGENT_PROMPT.format(branch=task["branch"])},
        can_use_tool=can_use_tool,
        hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[pre_tool_use])]},
        sandbox=sandbox_settings(task),
        env=_agent_env(),
    )


def _result_error(res):
    sub = str(getattr(res, "subtype", "") or "error")
    if sub == "error_max_turns":
        return "the agent hit the {}-turn limit".format(config.DEV_AGENT_MAX_TURNS)
    detail = getattr(res, "errors", None) or getattr(res, "result", None) or ""
    if isinstance(detail, list):
        detail = "; ".join(str(d) for d in detail)
    return "agent error ({}){}".format(sub, ": " + str(detail)[:200] if detail else "")


def sdk_runner(task, on_step, should_stop):
    """Run one coding agent on the Claude Agent SDK -> {"summary", "cost_usd"}.
    Raises on errors and timeouts, and CancelledError once should_stop()."""
    import asyncio

    import claude_agent_sdk as sdk

    options = agent_options(task, sdk)
    timeout = float(config.DEV_AGENT_TIMEOUT_MIN) * 60

    async def prompt():
        # can_use_tool and hooks need streaming input: one user message.
        yield {"type": "user", "message": {"role": "user", "content": task["instruction"]},
               "parent_tool_use_id": None, "session_id": "default"}

    async def run():
        stream = sdk.query(prompt=prompt(), options=options)
        try:
            async for msg in stream:
                if isinstance(msg, sdk.AssistantMessage):
                    for block in msg.content or []:
                        if isinstance(block, sdk.ToolUseBlock):
                            on_step(_step_text(block))
                elif isinstance(msg, sdk.ResultMessage):
                    return msg
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()
        return None

    async def supervise():
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        main = asyncio.ensure_future(run())
        try:
            while True:
                done, _ = await asyncio.wait({main}, timeout=0.2)
                if done:
                    return main.result()
                if should_stop():
                    raise asyncio.CancelledError("cancelled")
                if loop.time() >= deadline:
                    raise RuntimeError("the agent timed out after {:g} min".format(
                        float(config.DEV_AGENT_TIMEOUT_MIN)))
        finally:
            if not main.done():
                main.cancel()
                await asyncio.wait({main}, timeout=15)

    res = asyncio.run(supervise())
    if res is None:
        raise RuntimeError("the agent stopped without a result")
    if getattr(res, "is_error", False) or str(getattr(res, "subtype", "success")) != "success":
        raise RuntimeError(_result_error(res))
    return {"summary": str(getattr(res, "result", "") or ""),
            "cost_usd": float(getattr(res, "total_cost_usd", 0) or 0)}


_DEFAULT_RUNNER = RUNNER = sdk_runner


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

    # From here on the row says running: any error must end it as failed.
    try:
        wt.parent.mkdir(parents=True, exist_ok=True)
        _make_clone(repo, wt, branch, base)
    except Exception as e:  # noqa: BLE001
        reason = str(e)[:300]
        _finish(tid, state="failed", finished_at=_now(), summary=reason)
        return "I couldn't create the clone for {}: {}".format(name, reason)
    try:
        _update(tid, last_step="Starting agent")
        task = _get(tid)
        _stops[tid] = threading.Event()
        t = threading.Thread(target=_work, args=(task,), name="devtask-" + tid, daemon=True)
        _threads[tid] = t
        t.start()
    except Exception as e:  # noqa: BLE001
        _threads.pop(tid, None)
        reason = str(e)[:300] or e.__class__.__name__
        try:
            _finish(tid, state="failed", finished_at=_now(), summary=reason)
        except Exception:  # noqa: BLE001
            pass
        return "I couldn't start the agent for {}: {}".format(name, reason)
    _send({"type": "devtask", "id": tid, "state": "running", "last_step": "Starting agent"})
    return "Started task {} in {} on branch {}. I'll tell you when it's done.".format(tid, name, branch)


def _make_clone(repo, clone, branch, base):
    """Standalone clone sharing the repo's objects read-only (alternates;
    never --local, whose hardlinked objects could be edited in place), with
    no remote, on a new branch at base."""
    _git(clone.parent, "clone", "-q", "--shared", "--no-checkout", str(repo), str(clone))
    _git(clone, "remote", "remove", "origin")
    for key in ("user.name", "user.email"):
        try:
            val = _git(repo, "config", "--get", key).strip()
        except RuntimeError:
            val = ""
        if val:
            _git(clone, "config", key, val)
    _git(clone, "checkout", "-q", "-b", branch, base)


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
    _send({"type": "devtask", "id": r["id"], "state": "cancelled", "last_step": None})
    return "Stopped task {}. The worktree and branch {} are kept.".format(r["id"], r["branch"])


def _uncommitted(task):
    """Changed or untracked files in the clone. Never `git status` on the clone:
    it recurses into nested repos, whose .git/config the agent writes, and
    reads global config, so a filter could run as Jarvis. Instead a
    Jarvis-owned snapshot gets a fresh index from the committed tree and
    `ls-files` compares content in-process with no config but Jarvis's
    (STRICT_GIT), so no filter, textconv or hook is defined. Gitlinks are
    compared by HEAD only. .claude/ (CLI bookkeeping) is ignored."""
    snap, sha = _snapshot(task)
    try:
        if not sha:
            return "its branch is missing in the clone"
        wt = task["worktree"]
        _git(wt, "read-tree", sha, git_dir=snap, work_tree=wt, strict=True)
        out = _git(wt, "ls-files", "-z", "--modified", "--deleted", "--others",
                   "--exclude-standard", git_dir=snap, work_tree=wt, strict=True)
        changed = sorted({p for p in out.split("\0")
                          if p and p != ".claude" and not p.startswith(".claude/")})
        return "\n".join(changed)
    finally:
        shutil.rmtree(snap, ignore_errors=True)


def cleanup(task_id, _confirmed=False):
    r = _get(str(task_id).strip())
    if not r:
        return "No coding task {}.".format(task_id)
    if r["state"] == "running":
        return "Task {} is still running; cancel it first.".format(r["id"])
    if _alive(r["id"]):
        return "Task {}'s agent is still stopping; try again in a moment.".format(r["id"])
    wt = Path(r["worktree"] or "")
    try:
        base = _worktrees_dir().resolve()
        ok = not wt.is_symlink() and wt.resolve().parent == base and wt.resolve() != base
    except (OSError, ValueError):
        return "I can't tell where task {}'s clone is.".format(r["id"])
    if not ok:
        return "Task {}'s clone isn't in {}, so I won't remove it.".format(r["id"], WORKTREES)
    if not wt.exists():
        return "Task {}'s clone is already gone. Branch {} is kept.".format(r["id"], r["branch"])
    gd = _clone_git_dir(wt)
    if gd is None:
        return "Task {}'s clone has no usable .git, so I won't remove it.".format(r["id"])
    sha = _read_ref(gd, r["branch"])
    if sha and _main_sha(r) != sha:
        try:
            _import(r)
        except Exception:  # noqa: BLE001
            pass
    if not sha or _main_sha(r) != sha:
        return ("Task {}'s clone has work that isn't on branch {} in the repo, so I won't remove "
                "it.").format(r["id"], r["branch"])
    try:
        dirty = _uncommitted(r)
    except Exception as e:  # noqa: BLE001
        return "I couldn't check task {}'s clone for uncommitted changes: {}".format(r["id"], e)
    if dirty:
        return "Task {}'s clone has uncommitted changes, so I won't remove it.".format(r["id"])
    if not _confirmed:
        raise ConfirmationRequired("Remove the clone folder for task {} ({})? Branch {} is kept.".format(
            r["id"], wt.name, r["branch"]))
    try:
        shutil.rmtree(wt)
    except OSError as e:
        return "I couldn't remove task {}'s clone: {}".format(r["id"], e)
    _update(r["id"], last_step="Clone removed")
    return "Removed task {}'s clone. Branch {} is kept.".format(r["id"], r["branch"])
