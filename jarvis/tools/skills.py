"""Reusable skills: workflows Jarvis learns once and runs again by name.

"Save that as my end-of-day skill" stores the steps the model writes plus
the tool calls Jarvis actually made in the previous turn; "run my end-of-day
skill" hands those steps back so the model carries them out with its normal
tools. Running a skill grants nothing extra: every step goes through the
same dispatcher and confirmation gate as a spoken request.

Skills are Markdown files with a small header: starter skills ship in
skills/, the user's own live in data/skills/ (a user skill with the same
name replaces a starter). The files are the source of truth and can be
edited by hand.
"""
import json
import re
from datetime import date

from .. import config

_NAME = re.compile(r"[^a-z0-9]+")
_SKIP = ("skill_", "hud_", "voice_", "assistant_")   # not part of a workflow

# Tool calls seen this turn and the turn before, for skill_save.
_current = []
_previous = []


def begin_turn():
    """Called at the start of every user turn."""
    global _current, _previous
    if _current:
        _previous = _current
    _current = []


def on_tool(phase, name, args, is_error):
    if phase == "end" and not is_error and not name.startswith(_SKIP):
        _current.append((name, dict(args)))


def _slug(name):
    slug = _NAME.sub("-", (name or "").lower()).strip("-")
    if not slug:
        raise ValueError("A skill needs a name")
    return slug


def _parse(path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---\n"):
        head, _, body = text[4:].partition("\n---\n")
        for line in head.splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    meta.setdefault("name", path.parent.name if path.name == "SKILL.md" else path.stem)
    meta["body"] = body.strip()
    meta["path"] = path
    return meta


def _all():
    """Flat files (name.md) and Agent Skills folders (name/SKILL.md) both work,
    so a skill written for Claude can be dropped straight in."""
    found = {}
    for folder in (config.STARTER_SKILLS_DIR, config.SKILLS_DIR):
        if folder.exists():
            paths = sorted(folder.glob("*.md")) + sorted(folder.glob("*/SKILL.md"))
            for path in paths:
                skill = _parse(path)
                skill["root"] = folder
                found[_slug(skill["name"])] = skill
    return found


def _find(name):
    skills = _all()
    slug = _slug(name)
    if slug in skills:
        return skills[slug]
    # "end of day" finds "end-of-day-wrap-up"
    hits = [s for k, s in skills.items() if slug in k]
    if len(hits) == 1:
        return hits[0]
    raise ValueError("No skill called {!r}. Skills: {}".format(name, ", ".join(skills) or "none yet"))


def index_for_prompt():
    skills = _all()
    if not skills:
        return ""
    return "\n".join("- {}: {}".format(k, s.get("description", "")) for k, s in skills.items())


def save(name, description, steps, use_last_turn=True):
    slug = _slug(name)
    recorded = _previous if use_last_turn else []
    lines = [
        "---",
        "name: " + slug,
        "description: " + " ".join(description.split()),
        "created: " + date.today().isoformat(),
        "---",
        "",
        "## Steps",
        "",
        steps.strip(),
    ]
    if recorded:
        lines += ["", "## Tool calls when it was recorded", ""]
        lines += ["- `{}` {}".format(n, json.dumps(a, ensure_ascii=False)) for n, a in recorded]
    config.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.SKILLS_DIR / (slug + ".md")
    existed = path.exists()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "Skill '{}' {} with {} step(s){}.".format(
        slug, "updated" if existed else "saved", steps.count("\n") + 1,
        " and {} recorded tool call(s)".format(len(recorded)) if recorded else "",
    )


def run(name):
    skill = _find(name)
    return (
        "SKILL: {}\n{}\n\nCarry out these steps now with your tools, in order. "
        "Adapt names, dates and times to today. Anything that sends, deletes or "
        "changes shared events still needs the user's confirmation as usual. "
        "When done, give one short spoken summary.".format(skill["name"], skill["body"])
    )


def data():
    """Skills for the HUD shelf: newest of your own first, then the starters."""
    rows = []
    for key, s in _all().items():
        rows.append({
            "name": key,
            "description": s.get("description", ""),
            "starter": s["root"] == config.STARTER_SKILLS_DIR,
            "created": s.get("created", ""),
            "body": s["body"],
        })
    rows.sort(key=lambda r: r["created"], reverse=True)
    rows.sort(key=lambda r: r["starter"])   # stable: yours first, newest first
    return rows


def list_skills():
    skills = _all()
    if not skills:
        return "No skills yet. Do something once, then say 'save that as a skill'."
    return "\n".join(
        "{}{}: {}".format(k, " (starter)" if s["root"] == config.STARTER_SKILLS_DIR else "",
                          s.get("description", ""))
        for k, s in skills.items()
    )


def delete(name, _confirmed=False):
    from . import ConfirmationRequired

    skill = _find(name)
    if skill["root"] != config.SKILLS_DIR:
        raise ValueError("'{}' is a starter skill; save your own version to replace it".format(skill["name"]))
    if not _confirmed:
        raise ConfirmationRequired("Delete your skill '{}'?".format(skill["name"]))
    if skill["path"].name == "SKILL.md":
        raise ValueError("'{}' is a skill folder; remove it from data/skills by hand".format(skill["name"]))
    skill["path"].unlink()
    return "Skill '{}' deleted.".format(skill["name"])
