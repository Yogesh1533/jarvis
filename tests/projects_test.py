"""Offline test for the Projects.md status tool on a temp vault and temp repos.

Run:  .venv/bin/python tests/projects_test.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: {}".format(name)
    PASS.append(name)
    print("  ok - {}".format(name))


root = Path(tempfile.mkdtemp(prefix="jarvis-projects-test-"))
VDIR = root / "Brain"
VDIR.mkdir()
alpha, beta, gamma = root / "alpha", root / "beta", root / "gamma"
alpha.mkdir()
beta.mkdir()


def git(*args):
    subprocess.run(["git", "-C", str(alpha), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


git("init", "-q", "-b", "main")
(alpha / "a.txt").write_text("a\n")
git("add", "a.txt")
git("commit", "-q", "-m", "init")
(alpha / "new.txt").write_text("untracked\n")

(VDIR / "Projects.md").write_text("""# Projects

## Apps
| Project | What it is | Path on the mini | GitHub |
|---|---|---|---|
| alpha | The alpha app | `{a}` | yogesh/alpha |
| beta | Plain folder | `{b}` | none |

## Agents
| Project | What it is | Path | GitHub |
|---|---|---|---|
| gamma | Gone agent | `{g}` | none |

## Client work
- Acme site | `{a}`
- Other client
""".format(a=alpha, b=beta, g=gamma), encoding="utf-8")

config.VAULT_DIR = VDIR
config.DEV_ROOTS = [root]

from jarvis.tools import projects  # noqa: E402

print("== rows / find ==")
rows = projects.rows()
check("three rows from both tables", len(rows) == 3)
check("row keys and path type", rows[0]["name"] == "alpha" and rows[0]["path"] == alpha
      and rows[0]["github"] == "yogesh/alpha" and rows[0]["what"] == "The alpha app")
check("find prefix", projects.find("ALP")["name"] == "alpha")
check("find fuzzy", projects.find("alpah")["name"] == "alpha")
check("find none", projects.find("zzz") is None)

print("== git_info ==")
info = projects.git_info(alpha)
check("dirty count", info["dirty"] == 1)
check("last subject", info["last_subject"] == "init")
check("branch and agent branches", info["branch"] == "main" and info["agent_branches"] == 0)
check("non-git is None", projects.git_info(beta) is None)

print("== status ==")
s = projects.status()
check("status mentions alpha line", 'alpha (branch main): last commit' in s and '"init", 1 uncommitted file' in s)
check("status no git", "no git" in s)
check("status missing", "missing" in s)
one = projects.status("alpha")
check("status single project", "alpha" in one and "beta" not in one)
check("status unknown project", "don't see" in projects.status("zzz").lower() or "no project" in projects.status("zzz").lower())

print("ALL {} CHECKS PASSED".format(len(PASS)))
