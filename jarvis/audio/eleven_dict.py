"""Pronunciation dictionary for ElevenLabs voices.

Put one respelling per line in data/pronunciations.txt:

    Jarvis = JAR-vis
    Yogesh = YOH-gesh

then run `python -m jarvis eleven-pronunciations`. The dictionary is uploaded
to your ElevenLabs account and its id is saved to data/elevenlabs_pronunciations.json;
every spoken sentence then carries it. Re-run after editing the file.
"""
import json

import requests

from .. import config

SOURCE = config.ELEVEN_DICT_FILE.with_name("pronunciations.txt")


def rules():
    out = []
    if SOURCE.exists():
        for line in SOURCE.read_text(encoding="utf-8").splitlines():
            word, sep, alias = line.partition("=")
            if sep and word.strip() and alias.strip() and not line.lstrip().startswith("#"):
                out.append({"string_to_replace": word.strip(), "type": "alias", "alias": alias.strip()})
    return out


def run():
    if not config.ELEVENLABS_API_KEY:
        raise SystemExit("ELEVENLABS_API_KEY is not set")
    found = rules()
    if not found:
        raise SystemExit("No rules found. Add lines like `Jarvis = JAR-vis` to {}".format(SOURCE))
    resp = requests.post(
        "https://api.elevenlabs.io/v1/pronunciation-dictionaries/add-from-rules",
        headers={"xi-api-key": config.ELEVENLABS_API_KEY},
        json={"name": "jarvis", "rules": found},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    config.ELEVEN_DICT_FILE.write_text(
        json.dumps({"id": body["id"], "version_id": body["version_id"]}, indent=2), encoding="utf-8"
    )
    print("Uploaded {} rule(s). Saved {}.".format(len(found), config.ELEVEN_DICT_FILE))
