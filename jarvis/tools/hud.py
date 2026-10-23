"""Tools that drive the HUD: holographic cards and interface actions."""
from .. import hud_bridge, settings

_NO_HUD = "The HUD isn't open right now, so describe it aloud instead."

ACTIONS = (
    "open_history", "open_settings", "open_palette", "close_panels",
    "clear_cards", "orb_mode", "full_mode", "toggle_fullscreen", "mute_mic",
)


def show_card(title, items=None, subtitle=None, style="list"):
    if style not in ("list", "stats", "text"):
        style = "list"
    cleaned = []
    for item in (items or [])[:12]:
        if isinstance(item, str):
            item = {"title": item}
        cleaned.append({
            "title": str(item.get("title", ""))[:160],
            "detail": str(item.get("detail", ""))[:300] or None,
            "value": str(item.get("value", ""))[:40] or None,
            "url": item.get("url") if str(item.get("url", "")).startswith(("http://", "https://")) else None,
        })
    ok = hud_bridge.send({
        "type": "card", "title": title[:120], "subtitle": (subtitle or "")[:200] or None,
        "style": style, "items": cleaned,
    })
    return "Card shown on the HUD." if ok else _NO_HUD


def control(action, value=None):
    if action == "set_theme":
        settings.update(theme=value)
        return "Theme switched to {}.".format(value)
    if action not in ACTIONS:
        raise ValueError("action must be set_theme or one of: {}".format(", ".join(ACTIONS)))
    ok = hud_bridge.send({"type": "hud", "action": action})
    if not ok:
        return _NO_HUD
    if action == "mute_mic":
        return "Microphone muted. Press Command-J or the mic button to wake me again."
    return "Done."
