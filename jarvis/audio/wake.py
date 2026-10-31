"""Wake-word detection with openWakeWord — fully local, mic audio never
leaves the machine."""
from pathlib import Path

import numpy as np

from .. import config

_CHUNK = 1280  # 80 ms at 16 kHz, openWakeWord's expected frame size


class WakeWordDetector:
    def __init__(self):
        import openwakeword
        from openwakeword.model import Model

        model = config.WAKE_WORD_MODEL
        if model.endswith(".onnx") and not Path(model).exists():
            raise FileNotFoundError(
                "no wake-word model at {} (train one: docs/wake-word.md); "
                "press Space or tap the orb to talk".format(model)
            )
        # Fetches openWakeWord's shared feature models on first run.
        openwakeword.utils.download_models()
        self.model = Model(
            wakeword_models=[config.WAKE_WORD_MODEL],
            inference_framework="onnx",
        )

    def reset(self):
        self.model.reset()

    def detect(self, chunk):
        """Feed one 80 ms int16 chunk; True if the wake word just fired."""
        from .. import settings

        scores = self.model.predict(chunk)
        threshold = settings.wake_threshold()
        return any(s >= threshold for s in scores.values())

    def wait_for_wake(self):
        """Block until the wake word is heard on the local mic."""
        import sounddevice as sd

        self.reset()
        with sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_CHUNK,
        ) as stream:
            while True:
                chunk, _ = stream.read(_CHUNK)
                if self.detect(np.frombuffer(chunk, dtype=np.int16)):
                    return
