"""Project status from the Brain vault's Projects.md plus read-only git info.

Config is read at call time. git is only ever asked read-only questions
(`git -C`, 5 s timeout) and never fetches.
"""
import difflib
import re
import subprocess
from pathlib import Path

from .. import config
from . import vault

_GIT_TIMEOUT = 5


def _cells(line):
    line = line.strip()
    if not line.startswith("|"):
        return None
    return [c.strip() for c in line.strip("|").split("|")]


def _clean(cell):
    return cell.replace("`", "").strip()


def rows():
    """Every row of every Projects.md table with a Project and a Path* column."""
    p = Path(config.VAULT_DIR) / "Projects.md"
    if vault._is_dataless(p):
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out, cols = [], None
    for line in text.splitlines():
        cells = _cells(line)
        if cells is None:
            cols = None
            continue
        low = [c.lower() for c in cells]
        if "project" in low and any(c.startswith("path") for c in low):
            cols = {"name": low.index("project"),
                    "path": next(i for i, c in enumerate(low) if c.startswith("path")),
                    "what": next((i for i, c in enumerate(low) if c.startswith("what")), None),
                    "github": next((i for i, c in enumerate(low) if c.startswith("github")), None)}
            continue
        if cols is None or all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue

        def get(key):
            i = cols[key]
            return _clean(cells[i]) if i is not None and i < len(cells) else ""

        name = get("name")
        if not name:
            continue
        raw = get("path")
        path = Path(raw).expanduser() if raw and raw.lower() != "none" else None
        out.append({"name": name, "what": get("what"), "path": path, "github": get("github")})
    return out


def find(name):
    rs = rows()
    q = str(name).strip().lower()
    if not q:
        return None
    for r in rs:
        if r["name"].lower() == q:
            return r
    for r in rs:
        if r["name"].lower().startswith(q):
            return r
    close = difflib.get_close_matches(q, [r["name"].lower() for r in rs], n=1, cutoff=0.6)
    return next((r for r in rs if r["name"].lower() == close[0]), None) if close else None


def _git(path, *args):
    """(returncode, stdout, stderr); raises on timeout or missing git."""
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                       timeout=_GIT_TIMEOUT)
    return r.returncode, r.stdout, r.stderr


def _try(path, *args):
    """stdout, or None if the command failed, timed out or git is missing."""
    try:
        rc, out, _ = _git(path, *args)
    except (OSError, subprocess.SubprocessError):
        return None
    return out if rc == 0 else None


def git_info(path):
    """None if path isn't the root of a git repo; {"error": ...} if git failed;
    otherwise the info dict (dirty is None when status couldn't be read)."""
    try:
        rc, out, err = _git(path, "rev-parse", "--show-toplevel")
    except subprocess.TimeoutExpired:
        return {"error": "git timed out"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": "git unavailable ({})".format(e.__class__.__name__)}
    if rc != 0:
        if "not a git repository" in err.lower():
            return None
        return {"error": "git failed: {}".format(err.strip()[:80] or "exit {}".format(rc))}
    try:
        if Path(out.strip()).resolve() != Path(path).resolve():
            return None   # nested inside a parent repo: not this project's own repo
    except OSError:
        return {"error": "git failed"}
    branch = (_try(path, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or "unknown"
    log = _try(path, "log", "-1", "--format=%cr%x1f%s") or ""
    rel, _, subject = log.strip().partition("\x1f")
    st = _try(path, "status", "--porcelain")
    dirty = None if st is None else len([l for l in st.splitlines() if l.strip()])
    br = _try(path, "branch", "--list", "jarvis/*")
    agents = 0 if br is None else len([l for l in br.splitlines() if l.strip()])
    return {"branch": branch, "last_commit_rel": rel, "last_subject": subject,
            "dirty": dirty, "agent_branches": agents}


def _line(r):
    path = r["path"]
    if path is None or not path.exists():
        return "{}: folder missing".format(r["name"])
    info = git_info(path)
    if info is None:
        return "{}: no git repo".format(r["name"])
    if "error" in info:
        return "{}: git unavailable ({})".format(r["name"], info["error"])
    if info["last_subject"]:
        last = 'last commit {} "{}"'.format(info["last_commit_rel"], info["last_subject"])
    else:
        last = "no commits yet"
    d = info["dirty"]
    if d is None:
        tail = "uncommitted files unknown"
    elif d:
        tail = "{} uncommitted file{}".format(d, "" if d == 1 else "s")
    else:
        tail = "clean"
    out = "{} (branch {}): {}, {}".format(r["name"], info["branch"], last, tail)
    if info["agent_branches"]:
        out += ", {} agent branch{}".format(info["agent_branches"], "" if info["agent_branches"] == 1 else "es")
    return out


def status(project=None):
    p = Path(config.VAULT_DIR) / "Projects.md"
    if not p.exists():
        return "I can't find Projects.md in the vault."
    if vault._is_dataless(p):
        return "Projects.md isn't downloaded from iCloud yet."
    if project:
        r = find(project)
        return _line(r) if r else "I don't see a project called {}.".format(project)
    rs = rows()
    return "\n".join(_line(r) for r in rs) if rs else "No projects found in Projects.md."
