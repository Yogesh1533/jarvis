"""Speech to text: local faster-whisper (default) or the OpenAI Whisper API."""
import io
import threading
import wave

import numpy as np

from .. import config

_local_model = None
_lock = threading.Lock()  # partial and final transcriptions can overlap


def transcribe(audio_int16):
    """int16 mono 16 kHz numpy array -> text."""
    if config.STT_PROVIDER == "openai":
        return _transcribe_openai(audio_int16)
    return _transcribe_local(audio_int16)


def warm():
    """Load the local model ahead of the first utterance (it takes seconds)."""
    if config.STT_PROVIDER != "openai":
        _model()


def _model():
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel

        _local_model = WhisperModel(config.WHISPER_MODEL, compute_type="int8")
    return _local_model


def _transcribe_local(audio_int16):
    audio = audio_int16.astype(np.float32) / 32768.0
    with _lock:
        segments, _ = _model().transcribe(audio, language="en", beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()


def _to_wav_bytes(audio_int16):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(config.SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()


def _transcribe_openai(audio_int16):
    import requests

    if not config.OPENAI_API_KEY:
        raise RuntimeError("STT_PROVIDER=openai but OPENAI_API_KEY is not set")
    resp = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": "Bearer {}".format(config.OPENAI_API_KEY)},
        files={"file": ("speech.wav", _to_wav_bytes(audio_int16), "audio/wav")},
        data={"model": "whisper-1"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()
