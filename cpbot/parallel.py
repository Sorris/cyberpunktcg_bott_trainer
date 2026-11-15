"""Think on several cores at once (root parallelism).

ParallelISMCTSAgent runs one ISMCTSAgent search per worker process on the same
position, each with its own random seed and its own sampled guesses at hidden cards,
then adds up how often each worker tried each move and how well it did. With N cores
this gives roughly N times the samples in the same wall-clock time, and Henry's
arena showed more samples is what makes the bot stronger (1 s beats 0.3 s 66%).

Only worth it when one game has the machine to itself (the play page). Arena runs and
self-play already use every core by playing several games at once.
"""
from __future__ import annotations

import multiprocessing as mp
import pickle
import random

from .search import ISMCTSAgent, sensible_options

_W = {}
_POOLS = {}


def _init(kw):
    from . import effects
    effects.load_scripts()             # unpickled games skip Game.__init__, which loads them
    _W["agent"] = ISMCTSAgent(**kw)


def _search(job):
    blob, seed = job
    g = pickle.loads(blob)
    ag = _W["agent"]
    ag.rng = random.Random(seed)
    ag._kept = None
    ag.act(g)
    st = ag.last_stats or {"moves": [], "iterations": 0}
    return st["iterations"], [(m, n, w) for n, w, m in st["moves"]]


class ParallelISMCTSAgent:
    """Like ISMCTSAgent(seconds=...), searching on `workers` processes at once."""

    def __init__(self, workers=None, seed=None, **kw):
        self.workers = workers or max(1, (mp.cpu_count() or 2) - 1)
        self.kw = dict(kw, reuse=False)
        self.rng = random.Random(seed)
        self.pool = None
        self.local = ISMCTSAgent(iterations=1, **{k: v for k, v in kw.items() if k not in ("seconds", "iterations")})
        self.last_stats = None

    def _pool(self):
        # Pools are shared by agents with the same settings, so starting a new game
        # doesn't start (and leak) another set of worker processes.
        if self.pool is None:
            key = (self.workers, repr(sorted(self.kw.items())))
            if key not in _POOLS:
                _POOLS[key] = mp.get_context("spawn").Pool(self.workers, initializer=_init, initargs=(self.kw,))
            self.pool = _POOLS[key]
        return self.pool

    def act(self, game):
        d = game.decision
        if len(d.options) == 1:
            return d.options[0]
        if d.kind == "go_first":
            return True
        opts = sensible_options(game) if self.local.prune else d.options
        if len(opts) == 1:
            return opts[0]
        g = game.clone()
        g.observer = None
        g.logging = False
        blob = pickle.dumps(g)
        jobs = [(blob, self.rng.randrange(1 << 30)) for _ in range(self.workers)]
        total = {}
        its = 0
        for it, moves in self._pool().map(_search, jobs):
            its += it
            for m, n, w in moves:
                a = total.setdefault(m, [0, 0.0])
                a[0] += n
                a[1] += n * w                      # w is the mean result for that move
        legal = set(d.options)
        cands = [(n, s, m) for m, (n, s) in total.items() if m in legal]
        if not cands:
            return self.rng.choice(opts)
        n, s, best = max(cands, key=lambda t: (t[0], t[1]))
        self.last_stats = {"iterations": its, "kind": d.kind,
                           "moves": sorted(((n, round(s / max(n, 1), 3), m) for n, s, m in cands), reverse=True)}
        return best


def close_pools():
    for pool in _POOLS.values():
        pool.terminate()
    _POOLS.clear()
