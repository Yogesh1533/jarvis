"""Persistent memory: one Markdown file per fact, summary on the first line."""
import re

from .. import config
from . import ConfirmationRequired

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _path(name):
    if not _NAME_RE.match(name or ""):
        raise ValueError(
            "Memory name must be a kebab-case slug (a-z, 0-9, dashes), got {!r}".format(name)
        )
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return config.MEMORY_DIR / "{}.md".format(name)


def save(name, summary, content):
    path = _path(name)
    existed = path.exists()
    path.write_text("# {}\n\n{}\n".format(summary.strip(), content.strip()), encoding="utf-8")
    return "Memory '{}' {}.".format(name, "updated" if existed else "saved")


def read(name):
    path = _path(name)
    if not path.exists():
        return "No memory named '{}'.".format(name)
    return path.read_text(encoding="utf-8")


def delete(name, _confirmed=False):
    path = _path(name)
    if not path.exists():
        return "No memory named '{}'.".format(name)
    if not _confirmed:
        summary = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
        raise ConfirmationRequired("Delete the memory '{}' — {}?".format(name, summary))
    path.unlink()
    return "Memory '{}' deleted.".format(name)


def load_all():
    """All memories as one text block for the session-start system prompt."""
    if not config.MEMORY_DIR.is_dir():
        return ""
    parts = []
    for path in sorted(config.MEMORY_DIR.glob("*.md")):
        parts.append("--- memory: {} ---\n{}".format(path.stem, path.read_text(encoding="utf-8").strip()))
    return "\n\n".join(parts)
