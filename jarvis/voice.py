"""The always-on voice loop: wake word -> listen -> think -> speak -> follow-up."""
from . import config
from .assistant import Assistant
from .tools import reminders

_AFFIRMATIVE = {
    "yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "affirmative",
    "do it", "go ahead", "send it", "please do", "yes please", "ok", "okay",
}


def is_affirmative(text):
    cleaned = "".join(c for c in (text or "").lower() if c.isalpha() or c == " ").strip()
    return cleaned in _AFFIRMATIVE or any(
        cleaned.startswith(a + " ") for a in ("yes", "yeah", "yep", "sure", "confirm")
    )


def run():
    from .audio import stt, tts
    from .audio.recorder import record_utterance
    from .audio.wake import WakeWordDetector

    def voice_confirm(prompt):
        tts.speak(prompt + " Say yes to confirm, or anything else to cancel.")
        audio = record_utterance()
        if audio is None:
            return False
        answer = stt.transcribe(audio)
        print("  [confirm] you said: {!r}".format(answer))
        return is_affirmative(answer)

    assistant = Assistant(confirm=voice_confirm)
    reminders.start_scheduler(lambda msg: tts.speak("Reminder: " + msg))

    print("Loading wake-word model...")
    detector = WakeWordDetector()
    print("Jarvis is listening. Say 'Hey Jarvis'. Ctrl-C to quit.")

    while True:
        detector.wait_for_wake()
        tts.chime()

        # First utterance after the wake word
        audio = record_utterance()
        if audio is None:
            continue
        text = stt.transcribe(audio)
        if not text:
            continue

        while True:
            print("You: {}".format(text))
            reply = assistant.chat(text)
            print("Jarvis: {}".format(reply))
            tts.speak(reply)

            # Follow-up window: keep listening briefly so the user doesn't
            # have to repeat the wake word mid-conversation.
            audio = record_utterance(start_timeout=config.FOLLOWUP_WINDOW)
            if audio is None:
                break
            text = stt.transcribe(audio)
            if not text:
                break
        # back to sleep — wake word required again
