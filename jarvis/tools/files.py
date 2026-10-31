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
    """Find files by name or content. Exact phrase matches come first. Spotlight
    needs every word, and the model often adds words a file doesn't contain
    ("Northwind budget breakdown" for Northwind-Budget.csv), so files matching
    the individual words follow, ranked by how many words they match (a word in
    the file name counts double)."""
    max_results = int(max_results)
    roots = [r for r in config.FILES_ROOTS if r.is_dir()]
    exact = []
    for root in roots:
        exact.extend(h for h in _find(root, query) if h not in exact)
        if len(exact) >= max_results:
            break
    words = [w for w in re.findall(r"[\w-]{3,}", query.lower()) if w not in _STOP]
    score = {}
    if len(words) >= 2 and len(exact) < max_results:
        for w in words:
            for root in roots:
                for h in _find(root, w):
                    if h in exact:
                        continue
                    name = Path(h).name.lower()
                    score[h] = score.get(h, 0) + (2 if w in name else 1)
    # Keep only files matching more than one word, or a word in their name.
    close = sorted((h for h in score if score[h] >= 2), key=lambda h: (-score[h], h))
    if not exact and not close:
        return "No files match {!r}.".format(query)
    out = exact[:max_results]
    room = max_results - len(out)
    if close and room > 0:
        out_close = close[:room]
        if out:
            return "\n".join(out) + "\nAlso close (match some of the words):\n" + "\n".join(out_close)
        return "No exact match for {!r}. Closest files by the words in it:\n{}".format(query, "\n".join(out_close))
    return "\n".join(out)


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
