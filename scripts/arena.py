"""Pit two agents against each other and report the win rate.

    python scripts/arena.py --a ismcts:200 --b random --pairs 20 --procs 4

Each pair of games uses the same two random decks with the seats swapped, so
neither agent is helped by a lucky deck or by going first more often.
Agent specs: random, eager, ismcts[:iterations[:rollout_depth]].
"""
import argparse
import math
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import Game, default_db, random_deck  # noqa: E402
from cpbot.agents import EagerRandomAgent, RandomAgent  # noqa: E402
from cpbot.search import ISMCTSAgent  # noqa: E402


def make(spec, seed):
    name, *args = spec.split(":")
    if name == "random":
        return RandomAgent(seed)
    if name == "eager":
        return EagerRandomAgent(seed)
    if name == "ismcts":
        kw = {}
        if args:
            kw["iterations"] = int(args[0])
        if len(args) > 1:
            kw["rollout_depth"] = int(args[1])
        return ISMCTSAgent(seed=seed, **kw)
    raise ValueError(spec)


def play_pair(job):
    spec_a, spec_b, seed = job
    db = default_db()
    rng = random.Random(seed)
    decks = [random_deck(rng, db), random_deck(rng, db)]
    out = []
    for a_seat in (0, 1):
        g = Game(decks[0], decks[1], seed=seed * 2 + a_seat, db=db)
        agents = [None, None]
        agents[a_seat] = make(spec_a, seed * 7 + 1)
        agents[1 - a_seat] = make(spec_b, seed * 7 + 2)
        while not g.over:
            g.step(agents[g.current_player].act(g))
        out.append(0.5 if g.winner == "draw" else float(g.winner == a_seat))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="ismcts:200")
    ap.add_argument("--b", default="random")
    ap.add_argument("--pairs", type=int, default=20)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    jobs = [(a.a, a.b, a.seed + i) for i in range(a.pairs)]
    t = time.time()
    with Pool(a.procs) as pool:
        res = [x for pair in pool.map(play_pair, jobs) for x in pair]
    n = len(res)
    p = sum(res) / n
    half = 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / n)
    print(f"{a.a} vs {a.b}: {a.a} scores {p:.1%} over {n} games "
          f"(95% interval {max(0, p - half):.0%} to {min(1, p + half):.0%}), {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
