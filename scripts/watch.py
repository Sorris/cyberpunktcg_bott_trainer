"""Play one game and write it out so a person can follow it.

    python scripts/watch.py                 # random decks, random agents, seed 0
    python scripts/watch.py --seed 7 --agents ismcts eager --out games/
    python scripts/watch.py --replay games/seed7.json   # rebuild a recorded game

Writes <name>.txt (play-by-play), <name>.json (seed, decks and every choice, enough
to replay the game exactly) and <name>.html (a replay page you can step through).
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import Game, default_db, random_deck  # noqa: E402
from cpbot.agents import EagerRandomAgent, RandomAgent  # noqa: E402
from cpbot.search import ISMCTSAgent  # noqa: E402
from cpbot.watch import replay, watch_game  # noqa: E402

AGENTS = {"random": RandomAgent, "eager": EagerRandomAgent,
          "ismcts": lambda seed: ISMCTSAgent(iterations=300, seed=seed)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--agents", nargs=2, default=["eager", "eager"], choices=sorted(AGENTS))
    ap.add_argument("--out", default="games")
    ap.add_argument("--name", default=None)
    ap.add_argument("--replay", default=None, help="a recorded .json game to rebuild")
    a = ap.parse_args()

    db = default_db()
    if a.replay:
        rec = replay(json.loads(Path(a.replay).read_text()), db)
        name = a.name or Path(a.replay).stem
    else:
        rng = random.Random(a.seed)
        decks = [random_deck(rng, db), random_deck(rng, db)]
        game = Game(decks[0], decks[1], seed=a.seed, db=db)
        agents = [AGENTS[x](a.seed * 2 + i) for i, x in enumerate(a.agents)]
        rec = watch_game(game, agents, decks, seed=a.seed, names=[f"{x} agent" for x in a.agents])
        name = a.name or f"seed{a.seed}"

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.txt").write_text(rec.text())
    (out / f"{name}.json").write_text(rec.to_json())
    (out / f"{name}.html").write_text(rec.html(title="Match replay"))
    g = rec.g
    result = "draw" if g.winner == "draw" else f"P{g.winner + 1} wins"
    print(f"{result} ({g.end_reason}) after {g.turn_no} turns; wrote {out}/{name}.txt, .json, .html")


if __name__ == "__main__":
    main()
