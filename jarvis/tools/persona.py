"""Jarvis's own voice and behaviour, changeable by asking."""
from .. import config, moods, settings

_LABELS = {
    "patience": "how long I wait when you pause",
    "barge_in": "interrupting me by talking",
    "fillers": "short 'one moment' acknowledgements",
    "speak": "speaking typed replies aloud",
    "auto_mood": "picking a mood from your tone",
    "theme": "the HUD colour theme",
    "wake": "how easily I hear my wake word",
    "conversation": "how long I keep listening after I answer",
    "meeting_alerts": "warnings before your meetings (minutes)",
    "briefing": "when your morning briefing starts",
}


def set_mood(mood):
    s = settings.update(mood=mood, voice="")
    m = moods.MOODS[s["mood"]]
    return "Mood set to {}: {}. Voice: {}.".format(
        m["label"], m["blurb"], moods.VOICE_LABELS.get(moods.current()["voice"], moods.current()["voice"])
    )


def set_voice(voice):
    settings.update(voice=voice)
    return "Voice set to {} (the mood's pace and style still apply).".format(
        moods.VOICE_LABELS.get(voice, voice)
    )


def set_model(model):
    """Switch Claude model by name or family ("opus", "haiku", "default")."""
    key = (model or "").strip().lower()
    if key in ("", "default", "normal", "standard", "original"):
        settings.update(model="")
        return "Back to the default model, {}. It applies from my next reply.".format(
            settings.MODELS.get(config.LLM_MODEL, config.LLM_MODEL))
    matches = [m for m in settings.MODELS if key == m or key in m.replace("claude-", "").split("-")]
    if len(matches) != 1:
        raise ValueError("Say one of: {}, or default.".format(", ".join(
            m.replace("claude-", "").split("-")[0] for m in settings.MODELS)))
    settings.update(model=matches[0])
    return "Switched to {}. It applies from my next reply.".format(settings.MODELS[matches[0]])


def list_options():
    s = settings.get()
    lines = ["Moods:"]
    for key, m in moods.MOODS.items():
        lines.append("- {}{}: {}".format(key, " (current)" if key == s["mood"] else "", m["blurb"]))
    lines.append("Voices installed:")
    for key, label in moods.installed_voices().items():
        lines.append("- {}: {}{}".format(key, label, " (override)" if key == s["voice"] else ""))
    lines.append("Settings: " + ", ".join("{}={}".format(k, v) for k, v in s.items()))
    return "\n".join(lines)


def set_preference(setting, value):
    s = settings.update(**{setting: value})
    return "Updated {} to {}.".format(_LABELS.get(setting, setting), s[setting])
