"""Tool-calling eval on Nebius: does each Nemotron pick the right tool for
everyday voice requests, how fast, and how does per-request routing
compare with using one model for everything?

Tools are stubbed: every call is recorded and answered with a canned
result, so nothing is sent, played, deleted or changed. Each case starts a
fresh conversation with the real system prompt and all of Jarvis's tools.
Scores the first tool the model calls (or that it calls none, for small
talk), with one request per case, so "seconds" is time to that decision.
Costs real tokens, about 10k per request: the default (auto only, 27
cases) is ~270k tokens, and it stops early at --budget.

Run:  python tests/tool_eval.py                          # auto routing only
      python tests/tool_eval.py --limit 10               # cheaper smoke run
      python tests/tool_eval.py --configs auto lightning super ultra   # full, ~1M tokens
Writes tests/tool_eval_results.md (and .json) for the README.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config, nebius_backend, router, tools  # noqa: E402
from jarvis.assistant import build_system_prompt  # noqa: E402

# (request, acceptable first tools (None = no tool), route the router should pick)
CASES = [
    ("set a ten minute timer for the pasta", {"timer_set"}, "fast"),
    ("remind me in 20 minutes to stretch", {"reminder_set"}, "fast"),
    ("add a task to renew my visa by Friday", {"task_add"}, "fast"),
    ("pause the music", {"mac_media"}, "fast"),
    ("turn the volume down to 30", {"mac_set_volume"}, "fast"),
    ("switch to calm mode", {"voice_set_mood"}, "fast"),
    ("open Safari", {"mac_open_app"}, "fast"),
    ("what's playing right now", {"mac_now_playing"}, "fast"),
    ("what's on my task list", {"task_list"}, "main"),
    ("what's on my calendar tomorrow", {"calendar_list_events", "briefing_get"}, "main"),
    ("search my email for anything from the university", {"gmail_search"}, "main"),
    ("draft a reply to sara@digipearl.com.au saying I'll be there", {"gmail_create_draft"}, "main"),
    ("what's the weather in Sydney", {"weather_get"}, "main"),
    ("play Sajjan Raj Vaidya on YouTube Music", {"music_search_youtube"}, "fast"),
    ("remember that my sister's birthday is March 3rd", {"memory_save"}, "main"),
    ("what did I say about the landlord last week", {"recall"}, "main"),
    ("what's in the news about SpaceX", {"news_headlines", "web_search"}, "main"),
    ("summarise this page for me: https://example.com/post", {"web_read_page"}, "main"),
    ("what am I looking at on my screen", {"screen_look", "screen_context"}, "main"),
    ("find my resume", {"files_search"}, "main"),
    ("text Mum that I'm running late", {"message_send"}, "main"),
    ("make a note: ideas for the thesis intro", {"notes_create"}, "main"),
    ("how hard is my CPU working", {"system_status"}, "main"),
    ("good morning", {"briefing_get"}, "fast"),
    ("prep me for my 2pm", {"meeting_prep"}, "deep"),
    ("plan my week around a thesis deadline on Friday", {"calendar_list_events", "task_list", "briefing_get"}, "deep"),
    ("what's 17 times 23", {None}, "main"),
]

CONFIGS = {
    "auto": None,   # the router decides per request
    "lightning": lambda: config.NEBIUS_FAST_MODEL,
    "super": lambda: config.LLM_MODEL,
    "ultra": lambda: config.NEBIUS_DEEP_MODEL,
}


def run_case(text, model_for):
    calls = []

    def stub(name, args, confirm):
        calls.append(name)
        return "OK (eval stub: {} done; assume it worked and reply briefly).".format(name), False

    real_execute, tools.execute = tools.execute, stub
    try:
        backend = nebius_backend.NebiusBackend(confirm=lambda p: False, system_prompt=build_system_prompt())
        if model_for is not None:
            model = model_for()
            backend._route = lambda _t, m=model: (m, "pinned", "eval")
        started = time.monotonic()
        reply = backend.chat(text)
        seconds = time.monotonic() - started
    finally:
        tools.execute = real_execute
    stats = dict(nebius_backend.stats)
    return {
        "first_tool": calls[0] if calls else None,
        "tools": calls,
        "seconds": round(seconds, 2),
        "model": stats.get("model"),
        "route": stats.get("route"),
        "tokens": (stats.get("prompt_tokens") or 0) + (stats.get("completion_tokens") or 0),
        "failed": "couldn't reach" in reply,
        "reply": reply[:160],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", nargs="+", default=["auto"], choices=list(CONFIGS))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--limit", type=int, default=len(CASES), help="only the first N cases")
    parser.add_argument("--budget", type=int, default=300_000, help="stop after this many tokens")
    args = parser.parse_args()
    nebius_backend._MAX_TOOL_ROUNDS = 1   # one request per case: the first decision is what we score
    cases = CASES[:args.limit]
    spent = 0

    route_hits = sum(
        router.pick(t, "main", "fast", "deep")[1] == r for t, _, r in CASES
    )
    print("router agrees with the expected route on {}/{} requests\n".format(route_hits, len(CASES)))

    results = {}
    for name in args.configs:
        rows = []
        for _ in range(args.repeat):
            for text, expected, _route in cases:
                if spent >= args.budget:
                    print("token budget of {:,} reached; stopping".format(args.budget))
                    break
                row = run_case(text, CONFIGS[name])
                spent += row["tokens"]
                row.update(text=text, ok=row["first_tool"] in expected and not row["failed"])
                rows.append(row)
                print("{:<10} {:<4} {:>5.1f}s  {:<22} {}".format(
                    name, "ok" if row["ok"] else "MISS", row["seconds"],
                    str(row["first_tool"]), text))
        results[name] = rows
        print()

    out = Path(__file__).with_name("tool_eval_results")
    out.with_suffix(".json").write_text(json.dumps(results, indent=1))
    lines = [
        "| Config | Right tool | Median time to decide | p90 | Tokens / request |",
        "|---|---|---|---|---|",
    ]
    for name, rows in results.items():
        if not rows:
            continue
        secs = sorted(r["seconds"] for r in rows)
        p90 = secs[min(len(secs) - 1, int(len(secs) * 0.9))]
        lines.append("| {} | {}/{} ({:.0f}%) | {:.1f} s | {:.1f} s | {:,.0f} |".format(
            name, sum(r["ok"] for r in rows), len(rows), 100 * sum(r["ok"] for r in rows) / len(rows),
            statistics.median(secs), p90, statistics.mean(r["tokens"] for r in rows),
        ))
    table = "\n".join(lines)
    out.with_suffix(".md").write_text(
        "# Tool-calling eval ({} requests{})\n\n{}\n\nRouter agrees with the expected "
        "route on {}/{} requests.\n".format(
            len(cases), " x {}".format(args.repeat) if args.repeat > 1 else "",
            table, route_hits, len(CASES)))
    print(table)
    print("\nTokens used: {:,}".format(spent))
    misses = [(n, r["text"], r["first_tool"]) for n, rows in results.items() for r in rows if not r["ok"]]
    if misses:
        print("\nMisses:")
        for n, text, tool in misses:
            print("  {:<10} {!r} -> {}".format(n, text, tool))


if __name__ == "__main__":
    main()
