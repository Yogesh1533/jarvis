"""Offline test for the Brain vault tools (search, read, note) on a temp vault.

Run:  .venv/bin/python tests/vault_test.py
"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: {}".format(name)
    PASS.append(name)
    print("  ok - {}".format(name))


DAILY_TEMPLATE = """---
type: daily
created: {{date}}
---

# {{date}}

## Flags

## Schedule

## Deadlines (next 7 days)

## Top 3
- [ ] 
- [ ] 
- [ ] 

## Tasks
- [ ] 

## Notes / brain dump
"""

root = Path(tempfile.mkdtemp(prefix="jarvis-vault-test-"))
VDIR = root / "Brain"
for d in ("Daily", "Templates", "People", "Acme", "00 Inbox"):
    (VDIR / d).mkdir(parents=True)
(VDIR / "Templates" / "Daily.md").write_text(DAILY_TEMPLATE, encoding="utf-8")
(VDIR / "People" / "secret.md").write_text("# secret\nthe secret sauce\n", encoding="utf-8")
(VDIR / "Projects.md").write_text("# Dashboard\nall the things\n", encoding="utf-8")
(VDIR / "Acme" / "Café brief.md").write_text("# Café brief\nlogo due Friday\n", encoding="utf-8")
(root / "outside.md").write_text("outside\n", encoding="utf-8")
(root / "x.md").write_text("x\n", encoding="utf-8")
os.symlink(root / "x.md", VDIR / "Daily" / "link.md")

config.VAULT_DIR = VDIR
config.VAULT_EXCLUDE = [".obsidian", ".trash", "Templates", "People", "Life"]

from jarvis.tools import vault  # noqa: E402

NOW = datetime(2026, 11, 5, 9, 30)

print("== search ==")
check("content hit finds Café note", "Café brief" in vault.search("logo"))
first = vault.search("projects").splitlines()[0]
check("title hit ranks first", "Projects.md" in first)
check("words fallback finds note", "Café brief" in vault.search("friday logo"))
check("excluded folder not searched", "secret" not in vault.search("secret"))

print("== read ==")
for name, rel in (("excluded folder", "People/secret.md"), ("traversal", "../outside.md"),
                  ("symlink escape", "Daily/link.md"), ("non-md", "Templates/Daily.txt")):
    try:
        vault.read(rel)
        ok = False
    except ValueError:
        ok = True
    check("read refuses " + name, ok)
for rel in ("people/secret.md", "PEOPLE/secret.md", "templates/Daily.md"):
    try:
        vault.read(rel)
        ok = False
    except ValueError:
        ok = True
    check("read refuses case variant " + rel, ok)
check("case variants not searchable", "sauce" not in vault.search("sauce") and "secret" not in vault.search("SECRET"))
check("read round-trips unicode and spaces", "logo due Friday" in vault.read("Acme/Café brief.md"))
(VDIR / "Big.md").write_text("a" * 9000, encoding="utf-8")
big = vault.read("Big.md")
check("read cuts long notes", "…(cut, note is 9000 chars)" in big and len(big) < 8100)
check("is_excluded", vault.is_excluded(VDIR / "People" / "secret.md") and not vault.is_excluded(VDIR / "Projects.md"))

print("== note: daily ==")
r = vault.note("call Sam", _now=NOW)
check("note reply", r == "Added to Daily/2026-11-05.md")
daily = VDIR / "Daily" / "2026-11-05.md"
text1 = daily.read_text(encoding="utf-8")
check("daily created from template", "created: 2026-11-05" in text1 and "# 2026-11-05" in text1)
check("bullet after notes heading", text1.index("## Notes / brain dump") < text1.index("- 09:30 call Sam"))
vault.note("buy cable", _now=datetime(2026, 11, 5, 9, 45))
text2 = daily.read_text(encoding="utf-8")
check("second bullet appended after first", text2.index("- 09:30 call Sam") < text2.index("- 09:45 buy cable"))
check("earlier content kept as prefix", text2.startswith(text1.rstrip("\n")))

print("== note: heading not last ==")
mid = VDIR / "Daily" / "2026-11-06.md"
orig = "# d\n\n## Notes / brain dump\n- 08:00 old\n\n## After\nkeep me\n"
mid.write_text(orig, encoding="utf-8")
vault.note("new", _now=datetime(2026, 11, 6, 10, 0))
new_lines = mid.read_text(encoding="utf-8").splitlines()
it = iter(new_lines)
check("original lines kept in order", all(any(l == n for n in it) for l in orig.splitlines()))
check("inserted in the right section", new_lines.index("- 10:00 new") < new_lines.index("## After"))

print("== note: section ==")
before = daily.read_text(encoding="utf-8")
vault.note("line1\nline2", section="Wrap", _now=datetime(2026, 11, 5, 20, 0))
after = daily.read_text(encoding="utf-8")
check("section block appended at end", after.endswith("## Wrap 20:00\nline1\nline2\n") and after.startswith(before.rstrip("\n")))
vault.note("again", section="Wrap", _now=datetime(2026, 11, 5, 21, 0))
check("two wrap blocks", daily.read_text(encoding="utf-8").count("## Wrap") == 2)

print("== note: inbox ==")
r1 = vault.note("idea", where="inbox", title="New idea", _now=NOW)
r2 = vault.note("idea", where="inbox", title="New idea", _now=NOW)
f1 = VDIR / "00 Inbox" / "2026-11-05_new-idea.md"
f2 = VDIR / "00 Inbox" / "2026-11-05_new-idea-2.md"
check("inbox files created", f1.exists() and f2.exists())
check("inbox replies", r1 == "Created 00 Inbox/2026-11-05_new-idea.md" and r2.endswith("_new-idea-2.md"))
check("inbox frontmatter", "type: note" in f1.read_text(encoding="utf-8") and "idea" in f1.read_text(encoding="utf-8"))

print("== search skips unreadable files ==")
(VDIR / "Bad.md").write_text("logo trouble\n", encoding="utf-8")
orig_read = Path.read_text
orig_open = Path.open


def bad_read(self, *a, **k):
    if self.name == "Bad.md":
        raise OSError("dataless")
    return orig_read(self, *a, **k)


def bad_open(self, *a, **k):
    if self.name == "Bad.md":
        raise OSError("dataless")
    return orig_open(self, *a, **k)


Path.read_text = bad_read
Path.open = bad_open
try:
    res = vault.search("logo")
finally:
    Path.read_text = orig_read
    Path.open = orig_open
check("search survives OSError and returns others", "Café brief" in res)

print("== dataless (iCloud evicted) ==")
(VDIR / "Evicted.md").write_text("logo evicted body\n", encoding="utf-8")
real_dataless = vault._is_dataless
vault._is_dataless = lambda p: Path(p).name == "Evicted.md" or real_dataless(p)
try:
    res = vault.search("logo")
    msg = vault.read("Evicted.md")
finally:
    vault._is_dataless = real_dataless
check("search skips dataless, keeps others", "Evicted" not in res and "Café brief" in res)
check("read gives clear message for dataless", "isn't downloaded from iCloud" in msg)
real_stat = os.stat


class _St:
    st_flags = vault.SF_DATALESS


os.stat = lambda p, *a, **k: _St() if str(p).endswith("Evicted.md") else real_stat(p, *a, **k)
try:
    check("flag bit detected via os.stat", vault._is_dataless(VDIR / "Evicted.md") and not vault._is_dataless(VDIR / "Projects.md"))
finally:
    os.stat = real_stat

print("== tool registration and files exclusion ==")
from jarvis import tools  # noqa: E402
from jarvis.tools import files  # noqa: E402

names = [s["name"] for s in tools.TOOL_SCHEMAS]
check("vault and project tools registered", all(n in names for n in ("vault_search", "vault_read", "vault_note", "projects_status")))
note_schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "vault_note")["input_schema"]
check("vault_note schema hides _now", "_now" not in note_schema["properties"] and note_schema["properties"]["where"]["enum"] == ["daily", "inbox"])
out, is_err = tools.execute("vault_note", {"text": "via registry", "_now": "2020-01-01"}, lambda p: False)
today = datetime.now().strftime("%Y-%m-%d")
check("execute strips _now", not is_err and today in out and "2020" not in out and (VDIR / "Daily" / (today + ".md")).exists())
out, is_err = tools.execute("vault_search", {"query": "logo"}, lambda p: False)
check("vault_search via execute", not is_err and "Café brief" in out)

config.FILES_ROOTS = [root.resolve()]
def _refusal(fn, path):
    try:
        fn(path)
    except PermissionError as exc:
        return "private vault folder" in str(exc)
    except Exception:  # noqa: BLE001
        return False
    return False


secret = str(VDIR / "People" / "secret.md")
check("files.read refuses excluded vault path", _refusal(files.read, secret))
check("files.open refuses excluded vault path", _refusal(files.open_file, secret))
check("files.read refuses other casing", _refusal(files.read, str(VDIR / "people" / "secret.md")))
real_ex = vault.is_excluded


def _boom(p):
    raise OSError("boom")


vault.is_excluded = _boom
try:
    check("files.read fails closed if exclusion check errors", _refusal(files.read, str(VDIR / "Projects.md")))
finally:
    vault.is_excluded = real_ex
real_find = files._find
files._find = lambda r, q: [str(VDIR / "People" / "secret.md"), str(VDIR / "Projects.md")]
try:
    res = files.search("secret")
finally:
    files._find = real_find
check("files.search drops excluded vault paths", "secret.md" not in res and "Projects.md" in res)
check("files.read still reads normal vault file", "all the things" in files.read(str(VDIR / "Projects.md")))
config.VAULT_DIR = root / "missing-vault"
check("files.read works when vault missing", "outside" in files.read(str(root / "outside.md")))
config.VAULT_DIR = VDIR

print("ALL {} CHECKS PASSED".format(len(PASS)))
