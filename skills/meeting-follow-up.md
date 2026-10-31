---
name: meeting-follow-up
description: After a meeting: draft a short follow-up email to the attendees with the agreed next steps.
---

## Steps

1. Call `calendar_list_events` to find the meeting that ended most recently today, and its attendees.
2. Ask the user for the two or three outcomes or next steps, unless they already said them.
3. Call `gmail_create_draft` to the attendees: a subject like "Follow-up: <meeting>", a two-line thank you, the next steps as a short list, and the user's name.
4. Read the draft back in one sentence and ask whether to send it. Sending needs their confirmation.
