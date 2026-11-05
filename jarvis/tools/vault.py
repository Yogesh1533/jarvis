"""Obsidian "Brain" vault: search, read, and append-only notes.

Everything is confined to config.VAULT_DIR (read at call time) and skips the
folders in config.VAULT_EXCLUDE. Writes only create files or insert lines into
an existing note; nothing here truncates, replaces or deletes content.
"""
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

from .. import config

_READ_CHARS = 8000
_SCAN_BYTES = 200_000   # iCloud may evict notes; never slurp a huge file
_SNIPPET = 120
_NOTES_HEADING = "## Notes / brain dump"
_FALLBACK_DAILY = "# {date}\n\n" + _NOTES_HEADING + "\n"
SF_DATALESS = 0x40000000   # st_flags bit: iCloud-evicted file, open() would block
_NOT_DOWNLOADED = "That note isn't downloaded from iCloud yet."
_STOP = {"the", "and", "for", "with", "from", "that", "this", "my", "a", "an", "of", "to", "in", "on", "me", "note", "notes"}


def _fold(name):
    return unicodedata.normalize("NFC", name).casefold()


def _excluded_names():
    return {_fold(n) for n in config.VAULT_EXCLUDE}


def _is_dataless(p):
    """True if p is evicted to iCloud (or can't be stat'ed): don't open it."""
    try:
        return bool(getattr(os.stat(p), "st_flags", 0) & SF_DATALESS)
    except OSError:
        return True


def _root():
    return Path(config.VAULT_DIR).resolve()


def is_excluded(p):
    """True if p sits under the vault and its first relative part is excluded."""
    root = _root()
    try:
        rel = Path(p).resolve().relative_to(root)
    except ValueError:
        return False
    return bool(rel.parts) and _fold(rel.parts[0]) in _excluded_names()


def safe_path(rel):
    """Resolve rel inside the vault (following symlinks) or raise ValueError."""
    root = _root()
    p = (root / str(rel)).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise ValueError("{!r} is outside the vault.".format(rel)) from None
    if is_excluded(p):
        raise ValueError("{!r} is in a folder Jarvis doesn't open.".format(rel))
    if p.suffix.lower() != ".md":
        raise ValueError("{!r} isn't a markdown note.".format(rel))
    return p


def _scan_text(p):
    """First ~200 KB of a note, or None if it can't be read (evicted, binary, ...)."""
    if _is_dataless(p):
        return None
    try:
        with p.open("rb") as f:
            return f.read(_SCAN_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None


def _title(text, p):
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or p.stem
    return p.stem


def _snippet(text, needle):
    i = text.lower().find(needle.lower())
    if i < 0:
        flat = " ".join(text.split())
        return flat[:_SNIPPET]
    start = max(0, i - _SNIPPET // 2)
    return " ".join(text[start:i + len(needle) + _SNIPPET // 2].split())


def _notes():
    """Yield (Path, relpath) for every searchable .md note."""
    root = _root()
    for dirpath, dirs, files in os.walk(root):
        if Path(dirpath) == root:
            ex = _excluded_names()
            dirs[:] = [d for d in dirs if _fold(d) not in ex]
        for name in files:
            if not name.lower().endswith(".md"):
                continue
            p = Path(dirpath) / name
            try:
                rp = p.resolve()
                rp.relative_to(root)   # drops symlinks that leave the vault
            except (OSError, ValueError):
                continue
            if is_excluded(rp):
                continue
            yield p, str(p.relative_to(root))


def search(query, max_results=8):
    """Rank filename hits, then whole-phrase body hits, then all-words hits."""
    max_results = int(max_results)
    q = " ".join(str(query).split()).lower()
    words = [w for w in re.findall(r"\w+", q) if len(w) >= 2 and w not in _STOP]
    if not q:
        return "Give me something to search for."
    hits = []   # (tier, rel, line)
    for p, rel in _notes():
        name = p.stem.lower()
        text = _scan_text(p)
        if text is None:
            continue
        low = text.lower()
        if q in name or (words and all(w in name for w in words)):
            tier, needle = 0, q
        elif q in low:
            tier, needle = 1, q
        elif len(words) >= 2 and all(w in low or w in name for w in words):
            tier, needle = 2, next((w for w in words if w in low), words[0])
        else:
            continue
        hits.append((tier, rel, "{} — {} — {}".format(rel, _title(text, p), _snippet(text, needle))))
    if not hits:
        return "No notes found for that search."
    hits.sort(key=lambda h: (h[0], h[1]))
    return "\n".join(h[2] for h in hits[:max_results])


def read(path):
    p = safe_path(path)
    if not p.is_file():
        raise FileNotFoundError("No note at {}".format(path))
    if _is_dataless(p):
        return _NOT_DOWNLOADED
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > _READ_CHARS:
        return text[:_READ_CHARS] + "\n…(cut, note is {} chars)".format(len(text))
    return text or "(the note is empty)"


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "note"


def _replace_file(p, text):
    """Write the full new text next to p, then swap it in (never a partial write)."""
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".jarvis-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _insert_in_section(text, heading, line):
    """Insert line at the end of the section under heading (before the next
    heading or at the end). Every existing line is kept, in order."""
    lines = text.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == heading)
    except StopIteration:
        sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        return text + sep + heading + "\n" + line + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("#") and re.match(r"#{1,6} ", lines[i]):
            end = i
            break
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1   # land right after the last real line of the section
    lines.insert(at, line)
    return "\n".join(lines)


def _daily_text(date):
    tpl = _root() / "Templates" / "Daily.md"
    try:
        return tpl.read_text(encoding="utf-8").replace("{{date}}", date)
    except (OSError, UnicodeDecodeError):
        return _FALLBACK_DAILY.format(date=date)


def note(text, where="daily", title=None, section=None, _now=None):
    now = _now or datetime.now()
    date, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    root = _root()
    text = str(text).strip()
    if not text:
        raise ValueError("Nothing to write.")
    if where == "inbox":
        inbox = root / "00 Inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        base = "{}_{}".format(date, _slug(title or text.splitlines()[0]))
        n, target = 1, inbox / (base + ".md")
        while target.exists():
            n += 1
            target = inbox / "{}-{}.md".format(base, n)
        body = "---\ntype: note\ncreated: {}\n---\n\n# {}\n\n{}\n".format(
            date, title or text.splitlines()[0][:60], text)
        with open(target, "x", encoding="utf-8") as f:
            f.write(body)
        return "Created {}".format(target.relative_to(root).as_posix())
    daily_dir = root / "Daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    target = daily_dir / (date + ".md")
    rel = target.relative_to(root).as_posix()
    if not target.exists():
        with open(target, "x", encoding="utf-8") as f:
            f.write(_daily_text(date))
    current = target.read_text(encoding="utf-8")
    if section:
        base = current if current.endswith("\n") else current + "\n"
        new = "{}\n## {} {}\n{}\n".format(base, section.strip(), hhmm, text)
    else:
        bullets = text.splitlines()
        line = "- {} {}".format(hhmm, bullets[0])
        for extra in bullets[1:]:
            line += "\n  " + extra
        new = _insert_in_section(current, _NOTES_HEADING, line)
    _replace_file(target, new)
    return "Added to {}".format(rel)
