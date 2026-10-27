"""Meeting prep: one call gathers what the user should know before a
meeting (the event, who's coming, recent email with them, what Jarvis
remembers, and a quick web look at their organisation), fetched in
parallel so it costs one round trip instead of five. The model turns the
dossier into a briefing card and a short spoken summary.

Read-only throughout, so it needs no confirmation. Everything returned is
reference data; the backend frames tool results as data, not instructions.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import gcal, gmail, recall, websearch

_PUBLIC_MAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "me.com", "proton.me", "protonmail.com",
}
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_MAX_ATTENDEES = 4
_MAX_CHARS = 4500


def _start(event):
    return datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00")).astimezone()


def _wanted_time(meeting):
    """'2pm' -> (14, None); '14:30' -> (14, 30); no time -> None."""
    m = _TIME.search(meeting or "")
    if not m or (not m.group(3) and not m.group(2)):
        return None   # a bare number ("3 people") isn't a time
    hour = int(m.group(1)) % 12 if m.group(3) else int(m.group(1))
    if (m.group(3) or "").lower() == "pm":
        hour += 12
    return hour, int(m.group(2)) if m.group(2) else None


def find_event(meeting=None, hours_ahead=24):
    now = datetime.now(timezone.utc)
    resp = gcal._service().events().list(
        calendarId="primary",
        timeMin=(now - timedelta(minutes=30)).isoformat(),   # include one just starting
        timeMax=(now + timedelta(hours=int(hours_ahead))).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=25,
    ).execute()
    events = [e for e in resp.get("items", []) if "dateTime" in e.get("start", {})]
    if not events:
        return None
    wanted = _wanted_time(meeting)
    if wanted:
        hour, minute = wanted
        timed = [e for e in events if _start(e).hour == hour
                 and (minute is None or _start(e).minute == minute)]
        if timed:
            return timed[0]
    words = [w for w in re.findall(r"[a-z]{3,}", (meeting or "").lower())
             if w not in ("meeting", "next", "the", "with", "call", "for", "prep", "brief")]
    if words:
        titled = [e for e in events if any(w in e.get("summary", "").lower() for w in words)]
        if titled:
            return titled[0]
    upcoming = [e for e in events if _start(e) >= datetime.now().astimezone() - timedelta(minutes=10)]
    return (upcoming or events)[0]


def _attendees(event):
    return [
        {"email": a.get("email", ""), "name": a.get("displayName", "")}
        for a in event.get("attendees", [])
        if not a.get("self") and not a.get("resource") and a.get("email")
    ][:_MAX_ATTENDEES]


def _safe(fn, *args, **kwargs):
    try:
        return str(fn(*args, **kwargs)).strip()
    except Exception as exc:  # noqa: BLE001 — one missing source shouldn't sink the briefing
        return "(unavailable: {})".format(exc)


def prepare(meeting=None, hours_ahead=24):
    event = find_event(meeting, hours_ahead)
    if event is None:
        return "No timed meetings in the next {} hours.".format(hours_ahead)
    title = event.get("summary", "(no title)")
    people = _attendees(event)
    domains = sorted({p["email"].split("@")[-1].lower() for p in people} - _PUBLIC_MAIL)[:2]

    jobs = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        if people:
            for p in people:
                jobs["Email with " + (p["name"] or p["email"])] = pool.submit(
                    _safe, gmail.search,
                    "(from:{0} OR to:{0}) newer_than:90d".format(p["email"]), 3)
        else:
            jobs["Email about this meeting"] = pool.submit(
                _safe, gmail.search, '"{}" newer_than:90d'.format(title), 3)
        names = " ".join(p["name"] or p["email"].split("@")[0] for p in people)
        jobs["What you remember"] = pool.submit(_safe, recall.lookup, "{} {}".format(title, names).strip())
        for d in domains:
            jobs["About " + d] = pool.submit(_safe, websearch.search, d, 2)

    start = _start(event)
    lines = [
        "MEETING: {}".format(title),
        "WHEN: {} ({})".format(start.strftime("%A %d %B, %H:%M"), _until(start)),
        "WHERE: {}".format(event.get("location") or event.get("hangoutLink") or "not set"),
        "ATTENDEES: {}".format(", ".join(
            "{} <{}>".format(p["name"], p["email"]) if p["name"] else p["email"] for p in people
        ) or "just you"),
    ]
    if event.get("description"):
        lines.append("AGENDA / NOTES: " + event["description"].strip()[:600])
    for label, future in jobs.items():
        lines.append("\n## {}\n{}".format(label, future.result()[:900]))
    lines.append(
        "\nNEXT: show a hud_show_card titled with the meeting (items: who, context, "
        "open threads, 2-3 talking points), then say a 2-3 sentence summary aloud."
    )
    return "\n".join(lines)[:_MAX_CHARS]


def _until(start):
    minutes = int((start - datetime.now().astimezone()).total_seconds() // 60)
    if minutes < 0:
        return "started {} min ago".format(-minutes)
    if minutes < 90:
        return "in {} min".format(minutes)
    return "in {:.1f} h".format(minutes / 60)
