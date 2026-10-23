"""Recording one utterance from the local mic (voice mode).

End-of-turn detection lives in turns.py and is shared with the HUD, which
streams mic audio from the browser instead.
"""
import numpy as np

from .. import config
from .turns import CHUNK, TurnDetector, judge


def record_utterance(start_timeout=None, patience=None):
    """Record one utterance from the local mic.

    Returns a mono int16 numpy array, or None if the user never spoke.
    """
    import sounddevice as sd

    from . import stt
    from .. import settings

    turn = TurnDetector(start_timeout, patience or settings.get()["patience"])
    with sd.InputStream(
        samplerate=config.SAMPLE_RATE, channels=1, dtype="int16", blocksize=CHUNK
    ) as stream:
        while True:
            chunk, _ = stream.read(CHUNK)
            state = turn.feed(np.frombuffer(chunk, dtype=np.int16).copy())
            if state == "timeout":
                return None
            if state == "done":
                return turn.audio()
            if state == "check":
                # The stream keeps buffering while we transcribe.
                text = stt.transcribe(turn.audio())
                turn.verdict(judge(text), text)
