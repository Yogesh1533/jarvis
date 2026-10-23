"""Voice moods: each pairs a Piper voice and speaking pace with a short
style note that steers how Jarvis words its replies.

Switch from the HUD, or just ask ("Jarvis, calm mode"). The style note is
added to each user message rather than the system prompt so the prompt
stays cacheable for the whole session.
"""
from . import config

MOODS = {
    "classic": {
        "label": "Classic",
        "blurb": "The butler: calm, dry, precise",
        "voice": "en_GB-alan-medium",
        "speed": 1.0,
        "volume": 1.0,
        "style": "",
        "fillers": ["One moment.", "Right away.", "Checking now."],
    },
    "calm": {
        "label": "Calm",
        "blurb": "Gentle and unhurried, for stressful days",
        "voice": "en_GB-northern_english_male-medium",
        "speed": 0.88,
        "volume": 0.85,
        "style": "The user wants calm. Speak gently and unhurried, in short reassuring sentences. No jokes.",
        "fillers": ["Let me see.", "One moment.", "Just a second."],
    },
    "focused": {
        "label": "Focused",
        "blurb": "Brisk, one-line answers",
        "voice": "en_GB-alan-medium",
        "speed": 1.12,
        "volume": 1.0,
        "style": "The user is busy and focused. Be brisk: one sentence where possible, no pleasantries, no follow-up offers.",
        "fillers": ["On it.", "Checking."],
    },
    "upbeat": {
        "label": "Upbeat",
        "blurb": "Warm, energetic, a little playful",
        "voice": "en_US-ryan-high",
        "speed": 1.05,
        "volume": 1.0,
        "style": "The user is in good spirits. Be warm, energetic and a little playful while staying useful.",
        "fillers": ["On it!", "Let's see.", "Coming right up."],
    },
    "night": {
        "label": "Night",
        "blurb": "Soft and quiet, minimal words",
        "voice": "en_GB-alba-medium",
        "speed": 0.92,
        "volume": 0.55,
        "style": "It's late and quiet. Speak softly and use as few words as possible.",
        "fillers": ["One sec.", "Mm, checking."],
    },
}

VOICE_LABELS = {
    "en_GB-alan-medium": "Alan, British",
    "en_GB-northern_english_male-medium": "Northern, British",
    "en_US-ryan-high": "Ryan, American",
    "en_GB-alba-medium": "Alba, Scottish",
}


def voices_dir():
    return config.PIPER_VOICE.parent


def installed_voices():
    """Piper voices present on disk, as {name: label}."""
    d = voices_dir()
    if not d.is_dir():
        return {}
    return {
        p.stem: VOICE_LABELS.get(p.stem, p.stem)
        for p in sorted(d.glob("*.onnx"))
        if (d / (p.name + ".json")).exists()
    }


def voice_path(name):
    return voices_dir() / "{}.onnx".format(name)


def current():
    """The active mood dict, with the voice resolved to an installed one."""
    from . import settings

    s = settings.get()
    mood = dict(MOODS.get(s["mood"], MOODS["classic"]))
    installed = installed_voices()
    if s.get("voice") in installed:
        mood["voice"] = s["voice"]
    elif mood["voice"] not in installed:
        mood["voice"] = config.PIPER_VOICE.stem
    mood["id"] = s["mood"]
    return mood


def style_note():
    """Per-message steering text, or "" when there's nothing to add."""
    from . import settings

    parts = []
    style = current()["style"]
    if style:
        parts.append("Mood: " + style)
    if settings.get().get("auto_mood"):
        parts.append(
            "Auto mood is on: if the user's tone clearly suggests another mood "
            "(stressed, tired, cheerful, rushed), switch with voice_set_mood "
            "and mention it briefly."
        )
    return " ".join(parts)
