"""Claude Agent SDK backend: runs Jarvis on a Claude subscription login
(via the Claude Code CLI) instead of a pay-per-token API key.

The SDK is async and session-oriented, so this class owns a private event
loop on a daemon thread and exposes the same synchronous .chat() the rest
of Jarvis expects. All Jarvis tools are registered as an in-process MCP
server; each call is dispatched through jarvis.tools.execute, so the
confirmation gate (including the _confirmed stripping) applies unchanged.
"""
import asyncio
import os
import threading

from . import config, settings, tools

_BUILTIN_TOOLS_OFF = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch",
    "Task", "NotebookEdit", "TodoWrite", "BashOutput", "KillShell",
]


class AgentBackend:
    def __init__(self, confirm, system_prompt):
        self.confirm = confirm
        self.system_prompt = system_prompt
        self._client = None
        self._connecting = None
        self._model = None
        # The standalone CLI installs to ~/.local/bin; make sure the SDK
        # finds it even when launched from launchd/preview contexts.
        os.environ["PATH"] = (
            os.path.expanduser("~/.local/bin") + os.pathsep + os.environ.get("PATH", "")
        )
        # An API key in the environment outranks the subscription login in
        # the CLI's auth chain — remove it so this backend always uses the
        # Claude Code login it was chosen for.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        self._loop = asyncio.new_event_loop()
        threading.Thread(
            target=self._loop.run_forever, daemon=True, name="agent-sdk-loop"
        ).start()

    # -- sync facade ----------------------------------------------------
    def warm(self):
        """Start the CLI and connect in the background, so the first reply
        doesn't pay for it."""
        asyncio.run_coroutine_threadsafe(self._ensure_client(), self._loop)

    streams = True   # chat() can report the reply's text as it's written

    def chat(self, user_text, on_text=None):
        """on_text(text_so_far) is called from the SDK thread as each text
        block streams in, so the caller can start speaking early."""
        future = asyncio.run_coroutine_threadsafe(self._chat(user_text, on_text), self._loop)
        return future.result(timeout=600)

    # -- async internals -------------------------------------------------
    def _sdk_tools(self):
        from claude_agent_sdk import tool

        sdk_tools = []
        for schema in tools.TOOL_SCHEMAS:
            async def handler(args, _name=schema["name"]):
                loop = asyncio.get_running_loop()
                # tools.execute may block on user confirmation (TTS + mic,
                # or a browser dialog) — keep it off the event loop.
                text, _is_error = await loop.run_in_executor(
                    None, tools.execute, _name, args or {}, self.confirm
                )
                content = [{"type": "text", "text": str(text)}]
                if isinstance(text, tools.ToolImage):
                    content.insert(0, {"type": "image", "data": text.data, "mimeType": text.mime})
                return {"content": content}

            sdk_tools.append(
                tool(schema["name"], schema["description"], schema["input_schema"])(handler)
            )
        return sdk_tools

    async def _ensure_client(self):
        # One shared connect, so warm() and the first chat() never race.
        if self._connecting is None:
            self._connecting = asyncio.ensure_future(self._connect())
        try:
            return await self._connecting
        except Exception:
            self._connecting = self._client = None   # retry on the next turn
            raise

    async def _connect(self):
        from claude_agent_sdk import (
            ClaudeAgentOptions,
            ClaudeSDKClient,
            create_sdk_mcp_server,
        )

        server = create_sdk_mcp_server(
            name="jarvis", version="1.0.0", tools=self._sdk_tools()
        )
        options = ClaudeAgentOptions(
            system_prompt=self.system_prompt,
            model=settings.model_id(),
            cwd=str(config.ROOT),
            mcp_servers={"jarvis": server},
            allowed_tools=[
                "mcp__jarvis__" + s["name"] for s in tools.TOOL_SCHEMAS
            ],
            # Jarvis's tool surface is its own; no shell/file/web builtins.
            disallowed_tools=_BUILTIN_TOOLS_OFF,
            max_turns=24,
            include_partial_messages=True,   # stream text so speech can start early
            # Voice replies need speed, not deep thought (LLM_EFFORT, default low).
            effort=config.LLM_EFFORT,
            # Isolation: don't load ~/.claude settings, plugins, hooks, skills
            # or other MCP servers. They bloat every turn and slow startup.
            setting_sources=[],
            skills=[],
            extra_args={"strict-mcp-config": None},
        )
        self._model = options.model
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        return self._client

    async def _chat(self, user_text, on_text=None):
        from claude_agent_sdk import AssistantMessage, TextBlock
        from claude_agent_sdk.types import StreamEvent

        client = await self._ensure_client()
        wanted = settings.model_id()
        if wanted != self._model:   # picked in the HUD since the last reply
            await client.set_model(wanted)
            self._model = wanted
        from .assistant import stamp

        await client.query(stamp(user_text))
        parts = []
        streamed = ""
        async for message in client.receive_response():
            if isinstance(message, StreamEvent):
                event = message.event
                if on_text is None or message.parent_tool_use_id:
                    continue
                if event.get("type") == "content_block_start":
                    streamed = ""
                elif event.get("type") == "content_block_delta" \
                        and event.get("delta", {}).get("type") == "text_delta":
                    streamed += event["delta"].get("text", "")
                    try:
                        on_text(streamed)
                    except Exception as exc:  # noqa: BLE001 — never break the turn
                        print("[agent] on_text failed: {}".format(exc))
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        parts.append(block.text.strip())
        # Intermediate texts are between-tool narration; the last one is
        # the reply meant for the user.
        return parts[-1] if parts else "Done."
