"""Wake-word detection with openWakeWord — fully local, mic audio never
leaves the machine."""
import numpy as np

from .. import config

_CHUNK = 1280  # 80 ms at 16 kHz, openWakeWord's expected frame size


class WakeWordDetector:
    def __init__(self):
        import openwakeword
        from openwakeword.model import Model

        # Fetches the pre-trained models (incl. hey_jarvis) on first run.
        openwakeword.utils.download_models()
        self.model = Model(
            wakeword_models=[config.WAKE_WORD_MODEL],
            inference_framework="onnx",
        )

    def reset(self):
        self.model.reset()

    def detect(self, chunk):
        """Feed one 80 ms int16 chunk; True if the wake word just fired."""
        scores = self.model.predict(chunk)
        return any(s >= config.WAKE_THRESHOLD for s in scores.values())

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
