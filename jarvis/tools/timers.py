"""In-memory countdown timers. Short-lived by nature, so unlike reminders
they don't survive a restart. Front-ends register a notifier for when one
ends (spoken in voice mode, a HUD alert in the web UI)."""
import itertools
import threading
import time

_lock = threading.Lock()
_ids = itertools.count(1)
_timers = {}  # id -> {"label", "seconds", "ends_at", "thread"}
_notifier = [lambda label: print("\n[TIMER] {} is done".format(label))]


def set_notifier(fn):
    _notifier[0] = fn


def _fire(timer_id):
    with _lock:
        t = _timers.pop(timer_id, None)
    if t is not None:
        _notifier[0](t["label"])


def set_timer(seconds, label=None):
    seconds = int(seconds)
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    timer_id = next(_ids)
    label = (label or "").strip() or "{} timer".format(_human(seconds))
    th = threading.Timer(seconds, _fire, args=(timer_id,))
    th.daemon = True
    with _lock:
        _timers[timer_id] = {
            "label": label, "seconds": seconds,
            "ends_at": time.time() + seconds, "thread": th,
        }
    th.start()
    return "Timer {} started: {} ({}).".format(timer_id, label, _human(seconds))


def rows():
    now = time.time()
    with _lock:
        return [
            {
                "id": i, "label": t["label"], "seconds": t["seconds"],
                "ends_at": t["ends_at"], "remaining": max(0, round(t["ends_at"] - now)),
            }
            for i, t in sorted(_timers.items(), key=lambda kv: kv[1]["ends_at"])
        ]


def list_timers():
    items = rows()
    if not items:
        return "No timers running."
    return "\n".join(
        "#{} {}: {} left".format(t["id"], t["label"], _human(t["remaining"])) for t in items
    )


def cancel(timer_id):
    with _lock:
        t = _timers.pop(int(timer_id), None)
    if t is None:
        raise ValueError("No running timer with id {}".format(timer_id))
    t["thread"].cancel()
    return "Timer {} ({}) cancelled.".format(timer_id, t["label"])


def _human(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append("{} hour{}".format(h, "s" if h != 1 else ""))
    if m:
        parts.append("{} minute{}".format(m, "s" if m != 1 else ""))
    if s or not parts:
        parts.append("{} second{}".format(s, "s" if s != 1 else ""))
    return " ".join(parts)
