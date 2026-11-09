"""Train the move-choosing policy (cpbot.policy) on self-play records.

    python scripts/train_policy.py --data selfplay/round5 --out data/policy_weights.json

Reads the per-option records written by scripts/selfplay.py (p_idx/p_val/p_opt/
p_grp/p_n): each decision's options, their sparse features and how often the
search tried each one. Fits a softmax over options to the share of visits, holds
out every tenth game, and prints how often the policy's top move matches the
search's.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot.policy import DIM, POLICY_WEIGHTS  # noqa: E402


def load(folders):
    idx, val, nnz_opt, grp_sizes, n, test = [], [], [], [], [], []
    for folder in folders:
        for f in sorted(Path(folder).glob("*.npz")):
            z = np.load(f)
            if "p_n" not in z.files or len(z["p_n"]) == 0:
                continue
            idx.append(z["p_idx"].astype(np.int32))
            val.append(z["p_val"].astype(np.float32))
            nnz_opt.append(np.diff(z["p_opt"]))
            g = np.diff(z["p_grp"])
            grp_sizes.append(g)
            n.append(z["p_n"])
            test.append(np.full(len(g), int(z["seed"]) % 10 == 0))
    return (np.concatenate(idx), np.concatenate(val), np.concatenate(nnz_opt),
            np.concatenate(grp_sizes), np.concatenate(n), np.concatenate(test))


class Data:
    def __init__(self, idx, val, nnz_opt, sizes, n, keep, sharpen=1.0):
        """Keep only the decisions where keep is True."""
        opt_start = np.concatenate([[0], np.cumsum(nnz_opt)])
        grp_start = np.concatenate([[0], np.cumsum(sizes)])
        opts = np.concatenate([np.arange(grp_start[k], grp_start[k + 1]) for k in np.where(keep)[0]])
        self.sizes = sizes[keep]
        lens = nnz_opt[opts]
        sel = np.concatenate([np.arange(opt_start[o], opt_start[o + 1]) for o in opts])
        self.idx, self.val = idx[sel], val[sel]
        self.opt_of = np.repeat(np.arange(len(opts)), lens)          # option row of each nonzero
        self.n_opt = len(opts)
        self.grp_of = np.repeat(np.arange(len(self.sizes)), self.sizes)
        t = n[opts].astype(np.float64) ** sharpen
        tot = np.bincount(self.grp_of, t, minlength=len(self.sizes))
        self.target = t / np.maximum(tot[self.grp_of], 1e-9)

    def probs(self, w):
        s = np.bincount(self.opt_of, w[self.idx] * self.val, minlength=self.n_opt)
        m = np.full(len(self.sizes), -np.inf)
        np.maximum.at(m, self.grp_of, s)
        e = np.exp(s - m[self.grp_of])
        z = np.bincount(self.grp_of, e, minlength=len(self.sizes))
        return e / z[self.grp_of], s

    def loss_grad(self, w, l2):
        p, _ = self.probs(w)
        loss = -np.sum(self.target * np.log(np.maximum(p, 1e-12))) / len(self.sizes)
        coef = (p - self.target)[self.opt_of] * self.val
        grad = np.bincount(self.idx, coef, minlength=len(w)) / len(self.sizes) + l2 * w
        return loss + 0.5 * l2 * float(w @ w), grad

    def agree(self, w):
        """Share of decisions where the policy's top option (first one on ties) is
        one of the search's most-visited options."""
        _, s = self.probs(w)
        start = np.concatenate([[0], np.cumsum(self.sizes)])
        hits = 0
        for a, b in zip(start[:-1], start[1:]):
            k = a + int(np.argmax(s[a:b]))
            hits += self.target[k] >= self.target[a:b].max() - 1e-12
        return hits / len(self.sizes)


def train_mlp(tr, te, hidden, epochs, lr, l2, batch, seed, log):
    """Score = w2 . relu(x W1 + b1) per option, softmax per decision; minibatch Adam."""
    rng = np.random.default_rng(seed)
    P = {"W1": rng.normal(0, 0.1, (DIM, hidden)).astype(np.float32), "b1": np.zeros(hidden, np.float32),
         "w2": rng.normal(0, 0.1, hidden).astype(np.float32)}
    M = {k: np.zeros_like(v) for k, v in P.items()}
    S = {k: np.zeros_like(v) for k, v in P.items()}
    gstart = np.concatenate([[0], np.cumsum(tr.sizes)])          # option range of each decision
    ostart = np.concatenate([[0], np.cumsum(np.bincount(tr.opt_of, minlength=tr.n_opt))])
    step = 0

    def forward(d, opts_lo, opts_hi, nz_lo, nz_hi):
        idx, val = d.idx[nz_lo:nz_hi], d.val[nz_lo:nz_hi]
        rows = d.opt_of[nz_lo:nz_hi] - opts_lo
        n = opts_hi - opts_lo
        A = np.zeros((n, hidden), np.float32)
        np.add.at(A, rows, val[:, None] * P["W1"][idx])
        A += P["b1"]
        H = np.maximum(A, 0)
        return idx, val, rows, A, H, H @ P["w2"]

    def softmax_groups(sc, grp):
        m = np.full(grp.max() + 1, -np.inf)
        np.maximum.at(m, grp, sc)
        e = np.exp(sc - m[grp])
        z = np.bincount(grp, e)
        return e / z[grp]

    for ep in range(epochs):
        order = rng.permutation(len(tr.sizes) // batch + 1)
        for b in order:
            g0, g1 = b * batch, min(len(tr.sizes), (b + 1) * batch)
            if g0 >= g1:
                continue
            o0, o1 = gstart[g0], gstart[g1]
            idx, val, rows, A, H, sc = forward(tr, o0, o1, ostart[o0], ostart[o1])
            grp = tr.grp_of[o0:o1] - g0
            p = softmax_groups(sc, grp)
            ds = (p - tr.target[o0:o1]).astype(np.float32) / (g1 - g0)
            G = {"w2": H.T @ ds + l2 * P["w2"]}
            dA = np.outer(ds, P["w2"]) * (A > 0)
            G["b1"] = dA.sum(0)
            gW = np.zeros_like(P["W1"])
            np.add.at(gW, idx, val[:, None] * dA[rows])
            G["W1"] = gW + l2 * P["W1"]
            step += 1
            for k in P:
                M[k] = 0.9 * M[k] + 0.1 * G[k]
                S[k] = 0.999 * S[k] + 0.001 * G[k] ** 2
                P[k] -= lr * (M[k] / (1 - 0.9 ** step)) / (np.sqrt(S[k] / (1 - 0.999 ** step)) + 1e-8)
        _, _, _, _, _, sc = forward(te, 0, te.n_opt, 0, len(te.idx))
        p = softmax_groups(sc, te.grp_of)
        loss = -np.sum(te.target * np.log(np.maximum(p, 1e-12))) / len(te.sizes)
        start = np.concatenate([[0], np.cumsum(te.sizes)])
        hits = sum(te.target[a + int(np.argmax(sc[a:b]))] >= te.target[a:b].max() - 1e-12
                   for a, b in zip(start[:-1], start[1:]))
        log(f"epoch {ep + 1}: held-out {loss:.4f}, top move matches the search {hits / len(te.sizes):.3f}")
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", default=["selfplay/round5"])
    ap.add_argument("--out", default=str(POLICY_WEIGHTS))
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--sharpen", type=float, default=3.0,
                    help="target is visits**sharpen, normalised; higher leans towards the search's top move")
    ap.add_argument("--hidden", type=int, default=0, help="hidden units for a small network (0 = linear)")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=256, help="decisions per step (network only)")
    ap.add_argument("--l2", type=float, default=1e-5)
    a = ap.parse_args()
    t = time.time()
    idx, val, nnz_opt, sizes, n, test = load(a.data)
    tr, te = (Data(idx, val, nnz_opt, sizes, n, k, a.sharpen) for k in (~test, test))
    print(f"{len(sizes)} decisions ({int(test.sum())} held out), {len(n)} options, {time.time() - t:.0f}s")
    if a.hidden:
        P = train_mlp(tr, te, a.hidden, a.epochs, a.lr if a.lr != 0.05 else 3e-3, a.l2, a.batch, 0,
                      lambda msg: print(msg, flush=True))
        out = Path(a.out).with_suffix(".npz")
        np.savez_compressed(out, **P)
        print(f"saved {out}")
        return
    w = np.zeros(DIM)
    m, v = np.zeros(DIM), np.zeros(DIM)
    for k in range(1, a.steps + 1):
        loss, g = tr.loss_grad(w, a.l2)
        m = 0.9 * m + 0.1 * g
        v = 0.999 * v + 0.001 * g * g
        w -= a.lr * (m / (1 - 0.9 ** k)) / (np.sqrt(v / (1 - 0.999 ** k)) + 1e-8)
        if k % 50 == 0 or k == a.steps:
            tl, _ = te.loss_grad(w, 0)
            print(f"step {k}: train {loss:.4f}, held-out {tl:.4f}, top move matches the search "
                  f"{te.agree(w):.3f} (uniform {te.agree(np.zeros(DIM)):.3f})", flush=True)
    Path(a.out).write_text(json.dumps({
        "about": "Linear softmax move policy over cpbot.policy.move_features; fitted by scripts/train_policy.py",
        "data": a.data, "decisions": int(len(sizes)), "weights": [round(float(x), 5) for x in w]}))


if __name__ == "__main__":
    main()
