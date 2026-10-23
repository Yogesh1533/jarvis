"""Utterance recording with simple energy-based end-of-speech detection."""
import numpy as np
import sounddevice as sd

from .. import config

_CHUNK = 1280  # 80 ms at 16 kHz


def _rms(chunk):
    return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))


def record_utterance(start_timeout=None):
    """Record one utterance from the mic.

    Waits up to start_timeout seconds for speech to begin, then records
    until SILENCE_DURATION of quiet (or MAX_UTTERANCE_SECONDS). Returns a
    mono int16 numpy array, or None if the user never spoke.
    """
    if start_timeout is None:
        start_timeout = config.RECORD_START_TIMEOUT
    chunk_seconds = _CHUNK / config.SAMPLE_RATE
    max_wait_chunks = int(start_timeout / chunk_seconds)
    silence_chunks = int(config.SILENCE_DURATION / chunk_seconds)
    max_chunks = int(config.MAX_UTTERANCE_SECONDS / chunk_seconds)

    recorded = []
    started = False
    quiet_run = 0

    with sd.InputStream(
        samplerate=config.SAMPLE_RATE, channels=1, dtype="int16", blocksize=_CHUNK
    ) as stream:
        waited = 0
        while True:
            chunk, _ = stream.read(_CHUNK)
            chunk = np.frombuffer(chunk, dtype=np.int16)
            loud = _rms(chunk) >= config.RMS_THRESHOLD

            if not started:
                waited += 1
                if loud:
                    started = True
                    recorded.append(chunk)
                elif waited >= max_wait_chunks:
                    return None
                continue

            recorded.append(chunk)
            quiet_run = 0 if loud else quiet_run + 1
            if quiet_run >= silence_chunks or len(recorded) >= max_chunks:
                return np.concatenate(recorded)
