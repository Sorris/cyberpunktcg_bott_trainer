"""Fit the learned position score from self-play games.

    python scripts/learn_value.py --games 20000 --procs 4

Plays games with the search agent's playout policy, samples positions, labels
each with who went on to win, and fits a logistic model over cpbot.features.
Writes data/value_weights.json and prints how well it predicts held-out games.
"""
import argparse
import json
import math
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import Game, default_db, random_deck  # noqa: E402
from cpbot.features import NAMES, WEIGHTS, features  # noqa: E402
from cpbot.search import rollout_move, value  # noqa: E402


def play(seed, sample=0.15):
    db = default_db()
    rng = random.Random(seed)
    decks = [random_deck(rng, db), random_deck(rng, db)]
    g = Game(decks[0], decks[1], seed=seed, db=db)
    pos = []
    while not g.over:
        if g.turn_no > 0 and rng.random() < sample:
            pos.append((features(g, 0), features(g, 1), value(g, 0)))
        g.step(rollout_move(g, rng))
    y0 = 0.5 if g.winner == "draw" else float(g.winner == 0)
    rows = []
    for f0, f1, h0 in pos:
        rows.append((f0, y0, h0, seed))
        rows.append((f1, 1 - y0, 1 - h0, seed))
    return rows


def fit(X, y, l2=1e-3, iters=30):
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        z = np.clip(X @ w, -30, 30)
        p = 1 / (1 + np.exp(-z))
        grad = X.T @ (p - y) / len(y) + l2 * w
        W = p * (1 - p)
        H = (X.T * W) @ X / len(y) + l2 * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=100000)
    ap.add_argument("--out", default=str(WEIGHTS))
    a = ap.parse_args()
    t = time.time()
    with Pool(a.procs) as pool:
        chunks = pool.map(play, range(a.seed, a.seed + a.games), chunksize=50)
    rows = [r for c in chunks for r in c]
    X = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows])
    h = np.array([r[2] for r in rows])
    test = np.array([r[3] % 10 == 0 for r in rows])        # hold out whole games
    w = fit(X[~test], y[~test])
    p = 1 / (1 + np.exp(-np.clip(X[test] @ w, -30, 30)))
    base = float(np.mean(y[~test]))
    print(f"{a.games} games, {len(rows)} positions, {time.time() - t:.0f}s")
    print(f"held-out log loss: learned {logloss(p, y[test]):.4f}, hand-made {logloss(h[test], y[test]):.4f}, "
          f"coin flip {logloss(np.full(test.sum(), base), y[test]):.4f}")
    print(f"held-out accuracy: learned {np.mean((p > .5) == (y[test] > .5)):.3f}, "
          f"hand-made {np.mean((h[test] > .5) == (y[test] > .5)):.3f}")
    Path(a.out).write_text(json.dumps({
        "about": "Logistic position score over cpbot.features; fitted by scripts/learn_value.py",
        "games": a.games, "names": NAMES, "weights": [round(float(x), 5) for x in w]}, indent=1))
    for n, x in sorted(zip(NAMES, w), key=lambda t: -abs(t[1]))[:12]:
        print(f"  {n:22s} {x:+.3f}")


if __name__ == "__main__":
    main()
