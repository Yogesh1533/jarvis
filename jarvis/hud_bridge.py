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
