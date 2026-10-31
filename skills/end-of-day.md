---
name: end-of-day
description: Wrap up the day: what got done, what's still open, tomorrow's first commitment, and a reminder for anything that slipped.
---

## Steps

1. Call `task_list` and note what's still open and what was due today.
2. Call `calendar_list_events` with days_ahead 2 to find tomorrow's first commitment.
3. For each open task that was due today, ask whether to move it to tomorrow; if yes, add a reminder for tomorrow morning with `reminder_set`.
4. Show a `hud_show_card` titled "Wrap-up" with: open tasks, tomorrow's first event and time.
5. Say one or two sentences, ending on tomorrow's first commitment.
