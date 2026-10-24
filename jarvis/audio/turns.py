"""Turn-taking: deciding when you've finished talking.

Modelled on how modern voice assistants (e.g. ChatGPT's voice mode, via
OpenAI's "semantic VAD") avoid cutting people off mid-thought:

1. A neural speech detector (Silero, bundled with faster-whisper) scores
   every 80 ms of audio, instead of a loudness threshold that breath
   noise and quiet words fool.
2. ~320 ms of audio from before speech starts is kept, so the first
   syllable is never clipped.
3. A pause is not the end of a turn. When you pause, what you've said so
   far is transcribed and judged: "turn off the lights in the" or a
   trailing "um" means you're mid-thought, so Jarvis keeps waiting (up to
   the patience limit); "let me think" or "hold on" buys extra time; a
   complete request ends the turn quickly.

Patience (a setting, also changeable by voice) sets the timings:

    snappy    end after 0.45 s if complete, give up waiting at 2 s
    balanced  0.7 s / 4 s
    patient   1.0 s / 8 s
"""
import re

import numpy as np

from .. import config

CHUNK = 1280                      # 80 ms at 16 kHz
CHUNK_S = CHUNK / config.SAMPLE_RATE

PATIENCE = {
    #            complete  incomplete
    "snappy":   (0.45, 2.0),
    "balanced": (0.70, 4.0),
    "patient":  (1.00, 8.0),
}
HOLD_SECONDS = 15.0               # after "hold on" / "let me think"
PREROLL_CHUNKS = 4


class SpeechDetector:
    """Per-chunk speech probability: streaming Silero when available,
    else loudness.

    Silero is a recurrent model: carrying its state from one 32 ms frame to
    the next is what makes it steady (~0.95 through a whole word). Scoring
    frames in isolation, as faster-whisper's batch helper does, swings
    between 0.1 and 0.9 inside a single syllable."""

    FRAME = 512
    CONTEXT = 64

    def __init__(self):
        self.session = None
        try:
            from faster_whisper.vad import get_vad_model

            self.session = get_vad_model().session
        except Exception as exc:  # noqa: BLE001 — loudness fallback still works
            print("[turns] Silero VAD unavailable, using loudness: {}".format(exc))
        self.reset()

    def reset(self):
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._ctx = np.zeros(self.CONTEXT, dtype=np.float32)
        self._carry = np.zeros(0, dtype=np.float32)
        self._last = 0.0

    def prob(self, chunk):
        if self.session is None:
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            return min(1.0, rms / (config.RMS_THRESHOLD * 2))
        audio = np.concatenate([self._carry, chunk.astype(np.float32) / 32768.0])
        best = None
        while len(audio) >= self.FRAME:
            frame, audio = audio[: self.FRAME], audio[self.FRAME:]
            x = np.concatenate([self._ctx, frame])[None, :]
            out, self._h, self._c = self.session.run(
                None, {"input": x, "h": self._h, "c": self._c}
            )
            self._ctx = frame[-self.CONTEXT:]
            p = float(np.squeeze(out))
            best = p if best is None else max(best, p)
        self._carry = audio
        if best is not None:
            self._last = best
        return self._last


_HOLD = re.compile(
    r"\b(hold on|hang on|wait|one sec(ond)?|give me a (sec(ond)?|moment|minute)|"
    r"let me think|let me see|um+|uh+|erm|hmm+)\W*$"
)
_DANGLING = {
    "and", "or", "but", "so", "because", "cause", "the", "a", "an", "to", "of",
    "for", "with", "in", "on", "at", "my", "your", "our", "their", "his", "her",
    "is", "are", "was", "were", "if", "that", "which", "who", "then", "like",
    "also", "about", "from", "into", "than", "as", "when", "what", "where",
    "how", "could", "would", "should", "can", "will", "i", "we", "me", "maybe",
    "um", "uh", "er", "this", "these", "those", "some", "any", "by", "between",
    "plus", "and/or", "until", "before", "after", "jarvis",
}
_SHORT_OK = {
    "yes", "no", "yeah", "yep", "nope", "stop", "thanks", "okay", "ok", "sure",
    "cancel", "pause", "play", "next", "louder", "quieter", "mute", "continue",
}


def judge(text):
    """Does this transcript sound like a finished request?

    Returns "complete", "incomplete" (keep listening) or "hold" (the user
    asked for time). Whisper adds a full stop to almost everything, so the
    words decide, not the punctuation.
    """
    t = (text or "").strip().lower()
    if not t:
        return "incomplete"
    if _HOLD.search(t):
        return "hold"
    if t.endswith(("...", "…", ",", "-", "—")):
        return "incomplete"
    words = re.findall(r"[a-z'/]+", t)
    if not words:
        return "incomplete"
    if words[-1] in _DANGLING:
        return "incomplete"
    if len(words) == 1 and words[0] not in _SHORT_OK and not t.endswith("?"):
        return "incomplete"
    return "complete"


class TurnDetector:
    """Push-based turn detector, fed 80 ms int16 chunks.

    feed() returns:
      "wait"     keep feeding
      "timeout"  nobody spoke within start_timeout
      "check"    the user paused: transcribe audio() and call verdict()
      "live"     a good moment for a live (display-only) transcript
      "done"     the turn is over; audio() is the utterance
    """

    def __init__(self, start_timeout=None, patience="balanced", detector=None,
                 preroll=None, speaking=False):
        if start_timeout is None:
            start_timeout = config.RECORD_START_TIMEOUT
        self.detector = detector or SpeechDetector()
        self.base, self.limit = PATIENCE.get(patience, PATIENCE["balanced"])
        self.max_wait_chunks = max(1, int(start_timeout / CHUNK_S))
        self.max_chunks = int(config.MAX_UTTERANCE_SECONDS / CHUNK_S)
        self.recorded = list(preroll or [])
        self.started = speaking
        self.waited = 0
        self.loud_run = 0
        self.quiet_run = 0
        self.pending = None       # None | "checking" | verdict string
        self.since_live = 0
        self.last_text = ""
        self.text_len = 0         # len(recorded) when last_text was made

    @property
    def silence(self):
        return self.quiet_run * CHUNK_S

    def wait_limit(self):
        """Seconds of silence that will end the turn right now."""
        if self.pending == "complete":
            return self.base
        if self.pending == "hold":
            return HOLD_SECONDS
        return self.limit

    def feed(self, chunk):
        p = self.detector.prob(chunk)
        if not self.started:
            self.waited += 1
            self.recorded.append(chunk)
            self.recorded = self.recorded[-PREROLL_CHUNKS:]
            self.loud_run = self.loud_run + 1 if p >= 0.5 else 0
            if self.loud_run >= 2 or p >= 0.85:
                self.started = True
                return "wait"
            return "timeout" if self.waited >= self.max_wait_chunks else "wait"

        self.recorded.append(chunk)
        if len(self.recorded) >= self.max_chunks:
            return "done"
        if p >= 0.4:
            if self.quiet_run:
                self.pending = None   # they carried on; the old verdict is stale
            self.quiet_run = 0
            self.since_live += 1
            if self.since_live >= 20:  # ~1.6 s of new speech
                self.since_live = 0
                return "live"
            return "wait"

        self.quiet_run += 1
        if self.silence >= self.wait_limit():
            return "done"
        if self.pending is None and self.silence >= self.base:
            self.pending = "checking"
            return "check"
        return "wait"

    def verdict(self, kind, text):
        """Result of a "check": judge(text) of the audio so far."""
        self.last_text = text
        self.text_len = len(self.recorded)
        if self.pending == "checking":
            self.pending = kind

    def final_text(self):
        """The check's transcript, if nothing but silence came after it."""
        return self.last_text if self.pending == "complete" else None

    def audio(self):
        return np.concatenate(self.recorded)


# ── Talking over Jarvis ────────────────────────────────────────────────
# Modelled on how voice-agent frameworks avoid false interruptions: a burst
# of speech only ducks Jarvis's voice; it stops for good once the words
# are known, and only if they're real words from you rather than an
# "mm-hmm", Whisper's silence hallucinations, or Jarvis's own voice
# leaking back into the mic.
_BACKCHANNEL = {
    "yeah", "yes", "yep", "ok", "okay", "mm", "mhm", "mmhmm", "hmm", "uh", "um",
    "huh", "right", "sure", "cool", "nice", "wow", "ah", "oh", "ha", "haha",
    "great", "alright", "aha", "uhhuh", "mmm", "got", "it", "i", "see",
}
_HALLUCINATED = {"you", "thank you", "thanks for watching", "bye", "thank you."}
_STOP_WORDS = {
    "stop", "wait", "hold", "jarvis", "no", "pause", "quiet", "enough", "cancel",
    "shut", "actually", "sorry", "excuse", "hang",
}


def _words(text):
    return re.findall(r"[a-z']+", (text or "").lower().replace("-", ""))


def interruption(text, speaking_text="", min_words=2):
    """Is `text` (heard while Jarvis was talking) a real interruption?

    Returns "barge" (stop and listen) or "ignore" (carry on talking). A lone
    word that isn't "stop", "wait"... is a reaction (and Whisper often turns
    "mm-hmm" into a real word), so it takes `min_words` to interrupt; if
    the user keeps talking, the next look hears the rest."""
    t = (text or "").strip().lower().strip(".!?, ")
    words = _words(t)
    if not words or t in _HALLUCINATED:
        return "ignore"
    if any(w in _STOP_WORDS for w in words):
        return "barge"
    if all(w in _BACKCHANNEL for w in words) or len(words) < min_words:
        return "ignore"
    spoken = set(_words(speaking_text))
    if spoken and len(words) >= 2:
        echo = sum(w in spoken for w in words) / len(words)
        if echo >= 0.6:
            return "ignore"   # our own voice, picked up by the mic
    return "barge"


_DISMISS = re.compile(
    r"^(ok(ay)?,? )?((thanks|thank you)( jarvis)?,? )?"
    r"(that'?s (all|it)( for now)?|that is all|nothing( else)?|never ?mind|no,? thanks?|"
    r"good ?bye|bye( jarvis)?|stop listening|go to sleep|(thanks|thank you)( jarvis| so much)?)"
    r"\W*$"
)


def ends_conversation(text):
    """"That's all", "thanks Jarvis", "goodbye": stop listening after replying."""
    return bool(_DISMISS.match((text or "").strip().lower()))
