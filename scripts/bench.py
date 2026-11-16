"""Time the search on fixed work, to compare Python builds or engine changes.

    python scripts/bench.py

Plays 3 games between two 150-sample searches. Prints the Python build, the time
taken, and a fingerprint of every move: the fingerprint must match across builds
(same moves), so only the time should differ.
"""
import hashlib
import platform
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import Game, default_db, random_deck  # noqa: E402
from cpbot.search import ISMCTSAgent  # noqa: E402


def main():
    db = default_db()
    t = time.perf_counter()
    moves = []
    for s in range(3):
        rng = random.Random(s)
        g = Game(random_deck(rng, db), random_deck(rng, db), seed=s)
        ag = [ISMCTSAgent(iterations=150, seed=s * 2 + i, reuse=False) for i in (0, 1)]
        while not g.over:
            m = ag[g.decision.player].act(g)
            moves.append(m)
            g.step(m)
    fp = hashlib.md5(repr(moves).encode()).hexdigest()[:12]
    print(f"{platform.python_implementation()} {platform.python_version()}: "
          f"{time.perf_counter() - t:.1f}s, moves {fp}", flush=True)


if __name__ == "__main__":
    main()
