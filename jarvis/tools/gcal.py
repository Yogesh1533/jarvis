"""Google Calendar: read and create freely; edits/deletions of shared
meetings are gated behind user confirmation."""
from datetime import datetime, timedelta, timezone

from . import ConfirmationRequired


def _service():
    from googleapiclient.discovery import build

    from ..google_auth import get_credentials

    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


def _fmt(event):
    start = event.get("start", {})
    end = event.get("end", {})
    attendees = [
        a.get("email", "") for a in event.get("attendees", []) if not a.get("self")
    ]
    return "id: {}\ntitle: {}\nstart: {}\nend: {}{}".format(
        event.get("id", ""),
        event.get("summary", "(no title)"),
        start.get("dateTime", start.get("date", "")),
        end.get("dateTime", end.get("date", "")),
        "\nattendees: {}".format(", ".join(attendees)) if attendees else "",
    )


def _other_attendees(event):
    return [
        a.get("email", "") for a in event.get("attendees", []) if not a.get("self")
    ]


def list_events(days_ahead=7, query=None):
    svc = _service()
    now = datetime.now(timezone.utc)
    resp = svc.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=(now + timedelta(days=int(days_ahead))).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=25,
        q=query,
    ).execute()
    events = resp.get("items", [])
    if not events:
        return "No events in the next {} days.".format(days_ahead)
    return "\n\n".join(_fmt(e) for e in events)


def create_event(summary, start, end, description=None, attendees=None):
    svc = _service()
    body = {
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if description:
        body["description"] = description
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    # sendUpdates="none": creating an event never emails anyone.
    event = svc.events().insert(
        calendarId="primary", body=body, sendUpdates="none"
    ).execute()
    return "Event created.\n" + _fmt(event)


def update_event(event_id, summary=None, start=None, end=None, description=None,
                 _confirmed=False):
    svc = _service()
    event = svc.events().get(calendarId="primary", eventId=event_id).execute()
    others = _other_attendees(event)
    if others and not _confirmed:
        raise ConfirmationRequired(
            "The meeting '{}' has other attendees ({}). Modify it and notify them?".format(
                event.get("summary", "(no title)"), ", ".join(others)
            )
        )
    if summary:
        event["summary"] = summary
    if start:
        event["start"] = {"dateTime": start}
    if end:
        event["end"] = {"dateTime": end}
    if description:
        event["description"] = description
    updated = svc.events().update(
        calendarId="primary", eventId=event_id, body=event,
        sendUpdates="all" if others else "none",
    ).execute()
    return "Event updated.\n" + _fmt(updated)


def delete_event(event_id, _confirmed=False):
    svc = _service()
    event = svc.events().get(calendarId="primary", eventId=event_id).execute()
    others = _other_attendees(event)
    if not _confirmed:
        raise ConfirmationRequired(
            "Delete the event '{}'{}?".format(
                event.get("summary", "(no title)"),
                " and notify {}".format(", ".join(others)) if others else "",
            )
        )
    svc.events().delete(
        calendarId="primary", eventId=event_id,
        sendUpdates="all" if others else "none",
    ).execute()
    return "Event '{}' deleted.".format(event.get("summary", "(no title)"))


def upcoming(hours=3):
    """Timed events starting in the next `hours` that the user hasn't
    declined: [{id, title, start (aware datetime), location, link}]."""
    svc = _service()
    now = datetime.now(timezone.utc)
    resp = svc.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=(now + timedelta(hours=hours)).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()
    out = []
    for e in resp.get("items", []):
        start = e.get("start", {}).get("dateTime")
        me = next((a for a in e.get("attendees", []) if a.get("self")), {})
        if not start or me.get("responseStatus") == "declined":
            continue   # all-day events don't start at a moment worth flagging
        out.append({
            "id": e.get("id"),
            "title": e.get("summary", "(no title)"),
            "start": datetime.fromisoformat(start),
            "location": e.get("location"),
            "link": e.get("hangoutLink"),
        })
    return out


def events_data(days_ahead=2):
    """Structured upcoming events for the HUD agenda panel."""
    svc = _service()
    now = datetime.now(timezone.utc)
    resp = svc.events().list(
        calendarId="primary",
        timeMin=(now - timedelta(hours=2)).isoformat(),
        timeMax=(now + timedelta(days=int(days_ahead))).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()
    out = []
    for e in resp.get("items", []):
        start, end = e.get("start", {}), e.get("end", {})
        out.append({
            "id": e.get("id"),
            "title": e.get("summary", "(no title)"),
            "start": start.get("dateTime", start.get("date")),
            "end": end.get("dateTime", end.get("date")),
            "all_day": "date" in start,
            "location": e.get("location"),
            "attendees": len(_other_attendees(e)),
            "link": e.get("hangoutLink") or e.get("htmlLink"),
        })
    return out
