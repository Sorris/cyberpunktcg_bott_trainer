"""Pit two agents against each other and report the win rate.

    python scripts/arena.py --a ismcts:200 --b random --pairs 20 --procs 4

Each pair of games uses the same two random decks with the seats swapped, so
neither agent is helped by a lucky deck or by going first more often.
With --deck-a/--deck-b (deck list files, see cpbot/decklist.py) each agent keeps
its own deck in both seats, so `--a ismcts:200 --b ismcts:200 --deck-a x.txt
--deck-b y.txt` compares two decks. A side with no deck file gets a random deck.
Agent specs: random, eager, ismcts[:iterations[:rollout_depth]][:key=value,...],
for example ismcts:s=0.5,d=10,v=learned (see make()).
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
from cpbot.decklist import parse_file, report  # noqa: E402
from cpbot.agents import EagerRandomAgent, RandomAgent  # noqa: E402
from cpbot.features import LearnedValue, NetValue  # noqa: E402
from cpbot.search import ISMCTSAgent  # noqa: E402


def make(spec, seed):
    """random | eager | ismcts[:iterations[:rollout_depth]][:key=value,...]
    ismcts keys: it (iterations), d (rollout depth), s (seconds per move, overrides it),
    v (learned, the default, hand, net, or a weights .json/.npz file),
    i (1 = guess the rival's decklist from what it has seen instead of knowing it), c (exploration)."""
    name, *args = spec.split(":")
    if name == "random":
        return RandomAgent(seed)
    if name == "eager":
        return EagerRandomAgent(seed)
    if name == "ismcts":
        kw = {}
        pos = [x for x in args if "=" not in x]
        if pos:
            kw["iterations"] = int(pos[0])
        if len(pos) > 1:
            kw["rollout_depth"] = int(pos[1])
        for tok in ",".join(x for x in args if "=" in x).split(","):
            if not tok:
                continue
            k, v = tok.split("=")
            if k == "it":
                kw["iterations"] = int(v)
            elif k == "d":
                kw["rollout_depth"] = int(v)
            elif k == "s":
                kw["seconds"] = float(v)
            elif k == "c":
                kw["c"] = float(v)
            elif k == "v" and v in ("learned", "hand"):
                kw["value_fn"] = v
            elif k == "v" and v == "net":
                kw["value_fn"] = NetValue()
            elif k == "v" and v.endswith(".npz"):
                kw["value_fn"] = NetValue(path=v)
            elif k == "v":
                kw["value_fn"] = LearnedValue(path=v)     # a weights file
            elif k == "i":
                kw["infer_rival"] = bool(int(v))
            else:
                raise ValueError(tok)
        return ISMCTSAgent(seed=seed, **kw)
    raise ValueError(spec)


def play_pair(job):
    spec_a, spec_b, seed, deck_a, deck_b = job
    db = default_db()
    rng = random.Random(seed)
    decks = [random_deck(rng, db), random_deck(rng, db)]
    own_decks = deck_a is not None or deck_b is not None
    if own_decks:  # decks belong to agents: [A's deck, B's deck]
        decks = [deck_a or decks[0], deck_b or decks[1]]
    out = []
    for a_seat in (0, 1):
        seats = decks if not own_decks or a_seat == 0 else decks[::-1]
        g = Game(seats[0], seats[1], seed=seed * 2 + a_seat, db=db)
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
    ap.add_argument("--deck-a", default=None, help="deck list file for agent A")
    ap.add_argument("--deck-b", default=None, help="deck list file for agent B")
    a = ap.parse_args()
    decks = []
    for path in (a.deck_a, a.deck_b):
        if path is None:
            decks.append(None)
            continue
        dl = parse_file(path)
        print(report(dl))
        if dl.errors():
            sys.exit(f"{path} is not a legal deck")
        decks.append(dl.deck)
    jobs = [(a.a, a.b, a.seed + i, *decks) for i in range(a.pairs)]
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
