"""Pick a Nemotron size for each turn: quick commands go to the small, fast
model, requests that need real reasoning go to the big one, everything
else to the main model. Rule-based on purpose: it costs nothing, adds no
latency, and the HUD can say exactly why a model was chosen.

Only used when the user hasn't pinned a model (settings "model" is "").
"""
import re

_DEEP = re.compile(
    r"\b(think (it )?(through|hard|carefully)|step by step|plan(ning)?|compare|"
    r"analy[sz]e|pros and cons|prep(are)? me|brief me|strategy|explain why|"
    r"debug|trade-?offs?|what should i)\b",
    re.I,
)
_QUICK = re.compile(
    r"^\W*(hey jarvis\W*)?(please\W+)?("
    r"set|start|cancel|stop|pause|play|resume|skip|next|previous|mute|unmute|"
    r"volume|turn|open|close|quit|timer|remind|add|mark|"
    r"switch|use|what time|what's the time|what's playing|thanks|thank you|"
    r"ok|okay|yes|no|good (morning|night))\b",
    re.I,
)
_QUICK_MAX_WORDS = 14
_DEEP_MIN_WORDS = 60


def pick(text, main, fast="", deep=""):
    """Returns (model, route, reason). route is "fast", "main" or "deep"."""
    words = len(text.split())
    if deep and (_DEEP.search(text) or words >= _DEEP_MIN_WORDS):
        cue = _DEEP.search(text)
        return deep, "deep", "asked to '{}'".format(cue.group(0).lower()) if cue else "long request"
    if fast and words <= _QUICK_MAX_WORDS and _QUICK.search(text):
        return fast, "fast", "quick command"
    return main, "main", "general request"
