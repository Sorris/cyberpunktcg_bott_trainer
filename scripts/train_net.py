"""Train the network position score (cpbot.features.NetValue) on self-play data.

    python scripts/train_net.py --data selfplay/round2 --out data/value_net.npz

Reads the features_v2 rows recorded by scripts/selfplay.py, holds out every tenth
game of the first folder (the one that matters, usually search-agent self-play),
trains a one-hidden-layer network with Adam and prints held-out log loss and
accuracy next to the linear score's.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import default_db  # noqa: E402
from cpbot.features import NET_WEIGHTS, WEIGHTS, names_v2, pattern_features_from_v2  # noqa: E402


def load(folders, cols, max_files=None):
    """Read every game into one preallocated float16 array (memory-light: the
    rows are 838 numbers each and there can be millions of them)."""
    files = []
    for k, folder in enumerate(folders):
        for f in sorted(Path(folder).glob("*.npz"))[:max_files]:
            files.append((k, f))
    db = default_db()
    rows = 0
    for _, f in files:
        z = np.load(f)
        if "V" in z.files and len(z["y"]):
            rows += len(z["y"])
    d = len(cols) + 16                                 # chosen features_v2 columns + Gig patterns
    V = np.empty((rows, d), np.float16)
    X, y, seed, src, P = [], [], [], [], []
    i = 0
    for k, f in files:
        z = np.load(f)
        if "V" not in z.files or len(z["y"]) == 0:
            continue
        n = len(z["y"])
        p = pattern_features_from_v2(z["V"], db).astype(np.float32)
        V[i:i + n] = np.hstack([z["V"][:, cols], p])
        P.append(p)
        i += n
        X.append(z["X"].astype(np.float32))
        y.append(z["y"].astype(np.float32))
        seed.append(np.full(n, int(z["seed"])))
        src.append(np.full(n, k))
    return (V, np.concatenate(X), np.concatenate(y), np.concatenate(seed), np.concatenate(src),
            np.concatenate(P))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", default=["selfplay/round2"])
    ap.add_argument("--out", default=str(NET_WEIGHTS))
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--l2", type=float, default=1e-4)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--blocks", default="board,rival_board,hand,my_deck,rival_shown",
                    help="which card blocks of features_v2 to use (comma list, or 'none' for counts only); "
                         "my_deck makes games easy to tell apart, so it can overfit")
    ap.add_argument("--max-files", type=int, default=None, help="games to read per folder")
    a = ap.parse_args()
    t = time.time()
    db = default_db()
    n = len(db.cards)
    head = len(names_v2(db)) - 5 * n
    order = ["board", "rival_board", "hand", "my_deck", "rival_shown"]
    keep = [] if a.blocks == "none" else a.blocks.split(",")
    cols = list(range(head)) + [head + order.index(b) * n + j for b in keep for j in range(n)]
    cols = np.array(cols, dtype=np.int32)
    V, X, y, seed, src, Pat = load(a.data, cols, a.max_files)
    test = (seed % 10 == 0) & (src == 0)        # judge on held-out games from the first folder
    s1 = np.zeros(V.shape[1], np.float64)
    s2 = np.zeros(V.shape[1], np.float64)
    for i in range(0, len(V), 50000):                 # mean and spread over training rows
        b = V[i:i + 50000][~test[i:i + 50000]].astype(np.float64)
        s1 += b.sum(0)
        s2 += (b * b).sum(0)
    ntr = int((~test).sum())
    mu = (s1 / ntr).astype(np.float32)
    sd = (np.sqrt(np.maximum(s2 / ntr - (s1 / ntr) ** 2, 0)) + 1e-3).astype(np.float32)
    te_rows = np.where(test)[0]
    Xte = np.hstack([X[te_rows], Pat[te_rows]])        # for the linear score
    Z = V                                              # normalised in place, kept as float16
    for i in range(0, len(Z), 50000):
        Z[i:i + 50000] = (Z[i:i + 50000].astype(np.float32) - mu) / sd
    shape = Z.shape
    tr, te = np.where(~test)[0], np.where(test)[0]
    print(f"{len(y)} positions from {len(set(seed.tolist()))} games ({len(te)} held out), {shape[1]} features")

    rng = np.random.default_rng(a.seed)
    d, h = shape[1], a.hidden
    P = {"W1": rng.normal(0, np.sqrt(2 / d), (d, h)).astype(np.float32), "b1": np.zeros(h, np.float32),
         "W2": rng.normal(0, np.sqrt(1 / h), h).astype(np.float32), "b2": np.zeros((), np.float32)}
    M = {k: np.zeros_like(v) for k, v in P.items()}
    S = {k: np.zeros_like(v) for k, v in P.items()}
    step = 0

    def forward(Zb):
        H = np.maximum(Zb @ P["W1"] + P["b1"], 0)
        return H, H @ P["W2"] + P["b2"]

    best = (9.0, None)
    for ep in range(a.epochs):
        rng.shuffle(tr)
        for i in range(0, len(tr), a.batch):
            idx = tr[i:i + a.batch]
            Zb, yb = Z[idx].astype(np.float32), y[idx]
            H, z = forward(Zb)
            g = (sigmoid(z) - yb) / len(idx)                    # dLoss/dz
            G = {"W2": H.T @ g + a.l2 * P["W2"], "b2": g.sum()}
            dH = np.outer(g, P["W2"]) * (H > 0)
            G["W1"] = Zb.T @ dH + a.l2 * P["W1"]
            G["b1"] = dH.sum(0)
            step += 1
            for k in P:
                M[k] = 0.9 * M[k] + 0.1 * G[k]
                S[k] = 0.999 * S[k] + 0.001 * G[k] ** 2
                mh = M[k] / (1 - 0.9 ** step)
                sh = S[k] / (1 - 0.999 ** step)
                P[k] = P[k] - a.lr * mh / (np.sqrt(sh) + 1e-8)
        zt = np.concatenate([forward(Z[te[j:j + 50000]].astype(np.float32))[1]
                             for j in range(0, len(te), 50000)])
        ll = logloss(sigmoid(zt), y[te])
        acc = float(np.mean((zt > 0) == (y[te] > 0.5)))
        print(f"epoch {ep + 1}: held-out log loss {ll:.4f}, accuracy {acc:.3f}", flush=True)
        if ll < best[0]:
            best = (ll, {k: v.copy() for k, v in P.items()}, acc)
    ll, P, acc = best
    lin = np.array(json.loads(Path(WEIGHTS).read_text())["weights"], dtype=np.float32)
    q = sigmoid(Xte[:, :len(lin)] @ lin)
    print(f"best: log loss {ll:.4f}, accuracy {acc:.3f}; linear score on the same positions: "
          f"log loss {logloss(q, y[te]):.4f}, accuracy {np.mean((q > .5) == (y[te] > .5)):.3f}; "
          f"{time.time() - t:.0f}s")
    np.savez_compressed(a.out, W1=P["W1"], b1=P["b1"], W2=P["W2"], b2=P["b2"], mu=mu, sd=sd, cols=cols, patterns=True)


if __name__ == "__main__":
    main()
