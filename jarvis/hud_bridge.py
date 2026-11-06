"""Lets tools reach the HUD (show a card, open a panel) without importing
the web server. The HUD attaches a sender when it starts; in voice or text
mode nothing is attached and send() reports that."""
_sink = [None]


def attach(fn):
    _sink[0] = fn


def connected():
    return _sink[0] is not None


def send(event):
    fn = _sink[0]
    if fn is None:
        return False
    return bool(fn(event))


# Something that can tell the user about a finished background job (speak it
# when they're nearby, show a card). The assistant hub attaches it; without
# one, announce() falls back to a plain HUD notify event.
_announcer = [None]


def attach_announcer(fn):
    """fn(kind, text, speak) -> bool."""
    _announcer[0] = fn


def announce(kind, text, speak=True):
    fn = _announcer[0]
    if fn is not None:
        return bool(fn(kind, text, speak))
    return send({"type": "notify", "kind": kind, "text": text})
