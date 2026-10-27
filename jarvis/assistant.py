"""Conversation core: Anthropic API + tool loop + confirmation gate.

Audio-free by design so it can be driven by the voice loop, the text REPL,
or tests interchangeably.
"""
from datetime import datetime

from . import config, settings, tools
from .tools import memory

_MAX_TOOL_ROUNDS = 12


def build_system_prompt():
    if not config.SYSTEM_PROMPT_PATH.exists():
        raise SystemExit(
            "System prompt not found at {} — set SYSTEM_PROMPT_PATH in .env".format(
                config.SYSTEM_PROMPT_PATH
            )
        )
    text = config.SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    memories, full = memory.load_for_prompt()
    if memories and full:
        text += "\n\n## Your saved memories\n\n" + memories
    elif memories:
        text += (
            "\n\n## Your saved memories (index only)\n\n"
            "There are too many to list in full. Use `recall` to search them or "
            "`memory_read` to open one by name.\n\n" + memories
        )
    return text


def stamp(user_text):
    """Prefix the current time (and the active mood's style note) to a user
    message. Kept out of the system prompt so that stays cacheable."""
    from . import moods

    note = moods.style_note()
    return "[{}]{} {}".format(
        datetime.now().strftime("%A %Y-%m-%d %H:%M"),
        " [{}]".format(note) if note else "",
        user_text,
    )


class Assistant:
    """One conversation session.

    confirm: callable(prompt) -> bool. Asks the user to approve a gated
             action (spoken in voice mode, typed in text mode). Tool
             execution refuses gated actions unless this returns True
             within the same turn.
    client:  injectable for tests; defaults to the real Anthropic client.
    """

    def __init__(self, confirm, client=None):
        self.backend = None
        if client is None and config.LLM_BACKEND == "agent-sdk":
            # Claude subscription via the Claude Code CLI — no API key.
            from .agent_backend import AgentBackend

            self.backend = AgentBackend(
                confirm=confirm, system_prompt=build_system_prompt()
            )
        elif client is None and config.LLM_BACKEND == "nebius":
            # NVIDIA Nemotron on Nebius Token Factory (OpenAI-compatible API).
            from .nebius_backend import NebiusBackend

            self.backend = NebiusBackend(
                confirm=confirm, system_prompt=build_system_prompt()
            )
        elif client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.confirm = confirm
        self.messages = []
        # Built once per session so the prompt prefix stays cacheable.
        self.system = [
            {
                "type": "text",
                "text": build_system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _request(self):
        return self.client.beta.messages.create(
            model=settings.model_id(),
            max_tokens=config.LLM_MAX_TOKENS,
            system=self.system,
            tools=tools.TOOL_SCHEMAS,
            messages=self.messages,
            output_config={"effort": config.LLM_EFFORT},
            # Safety classifiers can decline benign requests; let the API
            # retry on its recommended fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def chat(self, user_text):
        """Send one user utterance; run tools until the model is done.

        Returns the assistant's final spoken/printed reply.
        """
        if self.backend is not None:
            return self.backend.chat(user_text)

        self.messages.append({"role": "user", "content": stamp(user_text)})

        for _ in range(_MAX_TOOL_ROUNDS):
            response = self._request()

            if response.stop_reason == "refusal":
                # Whole fallback chain declined; drop the turn from history
                # so the session can continue cleanly.
                self.messages.pop()
                return "I'm sorry, I can't help with that request."

            self.messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return self._final_text(response)

            results = []
            for block in tool_uses:
                print("  [tool] {} {}".format(block.name, block.input))
                text, is_error = tools.execute(block.name, block.input, self.confirm)
                content = str(text)
                if isinstance(text, tools.ToolImage):
                    content = [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": text.mime, "data": text.data,
                        }},
                        {"type": "text", "text": str(text)},
                    ]
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                        "is_error": is_error,
                    }
                )
            self.messages.append({"role": "user", "content": results})

        return "I seem to be going in circles — could you rephrase that?"

    def brain(self):
        """How the last turn was handled (route, model, timing, masking), or
        None on backends that don't report it."""
        if config.LLM_BACKEND == "nebius" and self.backend is not None:
            from . import nebius_backend

            return dict(nebius_backend.stats) or None
        return None

    @staticmethod
    def _final_text(response):
        parts = [b.text for b in response.content if b.type == "text"]
        return " ".join(p.strip() for p in parts if p.strip()) or "Done."
