"""Real-model check of semantic recall. Opt in: JARVIS_TEST_REAL_EMBED=1.

Uses a throwaway profile (temp DB and memory dir), never your data. Loads the
actual embedding model (downloads ~64 MB once), indexes a small corpus, and
reports how well paraphrased questions find the right item and how high
unrelated questions score, which is what RECALL_MIN_SCORE has to separate.

    JARVIS_TEST_REAL_EMBED=1 .venv/bin/python tests/recall_eval.py
"""
import os
import sys
import tempfile
from pathlib import Path

if os.environ.get("JARVIS_TEST_REAL_EMBED") != "1":
    print("skipped: set JARVIS_TEST_REAL_EMBED=1 to run the real-model evaluation")
    sys.exit(0)

tmp = Path(tempfile.mkdtemp(prefix="jarvis-eval-"))
os.environ["DB_PATH"] = str(tmp / "jarvis.db")
os.environ["MEMORY_DIR"] = str(tmp / "memory")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402
from jarvis.tools import history, memory, recall  # noqa: E402

MEMORIES = {
    "sister-birthday": ("Sister's birthday is March 14", "My sister Priya was born on 14 March; she lives in Melbourne."),
    "favorite-editor": ("Prefers Neovim for coding", "Writes code in Neovim with a dark theme, never VS Code."),
    "coffee-order": ("Flat white, no sugar", "Usual coffee is a flat white with oat milk and no sugar."),
    "dentist": ("Dentist appointment every six months", "Dr. Okafor on George Street; next checkup is in April."),
    "manager": ("Manager is Daniel Reyes", "Reports to Daniel Reyes; weekly one-on-one on Thursdays at 3pm."),
    "allergy": ("Allergic to peanuts", "Severe peanut allergy; carries an EpiPen. Tree nuts are fine."),
    "car": ("Drives a blue Mazda 3", "Blue 2019 Mazda 3, registration due in August."),
    "gym": ("Gym on Monday, Wednesday, Friday mornings", "Strength training at 6:30am at the Fitzroy gym."),
    "wifi-router": ("Router is in the hallway cupboard", "Wi-Fi router lives in the hallway cupboard; admin page is 192.168.1.1."),
    "book-club": ("Book club meets last Sunday of the month", "Reading The Overstory this month, hosted at Mia's place."),
}
TURNS = [
    ("what hotel did we pick for the Lisbon trip", "You picked the Alfama Inn for the Lisbon trip, three nights in March."),
    ("remind me what the plumber said about the kitchen tap", "The plumber said the washer is worn and quoted ninety dollars to replace it."),
    ("which flight did I book to Sydney", "You booked the 7:10am Qantas flight to Sydney on the twelfth of June."),
    ("what was the recipe I asked for yesterday", "You asked for a lentil dal recipe: red lentils, turmeric, cumin, and a squeeze of lemon."),
    ("how much was the electricity bill", "Your electricity bill was two hundred and forty dollars for the quarter."),
]

# (query, expected ref) — paraphrased, sharing few words with the stored text.
POSITIVE = [
    ("when does my sibling celebrate her birthday", "sister-birthday"),
    ("which text editor do I like", "favorite-editor"),
    ("how do I take my coffee", "coffee-order"),
    ("when is my next teeth cleaning", "dentist"),
    ("who is my boss", "manager"),
    ("what foods can't I eat", "allergy"),
    ("what vehicle do I own", "car"),
    ("what days do I work out", "gym"),
    ("where is the internet box", "wifi-router"),
    ("what novel are we reading", "book-club"),
    ("where are we staying in Portugal", "turn:0"),
    ("what's wrong with the leaky faucet", "turn:1"),
    ("what time is my plane to New South Wales", "turn:2"),
    ("what lentil dish did you suggest", "turn:3"),
    ("what did the power bill come to", "turn:4"),
]
NEGATIVE = [
    "how tall is mount everest",
    "who won the football world cup in 1998",
    "explain how photosynthesis works",
    "what is the capital of Mongolia",
    "translate good morning into Japanese",
    "how many calories are in an avocado",
    "what is the square root of 144",
    "tell me a joke about penguins",
]

for name, (summary, body) in MEMORIES.items():
    memory.save(name, summary, body)
turn_refs = []
for user, reply in TURNS:
    history.add("user", user)
    turn_refs.append(str(history.add("jarvis", reply)))
recall.flush(timeout=60)
assert recall.count("memory") == len(MEMORIES) and recall.count("turn") == len(TURNS), "index incomplete"

hits_ok, pos_scores = 0, []
for query, expected in POSITIVE:
    want = turn_refs[int(expected[5:])] if expected.startswith("turn:") else expected
    top = recall.search(query, limit=3, min_score=-1.0)
    best = top[0]
    pos_scores.append(best.score)
    found = best.ref == want
    hits_ok += found
    print("{} {:.2f}  {!r} -> {} {}".format("ok  " if found else "MISS", best.score, query, best.kind, best.ref if not found else ""))
neg_scores = []
for query in NEGATIVE:
    best = recall.search(query, limit=1, min_score=-1.0)[0]
    neg_scores.append(best.score)
    print("neg  {:.2f}  {!r} (nearest: {})".format(best.score, query, best.ref))

print("\ntop-1 accuracy: {}/{}".format(hits_ok, len(POSITIVE)))
print("right-answer scores: min {:.2f}  median {:.2f}".format(min(pos_scores), sorted(pos_scores)[len(pos_scores) // 2]))
print("unrelated scores:    max {:.2f}  median {:.2f}".format(max(neg_scores), sorted(neg_scores)[len(neg_scores) // 2]))
gap = min(pos_scores) - max(neg_scores)
print("gap between them: {:.2f}  (RECALL_MIN_SCORE = {}; a miss costs more than a stray hit, so keep it lenient)".format(gap, config.RECALL_MIN_SCORE))

print("\nWhat the model would see for one question:\n")
print(recall.lookup("where are we staying in Portugal"))
