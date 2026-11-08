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

from cpbot.features import NET_WEIGHTS, WEIGHTS  # noqa: E402


def load(folders, max_files=None):
    V, X, y, seed, src = [], [], [], [], []
    for k, folder in enumerate(folders):
        for f in sorted(Path(folder).glob("*.npz"))[:max_files]:
            z = np.load(f)
            if "V" not in z.files or len(z["y"]) == 0:
                continue
            V.append(z["V"])
            X.append(z["X"].astype(np.float32))
            y.append(z["y"].astype(np.float32))
            seed.append(np.full(len(z["y"]), int(z["seed"])))
            src.append(np.full(len(z["y"]), k))
    return (np.concatenate(V), np.concatenate(X), np.concatenate(y), np.concatenate(seed),
            np.concatenate(src))


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
    ap.add_argument("--max-files", type=int, default=None, help="games to read per folder")
    a = ap.parse_args()
    t = time.time()
    V, X, y, seed, src = load(a.data, a.max_files)
    test = (seed % 10 == 0) & (src == 0)        # judge on held-out games from the first folder
    mu = V[~test].astype(np.float32).mean(0)
    sd = V[~test].astype(np.float32).std(0) + 1e-3
    Z = np.empty(V.shape, np.float32)
    for i in range(0, len(V), 50000):
        Z[i:i + 50000] = (V[i:i + 50000].astype(np.float32) - mu) / sd
    shape = V.shape
    del V
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
            Zb, yb = Z[idx], y[idx]
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
        _, zt = forward(Z[te])
        ll = logloss(sigmoid(zt), y[te])
        acc = float(np.mean((zt > 0) == (y[te] > 0.5)))
        print(f"epoch {ep + 1}: held-out log loss {ll:.4f}, accuracy {acc:.3f}", flush=True)
        if ll < best[0]:
            best = (ll, {k: v.copy() for k, v in P.items()}, acc)
    ll, P, acc = best
    lin = np.array(json.loads(Path(WEIGHTS).read_text())["weights"], dtype=np.float32)
    q = sigmoid(X[te][:, :len(lin)] @ lin)
    print(f"best: log loss {ll:.4f}, accuracy {acc:.3f}; linear score on the same positions: "
          f"log loss {logloss(q, y[te]):.4f}, accuracy {np.mean((q > .5) == (y[te] > .5)):.3f}; "
          f"{time.time() - t:.0f}s")
    np.savez_compressed(a.out, W1=P["W1"], b1=P["b1"], W2=P["W2"], b2=P["b2"], mu=mu, sd=sd)


if __name__ == "__main__":
    main()
