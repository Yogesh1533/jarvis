# Jarvis round 1: Brain link, coding agents, evening wrap

Status: draft for Yogesh's review · 2026-11-05

## Why

Jarvis mostly shows up in demos and hackathons. It can already handle mail,
calendar, tasks, the Mac, the screen and memory. What it can't do yet is
(a) see Yogesh's own second brain, (b) do real work while he talks, or
(c) close the day without being asked. These three features cover one
area each, and they're built in an order where each one feeds the next. The
demo arc is "what are my projects up to?", then "go fix X in project Y", then
the evening wrap, which reports what got done (including the agent's work)
and writes it into today's vault note.

## Goals

1. Jarvis can search and read the Obsidian vault "Brain", report on
   project status from `Projects.md`, and add notes to it.
2. Jarvis can start a background Claude coding agent in one of Yogesh's
   repos by voice, on a separate branch, show it live on the HUD, and say
   when it's done.
3. Once a day (at a set time, or on "wrap up my day"), Jarvis gives a short
   evening rundown and writes it into today's daily note.
4. Every feature works in the demo profile with fictional data, so a
   recording never shows the real vault, repos or inbox.

## Non-goals (this round)

- Reaching the MacBook Air over Tailscale, reading iMessage or WhatsApp,
  phone or remote access.
- Semantic (embedding) search over the vault. Text search is enough for now.
- Editing or deleting existing vault content. Writes are append or create
  only.
- Merging, pushing or opening PRs for agent work. Yogesh reviews and merges
  himself.

## Anti-goals (failure even if it "works")

- A demo shows real personal data from the vault, inbox or repos.
- A coding agent writes to `main`/the checked-out branch, pushes, or touches
  files outside its own worktree.
- Jarvis stops answering while an agent runs.
- Anything in the vault gets overwritten or lost.

## Constraints

- Runs on the Mac mini (`hostname` → `Yogeshs-Mac-mini.local`). Code lives in
  `~/Developer`. The vault is at
  `~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian/Brain`, synced
  through iCloud and committed nightly by `com.yogesh.vault-backup`.
- Follow the existing patterns: tool schema in `TOOL_SCHEMAS` plus a handler
  in `_handlers()` (`jarvis/tools/__init__.py`), dangerous handlers take
  `_confirmed=False` and raise `ConfirmationRequired`, proactive work goes
  through `Proactive.tick()` and `hub.brief()/announce()`, HUD events go
  through `hud_bridge.send`, user prefs go in `settings.py` with validation.
- Must keep working on all three brains (`agent-sdk`, `api`, `nebius`).
  The coding agent itself always runs on Claude through the Claude Agent SDK
  (subscription login), whatever brain Jarvis is using.
- No secrets in the vault, git or logs.

---

## Feature 1: Brain link

### Config (`.env`, documented in `.env.example`)

- `VAULT_DIR`: defaults to the Brain path above.
- `VAULT_EXCLUDE`: comma-separated folder names (relative to the vault) that
  are never searched or read. Defaults to
  `.obsidian,.trash,Templates,People,Life` (Yogesh's choice). Everything
  else, including `USER.md`, `CLAUDE.md`, `Digipearl/` and `AIBI/`, is readable.
  Templates are still used internally to create daily notes, but they're
  never returned by search or read.
- `DEV_ROOTS`: defaults to `~/Developer`. Shared with Feature 2.

### Tools

| Tool | Does | Gate |
|---|---|---|
| `vault_search(query, max_results=8)` | Case-insensitive text search over `*.md` in the vault. Filename/title hits rank above body hits. Returns the relative path, title and a one-line snippet around the first match. If the whole phrase finds nothing, falls back to matching all the words (same approach as `files.search`). | none |
| `vault_read(path)` | Reads one note by vault-relative path (from `vault_search`). Truncated to about 8,000 chars with a note saying it was cut. Refuses paths outside `VAULT_DIR`, inside excluded folders, or files that aren't `.md`. Resolves symlinks before checking. | none |
| `vault_note(text, where="daily", title=None, section=None)` | `daily`: appends a timestamped bullet under `## Notes / brain dump` in `Daily/YYYY-MM-DD.md`. If the note doesn't exist yet, it's created from `Templates/Daily.md` with `{{date}}` filled in. If the heading is missing, it's added at the end. With `section="Wrap"`, a new `## Wrap HH:MM` block holding `text` as-is (multi-line) is added at the end of the note instead. Running it twice adds two blocks; nothing is replaced (builder's call, keeps it append-only). `inbox`: creates `00 Inbox/YYYY-MM-DD_<slug>.md` with `type: note` frontmatter. It never overwrites; on a name clash it adds `-2`, `-3`. | none (append/create only) |
| `projects_status(project=None)` | Parses the markdown tables in `Projects.md` (Project, What it is, Path, GitHub). For each row whose path sits under `DEV_ROOTS` and is a git repo it adds the current branch, last commit (relative date + subject), the number of uncommitted files and whether there's an open Jarvis agent branch. Rows with no git say "no git". One project when named (fuzzy match on name), all of them otherwise. Read-only git, no fetch. | none |

The system prompt gets a short section: use `vault_*` for "my notes / my
vault / my brain / what did I write about…", and `projects_status` for "my
projects".

### Privacy

- Vault text that a tool returns goes to the cloud brain. On Nebius the
  existing `privacy.Vault` masks emails, phones and cards, but on Claude
  nothing is masked. `VAULT_EXCLUDE` is the control for that.
- `FILES_ROOTS` already covers iCloud Drive, so `files_search` can reach the
  vault today. That doesn't change, but the excluded folders are also
  skipped by `files_search` when they sit under `VAULT_DIR`.

### Demo profile

`scripts/seed_demo.py` creates a fictional vault at
`~/Documents/jarvis-demo/vault` (with `Projects.md`, `Daily/`, `Templates/Daily.md`,
`00 Inbox/` and a few notes), and `scripts/run_demo.sh` sets `VAULT_DIR` to it.

## Feature 2: Coding agents by voice

### Tools

| Tool | Does | Gate |
|---|---|---|
| `dev_task_start(project, instruction)` | Resolves `project` to a git repo under `DEV_ROOTS` (via `Projects.md` rows first, then folder names under `DEV_ROOTS/*/*`). Refuses non-git folders, and refuses when the cap of running agents is already hit. On confirm, it creates the worktree and starts the agent in the background, then returns at once with the task id and branch. | **always confirms**: "Start a coding agent in *jarvis* on branch *jarvis/dark-mode-a1b2* to: …?" |
| `dev_task_status(task_id=None)` | Status of one task (the latest if no id is given): state, elapsed time, last step, and once finished the summary, diffstat and branch. | none |
| `dev_task_list()` | Today's and running tasks. | none |
| `dev_task_cancel(task_id)` | Interrupts a running agent. The worktree and branch are kept. | confirms |
| `dev_task_cleanup(task_id)` | For a finished task: removes its worktree (`git worktree remove`). The branch is kept so the work is never lost. Refuses running tasks. | confirms (it deletes a folder) |

Project lookup skips `DEV_ROOTS/.jarvis-worktrees`.

### How a task runs (new module `jarvis/devtasks.py`)

1. Branch `jarvis/<slug>-<4 hex>` from the repo's current `HEAD`. Worktree
   at `DEV_ROOTS/.jarvis-worktrees/<project>-<id>`. The checked-out branch
   of the main repo is never touched.
2. A daemon thread runs `claude_agent_sdk.query()` with:
   - `cwd` = the worktree, `permission_mode="acceptEdits"`
   - `setting_sources=["project"]`: it loads the repo's `CLAUDE.md` and
     `.claude/` settings but not `~/.claude` hooks, plugins or user settings
     (Yogesh's choice)
   - network allowed: it can install dependencies inside the worktree
     (`npm`/`pnpm install`, `pip`/`uv` into a worktree-local `.venv`) and
     run tests. Global installs (`npm -g`, `brew`, `pip` outside a venv)
     are denied
   - allowed tools: Read, Edit, Write, Glob, Grep, Bash
   - a `can_use_tool` guard that denies: file paths that resolve outside the
     worktree; Bash commands containing `git push`, `git remote`,
     `git checkout`/`switch` to other branches, `git worktree`, `ssh`,
     `scp`, `rsync`, `sudo`, `rm -rf /`/`~`, or `curl … | sh`-style pipes;
     and any read of `.env`, `*.pem`, `id_*`, `credentials.json`, `~/.secrets`
   - `max_turns` = `DEV_AGENT_MAX_TURNS` (40), a wall-clock timeout of
     `DEV_AGENT_TIMEOUT_MIN` (20), model `DEV_AGENT_MODEL` (default `sonnet`)
   - a system prompt addition: "You're working in a throwaway worktree on
     branch X. Make the change, run the project's tests if there are any,
     commit on this branch with a clear message, and end with a 2–3
     sentence summary. Never push."
3. Progress: each assistant tool call updates `last_step` (e.g. "Edit
   frontend/src/App.tsx") and sends a `devtask` HUD event.
4. On finish: collect `git diff --stat <base>...<branch>` and the commit
   list. Store the summary and cost. Then `hub.announce("devtask", "<project>
   agent finished: <summary>. N files changed on branch X.", speak=nearby)`
   plus a HUD card.
5. Errors and timeouts get state `failed` with the reason, and are announced
   the same way.
6. At most `DEV_AGENT_MAX_RUNNING` (2) at once.

State lives in a `dev_tasks` table in `jarvis.db`: id, project, repo_path,
instruction, branch, base_sha, worktree, state
(running/done/failed/cancelled), started_at, finished_at, last_step,
summary, diffstat, cost_usd. When Jarvis restarts, tasks still marked
`running` are switched to `failed` ("Jarvis restarted").

### HUD

A small **Agents** panel (collapsible like Agenda/Tasks) lists running and
today's tasks with project, live last step, elapsed time and state. Finished
ones show the diffstat and branch. It's fed by `devtask` events plus a
snapshot in the initial state payload. The demo mode in `frontend/src/lib/demo.ts`
gets a scripted fake task.

### Security

This runs model-written code on the mini with Yogesh's user rights. The
controls: always-confirm, worktree isolation, path/command guard, no push,
caps on turns, time and how many run at once. The command guard is
best-effort (a determined agent can get around string matching), so the
confirmation and worktree are the main boundary. ARCHITECTURE.md gets a
section saying this plainly.

### Demo profile

`run_demo.sh` sets `DEV_ROOTS=~/Documents/jarvis-demo/dev`, and
`seed_demo.py` creates a tiny git repo there (for example a todo web page)
that the agent can safely change on stage.

## Feature 3: Evening wrap

### Trigger

- Setting `wrap` (Settings panel + `assistant_set_preference`): `"off"` or
  a time like `"20:00"`. **Default `"off"`**, so nothing surprises
  anyone. The demo profile sets it in its own settings.
- It fires once per day: after the set time, before midnight, when Yogesh is
  present (`idle < PRESENT_IDLE`) and Jarvis is free. This mirrors
  `briefing_due` and is stored in `proactive.json` as `"wrap": "<date>"`.
- On demand: "wrap up my day" / "how did today go" calls `wrap_get`
  (system prompt guidance).

### `wrap_get()` returns (each section skipped if empty or failing)

- Tasks completed today, and open tasks due tomorrow or overdue. The `tasks`
  table has no completion time yet, so a `done_at` column is added with a
  migration, set by `task_complete`. Older completed tasks have no
  `done_at` and are ignored.
- Today's commits across git repos in `Projects.md` (`git log --since=midnight
  --author=<git user.email>`), grouped by project, max 5 per project.
- Coding agent tasks finished today (from `dev_tasks`).
- Tomorrow's calendar events.
- Possible replies: up to 8 from `is:unread newer_than:1d -category:promotions
  -category:social -category:updates` (sender, subject, snippet, id). The
  model picks the ones that look like they need a reply.

### Proactive prompt

"(Automatic evening wrap: call wrap_get, then give a ~30 second spoken
rundown: what got done, what's tomorrow, and up to 3 emails that look like
they need a reply. Show it as a HUD card. Then call vault_note(section='Wrap')
with a short summary for today. Offer to draft replies; don't draft unasked.)"
Writing to the vault is controlled by the `wrap_to_vault` setting (default
on). Sending still goes through the existing gate.

---

## Testing

- Unit tests in the style of `tests/smoke_test.py`, all offline, using a
  temp vault, temp git repos and a fake `claude_agent_sdk.query`:
  - vault: search ranking, excluded folders blocked, path traversal and
    symlink escape blocked, daily note creation from the template, append
    under the heading, inbox name clashes.
  - projects_status: table parsing, non-git rows, fuzzy match.
  - devtasks: `dev_task_start` blocked without confirmation (including a
    smuggled `_confirmed`), the worktree/branch is created and the main
    checkout is unchanged, the guard denies an out-of-tree write and
    `git push`, restart marks running tasks as failed, the cap is enforced.
  - wrap: `wrap_due` timing rules, and `wrap_get` sections with fakes.
- Manual: run the demo profile end to end (projects → agent task → wrap)
  in the desktop app.

## Build order

1. Brain link (with demo vault) → commit.
2. Coding agents (backend, then HUD panel, then demo repo) → commit.
3. Evening wrap → commit.
4. README/ARCHITECTURE/.env.example updates go with each feature.

## Calls made without Yogesh (check these)

- The wrap goes in its own `## Wrap HH:MM` block that's added each run, never replaced.
- `dev_task_cleanup` removes the worktree only and keeps the branch, behind confirmation.
- A `done_at` column is added to tasks.
- `wrap` defaults to off. `wrap_to_vault` defaults to on.
- At most 2 agents run at once, with 40 turns and 20 minutes each, on Sonnet.

## Left to the builder

Exact snippet formatting, how fuzzy project matching works, the HUD panel's
visual details (match the existing panels), log wording, and how to split
`devtasks.py` vs a `tools/dev.py` wrapper.
