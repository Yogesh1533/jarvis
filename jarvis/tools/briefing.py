"""One-call daily briefing. Each section fails soft, so a missing Google
login or no network still yields a useful briefing."""
from . import gcal, gmail, reminders, tasks, weather


def _section(title, fn):
    try:
        return "## {}\n{}".format(title, fn())
    except Exception as exc:  # noqa: BLE001 — report and carry on
        return "## {}\nUnavailable: {}".format(title, exc)


def get():
    return "\n\n".join([
        _section("Weather", weather.get),
        _section("Calendar (next 24 hours)", lambda: gcal.list_events(days_ahead=1)),
        _section("Open tasks", tasks.list_tasks),
        _section("Pending reminders", reminders.list_reminders),
        _section("Unread email (last 2 days)",
                 lambda: gmail.search("is:unread newer_than:2d", max_results=5)),
    ])
