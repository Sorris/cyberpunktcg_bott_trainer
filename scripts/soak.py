"""Soak test: play many games between random agents with random legal decks.

Checks game invariants after every decision and reports crashes, game length
and how games end. Usage: python scripts/soak.py [games] [workers]
"""
import os
import random
import sys
import time
import traceback
from collections import Counter
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cpbot import Game, default_db, random_deck  # noqa: E402
from cpbot.agents import EagerRandomAgent, RandomAgent, play_game  # noqa: E402


def run(seed, check_every=1):
    db = default_db()
    rng = random.Random(seed)
    d0, d1 = random_deck(rng, db), random_deck(rng, db)
    A = EagerRandomAgent if seed % 2 else RandomAgent
    try:
        g = Game(d0, d1, seed=seed)
        play_game(g, [A(seed * 2), A(seed * 2 + 1)], check=bool(check_every))
        return ("ok", g.winner, g.end_reason, g.turn_no, len(g.history), None)
    except Exception:
        return ("crash", None, None, None, None, f"seed {seed}:\n{traceback.format_exc()}")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else os.cpu_count()
    t = time.time()
    with Pool(workers) as pool:
        res = pool.map(run, range(n), chunksize=50)
    dt = time.time() - t
    crashes = [r for r in res if r[0] == "crash"]
    ok = [r for r in res if r[0] == "ok"]
    print(f"{n} games in {dt:.1f}s ({n / dt:.0f} games/s), {len(crashes)} crashes")
    if ok:
        print("end reasons:", Counter(r[2] for r in ok).most_common())
        print("winner:", Counter(r[1] for r in ok))
        turns = sorted(r[3] for r in ok)
        print(f"turns: median {turns[len(turns) // 2]}, max {turns[-1]}")
        dec = sorted(r[4] for r in ok)
        print(f"decisions per game: median {dec[len(dec) // 2]}, max {dec[-1]}")
    for c in crashes[:3]:
        print(c[5])
    sys.exit(1 if crashes else 0)


if __name__ == "__main__":
    main()
