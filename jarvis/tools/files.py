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


def search(query, max_results=15):
    max_results = int(max_results)
    hits = []
    for root in config.FILES_ROOTS:
        if not root.is_dir():
            continue
        try:
            out = subprocess.run(
                ["mdfind", "-onlyin", str(root), query],
                capture_output=True, text=True, timeout=20,
            ).stdout
            found = [line for line in out.splitlines() if line and not _NOISE.search(line)]
        except FileNotFoundError:  # no Spotlight (non-mac): match on names
            q = query.lower()
            found = [str(p) for p in root.rglob("*") if q in p.name.lower()][:max_results]
        hits.extend(found)
        if len(hits) >= max_results:
            break
    if not hits:
        return "No files match {!r}.".format(query)
    return "\n".join(hits[:max_results])


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
