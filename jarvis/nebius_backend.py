"""Nebius Token Factory backend: NVIDIA open models (Nemotron) as the brain.

Token Factory speaks the OpenAI Chat Completions API, so this is a manual
tool loop over the openai SDK, behind the same synchronous .chat() as the
other backends. Every tool call is dispatched through jarvis.tools.execute,
so the confirmation gate (including the _confirmed stripping) applies
unchanged. The wake word, speech-to-text and memory recall stay on the Mac;
only conversation text and tool results are sent to Nebius, plus
screenshots when NEBIUS_VISION_MODEL is set.
"""
import json
import re
import time

from . import config, settings, tools

_MAX_TOOL_ROUNDS = 12
# Reasoning models may emit their chain of thought inline; never speak it.
_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.S)

# The last request, for the HUD: model, latency (s), token counts.
stats = {}


def openai_tools():
    """Jarvis's Anthropic-style schemas as OpenAI function tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in tools.TOOL_SCHEMAS
    ]


def clean(text):
    return _THINK.sub("", text or "").strip()


def make_client():
    if not config.NEBIUS_API_KEY:
        raise SystemExit(
            "NEBIUS_API_KEY is not set. Create a key in the Nebius Token Factory "
            "console and put it in .env (never in git)."
        )
    from openai import OpenAI

    return OpenAI(
        base_url=config.NEBIUS_BASE_URL,
        api_key=config.NEBIUS_API_KEY,
        timeout=90,
        max_retries=2,
    )


class NebiusBackend:
    def __init__(self, confirm, system_prompt, client=None):
        self.client = client or make_client()
        self.confirm = confirm
        prefix = config.NEBIUS_SYSTEM_PREFIX.strip()
        self.messages = [{
            "role": "system",
            "content": "{}\n\n{}".format(prefix, system_prompt) if prefix else system_prompt,
        }]
        self.tools = openai_tools()

    def _request(self, model):
        started = time.monotonic()
        response = self.client.chat.completions.create(
            model=model,
            messages=self.messages,
            tools=self.tools,
            tool_choice="auto",
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.NEBIUS_TEMPERATURE,
        )
        usage = getattr(response, "usage", None)
        stats.clear()
        stats.update(
            model=model,
            latency=round(time.monotonic() - started, 2),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
        return response

    def chat(self, user_text):
        from .assistant import stamp

        mark = len(self.messages)
        self.messages.append({"role": "user", "content": stamp(user_text)})
        model = settings.model_id()
        try:
            for _ in range(_MAX_TOOL_ROUNDS):
                message = self._request(model).choices[0].message
                calls = message.tool_calls or []
                entry = {"role": "assistant", "content": message.content or ""}
                if calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.function.name,
                                "arguments": c.function.arguments or "{}",
                            },
                        }
                        for c in calls
                    ]
                self.messages.append(entry)
                if not calls:
                    return clean(message.content) or "Done."
                for call in calls:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": self._run(call),
                    })
        except Exception as exc:  # noqa: BLE001 — network/API errors must not kill the session
            # Drop the half-finished turn so the history stays valid.
            del self.messages[mark:]
            print("  [nebius] {}: {}".format(type(exc).__name__, exc))
            return "I couldn't reach my model just now. Please try again in a moment."
        return "I seem to be going in circles — could you rephrase that?"

    def _run(self, call):
        name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError as exc:
            return "Invalid arguments for {}: not valid JSON ({})".format(name, exc)
        if not isinstance(args, dict):
            return "Invalid arguments for {}: expected a JSON object".format(name)
        print("  [tool] {} {}".format(name, args))
        text, _is_error = tools.execute(name, args, self.confirm)
        if isinstance(text, tools.ToolImage):
            return self._describe(text)
        return str(text)

    def _describe(self, image):
        """Chat models here are text-only: have the vision model put the
        picture into words, and hand the brain that description."""
        if not config.NEBIUS_VISION_MODEL:
            return "{}\n\n(The image can't be viewed: no vision model is configured.)".format(image)
        response = self.client.chat.completions.create(
            model=config.NEBIUS_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "Describe this image for an assistant that cannot see it: "
                        "all readable text, apps and windows, any errors, and the "
                        "layout. Context: {}".format(image)
                    )},
                    {"type": "image_url", "image_url": {
                        "url": "data:{};base64,{}".format(image.mime, image.data),
                    }},
                ],
            }],
            max_tokens=800,
        )
        return "{}\n\nWhat the image shows: {}".format(
            image, clean(response.choices[0].message.content)
        )


_PROBE_TOOL = [{
    "type": "function",
    "function": {
        "name": "weather_get",
        "description": "Current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]


def _probe(client, model):
    """Does this model return a proper tool call? Returns (ok, seconds)."""
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "What's the weather in Sydney?"}],
            tools=_PROBE_TOOL,
            tool_choice="auto",
            max_tokens=300,
        )
        calls = response.choices[0].message.tool_calls or []
        ok = any(c.function.name == "weather_get" for c in calls)
    except Exception as exc:  # noqa: BLE001 — report and move on
        return "error: {}".format(str(exc)[:80]), time.monotonic() - started
    return ("tools OK" if ok else "no tool call"), time.monotonic() - started


def list_models(probe=False):
    """`python -m jarvis nebius-models [--probe]`: print the models this key
    can use, NVIDIA's first, so the right ids go into .env. --probe checks
    each NVIDIA model returns a real tool call (costs a few tokens each)."""
    client = make_client()
    ids = sorted(m.id for m in client.models.list().data)
    nvidia = [i for i in ids if "nvidia" in i.lower() or "nemotron" in i.lower()]
    print("NVIDIA / Nemotron models:")
    for i in nvidia:
        if probe:
            verdict, secs = _probe(client, i)
            print("  {:<60} {} ({:.1f}s)".format(i, verdict, secs))
        else:
            print("  " + i)
    print("\nAll other models:")
    for i in ids:
        if i not in nvidia:
            print("  " + i)
