"""Speech to text.

Providers (STT_PROVIDER):
  auto    mlx on Apple Silicon when mlx-whisper is installed, else local
  mlx     Whisper large-v3-turbo on the Mac's GPU (MLX_WHISPER_MODEL).
          Benchmarked on spoken commands in five accents with room noise:
          10.5% word errors vs 27.2% for base.en, ~0.4 s per command.
  local   faster-whisper on the CPU (WHISPER_MODEL, default base.en)
  openai  the OpenAI Whisper API

STT_VOCABULARY (comma-separated) lists names and words Whisper should
expect: contacts, artists, places. They go in as the decoder's prompt
(in the same benchmark: 14.2% -> 10.5% word errors for the turbo model).
"""
import importlib.util
import io
import platform
import threading
import wave

import numpy as np

from .. import config

_local_model = None
_provider = None
_lock = threading.Lock()  # partial and final transcriptions can overlap


def provider():
    """The provider actually in use ("auto" resolved)."""
    global _provider
    if _provider is None:
        choice = config.STT_PROVIDER
        if choice == "auto":
            apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
            has_mlx = importlib.util.find_spec("mlx_whisper") is not None
            choice = "mlx" if apple_silicon and has_mlx else "local"
        _provider = choice
    return _provider


def prompt():
    words = ["Jarvis"] + [w.strip() for w in config.STT_VOCABULARY.split(",") if w.strip()]
    return ", ".join(words) + "."


def transcribe(audio_int16):
    """int16 mono 16 kHz numpy array -> text."""
    if provider() == "openai":
        return _transcribe_openai(audio_int16)
    audio = audio_int16.astype(np.float32) / 32768.0
    with _lock:
        if provider() == "mlx":
            return _transcribe_mlx(audio)
        return _transcribe_local(audio)


def warm():
    """Load the model ahead of the first utterance (it takes seconds)."""
    if provider() != "openai":
        transcribe(np.zeros(8000, dtype=np.int16))


def _transcribe_mlx(audio):
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=config.MLX_WHISPER_MODEL, language="en",
        temperature=0.0, initial_prompt=prompt(),
    )
    return result["text"].strip()


def _model():
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel

        _local_model = WhisperModel(config.WHISPER_MODEL, compute_type="int8")
    return _local_model


def _transcribe_local(audio):
    segments, _ = _model().transcribe(
        audio, language="en", beam_size=5, initial_prompt=prompt()
    )
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
        data={"model": "whisper-1", "prompt": prompt()},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()
