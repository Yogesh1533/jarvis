"""Tool registry and dispatcher.

The confirmation gate lives here, in code: a tool that needs the user's
explicit go-ahead raises ConfirmationRequired. The dispatcher then asks the
user (voice or keyboard, via the confirm callback supplied by the caller)
and only re-invokes the tool with _confirmed=True if they said yes.

The model can never grant confirmation itself: any argument starting with
an underscore is stripped from model-supplied input before dispatch, and
the confirmation flag is only ever set by this dispatcher within the same
conversation turn.
"""


class ConfirmationRequired(Exception):
    def __init__(self, prompt: str):
        super().__init__(prompt)
        self.prompt = prompt


DECLINED_MESSAGE = (
    "The user declined the confirmation. The action was NOT performed. "
    "Do not retry it; ask the user what they would like instead."
)

TOOL_SCHEMAS = [
    # ── Gmail ──────────────────────────────────────────────────────
    {
        "name": "gmail_search",
        "description": (
            "Search the user's Gmail. Use Gmail query syntax, e.g. "
            "'is:unread', 'from:alice newer_than:7d'. Returns sender, "
            "subject, date, snippet and message id for each hit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "max_results": {"type": "integer", "description": "Default 10"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "gmail_read",
        "description": "Read the full body of one email by message id (from gmail_search).",
        "input_schema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
            "required": ["message_id"],
        },
    },
    {
        "name": "gmail_create_draft",
        "description": (
            "Create a Gmail draft. This never sends anything. Returns the "
            "draft id, which gmail_send_draft needs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain-text body"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_send_draft",
        "description": (
            "Send an existing draft by draft id. REQUIRES the user's spoken "
            "confirmation — the system will ask them before executing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"draft_id": {"type": "string"}},
            "required": ["draft_id"],
        },
    },
    # ── Calendar ───────────────────────────────────────────────────
    {
        "name": "calendar_list_events",
        "description": "List upcoming events on the user's primary Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "Look-ahead window, default 7"},
                "query": {"type": "string", "description": "Optional free-text filter"},
            },
        },
    },
    {
        "name": "calendar_create_event",
        "description": (
            "Create a calendar event. Times must be ISO 8601 with a UTC "
            "offset, e.g. 2026-07-10T15:00:00+05:45. Invites are NOT "
            "emailed to attendees on creation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start": {"type": "string", "description": "ISO 8601 with offset"},
                "end": {"type": "string", "description": "ISO 8601 with offset"},
                "description": {"type": "string"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Attendee email addresses",
                },
            },
            "required": ["summary", "start", "end"],
        },
    },
    {
        "name": "calendar_update_event",
        "description": (
            "Update an event's time, title or description by event id. If "
            "the event has other attendees this REQUIRES the user's spoken "
            "confirmation and attendees are notified of the change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "summary": {"type": "string"},
                "start": {"type": "string", "description": "ISO 8601 with offset"},
                "end": {"type": "string", "description": "ISO 8601 with offset"},
                "description": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_delete_event",
        "description": (
            "Delete a calendar event by id. ALWAYS requires the user's "
            "spoken confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        },
    },
    # ── Tasks ──────────────────────────────────────────────────────
    {
        "name": "task_add",
        "description": "Add a task to the local task list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due": {"type": "string", "description": "Optional 'YYYY-MM-DD HH:MM' local time"},
                "notes": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "task_list",
        "description": "List tasks. Open tasks by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_done": {"type": "boolean", "description": "Default false"}
            },
        },
    },
    {
        "name": "task_complete",
        "description": "Mark a task done by its numeric id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_delete",
        "description": "Delete a task by id. ALWAYS requires the user's spoken confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    # ── Reminders ──────────────────────────────────────────────────
    {
        "name": "reminder_set",
        "description": (
            "Set a reminder that will be spoken aloud when due. Compute the "
            "absolute local time from the timestamp on the user's message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to say when it fires"},
                "due_at": {"type": "string", "description": "'YYYY-MM-DD HH:MM' local time"},
            },
            "required": ["message", "due_at"],
        },
    },
    {
        "name": "reminder_list",
        "description": "List pending reminders.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reminder_cancel",
        "description": "Cancel a pending reminder by id. Requires the user's spoken confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"reminder_id": {"type": "integer"}},
            "required": ["reminder_id"],
        },
    },
    # ── Web search ─────────────────────────────────────────────────
    {
        "name": "web_search",
        "description": "Search the web (DuckDuckGo). Use for anything current or outside your knowledge.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "description": "Default 5"},
            },
            "required": ["query"],
        },
    },
    # ── Memory ─────────────────────────────────────────────────────
    {
        "name": "memory_save",
        "description": (
            "Save one durable fact about the user to persistent memory. "
            "Updates the file if the name already exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "kebab-case slug, e.g. 'sister-birthday'",
                },
                "summary": {"type": "string", "description": "One-line summary"},
                "content": {"type": "string", "description": "The fact itself"},
            },
            "required": ["name", "summary", "content"],
        },
    },
    {
        "name": "memory_read",
        "description": "Read one memory by name (memories are also preloaded each session).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "memory_delete",
        "description": "Delete a memory by name. ALWAYS requires the user's spoken confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def _handlers():
    # Imported lazily so text mode starts even if e.g. Google libs are
    # missing; a broken dependency surfaces as a tool error, not a crash.
    from . import gmail, gcal, tasks, reminders, websearch, memory

    return {
        "gmail_search": gmail.search,
        "gmail_read": gmail.read,
        "gmail_create_draft": gmail.create_draft,
        "gmail_send_draft": gmail.send_draft,
        "calendar_list_events": gcal.list_events,
        "calendar_create_event": gcal.create_event,
        "calendar_update_event": gcal.update_event,
        "calendar_delete_event": gcal.delete_event,
        "task_add": tasks.add,
        "task_list": tasks.list_tasks,
        "task_complete": tasks.complete,
        "task_delete": tasks.delete,
        "reminder_set": reminders.set_reminder,
        "reminder_list": reminders.list_reminders,
        "reminder_cancel": reminders.cancel,
        "web_search": websearch.search,
        "memory_save": memory.save,
        "memory_read": memory.read,
        "memory_delete": memory.delete,
    }


def execute(name, args, confirm):
    """Run a tool call from the model. Returns (result_text, is_error).

    `confirm` is a callable(prompt) -> bool that asks the user out loud
    (voice mode) or on the keyboard (text mode).
    """
    handlers = _handlers()
    if name not in handlers:
        return "Unknown tool: {}".format(name), True

    # The model must not be able to smuggle in the confirmation flag.
    args = {k: v for k, v in (args or {}).items() if not k.startswith("_")}

    handler = handlers[name]
    try:
        return str(handler(**args)), False
    except ConfirmationRequired as exc:
        if confirm(exc.prompt):
            try:
                return str(handler(_confirmed=True, **args)), False
            except Exception as exc2:  # noqa: BLE001 — tool errors go back to the model
                return "Tool error: {}".format(exc2), True
        return DECLINED_MESSAGE, False
    except TypeError as exc:
        return "Invalid arguments for {}: {}".format(name, exc), True
    except Exception as exc:  # noqa: BLE001 — tool errors go back to the model
        return "Tool error: {}".format(exc), True
