"""Let the search agent play itself and record positions for training.

    python scripts/selfplay.py --games 400 --iterations 60 --out selfplay/round1
    python scripts/selfplay.py --games 20000 --iterations 0 --out selfplay/playout   # fast, weaker play

Each game uses two fresh random decks. Every decision with more than one option is
recorded from both players' points of view (cpbot.features) and labelled with who
went on to win (y), and with the search's own estimate of the win chance (q, NaN
where no search was run), which is a less noisy training target. Results go to
<out>/chunk-<seed>.npz, one file per game, so a long run can be stopped and
resumed (finished games are skipped). --weights takes a .json linear score or an
.npz network score.
"""
import argparse
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import Game, default_db, random_deck  # noqa: E402
from cpbot.features import LearnedValue, NetValue, card_features, features, features_v2  # noqa: E402
from cpbot.search import ISMCTSAgent, rollout_move  # noqa: E402


def play(job):
    seed, out, iterations, depth, weights, explore = job
    path = Path(out) / f"chunk-{seed}.npz"
    if path.exists():
        return 0
    db = default_db()
    rng = random.Random(seed)
    decks = [random_deck(rng, db), random_deck(rng, db)]
    g = Game(decks[0], decks[1], seed=seed, db=db)
    if not weights:
        vf = "learned"
    elif str(weights).endswith(".npz"):
        vf = NetValue(path=weights)
    else:
        vf = LearnedValue(path=weights)
    agents = [ISMCTSAgent(iterations=max(iterations, 1), rollout_depth=depth, seed=seed * 2 + i, value_fn=vf)
              for i in (0, 1)]
    X, C, V, Q, turn = [], [], [], [], []
    fast = iterations == 0                         # cheap playout-policy games, sampled positions
    while not g.over:
        d = g.decision
        rec = g.turn_no > 0 and len(d.options) > 1 and (not fast or rng.random() < 0.15)
        if rec:
            X.append(features(g, 0))
            X.append(features(g, 1))
            C.append(card_features(g, 0))
            C.append(card_features(g, 1))
            V.append(features_v2(g, 0))
            V.append(features_v2(g, 1))
            turn.append(g.turn_no)
        q = float("nan")
        if fast:
            move = rollout_move(g, rng)
        elif explore and g.turn_no > 0 and rng.random() < explore:
            move = rng.choice(d.options)          # a little randomness for variety
        else:
            ag = agents[d.player]
            ag.last_stats = None
            move = ag.act(g)
            st = ag.last_stats
            if st and st.get("moves"):
                q = st["moves"][0][1]           # win chance of the most-visited move
                q = q if d.player == 0 else 1 - q
        if rec:
            Q += [q, 1 - q]
        g.step(move)
    y0 = 0.5 if g.winner == "draw" else float(g.winner == 0)
    y = np.array([y0, 1 - y0] * (len(X) // 2))
    np.savez_compressed(path, X=np.array(X), C=np.array(C, dtype=np.int8),
                        V=np.array(V, dtype=np.float16), y=y, q=np.array(Q, dtype=np.float32), seed=seed)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--seed", type=int, default=500000)
    ap.add_argument("--iterations", type=int, default=60)
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument("--weights", default=None, help="position score to search with (default: data/value_weights.json)")
    ap.add_argument("--explore", type=float, default=0.03)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--out", default="selfplay/round1")
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    jobs = [(a.seed + i, a.out, a.iterations, a.depth, a.weights, a.explore) for i in range(a.games)]
    t = time.time()
    done = 0
    with Pool(a.procs) as pool:
        for k, n in enumerate(pool.imap_unordered(play, jobs), 1):
            done += n
            if k % 25 == 0 or k == len(jobs):
                print(f"{k}/{len(jobs)} games ({done} new), {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
