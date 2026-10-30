"""Wake on Jarvis's name without a trained wake-word model.

openWakeWord ships ready-made models for a few English phrases, not for
"Hey Jarvis". Until a custom model is trained (docs/wake-word.md), the idle
loop can listen a different way: the speech detector finds short bursts of
speech, the local Whisper model transcribes each one, and a burst that
starts with the name wakes Jarvis. Everything stays on the Mac.

It costs more compute than a wake-word model (a transcription per burst of
speech in the room), so a trained model is used instead whenever it exists.
"""
import re

import numpy as np

# Whisper is primed with "Jarvis", but still hears it a few ways.
_NAME = r"(?:jarvis|jarvas|jervis|jarviss|javis|charvis)"
_WAKE = re.compile(
    r"^\W*(?:(?:hey|hi|hello|ok|okay|oi|o)\W+)?" + _NAME + r"\b[\s,.!?:;-]*(?P<rest>.*)$",
    re.I | re.S,
)

ONSET_WINDOW, ONSET_NEEDED, ONSET_PROB = 5, 3, 0.6
QUIET_PROB = 0.35
END_QUIET = 7        # chunks (~560 ms) of quiet end a burst
MAX_CHUNKS = 75      # ~6 s: long enough for "Hey Jarvis, <a short request>"
MIN_SPEECH = 5       # chunks (~400 ms) of speech: shorter bursts are clicks and coughs
PREROLL = 4          # chunks kept from just before speech started


def match(text):
    """'Hey Jarvis, what's the time?' -> (True, "what's the time?")."""
    m = _WAKE.match(text or "")
    if not m:
        return False, ""
    return True, m.group("rest").strip()


class NameSpotter:
    """Cuts the idle mic stream into speech bursts. feed() returns a
    finished burst (int16 array) or None."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.recent = []
        self.onset = []
        self.burst = None
        self.quiet = 0
        self.speech = 0

    def feed(self, chunk, prob):
        if self.burst is None:
            self.recent = (self.recent + [chunk])[-PREROLL:]
            self.onset = (self.onset + [prob])[-ONSET_WINDOW:]
            if sum(p >= ONSET_PROB for p in self.onset) >= ONSET_NEEDED:
                self.burst = list(self.recent)
                self.speech = ONSET_NEEDED
                self.quiet = 0
            return None
        self.burst.append(chunk)
        if prob >= ONSET_PROB:
            self.speech += 1
        self.quiet = self.quiet + 1 if prob < QUIET_PROB else 0
        if self.quiet >= END_QUIET or len(self.burst) >= MAX_CHUNKS:
            burst, speech = self.burst, self.speech
            self.reset()
            if speech >= MIN_SPEECH:
                return np.concatenate(burst)
        return None
