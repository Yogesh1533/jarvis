"""File search/read/open, confined to the folders in FILES_ROOTS."""
import re
import subprocess
from pathlib import Path

from .. import config

_MAX_CHARS = 10000
_NOISE = re.compile(r"/(node_modules|\.venv|site-packages|\.git)(/|\.)|\.nosync/")
_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".py", ".js",
    ".ts", ".tsx", ".html", ".css", ".log", ".rtf", ".tex", ".xml", ".ini",
    ".toml", ".sh", ".c", ".cpp", ".h", ".java", ".go", ".rs", ".swift",
}


def _allowed(path):
    p = Path(path).expanduser().resolve()
    for root in config.FILES_ROOTS:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    raise PermissionError(
        "{} is outside the folders Jarvis may access ({}). Add it to FILES_ROOTS "
        "in .env to allow it.".format(p, ", ".join(str(r) for r in config.FILES_ROOTS))
    )


_STOP = {"the", "and", "for", "with", "from", "that", "this", "my", "a", "an", "of", "to", "in", "on", "me", "file", "files", "doc", "document"}


def _find(root, query):
    """Spotlight inside one root (or a name match off macOS), minus build noise."""
    try:
        out = subprocess.run(
            ["mdfind", "-onlyin", str(root), query],
            capture_output=True, text=True, timeout=20,
        ).stdout
        return [line for line in out.splitlines() if line and not _NOISE.search(line)]
    except FileNotFoundError:  # no Spotlight (non-mac): match on names
        q = query.lower()
        return [str(p) for p in root.rglob("*") if q in p.name.lower() and not _NOISE.search(str(p))]


def search(query, max_results=15):
    """Find files by name or content. Tries the whole phrase first; if nothing
    matches (the model often adds words the file doesn't contain, like
    "Northwind budget breakdown" for Northwind-Budget.csv), it searches each
    word and ranks files by how many of the words they match."""
    max_results = int(max_results)
    roots = [r for r in config.FILES_ROOTS if r.is_dir()]
    hits = []
    for root in roots:
        hits.extend(h for h in _find(root, query) if h not in hits)
        if len(hits) >= max_results:
            break
    if hits:
        return "\n".join(hits[:max_results])
    words = [w for w in re.findall(r"[\w-]{3,}", query.lower()) if w not in _STOP]
    if len(words) < 2:
        return "No files match {!r}.".format(query)
    score = {}
    for w in words:
        for root in roots:
            for h in _find(root, w):
                name = Path(h).name.lower()
                score[h] = score.get(h, 0) + (2 if w in name else 1)
    if not score:
        return "No files match {!r}.".format(query)
    ranked = sorted(score, key=lambda h: (-score[h], h))
    return "No exact match for {!r}. Closest files by the words in it:\n{}".format(
        query, "\n".join(ranked[:max_results]))


def read(path):
    p = _allowed(path)
    if not p.is_file():
        raise FileNotFoundError("No file at {}".format(p))
    if p.suffix.lower() == ".pdf":
        text = _pdf_text(p)
    elif p.suffix.lower() in _TEXT_SUFFIXES:
        text = p.read_text(encoding="utf-8", errors="replace")
    else:
        raise ValueError(
            "Can't read {} files as text; try files_open to open it instead.".format(p.suffix)
        )
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n[truncated]"
    return text or "(the file is empty)"


def _pdf_text(p):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("Reading PDFs needs 'pip install pypdf' in the Jarvis venv.") from None
    reader = PdfReader(str(p))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:30])


def open_file(path):
    p = _allowed(path)
    if not p.exists():
        raise FileNotFoundError("No file at {}".format(p))
    subprocess.run(["open", str(p)], check=True)
    return "Opened {}.".format(p.name)
