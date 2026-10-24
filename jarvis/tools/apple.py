"""Apple Notes and Messages (iMessage / SMS), via AppleScript.

The first use of each asks macOS for permission to control that app.
Sending a message always needs the user's spoken confirmation.
"""
import html
import re
import subprocess

from . import ConfirmationRequired
from .mac import osa

_SEP = "␞"   # record separator that won't appear in note text


# ── Notes ───────────────────────────────────────────────────────────
def notes_create(title, body=""):
    paragraphs = "".join(
        "<div>{}</div>".format(html.escape(line) or "<br>") for line in body.splitlines()
    )
    osa(
        'tell application "Notes" to make new note with properties '
        "{body:(item 1 of argv)}",
        "<h1>{}</h1>{}".format(html.escape(title), paragraphs),
    )
    return "Created the note '{}' in Apple Notes.".format(title)


def notes_search(query, limit=8):
    out = osa(
        'set q to item 1 of argv\n'
        'set sep to item 2 of argv\n'
        'set lim to (item 3 of argv) as integer\n'
        'set found to ""\n'
        'tell application "Notes"\n'
        'set hits to (notes whose name contains q or plaintext contains q)\n'
        'set k to 0\n'
        'repeat with n in hits\n'
        'set k to k + 1\n'
        'if k > lim then exit repeat\n'
        'set p to plaintext of n\n'
        'if length of p > 200 then set p to text 1 thru 200 of p\n'
        'set found to found & (name of n) & sep & (modification date of n as text) & sep & p & (ASCII character 30)\n'
        'end repeat\n'
        'end tell\n'
        'return found',
        query, _SEP, limit, timeout=30,
    )
    rows = [r for r in out.split("\x1e") if r.strip()]
    if not rows:
        return "No notes match '{}'.".format(query)
    lines = []
    for row in rows:
        name, _, rest = row.partition(_SEP)
        when, _, snippet = rest.partition(_SEP)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        lines.append("- {} (edited {}): {}".format(name.strip(), when.strip(), snippet))
    return "\n".join(lines)


def notes_read(title):
    out = osa(
        'tell application "Notes"\n'
        'set hits to (notes whose name is (item 1 of argv))\n'
        'if (count of hits) = 0 then set hits to (notes whose name contains (item 1 of argv))\n'
        'if (count of hits) = 0 then return ""\n'
        'return plaintext of item 1 of hits\n'
        'end tell',
        title, timeout=20,
    )
    if not out:
        return "No note called '{}'.".format(title)
    return out[:6000]


# ── Messages ────────────────────────────────────────────────────────
_HANDLE = re.compile(r"^\+?[\d\s().-]{6,}$|^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _lookup(name):
    """[(full name, phone or email)] from Contacts for a name."""
    out = osa(
        'set sep to item 2 of argv\n'
        'set found to ""\n'
        'tell application "Contacts"\n'
        'repeat with p in (people whose name contains (item 1 of argv))\n'
        'repeat with ph in phones of p\n'
        'set found to found & (name of p) & sep & (value of ph) & linefeed\n'
        'end repeat\n'
        'repeat with em in emails of p\n'
        'set found to found & (name of p) & sep & (value of em) & linefeed\n'
        'end repeat\n'
        'end repeat\n'
        'end tell\n'
        'return found',
        name, _SEP, timeout=20,
    )
    pairs = []
    for line in out.splitlines():
        who, _, handle = line.partition(_SEP)
        if handle and (who, handle) not in pairs:
            pairs.append((who, handle))
    return pairs


def message_send(to, text, _confirmed=False):
    """Send an iMessage (or SMS via a paired iPhone) to a contact or number."""
    to = to.strip()
    if _HANDLE.match(to):
        who, handle = to, to
    else:
        matches = _lookup(to)
        people = sorted({m[0] for m in matches})
        if not matches:
            return "No contact matches '{}'. Ask for their number or email.".format(to)
        if len(people) > 1:
            return "Several contacts match '{}': {}. Ask which one.".format(to, ", ".join(people))
        # Prefer a phone number; the confirmation shows which one is used.
        phones = [h for _, h in matches if "@" not in h]
        who, handle = people[0], phones[0] if phones else matches[0][1]
    if not _confirmed:
        raise ConfirmationRequired(
            "Send a message to {} ({})?\n\"{}\"".format(who, handle, text)
        )
    try:
        osa(
            'tell application "Messages"\n'
            'set svc to 1st account whose service type = iMessage\n'
            'send (item 2 of argv) to participant (item 1 of argv) of svc\n'
            'end tell',
            handle, text, timeout=20,
        )
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        return "Messages couldn't send it: {}".format(exc)
    return "Message sent to {} ({}).".format(who, handle)
