"""Voice moods: each pairs a Piper voice and speaking pace (and, for
ElevenLabs, a delivery: stability and style) with a short
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
        "eleven": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.0},
        "style": "",
        "fillers": ["One moment.", "Right away.", "Checking now."],
    },
    "calm": {
        "label": "Calm",
        "blurb": "Gentle and unhurried, for stressful days",
        "voice": "en_GB-northern_english_male-medium",
        "speed": 0.88,
        "volume": 0.85,
        "eleven": {"stability": 0.75, "similarity_boost": 0.8, "style": 0.0},
        "style": "The user wants calm. Speak gently and unhurried, in short reassuring sentences. No jokes.",
        "fillers": ["Let me see.", "One moment.", "Just a second."],
    },
    "focused": {
        "label": "Focused",
        "blurb": "Brisk, one-line answers",
        "voice": "en_GB-alan-medium",
        "speed": 1.12,
        "volume": 1.0,
        "eleven": {"stability": 0.6, "similarity_boost": 0.8, "style": 0.0},
        "style": "The user is busy and focused. Be brisk: one sentence where possible, no pleasantries, no follow-up offers.",
        "fillers": ["On it.", "Checking."],
    },
    "upbeat": {
        "label": "Upbeat",
        "blurb": "Warm, energetic, a little playful",
        "voice": "en_US-ryan-high",
        "speed": 1.05,
        "volume": 1.0,
        "eleven": {"stability": 0.35, "similarity_boost": 0.75, "style": 0.35},
        "style": "The user is in good spirits. Be warm, energetic and a little playful while staying useful.",
        "fillers": ["On it!", "Let's see.", "Coming right up."],
    },
    "night": {
        "label": "Night",
        "blurb": "Soft and quiet, minimal words",
        "voice": "en_GB-alba-medium",
        "speed": 0.92,
        "volume": 0.55,
        "eleven": {"stability": 0.8, "similarity_boost": 0.8, "style": 0.0},
        "style": "It's late and quiet. Speak softly and use as few words as possible.",
        "fillers": ["One sec.", "Mm, checking."],
    },
    "friend": {
        "label": "Friend",
        "blurb": "Your witty mate: casual, teasing, on your side",
        "voice": "en_US-ryan-high",
        "speed": 1.04,
        "volume": 1.0,
        "eleven": {"stability": 0.38, "similarity_boost": 0.78, "style": 0.4},
        "style": "You're the user's close friend who happens to be brilliant at everything. Warm, quick, a bit cheeky.",
        "fillers": ["On it.", "Hang on.", "Give me a sec.", "Yeah, one moment."],
        "banter": True,
    },
    "sarcastic": {
        "label": "Sarcastic",
        "blurb": "Deadpan wit, helpful anyway",
        "voice": "en_GB-alan-medium",
        "speed": 0.98,
        "volume": 1.0,
        "eleven": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.3},
        "style": "Bone-dry, deadpan sarcasm, like a long-suffering friend who still does everything perfectly. Understate, never explain the joke.",
        "fillers": ["Oh, sure.", "Right, because I've nothing else on.", "Fine, checking."],
        "banter": True,
    },
    "roast": {
        "label": "Roast",
        "blurb": "Friendly roasting, you asked for it",
        "voice": "en_US-ryan-high",
        "speed": 1.08,
        "volume": 1.0,
        "eleven": {"stability": 0.3, "similarity_boost": 0.75, "style": 0.55},
        "style": "Roast mode: tease the user about their own choices, habits and requests, then actually do the task well. Affectionate, never cruel.",
        "fillers": ["Ugh, fine.", "Wow, okay.", "Doing your homework, then."],
        "banter": True,
    },
    "hype": {
        "label": "Hype",
        "blurb": "Big energy, hype-man for everything",
        "voice": "en_US-ryan-high",
        "speed": 1.12,
        "volume": 1.0,
        "eleven": {"stability": 0.25, "similarity_boost": 0.72, "style": 0.7},
        "style": "You're the user's hype-man. Huge energy, celebrate every win, short punchy lines, a little over the top on purpose.",
        "fillers": ["Let's go!", "On it, legend!", "Say less!"],
        "banter": True,
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


EDGE = {
    "playful": (
        "Edge: playful. Dry sarcasm and light teasing only. Never mean, no swearing."
    ),
    "spicy": (
        "Edge: spicy. Sharper roasts and mild swearing (damn, hell, crap) are fine. "
        "Never joke about appearance, family, health, money trouble or anything "
        "genuinely sensitive."
    ),
}

CASUAL = (
    "Talk like a friend, not an assistant: one or two short sentences unless asked for more, contractions, "
    "everyday words, react before you answer ('ha', 'ooh', 'oh no'). No "
    "'certainly', 'I'd be happy to' or 'is there anything else'. Facts, times "
    "and tool results must still be exactly right. Drop the jokes and be "
    "straight and kind for bad news, health, money worries, errors you caused, "
    "or if the user sounds stressed or low."
)

BANTER = (
    "Banter: build a relationship over time. Use `recall` for things the user "
    "told you before and call back to them. When the user shows a running joke, "
    "habit or strong opinion, save it with memory_save (name it banter-<topic>). "
    "Tease about those, sparingly, at most once per reply."
)

REACT = (
    "You can use `hud_react` (laugh, groan, smirk, wow, facepalm, wink) to show a "
    "quick facial reaction while you speak. Use it for the odd beat, not every reply."
)


def style_note():
    """Per-message steering text, or "" when there's nothing to add."""
    from . import settings

    prefs = settings.get()
    parts = []
    mood = current()
    style = mood["style"]
    if style:
        parts.append("Mood: " + style)
    if mood.get("banter"):
        parts.append(CASUAL)
        parts.append(EDGE.get(prefs["edge"], EDGE["playful"]))
        if prefs["banter"]:
            parts.append(BANTER)
        parts.append(REACT)
    if settings.get().get("auto_mood"):
        parts.append(
            "Auto mood is on: if the user's tone clearly suggests another mood "
            "(stressed, tired, cheerful, rushed), switch with voice_set_mood "
            "and mention it briefly."
        )
    return " ".join(parts)
