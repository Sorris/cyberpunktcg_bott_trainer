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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", default=["selfplay/round5"])
    ap.add_argument("--out", default=str(POLICY_WEIGHTS))
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--sharpen", type=float, default=3.0,
                    help="target is visits**sharpen, normalised; higher leans towards the search's top move")
    ap.add_argument("--l2", type=float, default=1e-5)
    a = ap.parse_args()
    t = time.time()
    idx, val, nnz_opt, sizes, n, test = load(a.data)
    tr, te = (Data(idx, val, nnz_opt, sizes, n, k, a.sharpen) for k in (~test, test))
    print(f"{len(sizes)} decisions ({int(test.sum())} held out), {len(n)} options, {time.time() - t:.0f}s")
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
