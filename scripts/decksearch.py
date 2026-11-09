"""Let the bot build and test its own decks (see cpbot/decksearch.py).

    python scripts/decksearch.py --run decksearch/run1 --generations 30
    python scripts/decksearch.py --run decksearch/run1 --generations 60   # resume and continue

Writes <run>/state.json (everything needed to resume), <run>/log.txt and
<run>/best.txt (the current top decks with their records).
"""
import argparse
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import Game, default_db  # noqa: E402
from cpbot.agents import EagerRandomAgent  # noqa: E402
from cpbot.decksearch import (Entry, SearchState, breed, deck_from_key, deck_key, describe,  # noqa: E402
                              new_state, schedule)
from cpbot.deck import random_deck  # noqa: E402
from cpbot.search import ISMCTSAgent  # noqa: E402

AGENT = {"iterations": 30, "value": None, "vf": None}


def _value_fn():
    v = AGENT["value"]
    if not v:
        return "learned"
    if AGENT["vf"] is None:
        from cpbot.features import LearnedValue, NetValue
        AGENT["vf"] = NetValue(path=v) if v.endswith(".npz") else LearnedValue(path=v)
    return AGENT["vf"]


def _agent(seed):
    if AGENT["iterations"] == 0:
        return EagerRandomAgent(seed)
    return ISMCTSAgent(iterations=AGENT["iterations"], rollout_depth=20, seed=seed, value_fn=_value_fn())


def _init(iterations, value=None):
    AGENT["iterations"] = iterations
    AGENT["value"] = value


def play_pair(job):
    ka, kb, seed = job
    db = default_db()
    da, dbk = deck_from_key(ka), deck_from_key(kb)
    wins = 0.0
    for a_seat in (0, 1):
        decks = (da, dbk) if a_seat == 0 else (dbk, da)
        g = Game(decks[0], decks[1], seed=seed * 2 + a_seat, db=db)
        agents = [_agent(seed + 11), _agent(seed + 13)]
        while not g.over:
            g.step(agents[g.current_player].act(g))
        wins += 0.5 if g.winner == "draw" else float(g.winner == a_seat)
    return ka, kb, wins


def legend_names(key, db):
    return " / ".join(db[i].title.split(" - ")[0] for i in deck_from_key(key).legends)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="decksearch/run1")
    ap.add_argument("--generations", type=int, default=30, help="stop after this many generations in total")
    ap.add_argument("--pop", type=int, default=16)
    ap.add_argument("--children", type=int, default=8)
    ap.add_argument("--immigrants", type=int, default=2, help="new random decks added each generation")
    ap.add_argument("--pairs", type=int, default=3, help="pairs of games per deck per generation")
    ap.add_argument("--iterations", type=int, default=30, help="search budget per move (0 = eager random)")
    ap.add_argument("--value", default=None, help="position score for the bot (.json linear or .npz network)")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    db = default_db()
    run = Path(a.run)
    run.mkdir(parents=True, exist_ok=True)
    state_file = run / "state.json"
    s = SearchState.from_json(state_file.read_text()) if state_file.exists() else new_state(db, a.seed, a.pop)
    rng = random.Random(a.seed * 1000 + s.generation)
    log = open(run / "log.txt", "a")

    with Pool(a.procs, initializer=_init, initargs=(a.iterations, a.value)) as pool:
        while s.generation < a.generations:
            t = time.time()
            kids = breed(s, db, rng, a.children) if s.generation > 0 else []
            # a few brand-new random decks each generation keep the search exploring
            kids += [Entry(deck_key(random_deck(rng, db)), s.generation + 1) for _ in range(a.immigrants)]
            entries = s.population + kids
            by_key = {e.key: e for e in entries}
            jobs = schedule(s, entries, rng, a.pairs)
            for ka, kb, w in pool.imap_unordered(play_pair, jobs):
                by_key[ka].wins += w
                by_key[ka].games += 2
                if kb in by_key:                       # population games count for both decks
                    by_key[kb].wins += 2 - w
                    by_key[kb].games += 2
            ranked = sorted(entries, key=lambda e: -e.score())
            s.population = ranked[:a.pop]
            best = ranked[0]
            if best.games >= 12 and best.key not in s.hall:
                s.hall = (s.hall + [best.key])[-12:]
            s.generation += 1
            kept = sum(1 for e in kids if e in s.population)
            summary = {"generation": s.generation, "best": round(best.score(), 3), "best_games": best.games,
                       "best_legends": legend_names(best.key, db), "children_kept": kept,
                       "seconds": round(time.time() - t)}
            s.history.append(summary)
            line = (f"gen {s.generation}: best {best.score():.0%} over {best.games} games "
                    f"({summary['best_legends']}), {kept}/{len(kids)} new decks kept, {summary['seconds']}s")
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
            state_file.write_text(s.to_json())
            out = []
            for i, e in enumerate(s.population[:5], 1):
                out.append(f"## {i}. {legend_names(e.key, db)}: {e.wins:g}/{e.games} wins "
                           f"(score {e.score():.0%}, born in generation {e.born})\n")
                out.append(describe(e.key, db) + "\n")
            (run / "best.txt").write_text("\n".join(out))


if __name__ == "__main__":
    main()
