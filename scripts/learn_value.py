"""Fit the learned position score from self-play games.

    python scripts/learn_value.py --games 20000 --procs 4
    python scripts/learn_value.py --data selfplay/round1 --games 0 --out data/value_weights.json

Without --data it plays games with the search agent's playout policy. With --data it
also (or only, with --games 0) reads positions recorded by scripts/selfplay.py.
Each position is labelled with who went on to win, and a logistic model over
cpbot.features is fitted. Prints how well it predicts held-out games.
"""
import argparse
import json
import math
import os
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import Game, default_db, random_deck  # noqa: E402
from cpbot.features import NAMES, PATTERN_NAMES, TACTIC_NAMES, WEIGHTS, card_features, card_names, \
    features, pattern_features, pattern_features_from_v2, tactic_features  # noqa: E402
from cpbot.search import rollout_move, value  # noqa: E402


CARDS = {"on": False, "patterns": False, "tactics": False}


def _init(cards, patterns=False, tactics=False):
    CARDS["on"] = cards
    CARDS["patterns"] = patterns
    CARDS["tactics"] = tactics


def play(seed, sample=0.15):
    db = default_db()
    rng = random.Random(seed)
    decks = [random_deck(rng, db), random_deck(rng, db)]
    g = Game(decks[0], decks[1], seed=seed, db=db)
    pos = []
    while not g.over:
        if g.turn_no > 0 and rng.random() < sample:
            f0, f1 = features(g, 0), features(g, 1)
            if CARDS["patterns"]:
                f0, f1 = f0 + pattern_features(g, 0), f1 + pattern_features(g, 1)
            if CARDS["tactics"]:
                f0, f1 = f0 + tactic_features(g, 0), f1 + tactic_features(g, 1)
            if CARDS["on"]:
                f0, f1 = f0 + card_features(g, 0), f1 + card_features(g, 1)
            pos.append((f0, f1, value(g, 0)))
        g.step(rollout_move(g, rng))
    y0 = 0.5 if g.winner == "draw" else float(g.winner == 0)
    rows = []
    for f0, f1, h0 in pos:
        rows.append((f0, y0, h0, seed))
        rows.append((f1, 1 - y0, 1 - h0, seed))
    return rows


def fit(X, y, l2=1e-3, iters=30, off=None):
    w = np.zeros(X.shape[1])
    off = 0.0 if off is None else off
    for _ in range(iters):
        z = np.clip(X @ w + off, -30, 30)
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
    ap.add_argument("--cards", action="store_true", help="add card-aware features (which cards are in play)")
    ap.add_argument("--patterns", action="store_true",
                    help="add Gig-pattern features (each colour's pattern times its RAM and pay-offs)")
    ap.add_argument("--q-weight", type=float, default=0.0,
                    help="weight of the search's win estimate (q, when recorded) in the target")
    ap.add_argument("--tactics", action="store_true",
                    help="add attack-planning features (steal threat after blockers, lethal, ...)")
    ap.add_argument("--freeze", help="keep this weights file's weights fixed and fit only the other "
                    "features (and the bias)")
    ap.add_argument("--l2", type=float, default=1e-3)
    ap.add_argument("--data", nargs="*", default=[], help="folders of selfplay .npz files")
    ap.add_argument("--out", default=str(WEIGHTS))
    a = ap.parse_args()
    t = time.time()
    rows = []
    if a.games:
        with Pool(a.procs, initializer=_init, initargs=(a.cards, a.patterns, a.tactics)) as pool:
            chunks = pool.map(play, range(a.seed, a.seed + a.games), chunksize=50)
        rows = [r for c in chunks for r in c]
    db = default_db()
    names = (NAMES + (PATTERN_NAMES if a.patterns else []) + (TACTIC_NAMES if a.tactics else [])
             + (card_names(db) if a.cards else []))
    Xs = [np.array([r[0] for r in rows], dtype=np.float32).reshape(len(rows), len(names))]
    ys = [np.array([r[1] for r in rows])]
    rs = [ys[0]]                                            # game results, for judging
    hs = [np.array([r[2] for r in rows])]
    seeds = [np.array([r[3] for r in rows], dtype=int)]
    for folder in a.data:
        for f in sorted(Path(folder).glob("*.npz")):
            z = np.load(f)
            if len(z["y"]) == 0:
                continue
            parts = [z["X"]]
            if a.patterns:
                if "V" not in z.files:
                    continue
                parts.append(pattern_features_from_v2(z["V"], db))
            if a.tactics:
                if "T" not in z.files:
                    continue
                parts.append(z["T"].astype(np.float32))
            if a.cards:
                parts.append(z["C"])
            Xs.append(np.hstack(parts) if len(parts) > 1 else parts[0])
            yy = z["y"].astype(float)
            if a.q_weight and "q" in z.files:
                q = z["q"].astype(float)
                yy = np.where(np.isnan(q), yy, a.q_weight * np.nan_to_num(q) + (1 - a.q_weight) * yy)
            ys.append(yy)
            rs.append(z["y"].astype(float))
            hs.append(np.full(len(z["y"]), np.nan))
            seeds.append(np.full(len(z["y"]), int(z["seed"])))
    X, y, h, seed, res = (np.concatenate(v) for v in (Xs, ys, hs, seeds, rs))
    rows = y
    test = seed % 10 == 0                                   # hold out whole games
    if a.freeze:
        old = json.loads(Path(a.freeze).read_text())
        fixed = dict(zip(old["names"], old["weights"]))
        fixed.pop("bias", None)
        wf = np.array([fixed.get(n, 0.0) for n in names])
        free = np.array([n not in fixed for n in names])
        off = X[:, ~free].astype(np.float64) @ wf[~free]
        wfree = fit(X[~test][:, free].astype(np.float64), y[~test], l2=a.l2, off=off[~test])
        w = wf.copy()
        w[free] = wfree
        print(f"kept {int((~free).sum())} weights from {a.freeze}, fitted {int(free.sum())}")
    else:
        w = fit(X[~test].astype(np.float64), y[~test], l2=a.l2)
    p = 1 / (1 + np.exp(-np.clip(X[test] @ w, -30, 30)))
    y = res                                                 # judge against who actually won
    base = float(np.mean(y[~test]))
    print(f"{len(y)} positions ({a.games} new playout games, {len(a.data)} self-play folders), "
          f"{time.time() - t:.0f}s")
    print(f"held-out log loss: learned {logloss(p, y[test]):.4f}, "
          f"coin flip {logloss(np.full(test.sum(), base), y[test]):.4f}")
    print(f"held-out accuracy: learned {np.mean((p > .5) == (y[test] > .5)):.3f}")
    if os.environ.get("COMPARE"):
        old = np.array(json.loads(Path(os.environ["COMPARE"]).read_text())["weights"])
        q = 1 / (1 + np.exp(-np.clip(X[test][:, :len(old)] @ old, -30, 30)))
        print(f"  {os.environ['COMPARE']} on the same positions: log loss {logloss(q, y[test]):.4f}, "
              f"accuracy {np.mean((q > .5) == (y[test] > .5)):.3f}")
    Path(a.out).write_text(json.dumps({
        "about": "Logistic position score over cpbot.features; fitted by scripts/learn_value.py",
        "games": a.games, "selfplay": a.data, "positions": int(len(y)), "names": names, "weights": [round(float(x), 5) for x in w]}, indent=1))
    for n, x in sorted(zip(names, w), key=lambda t: -abs(t[1]))[:16]:
        print(f"  {n:22s} {x:+.3f}")


if __name__ == "__main__":
    main()
