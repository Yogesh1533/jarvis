"""Text-only chat mode: same brain, no audio stack. For testing and quiet use."""
from .assistant import Assistant
from .tools import recall, reminders, timers


def run():
    def text_confirm(prompt):
        answer = input("\n[CONFIRM] {} [yes/no]: ".format(prompt)).strip().lower()
        return answer in ("y", "yes")

    recall.warm()
    assistant = Assistant(confirm=text_confirm)
    reminders.start_scheduler(lambda msg: print("\n[REMINDER] {}".format(msg)))
    timers.set_notifier(lambda label: print("\n[TIMER] {} is done".format(label)))

    print("Jarvis text mode. Type your message; 'quit' to exit.\n")
    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() in ("quit", "exit"):
            break
        reply = assistant.chat(user)
        brain = assistant.brain()
        if brain:
            print("  [brain] {route} · {model} · {seconds}s · {masked} masked".format(**brain))
        print("Jarvis: {}\n".format(reply))
