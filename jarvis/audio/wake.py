"""Wake-word detection with openWakeWord — fully local, mic audio never
leaves the machine."""
import numpy as np
import sounddevice as sd

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

    def wait_for_wake(self):
        """Block until the wake word is heard."""
        self.model.reset()
        with sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_CHUNK,
        ) as stream:
            while True:
                chunk, _ = stream.read(_CHUNK)
                scores = self.model.predict(np.frombuffer(chunk, dtype=np.int16))
                if any(s >= config.WAKE_THRESHOLD for s in scores.values()):
                    return
