"""Fit SmallNetValue: a one-hidden-layer network (plus a linear skip) over the linear
score's inputs (features + pattern_features + tactic_features).

    python scripts/train_small_net.py --data selfplay/round8pc selfplay/round9pc --out data/value_small_net.npz

Needs self-play recorded with tactic features (T), i.e. round 8 onwards. Holds out
every game whose seed ends in 0 and keeps the epoch with the best held-out log loss,
judged against who actually won.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import default_db  # noqa: E402
from cpbot.features import NAMES, PATTERN_NAMES, TACTIC_NAMES, pattern_features_from_v2  # noqa: E402


def load(folders, q_weight):
    db = default_db()
    Xs, ys, rs, ss = [], [], [], []
    for d in folders:
        for f in sorted(Path(d).glob("*.npz")):
            z = np.load(f)
            if len(z["y"]) == 0 or "T" not in z.files:
                continue
            Xs.append(np.hstack([z["X"], pattern_features_from_v2(z["V"], db),
                                 z["T"].astype(np.float32)]).astype(np.float32))
            y = z["y"].astype(float)
            q = z["q"].astype(float) if "q" in z.files else np.full(len(y), np.nan)
            ys.append(np.where(np.isnan(q), y, q_weight * np.nan_to_num(q) + (1 - q_weight) * y))
            rs.append(y)
            ss.append(np.full(len(y), int(z["seed"])))
    return (np.concatenate(v) for v in (Xs, ys, rs, ss))


def logloss(p, t):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(t * np.log(p) + (1 - t) * np.log(1 - p)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--q-weight", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    X, y, r, s = load(a.data, a.q_weight)
    names = NAMES + PATTERN_NAMES + TACTIC_NAMES
    assert X.shape[1] == len(names), (X.shape, len(names))
    test = s % 10 == 0
    mu, sd = X[~test].mean(0), X[~test].std(0) + 1e-6
    mu[0], sd[0] = 0.0, 1.0                                 # keep the bias column at 1
    Xn = ((X - mu) / sd).astype(np.float32)
    rng = np.random.default_rng(a.seed)
    P = [rng.normal(0, 1 / np.sqrt(X.shape[1]), (X.shape[1], a.hidden)).astype(np.float32),
         np.zeros(a.hidden, np.float32), np.zeros(a.hidden, np.float32), np.zeros(X.shape[1], np.float32)]
    M = [np.zeros_like(p) for p in P]
    V = [np.zeros_like(p) for p in P]

    def fwd(A):
        h = np.maximum(A @ P[0] + P[1], 0)
        return h, h @ P[2] + A @ P[3]

    tr = np.where(~test)[0]
    step, best = 0, (9.9, None, -1)
    print(f"{len(y)} positions, {int(test.sum())} held out")
    for ep in range(a.epochs):
        rng.shuffle(tr)
        for i in range(0, len(tr), 1024):
            b = tr[i:i + 1024]
            A = Xn[b]
            h, z = fwd(A)
            p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
            g = ((p - y[b]) / len(b)).astype(np.float32)
            gh = np.outer(g, P[2]) * (h > 0)
            G = [A.T @ gh, gh.sum(0), h.T @ g, A.T @ g]
            step += 1
            for k in range(4):
                M[k] = .9 * M[k] + .1 * G[k]
                V[k] = .999 * V[k] + .001 * G[k] ** 2
                P[k] -= a.lr * (M[k] / (1 - .9 ** step)) / (np.sqrt(V[k] / (1 - .999 ** step)) + 1e-8)
        _, z = fwd(Xn[test])
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        loss = logloss(p, r[test])
        print(f"epoch {ep + 1}: held-out log loss {loss:.4f}, accuracy {np.mean((p > .5) == (r[test] > .5)):.4f}",
              flush=True)
        if loss < best[0]:
            best = (loss, [x.copy() for x in P], ep + 1)
    W1, b1, W2, w = best[1]
    np.savez(a.out, W1=W1, b1=b1, W2=W2, w=w, mu=mu.astype(np.float32), sd=sd.astype(np.float32),
             names=np.array(names), data=np.array(a.data))
    print(f"saved {a.out} (epoch {best[2]}, held-out log loss {best[0]:.4f})")


if __name__ == "__main__":
    main()
