"""Assistant settings shared by every front-end and changeable by voice.

Persisted to data/settings.json. The HUD shows them and edits them, and
Jarvis can change them through its tools ("calm mode", "red theme", "give
me more time to think"); listeners are told about every change so the HUD
updates live either way.
"""
import json
import threading

from . import config

DEFAULTS = {
    "theme": "arc",          # HUD colour scheme
    "mood": "classic",       # voice + speaking style (see moods.py)
    "voice": "",             # optional Piper voice override; "" = mood's voice
    "patience": "balanced",  # how long Jarvis waits when you pause mid-thought
    "barge_in": True,        # talk over Jarvis to interrupt it
    "fillers": True,         # brief "one moment" while slow tools run
    "speak": True,           # speak typed replies too
    "auto_mood": False,      # let Jarvis pick a mood from your tone
    "wake": "normal",        # wake-word sensitivity: low / normal / high
    "conversation": "open",  # after replying, keep listening briefly or for a while
}

CHOICES = {
    "theme": ("arc", "mark", "vibranium"),
    "patience": ("snappy", "balanced", "patient"),
    "wake": ("low", "normal", "high"),
    "conversation": ("brief", "open"),
}

# Wake-word score needed to trigger, by sensitivity. "normal" honours
# WAKE_THRESHOLD from .env.
WAKE_THRESHOLDS = {"low": 0.65, "high": 0.32}

# Seconds Jarvis keeps listening for a follow-up after it replies.
# "brief" honours FOLLOWUP_WINDOW from .env.
CONVERSATION_WINDOW = {"open": 20.0}


def wake_threshold():
    return WAKE_THRESHOLDS.get(get()["wake"], config.WAKE_THRESHOLD)


def followup_window():
    return CONVERSATION_WINDOW.get(get()["conversation"], config.FOLLOWUP_WINDOW)

_lock = threading.Lock()
_cache = None
_listeners = []


def _path():
    return config.DB_PATH.parent / "settings.json"


def get():
    global _cache
    with _lock:
        if _cache is None:
            data = {}
            try:
                data = json.loads(_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            _cache = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
        return dict(_cache)


def update(**changes):
    """Validate and apply changes; returns the new settings."""
    from . import moods

    current = get()
    clean = {}
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise ValueError("Unknown setting {!r}".format(key))
        if isinstance(DEFAULTS[key], bool):
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "on", "yes", "enable", "enabled")
            value = bool(value)
        elif key in CHOICES and value not in CHOICES[key]:
            raise ValueError("{} must be one of: {}".format(key, ", ".join(CHOICES[key])))
        elif key == "mood" and value not in moods.MOODS:
            raise ValueError("mood must be one of: {}".format(", ".join(moods.MOODS)))
        elif key == "voice" and value and value not in moods.installed_voices():
            raise ValueError("voice must be one of: {}".format(", ".join(moods.installed_voices())))
        clean[key] = value
    if key_changes := {k: v for k, v in clean.items() if current.get(k) != v}:
        global _cache
        with _lock:
            _cache = {**current, **key_changes}
            snapshot = dict(_cache)
            try:
                _path().parent.mkdir(parents=True, exist_ok=True)
                _path().write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            except OSError as exc:
                print("[settings] couldn't save: {}".format(exc))
        for fn in list(_listeners):
            try:
                fn(snapshot, key_changes)
            except Exception:  # noqa: BLE001 — a listener must not break a setting change
                pass
    return get()


def add_listener(fn):
    _listeners.append(fn)
