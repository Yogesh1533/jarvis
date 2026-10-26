"""Persistent memory: one Markdown file per fact, summary on the first line."""
import re

from .. import config
from . import ConfirmationRequired, recall

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _path(name):
    if not _NAME_RE.match(name or ""):
        raise ValueError(
            "Memory name must be a kebab-case slug (a-z, 0-9, dashes), got {!r}".format(name)
        )
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return config.MEMORY_DIR / "{}.md".format(name)


def _index(name):
    """Keep the recall index in step with a memory file. A failure here must
    never lose or block the memory itself: reindex() repairs it later.
    Returns True only if a vector was (re)computed."""
    try:
        return recall.upsert("memory", name, _path(name).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — the file is the source of truth
        print("[memory] not indexed ({}): {}".format(name, exc))
        return False


def reindex():
    """Reconcile the recall index with the memory files (run at startup):
    embed new or edited files, drop vectors whose file is gone."""
    names = [p.stem for p in sorted(config.MEMORY_DIR.glob("*.md"))] if config.MEMORY_DIR.is_dir() else []
    indexed = sum(_index(name) for name in names)
    orphans = [ref for ref in recall.refs("memory") if ref not in names]
    for ref in orphans:
        recall.delete("memory", ref)
    return {"indexed": indexed, "removed": len(orphans)}


def save(name, summary, content):
    path = _path(name)
    existed = path.exists()
    path.write_text("# {}\n\n{}\n".format(summary.strip(), content.strip()), encoding="utf-8")
    _index(name)
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
    recall.delete("memory", name)
    return "Memory '{}' deleted.".format(name)


def load_all():
    """All memories as one text block for the session-start system prompt."""
    if not config.MEMORY_DIR.is_dir():
        return ""
    parts = []
    for path in sorted(config.MEMORY_DIR.glob("*.md")):
        parts.append("--- memory: {} ---\n{}".format(path.stem, path.read_text(encoding="utf-8").strip()))
    return "\n\n".join(parts)


def items():
    """All memories as {name, summary, content} for the HUD memory panel."""
    if not config.MEMORY_DIR.is_dir():
        return []
    out = []
    for path in sorted(config.MEMORY_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        first, _, rest = text.partition("\n")
        out.append({
            "name": path.stem,
            "summary": first.lstrip("# ").strip(),
            "content": rest.strip(),
        })
    return out
