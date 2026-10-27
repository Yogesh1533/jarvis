"""Central configuration. Everything comes from .env at the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(key: str, default: str) -> Path:
    raw = os.getenv(key, default)
    p = Path(os.path.expanduser(raw))
    return p if p.is_absolute() else (ROOT / p).resolve()


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "") or default)
    except ValueError:
        return default


# LLM access
# "agent-sdk" — your Claude subscription via the Claude Code CLI login
# "api"       — Anthropic API key + credits (ANTHROPIC_API_KEY)
# "nebius"    — NVIDIA open models on Nebius Token Factory (NEBIUS_API_KEY)
LLM_BACKEND = os.getenv("LLM_BACKEND", "agent-sdk")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")

# Nebius Token Factory (OpenAI-compatible). Model ids: python -m jarvis nebius-models
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
NEBIUS_MODEL = os.getenv("NEBIUS_MODEL", "nvidia/nemotron-3-super-120b-a12b")
NEBIUS_FAST_MODEL = os.getenv("NEBIUS_FAST_MODEL", "nvidia/Nemotron-3_5-Lightning")   # quick turns
NEBIUS_DEEP_MODEL = os.getenv("NEBIUS_DEEP_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b")  # hard ones
NEBIUS_VISION_MODEL = os.getenv("NEBIUS_VISION_MODEL", "nvidia/Nemotron-3.5-Super-VL")  # screenshots; "" = off
# Prepended to the system prompt. Nemotron reasoning models read "/no_think"
# (snappy voice replies) or "/think"; Llama-Nemotron uses "detailed thinking off".
NEBIUS_SYSTEM_PREFIX = os.getenv("NEBIUS_SYSTEM_PREFIX", "/no_think")
NEBIUS_TEMPERATURE = _float("NEBIUS_TEMPERATURE", 0.3)
# Mask emails, phone and card numbers before anything is sent to Nebius.
NEBIUS_PRIVACY = os.getenv("NEBIUS_PRIVACY", "on").strip().lower() not in ("off", "0", "false", "no")
if LLM_BACKEND == "nebius" and LLM_MODEL.startswith("claude-"):
    LLM_MODEL = NEBIUS_MODEL
LLM_EFFORT = os.getenv("LLM_EFFORT", "low")
LLM_MAX_TOKENS = int(_float("LLM_MAX_TOKENS", 4096))

# Speech to text
STT_PROVIDER = os.getenv("STT_PROVIDER", "auto")   # auto | mlx | local | openai
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")   # faster-whisper (local)
MLX_WHISPER_MODEL = os.getenv("MLX_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
STT_VOCABULARY = os.getenv("STT_VOCABULARY", "")   # names/words to expect, comma-separated
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Text to speech
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "piper")
PIPER_VOICE = _path("PIPER_VOICE", "./data/voices/en_GB-alan-medium.onnx")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")

# Wake word
WAKE_WORD_MODEL = os.getenv("WAKE_WORD_MODEL", "hey_jarvis")
WAKE_THRESHOLD = _float("WAKE_THRESHOLD", 0.5)

# Timings
FOLLOWUP_WINDOW = _float("FOLLOWUP_WINDOW", 6)
RECORD_START_TIMEOUT = _float("RECORD_START_TIMEOUT", 6)
MAX_UTTERANCE_SECONDS = _float("MAX_UTTERANCE_SECONDS", 60)
REMINDER_POLL_SECONDS = _float("REMINDER_POLL_SECONDS", 5)
RMS_THRESHOLD = _float("RMS_THRESHOLD", 500)

SAMPLE_RATE = 16000  # required by openWakeWord and Whisper

# Google
GOOGLE_CREDENTIALS_PATH = _path("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
GOOGLE_TOKEN_PATH = _path("GOOGLE_TOKEN_PATH", "./data/google_token.json")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

# Weather: city name for the default location; empty = locate by IP
WEATHER_LOCATION = os.getenv("WEATHER_LOCATION", "")

# Folders Jarvis may search, read and open files in (comma-separated)
FILES_ROOTS = [
    Path(os.path.expanduser(p.strip())).resolve()
    for p in os.getenv(
        "FILES_ROOTS",
        "~/Documents,~/Desktop,~/Downloads,~/Library/Mobile Documents/com~apple~CloudDocs",
    ).split(",")
    if p.strip()
]

# Semantic recall: a small local embedding model (ONNX, CPU). The cache lives
# outside the project because the project sits in iCloud, which evicts files.
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_CACHE_DIR = _path("EMBED_CACHE_DIR", "~/.cache/jarvis/models")
RECALL_MIN_SCORE = _float("RECALL_MIN_SCORE", 0.50)   # cosine; below this is "not relevant"
RECALL_INDEX_TURNS = os.getenv("RECALL_INDEX_TURNS", "1") != "0"
MEMORY_PRELOAD_CHARS = int(_float("MEMORY_PRELOAD_CHARS", 6000))

# Paths
SYSTEM_PROMPT_PATH = _path(
    "SYSTEM_PROMPT_PATH", "./config/jarvis-voice-assistant-system-prompt.md"
)
MEMORY_DIR = _path("MEMORY_DIR", "./memory")
DB_PATH = _path("DB_PATH", "./data/jarvis.db")
