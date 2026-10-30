---
name: morning-kickoff
description: Start the day: weather, first meetings, urgent email and the three tasks that matter most, on screen and spoken briefly.
---

## Steps

1. Call `briefing_get` for weather, today's calendar, open tasks, reminders and unread email.
2. Pick the three tasks that matter most today (due today first, then anything tied to today's meetings).
3. Show a `hud_show_card` titled "Today" with: first meeting and time, the three tasks, and any email that needs a reply today.
4. Say two or three sentences: the first commitment, the top task, and anything urgent.
