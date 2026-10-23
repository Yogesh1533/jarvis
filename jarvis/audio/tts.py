"""Text to speech with pluggable providers: piper (local), elevenlabs, openai."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import config


def speak(text):
    text = (text or "").strip()
    if not text:
        return
    provider = config.TTS_PROVIDER
    if provider == "elevenlabs":
        _play_bytes(_elevenlabs(text))
    elif provider == "openai":
        _play_bytes(_openai(text))
    else:
        _piper(text)


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


def _piper_bin():
    # Prefer the piper that lives next to this interpreter (works even when
    # the venv isn't activated, e.g. launched from launchd/Task Scheduler).
    import sys

    candidate = Path(sys.executable).parent / "piper"
    if candidate.exists():
        return str(candidate)
    return shutil.which("piper")


def _piper(text):
    binary = _piper_bin()
    if binary is None:
        raise RuntimeError(
            "piper CLI not found — install with 'pip install piper-tts' "
            "(inside the same venv) or set TTS_PROVIDER to elevenlabs/openai."
        )
    if not config.PIPER_VOICE.exists():
        raise RuntimeError(
            "Piper voice model missing at {}. Download one, e.g.:\n"
            "  python -m piper.download_voices en_GB-alan-medium "
            "--data-dir {}".format(config.PIPER_VOICE, config.PIPER_VOICE.parent)
        )
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = Path(f.name)
    try:
        subprocess.run(
            [binary, "--model", str(config.PIPER_VOICE), "--output_file", str(tmp)],
            input=text.encode("utf-8"),
            check=True,
            capture_output=True,
        )
        _play_file(tmp)
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
