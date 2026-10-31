"""Text to speech with pluggable providers: piper (local), elevenlabs, openai."""
import io
import shutil
import subprocess
import tempfile
import threading
import os
import re
import wave
from pathlib import Path

from .. import config

# Optional respelling of the assistant's name before synthesis, for voices
# that say it oddly. Empty (the default) leaves the text alone.
_SAY = os.getenv("JARVIS_SAY", "").strip()
_NAME = re.compile(r"\bjarvis\b", re.I)


def pronounce(text):
    return _NAME.sub(_SAY, text) if _SAY else text


def speak(text):
    text = (text or "").strip()
    if not text:
        return
    audio, mime = synthesize(text)
    _play_bytes(audio, suffix=".wav" if mime == "audio/wav" else ".mp3")


def synthesize(text):
    """Text -> (audio bytes, mime type), without playing it. The HUD sends
    these bytes to the browser, which plays them and animates the reactor."""
    provider = config.TTS_PROVIDER
    text = pronounce(text)
    if provider == "elevenlabs":
        return _elevenlabs(text), "audio/mpeg"
    if provider == "openai":
        return _openai(text), "audio/mpeg"
    return _piper(text), "audio/wav"


def _play_file(path):
    import sounddevice as sd
    import soundfile as sf

    data, samplerate = sf.read(str(path), dtype="float32")
    sd.play(data, samplerate)
    sd.wait()


def _play_bytes(audio_bytes, suffix=".mp3"):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp = Path(f.name)
    try:
        _play_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)


_voices = {}
_voice_lock = threading.Lock()


def _piper(text):
    """Synthesize with the active mood's voice, pace and volume. Runs Piper
    in-process (voices stay loaded, so short sentences start fast) and
    falls back to the piper CLI if the Python API isn't available."""
    from .. import moods

    mood = moods.current()
    path = moods.voice_path(mood["voice"])
    if not path.exists():
        path = config.PIPER_VOICE
    if not path.exists():
        raise RuntimeError(
            "Piper voice model missing at {}. Download one, e.g.:\n"
            "  python -m piper.download_voices en_GB-alan-medium "
            "--data-dir {}".format(path, path.parent)
        )
    try:
        from piper import PiperVoice, SynthesisConfig
    except ImportError:
        return _piper_cli(text, path)
    with _voice_lock:
        voice = _voices.get(path)
        if voice is None:
            voice = _voices[path] = PiperVoice.load(str(path))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            voice.synthesize_wav(
                text, wav,
                syn_config=SynthesisConfig(
                    length_scale=1.0 / mood["speed"], volume=mood["volume"]
                ),
            )
    return buf.getvalue()


def _piper_bin():
    # Prefer the piper that lives next to this interpreter (works even when
    # the venv isn't activated, e.g. launched from launchd/Task Scheduler).
    import sys

    candidate = Path(sys.executable).parent / "piper"
    if candidate.exists():
        return str(candidate)
    return shutil.which("piper")


def _piper_cli(text, model):
    binary = _piper_bin()
    if binary is None:
        raise RuntimeError(
            "piper CLI not found — install with 'pip install piper-tts' "
            "(inside the same venv) or set TTS_PROVIDER to elevenlabs/openai."
        )
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = Path(f.name)
    try:
        subprocess.run(
            [binary, "--model", str(model), "--output_file", str(tmp)],
            input=text.encode("utf-8"),
            check=True,
            capture_output=True,
        )
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def _elevenlabs(text):
    import requests

    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError("TTS_PROVIDER=elevenlabs but ELEVENLABS_API_KEY is not set")
    resp = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/{}".format(
            config.ELEVENLABS_VOICE_ID
        ),
        headers={"xi-api-key": config.ELEVENLABS_API_KEY},
        json={"text": text, "model_id": "eleven_turbo_v2_5"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content


def _openai(text):
    import requests

    if not config.OPENAI_API_KEY:
        raise RuntimeError("TTS_PROVIDER=openai but OPENAI_API_KEY is not set")
    resp = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": "Bearer {}".format(config.OPENAI_API_KEY)},
        json={"model": "tts-1", "voice": config.OPENAI_TTS_VOICE, "input": text},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content


def chime():
    """Short tone confirming the wake word was heard."""
    import numpy as np
    import sounddevice as sd

    sr = config.SAMPLE_RATE
    t = np.linspace(0, 0.15, int(sr * 0.15), dtype=np.float32)
    tone = 0.25 * np.sin(2 * np.pi * 880 * t) * np.exp(-6 * t)
    sd.play(tone, sr)
    sd.wait()
