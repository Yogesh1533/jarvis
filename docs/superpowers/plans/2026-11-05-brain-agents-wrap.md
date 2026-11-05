# Brain link, coding agents, evening wrap: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis can read and add to the Obsidian vault, report on project status, start background coding agents in Yogesh's repos by voice, and give a daily evening wrap that gets written into the vault.

**Architecture:** There are three new tool modules (`tools/vault.py`, `tools/projects.py`, `tools/dev.py`) plus `tools/wrap.py`. Each is registered in the existing `TOOL_SCHEMAS`/`_handlers()` registry and goes through the existing confirmation gate. Coding agents run `claude_agent_sdk.query()` on daemon threads inside git worktrees. They report back through a new `hud_bridge.announce()` hook and a `devtask` HUD event. The wrap is a new trigger in `Proactive.tick()`.

**Tech Stack:** Python 3.12 (`.venv`), FastAPI, `claude-agent-sdk`, git CLI, SQLite; React + TypeScript + Vite HUD.

**Spec:** `docs/superpowers/specs/2026-11-05-brain-agents-wrap-design.md`. Read it alongside this plan.

## Global Constraints

- Tests follow the repo's script style: `tests/<name>_test.py`, using the same `check(name, cond)` helper as `tests/smoke_test.py`. Each test sandboxes `config.DB_PATH`/dirs into `tempfile.mkdtemp()` before importing tools, runs with `.venv/bin/python tests/<name>_test.py`, and ends by printing `ALL N CHECKS PASSED`. There's no pytest and no network.
- `tests/smoke_test.py` must still pass after every task.
- Dangerous handlers take `_confirmed=False` and raise `tools.ConfirmationRequired(prompt)`. Never trust a model-supplied `_confirmed`.
- New config lives in `jarvis/config.py` and gets documented in `.env.example`:
  - `VAULT_DIR` (default `~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian/Brain`)
  - `VAULT_EXCLUDE` (default `.obsidian,.trash,Templates,People,Life`)
  - `DEV_ROOTS` (default `~/Developer`)
  - `DEV_AGENT_MODEL` (default `sonnet`), `DEV_AGENT_MAX_TURNS` (40), `DEV_AGENT_TIMEOUT_MIN` (20), `DEV_AGENT_MAX_RUNNING` (2)
- Vault writes only append or create. No vault function ever truncates, replaces or deletes an existing file.
- Agents never push and never touch the main checkout's branch. Worktrees live under `<first DEV_ROOT>/.jarvis-worktrees/<project>-<id>`, on branch `jarvis/<slug>-<4 hex>`.
- Agent SDK options: `setting_sources=["project"]`, `permission_mode="acceptEdits"`, allowed tools `Read, Edit, Write, Glob, Grep, Bash`.
- New settings: `wrap` defaults to `"off"`, `wrap_to_vault` defaults to `True`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never open `.env`, `credentials.json`, `data/google_token.json`.

## Review Focus

1. **iCloud evicted (dataless) notes:** reading a vault note that isn't downloaded yet must not hang search for minutes. `vault_search` skips files it can't open within the read, using a size/`OSError` guard, and keeps going. Test in Task 1.
2. **Unicode and spaces in vault paths** (`00 Inbox`, `Digipearl/Café.md`): read and note must round-trip them. Test in Task 1.
3. **Proactive state clobbering:** `_briefing` currently overwrites `proactive.json` with only `{"briefing": ...}`, which would wipe the wrap date and replay the wrap. State writes must merge. Test in Task 9.
4. **A dirty or detached main repo** when an agent starts: creating the worktree must not change the main checkout's files or branch. Test in Task 5.
5. **An agent that hangs or crashes mid-run:** the task must end in `failed` with a reason and get announced, never stay stuck in `running`. Test in Task 6.

---

### Task 1: Vault core (search, read, note)

**Files:**
- Modify: `jarvis/config.py` (add the `VAULT_DIR`, `VAULT_EXCLUDE` and `DEV_ROOTS` parsing helpers next to `FILES_ROOTS`)
- Create: `jarvis/tools/vault.py`
- Modify: `.env.example`
- Test: `tests/vault_test.py`

**Interfaces:**
- Produces:
  - `vault.safe_path(rel: str) -> Path`: resolves symlinks. Raises `ValueError` if the path is outside `VAULT_DIR`, inside an excluded folder, or not `.md`.
  - `vault.is_excluded(p: Path) -> bool`: True if `p` sits under `VAULT_DIR` and its first relative part is in `VAULT_EXCLUDE`.
  - `vault.search(query: str, max_results: int = 8) -> str`
  - `vault.read(path: str) -> str`
  - `vault.note(text: str, where: str = "daily", title: str | None = None, section: str | None = None, _now: datetime | None = None) -> str`. Returns `"Added to Daily/2026-11-05.md"` or `"Created 00 Inbox/<file>"`. `_now` is for tests only (stripped from model input anyway).

- [ ] **Step 1: Write the failing tests** in `tests/vault_test.py`. Build a temp vault with `Daily/`, `Templates/Daily.md` (the real template text: frontmatter `created: {{date}}`, `# {{date}}`, `## Notes / brain dump` last), `People/secret.md`, `Projects.md`, `Digipearl/Café brief.md` ("logo due Friday") and `00 Inbox/`. Then set `config.VAULT_DIR` and `config.VAULT_EXCLUDE = [".obsidian", ".trash", "Templates", "People", "Life"]`. Checks:
  - `"Café brief" in vault.search("logo")`
  - a title hit ranks first: search `"projects"` → the first result line contains `Projects.md`
  - the whole phrase misses but the words hit: `vault.search("friday logo")` finds the Café note
  - `"secret" not in vault.search("secret")` and `vault.read("People/secret.md")` raises `ValueError`
  - `vault.read("../outside.md")` and a symlink `Daily/link.md → /tmp/x.md` both raise `ValueError`
  - `vault.read("Digipearl/Café brief.md")` contains `"logo due Friday"`
  - `note("call Sam", _now=datetime(2026,11,5,9,30))` creates `Daily/2026-11-05.md` with `created: 2026-11-05`, and `- 09:30 call Sam` sits after `## Notes / brain dump`
  - a second `note("buy cable", ...)` adds to the end of that section and the earlier content is byte-for-byte kept as a prefix
  - `note("line1\nline2", section="Wrap", _now=...20:00)` adds `## Wrap 20:00\nline1\nline2` at the end, and calling it twice gives two `## Wrap` blocks
  - `note("idea", where="inbox", title="New idea", _now=...)` twice creates `00 Inbox/2026-11-05_new-idea.md` and `..._new-idea-2.md`, each with `type: note` frontmatter
  - a file that raises `OSError` on open (monkeypatch `Path.read_text` for one path) is skipped by search, which still returns other hits

- [ ] **Step 2: Run** `.venv/bin/python tests/vault_test.py`. Expected: fails with `ImportError: cannot import name 'vault'`.

- [ ] **Step 3: Implement `jarvis/tools/vault.py` and the config entries.**
  - Search walks `VAULT_DIR.rglob("*.md")`, skipping excluded folders. For snippets it reads only the first ~200 KB and catches `OSError`/`UnicodeDecodeError`.
  - Ranking: filename hits, then body hits on the whole phrase, then all-words hits. It returns one line per hit, `path — title — snippet` (~120 chars around the first match).
  - `read` cuts the text at 8000 chars and adds `"\n…(cut, note is N chars)"`.
  - For `note`, the template comes from `VAULT_DIR/Templates/Daily.md`, read directly (not through `safe_path`), with `{{date}}` → ISO date. If there's no template it falls back to `# <date>\n\n## Notes / brain dump\n`.
  - Inserting a bullet under the heading means writing the whole file back as `head + inserted + tail`. That's an append into the section, not a replacement, and the test pins that existing text is kept.
  - The slug is lowercase, with `[^a-z0-9]+` → `-`, max 40 chars.

- [ ] **Step 4: Run** `.venv/bin/python tests/vault_test.py` → `ALL … CHECKS PASSED`. Then run `.venv/bin/python tests/smoke_test.py` → passes.

- [ ] **Step 5: Commit** `feat(vault): search, read and append-only notes for the Brain vault`

### Task 2: Projects status

**Files:**
- Create: `jarvis/tools/projects.py`
- Test: `tests/projects_test.py`

**Interfaces:**
- Consumes: `config.VAULT_DIR`, `config.DEV_ROOTS`
- Produces:
  - `projects.rows() -> list[dict]`. Keys: `name, what, path (Path|None), github`. It parses every markdown table in `Projects.md` whose header row has `Project` and a column starting with `Path`. Backticks are stripped and `~` is expanded.
  - `projects.find(name: str) -> dict | None`. Match order: case-insensitive exact, then prefix, then `difflib.get_close_matches(cutoff=0.6)` on names.
  - `projects.git_info(path: Path) -> dict | None`. Keys: `branch, last_commit_rel, last_subject, dirty (int), agent_branches (int)`. Returns None if the folder isn't a git repo. It uses `git -C` with read-only commands only (`rev-parse`, `log -1 --format=%cr%x1f%s`, `status --porcelain`, `branch --list 'jarvis/*'`) and a 5 s timeout each.
  - `projects.status(project: str | None = None) -> str`

- [ ] **Step 1: Write failing tests.** Use a temp vault whose `Projects.md` copies the real two-table layout (Apps and Agents tables, plus a "Client work" bullet list that should be ignored). The rows point at:
  - a temp git repo `alpha` with one commit "init" and one untracked file
  - a non-git folder `beta`
  - a path that doesn't exist (`gamma`)

  Checks:
  - `len(projects.rows()) == 3`
  - `projects.find("ALP")["name"] == "alpha"` and `projects.find("alpah")["name"] == "alpha"`
  - `projects.find("zzz") is None`
  - `git_info(alpha)["dirty"] == 1`, its `last_subject == "init"`, and `git_info(beta) is None`
  - `status()` mentions `alpha`, `"no git"` for beta and `"missing"` for gamma
  - `status("alpha")` doesn't mention beta

- [ ] **Step 2: Run** → fails with ImportError.
- [ ] **Step 3: Implement** per the interfaces. The status line format is `alpha (branch main): last commit 2 minutes ago "init", 1 uncommitted file`.
- [ ] **Step 4: Run** the projects and smoke tests → pass.
- [ ] **Step 5: Commit** `feat(projects): project status from Projects.md with read-only git info`

### Task 3: Register the vault and project tools, prompt, and files exclusion

**Files:**
- Modify: `jarvis/tools/__init__.py`. Add 4 schemas after the `files_*` block, plus handlers: `vault_search → vault.search`, `vault_read → vault.read`, `vault_note → vault.note`, `projects_status → projects.status`. The `vault_note` schema exposes `text`, `where` (enum `daily|inbox`), `title` and `section` but never `_now`.
- Modify: `jarvis/tools/files.py`. `search`/`read`/`open_file` skip or refuse paths where `vault.is_excluded(p)`.
- Modify: `config/jarvis-voice-assistant-system-prompt.md`. Under "## Your abilities", add one bullet:
  > Notes and projects: for "my notes / my vault / my brain / what did I write about…" use `vault_search` then `vault_read`; to jot something down use `vault_note` (today's daily note unless they say inbox). For "my projects" / "what's X up to" use `projects_status`.
- Modify: `frontend/src/lib/format.ts` (tool labels: "Searching your vault", "Reading a note", "Adding to your vault", "Checking your projects")
- Test: extend `tests/vault_test.py`

- [ ] **Step 1: Add failing checks:**
  - `tools.execute("vault_note", {"text": "x", "_now": "2020-01-01"}, confirm)` doesn't raise, and the file it writes is today's date, not 2020 (proves `_now` is stripped)
  - `"vault_search" in [s["name"] for s in tools.TOOL_SCHEMAS]`
  - `files.read(<temp vault>/People/secret.md)` returns an error/refusal string, or raises

- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement** the edits above.
- [ ] **Step 4: Run** the vault, projects and smoke tests → pass. Then `cd frontend && npx tsc --noEmit` → no errors.
- [ ] **Step 5: Commit** `feat(vault): expose vault and project tools to Jarvis`

### Task 4: Demo vault

**Files:**
- Modify: `scripts/seed_demo.py`. Add `seed_vault(now, dry)`, called from `main()` after `seed_files`.
- Modify: `scripts/run_demo.sh`. Add `VAULT_DIR="$HOME/Documents/jarvis-demo/vault"`.

**Interfaces:**
- Produces: a demo vault at `~/Documents/jarvis-demo/vault`, which Task 8 adds a dev repo next to.

- [ ] **Step 1: Implement `seed_vault`.** It writes `Projects.md` with one Apps table of 3 fictional rows, one of which points at `~/Documents/jarvis-demo/dev/todo-app` (created in Task 8). It also writes `Templates/Daily.md` (copied from the real template text, which has no personal content), a `Daily/<yesterday>.md` with fictional content, two `00 Inbox` notes and a `Clients/Northwind.md` note.
  - It writes only under the demo folder. On reruns it overwrites only files it created.
  - Fictional people only, so the demo never shows a real name.
- [ ] **Step 2: Verify:** `.venv/bin/python scripts/seed_demo.py --dry-run` lists the vault files and writes nothing (check that `ls ~/Documents/jarvis-demo/vault` is unchanged).
- [ ] **Step 3: Commit** `feat(demo): fictional Brain vault for the demo profile`

### Task 5: Dev tasks core (resolve, worktree, guard, state)

**Files:**
- Create: `jarvis/tools/dev.py`
- Modify: `jarvis/tools/db.py` (add the `dev_tasks` table to `_SCHEMA`, with columns exactly as in the spec)
- Modify: `jarvis/hud_bridge.py` (add `attach_announcer(fn)` and `announce(kind, text, speak=True) -> bool`, which falls back to `send({"type": "notify", ...})` when no announcer is attached)
- Test: `tests/dev_test.py`

**Interfaces:**
- Consumes: `projects.find(name)`, `config.DEV_ROOTS`
- Produces:
  - `dev.resolve_repo(project: str) -> Path`. Tries `projects.find` first, then folder names matching `DEV_ROOTS/*/*`, skipping `.jarvis-worktrees`. Raises `ValueError("… isn't a git repo")` or `ValueError("No project called …")`.
  - `dev.guard(tool_name: str, tool_input: dict, worktree: Path) -> str | None`. Returns the reason to deny, or None to allow.
  - `dev.RUNNER`: a module-level callable `(task: dict, on_step: Callable[[str], None], should_stop: Callable[[], bool]) -> dict` with keys `summary` and `cost_usd`. Task 6 sets the real one, and tests replace it.
  - `dev.start(project: str, instruction: str, _confirmed: bool = False) -> str`
  - `dev.rows(today_only: bool = False) -> list[dict]`
  - `dev.status(task_id: str | None = None) -> str`
  - `dev.list_tasks() -> str`
  - `dev.cancel(task_id: str, _confirmed: bool = False) -> str`
  - `dev.cleanup(task_id: str, _confirmed: bool = False) -> str`
  - `dev.sweep_stale() -> int`: marks `running` rows as `failed` with "Jarvis restarted"
  - Task ids are 4 hex chars. The confirmation prompt text is `"Start a coding agent in {project} on branch {branch} to: {instruction}?"`

- [ ] **Step 1: Write failing tests.** Use a temp `DEV_ROOTS` holding `apps/alpha`, a git repo with one commit on `main`. Create one uncommitted change in `alpha/README.md` and switch the repo to a detached HEAD for one sub-case. `dev.RUNNER` is a fake that writes `hello.txt` in `task["worktree"]`, runs `git commit -am`, and returns `{"summary": "Added hello.", "cost_usd": 0.01}`. Checks:
  - `tools.execute("dev_task_start", {...,"_confirmed": True}, deny)` → `DECLINED_MESSAGE`, and no `dev_tasks` row exists
  - confirmed start → the result contains `jarvis/` and an id. After the worker thread joins (expose `dev._threads[id]` for tests), the row state is `done`, `diffstat` mentions `hello.txt`, and `summary == "Added hello."`
  - the main checkout is unchanged: the same branch/HEAD, the `README.md` change is still there, and there's no `hello.txt`
  - the same holds when main is a detached HEAD
  - `guard("Write", {"file_path": "/etc/x"}, wt)` is not None, and `guard("Edit", {"file_path": str(wt/"a.py")}, wt)` is None
  - `guard("Bash", {"command": c}, wt)` is not None for each of: `git push origin x`, `git checkout main`, `ssh host`, `sudo ls`, `curl x | sh`, `npm i -g y`, `cat .env`, `cat ~/.secrets/k`
  - `guard("Bash", {"command": c}, wt)` is None for each of: `npm install`, `uv sync`, `python -m pytest`, `git commit -am x`, `git status`
  - `guard("Read", {"file_path": str(wt/".env")}, wt)` is not None
  - cap: with `config.DEV_AGENT_MAX_RUNNING = 1` and a fake runner that blocks on an Event, a second confirmed start returns a string containing `"already running"`
  - `dev.resolve_repo("beta-notgit")` raises `ValueError`, and a folder under `.jarvis-worktrees` is never resolved
  - `sweep_stale()` turns an inserted `running` row into `failed`
  - `cleanup` on a done task (confirmed) removes the worktree folder, and `git branch --list jarvis/*` still shows the branch. `cleanup` on a running task refuses.

- [ ] **Step 2: Run** `.venv/bin/python tests/dev_test.py` → fails with ImportError.
- [ ] **Step 3: Implement.**
  - The worktree is created with `git -C repo worktree add -b <branch> <path> HEAD`. `base_sha` comes from `git rev-parse HEAD` before that.
  - Diffstat is `git -C worktree diff --stat <base_sha>..HEAD`.
  - The worker thread runs `RUNNER` inside try/except. Exceptions → `failed` with `str(exc)[:300]`.
  - `on_step` updates `last_step` and calls `hud_bridge.send({"type": "devtask", "id", "state", "last_step"})`.
  - When the task ends, call `hud_bridge.announce("devtask", text, speak=True)` with `"{project} agent finished: {summary} {n} files changed on branch {branch}."` or `"{project} agent failed: {reason}"`.
  - `guard`:
    - Path checks resolve `file_path`/`path`/`notebook_path` and require them to be inside the worktree.
    - Secret names are `.env*`, `*.pem`, `id_*`, `credentials.json` and anything under `~/.secrets`.
    - Bash checks are regexes on the command: `\bgit\s+(push|remote|worktree)\b`, `\bgit\s+(checkout|switch)\b(?!\s+-b)` (creating a branch is fine), `\b(ssh|scp|rsync|sudo|brew)\b`, `\|\s*(ba|z)?sh\b`, `\bnpm\s+(i|install)\s+(-g|--global)\b`, `\bpip3?\s+install\b` without an active venv (deny when the command doesn't start with `uv`, `.venv/bin/` or `python -m venv`), `rm\s+-rf\s+(/|~)`, plus the secret names above appearing anywhere in the command.
- [ ] **Step 4: Run** the dev and smoke tests → pass.
- [ ] **Step 5: Commit** `feat(dev): coding-agent tasks in git worktrees with a guard and confirmation`

### Task 6: Real SDK runner, tool registration, wiring

**Files:**
- Modify: `jarvis/tools/dev.py` (add `sdk_runner`, which becomes the default `RUNNER`)
- Modify: `jarvis/tools/__init__.py` (5 schemas: `dev_task_start`, `dev_task_status`, `dev_task_list`, `dev_task_cancel`, `dev_task_cleanup`, with handlers mapped to the `dev.*` functions from Task 5)
- Modify: `jarvis/web.py` (call `hud_bridge.attach_announcer(hub.announce)` right after `hud_bridge.attach(hub.to_hud)` at line ~1046, call `dev.sweep_stale()` at startup, add `GET /api/devtasks` → `_safe(lambda: dev.rows(today_only=True))`)
- Modify: `config/jarvis-voice-assistant-system-prompt.md`. Add this bullet:
  > Coding work: "in <project>, <do something>" / "get an agent to…": call `dev_task_start` straight away (the on-screen Approve decides). Say one line, e.g. "On it, I'll tell you when it's done." "How's the agent doing?" → `dev_task_status`. Never claim the work is merged or pushed; it sits on its branch for Yogesh to review.
- Modify: `ARCHITECTURE.md`. Add a section "Coding agents (`tools/dev.py`)" covering the flow, the guard, and the plain warning that the guard is best-effort while the confirmation and worktree are the main boundary.
- Modify: `README.md` (short "What else" bullets for the vault and coding agents), `.env.example` (`DEV_*` variables)
- Test: extend `tests/dev_test.py`

**Interfaces:**
- Consumes: everything from Task 5
- Produces: `sdk_runner(task, on_step, should_stop) -> {"summary": str, "cost_usd": float}`

- [ ] **Step 1: Add failing checks.** Monkeypatch a fake `claude_agent_sdk` module into `sys.modules`. Its `query()` async-yields one `AssistantMessage` with a `ToolUseBlock(name="Edit", input={"file_path": ...})`, then a `ResultMessage(result="Did it.", total_cost_usd=0.02)`. Checks:
  - with `dev.RUNNER = dev.sdk_runner`, the task ends `done` with `summary == "Did it."` and `last_step` starting `"Edit"`
  - the fake records the options it got: `cwd == worktree`, `setting_sources == ["project"]`, `permission_mode == "acceptEdits"`, `max_turns == 40`, `can_use_tool` is set, and the system prompt contains `"Never push"`
  - a fake `query` that sleeps past a timeout of 0.01 min (`config.DEV_AGENT_TIMEOUT_MIN = 0.01`) → state `failed`, the reason contains `"timed out"`, and the announcer was called once with `"failed"` in the text (Review Focus 5)
  - a fake `query` that raises `RuntimeError("boom")` → `failed`, the reason contains `boom`, and the announcer was called
  - `dev_task_status` without an id returns the latest task's state

- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement `sdk_runner`.**
  - It runs `asyncio.run` of an inner coroutine wrapped in `asyncio.wait_for(timeout=DEV_AGENT_TIMEOUT_MIN*60)`.
  - Options: `ClaudeAgentOptions(cwd, model=DEV_AGENT_MODEL, max_turns=DEV_AGENT_MAX_TURNS, permission_mode="acceptEdits", allowed_tools=[...], setting_sources=["project"], system_prompt={"type": "preset", "preset": "claude_code", "append": <the spec's instruction text with the branch filled in>}, can_use_tool=<async wrapper over guard returning PermissionResultAllow/PermissionResultDeny>)`.
  - `can_use_tool` needs streaming input, so the prompt goes in as an async iterator of one user message.
  - It checks `should_stop()` between messages and raises `CancelledError` → state `cancelled`.
- [ ] **Step 4: Run** the dev and smoke tests → pass. Then do one manual smoke test against a scratch repo: `.venv/bin/python -c "from jarvis.tools import dev; ..."` with `DEV_ROOTS` pointed at the scratch folder and the instruction "add a line to README". Expected: the branch exists with one commit, and the main checkout is untouched.
- [ ] **Step 5: Commit** `feat(dev): run coding agents on the Claude Agent SDK and announce results`

### Task 7: HUD Agents panel

**Files:**
- Modify: `frontend/src/lib/store.ts` (add `"agents"` to the `Panel` union and to `refresh`)
- Modify: `frontend/src/lib/api.ts` (`panelsForTool`: `dev_task_*` → `["agents"]`)
- Modify: `frontend/src/App.tsx`
  - add `case "devtask": s.bump("agents"); break;`
  - render `<AgentsPanel />` after `<TasksPanel />`
- Modify: `frontend/src/components/Panels.tsx`. Add `AgentsPanel`, which uses `usePanelData<DevTask[]>("/api/devtasks", "agents")` and `<Panel title="Agents" meta={running ? `${running} running` : undefined} fold="open">`. Each row shows project, instruction (1 line), state badge, `last_step`, elapsed time (ticking every 1 s while running), and the `diffstat` + `branch` once done. If there are no tasks it shows `<Empty>` with "Say “in jarvis, add …” to start one".
- Modify: `frontend/src/lib/demo.ts`. The scripted demo adds a fake `devtask` sequence (running → 3 steps → done) driven through the store, with no backend.

- [ ] **Step 1: Implement** the edits above, matching the styling of the existing panels.
- [ ] **Step 2: Verify:** `cd frontend && npx tsc --noEmit && npm run build` → succeeds. Start `.venv/bin/python run_web.py`. Check that `curl -s localhost:<port>/api/devtasks` returns a JSON list. Open the HUD in the browser pane, start demo mode from the palette, and screenshot the Agents panel going running → done.
- [ ] **Step 3: Commit** `feat(hud): Agents panel with live coding-agent progress`

### Task 8: Demo dev repo

**Files:**
- Modify: `scripts/seed_demo.py`. Add `seed_dev(now, dry)`: it creates `~/Documents/jarvis-demo/dev/todo-app` (a tiny `index.html` + `app.js` todo page and a `README.md`), runs `git init`, and makes one commit. If the folder already exists as a repo it's left alone.
- Modify: `scripts/run_demo.sh`. Add `DEV_ROOTS="$HOME/Documents/jarvis-demo/dev"`.

- [ ] **Step 1: Implement.** Because `resolve_repo` globs `DEV_ROOTS/*/*`, the demo layout needs one level of grouping folder, so the path is `dev/apps/todo-app`. Update the Task 4 `Projects.md` row to that path.
- [ ] **Step 2: Verify:** run `seed_demo.py --dry-run`, then (writing) check that `git -C ~/Documents/jarvis-demo/dev/apps/todo-app log --oneline` shows 1 commit.
- [ ] **Step 3: Commit** `feat(demo): safe demo repo for coding agents`

### Task 9: Tasks `done_at`, `wrap_get`, and merged proactive state

**Files:**
- Modify: `jarvis/tools/db.py`. In `connect()`, after `executescript`, add the `done_at TEXT` column if `PRAGMA table_info(tasks)` lacks it.
- Modify: `jarvis/tools/tasks.py`. `complete` sets `done_at = datetime('now','localtime')`.
- Create: `jarvis/tools/wrap.py`
- Modify: `jarvis/proactive.py`. Replace the direct `write_text` in `_briefing` with `_save_state(key, value)` (read-merge-write) and `_load_state(key)`. `_last_briefing` uses `_load_state("briefing")`.
- Test: `tests/wrap_test.py`

**Interfaces:**
- Consumes: `projects.rows()`, `dev.rows(today_only=True)`, `gcal.list_events`, `gmail.search`, `tasks.rows`
- Produces:
  - `wrap.get() -> str`. Sections in the order the spec gives: "Done today", "Due tomorrow or overdue", "Commits today", "Coding agents", "Tomorrow", "Might need a reply". Each section is built inside its own try/except and skipped when empty or failing, using the `_section` pattern from `briefing.py`.
  - The commits query is `git -C <repo> log --since=midnight --author=<git config user.email> --format=%s`, max 5 per project.
  - The reply-candidates query is the spec's exact Gmail query, `max_results=8`.
  - `Proactive._save_state(key: str, value) -> None` and `Proactive._load_state(key: str) -> Any`

- [ ] **Step 1: Write failing tests.**
  - Completing a task sets `done_at`. A db created with the old schema (create the table without `done_at` first) migrates when it's opened.
  - With gcal/gmail/projects monkeypatched to fakes and one git repo committed today by the configured email: `wrap.get()` contains "Done today", the task title, the commit subject and the email subject.
  - With gmail raising: the output still has the other sections and no traceback text.
  - Proactive state: `_save_state("wrap", "2026-11-05")`, then `_save_state("briefing", "2026-11-05")` → `_load_state("wrap") == "2026-11-05"` (Review Focus 3).
- [ ] **Step 2: Run** `.venv/bin/python tests/wrap_test.py` → fails.
- [ ] **Step 3: Implement** per the interfaces.
- [ ] **Step 4: Run** the wrap and smoke tests → pass.
- [ ] **Step 5: Commit** `feat(wrap): evening wrap data and task completion times`

### Task 10: Wrap trigger, setting and prompts

**Files:**
- Modify: `jarvis/settings.py`
  - `DEFAULTS`: `"wrap": "off"`, `"wrap_to_vault": True`
  - in `update()`, validate `wrap` with the same clock rule as `briefing` (pull out a `_clock(key, value)` helper used by both, with the error `"wrap must be 'off' or a time like 20:00"`)
- Modify: `jarvis/tools/persona.py` (preference labels: `"wrap": "when your evening wrap starts"`, `"wrap_to_vault": "writing the evening wrap into your daily note"`)
- Modify: `jarvis/proactive.py`
  - add `wrap_due(now, setting, last_date, idle) -> bool`: true when `setting != "off"`, `now.time() >= setting`, `last_date != today`, idle is not None and `idle < PRESENT_IDLE`. Mirrors `briefing_due` but has no noon cutoff, because midnight ends the day naturally.
  - add `WRAP_PROMPT`: the spec's prompt text, plus the sentence "Skip the vault_note step." when `wrap_to_vault` is off
  - add a `_wrap(setting)` method called from `tick()`. It calls `hub.brief(prompt, label="Your evening wrap")` and on success `_save_state("wrap", today)`
- Modify: `jarvis/tools/__init__.py` (the `wrap_get` schema + handler)
- Modify: `config/jarvis-voice-assistant-system-prompt.md`. Add this bullet:
  > "Wrap up my day" / "how did today go": call `wrap_get` once, give a ~30 second rundown (done, tomorrow, up to 3 emails that may need a reply), show a `hud_show_card`, then `vault_note` with `section="Wrap"` unless the wrap_to_vault preference is off. Offer to draft replies; don't draft unasked.
- Modify: the frontend settings UI (`frontend/src/components/Extras.tsx`/`Chrome.tsx`, wherever the `briefing` control lives). Add an "Evening wrap" time-or-off control and a "Write wrap to vault" toggle next to it, plus their labels in `frontend/src/lib/format.ts`.
- Modify: `scripts/seed_demo.py`/`run_demo.sh` so the demo profile's settings file sets `wrap` to `"off"`. Demos trigger the wrap by voice, so it never fires mid-recording.
- Test: extend `tests/wrap_test.py`

- [ ] **Step 1: Add failing checks:**
  - `wrap_due(20:05, "20:00", None, 10)` is True
  - `wrap_due(19:59, "20:00", None, 10)` is False
  - `wrap_due(20:05, "20:00", today, 10)` is False
  - `wrap_due(20:05, "off", None, 10)` is False
  - `wrap_due(20:05, "20:00", None, 300)` is False
  - `settings.update(wrap="8:30")["wrap"] == "08:30"`, and `settings.update(wrap="25:00")` raises `ValueError`
  - a fake hub whose `brief` returns True, with `wrap="00:00"` and `wrap_to_vault=False`: one `tick()` calls `brief` once, and the prompt contains `wrap_get` and "Skip the vault_note step". A second `tick()` doesn't call it again.
- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** all four new tests and the smoke test → pass. Then `cd frontend && npx tsc --noEmit` → clean.
- [ ] **Step 5: Manual end-to-end on the demo profile.** Run `scripts/seed_demo.py`, then `scripts/run_demo.sh`. In the HUD, type or say these in order:
  1. "what are my projects up to?" → projects card or answer
  2. "in todo-app, add a clear-completed button" → Approve → the Agents panel shows progress → spoken "finished"
  3. "wrap up my day" → the rundown mentions the agent's work and a `## Wrap` block appears in `~/Documents/jarvis-demo/vault/Daily/<today>.md`

  Then update the README (feature bullets + the `wrap` setting) and `.env.example` if still missing.
- [ ] **Step 6: Commit** `feat(wrap): scheduled and on-demand evening wrap written to the vault`
