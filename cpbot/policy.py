"""A learned move-choosing policy: which of the options in front of the bot the
search tends to prefer.

Each option gets a small sparse feature vector (`move_features`): what kind of
decision and move it is, which card it involves (so the bot can learn which cards
to sell, play or keep), and for attacks how the fight looks. The policy scores
each option with a weight vector and turns the scores into chances with a softmax.
It's trained (scripts/train_policy.py) on self-play records of how often the
search visited each option, and used by the search to guide its playouts and its
tree (cpbot.search, policy=...).
"""
from __future__ import annotations

import json
import math
import random
import zlib
from pathlib import Path

POLICY_WEIGHTS = Path(__file__).resolve().parent.parent / "data" / "policy_weights.json"

N_KIND = 256          # hashed (decision kind, move kind) buckets
N_CARDS = 160         # card slots per role (the database has 152 cards)
ROLES = ("play", "sell", "activate", "attacker", "target", "pay", "other")
CTX = ("eddies", "hand", "gigs", "rival_gigs", "turn", "units", "rival_units")
OFF_CARD = N_KIND
OFF_ATK = OFF_CARD + len(ROLES) * N_CARDS
ATK = ("gigs", "win", "tie", "lose", "margin", "power", "blocked")
OFF_CTX = OFF_ATK + len(ATK)
N_CTX_KIND = 32       # move kinds crossed with context numbers
DIM = OFF_CTX + N_CTX_KIND * len(CTX)

_hash_cache: dict = {}


def _bucket(s: str, n: int) -> int:
    b = _hash_cache.get((s, n))
    if b is None:
        b = zlib.crc32(s.encode()) % n
        _hash_cache[(s, n)] = b
    return b


def _head(opt):
    if isinstance(opt, tuple) and opt:
        return str(opt[0])
    if isinstance(opt, bool):
        return "yes" if opt else "no"
    if isinstance(opt, int):
        return "int"
    return str(opt)


def _context(g, p):
    me, op = g.players[p], g.players[1 - p]
    ready = sum(1 for u in me.eddies if not g.cards[u].spent)
    return [ready / 5.0, len(me.hand) / 5.0, len(me.gigs) / 5.0, len(op.gigs) / 5.0,
            g.turn_no / 10.0, len(me.field) / 3.0, len(op.field) / 3.0]


def move_features(g, d, opt, ctx=None):
    """Sparse features of one option: a list of (index, value)."""
    kind = d.kind.split(":")[0] if not d.kind.startswith("may:") else d.kind
    head = _head(opt)
    out = [(_bucket(kind + "|" + head, N_KIND), 1.0)]
    cards = g.cards

    def card(role, cid):
        if cid is not None and 0 <= cid < N_CARDS:
            out.append((OFF_CARD + ROLES.index(role) * N_CARDS + cid, 1.0))

    if isinstance(opt, tuple) and len(opt) >= 2:
        a = opt[1]
        if kind == "main" and head in ("play", "sell"):
            if head == "play":
                card("play", a)
            else:
                card("sell", cards[a].cid if a in cards else None)
        elif head == "activate":
            card("activate", cards[a].cid if a in cards else None)
        elif head == "attack":
            card("attacker", cards[a].cid)
            pa = g.power(a)
            t = opt[2]
            if t[0] == "unit":
                card("target", cards[t[1]].cid)
                m = pa - g.power(t[1])
                out.append((OFF_ATK + ATK.index("win" if m > 0 else "tie" if m == 0 else "lose"), 1.0))
                out.append((OFF_ATK + ATK.index("margin"), max(-10, min(10, m)) / 5.0))
            else:
                out.append((OFF_ATK + ATK.index("gigs"), 1.0))
                rival = g.players[1 - d.player]
                if any(not cards[u].spent and g.has_kw(u, "blocker") and g.power(u) >= pa for u in rival.field):
                    out.append((OFF_ATK + ATK.index("blocked"), 1.0))
            out.append((OFF_ATK + ATK.index("power"), pa / 10.0))
        elif head in ("legend", "block", "unit", "deploy", "solo", "equip") and isinstance(a, int) and a in cards:
            card("pay" if kind == "pay" else "target" if head in ("unit", "block") else "other", cards[a].cid)
        elif head == "card" and isinstance(a, int):
            card("other", a)
    if ctx is None:
        ctx = _context(g, d.player)
    k = _bucket(kind + "|" + head, N_CTX_KIND)
    base = OFF_CTX + k * len(CTX)
    out.extend((base + i, v) for i, v in enumerate(ctx) if v)
    return out


class Policy:
    """Chances for each option, from a linear score over move_features."""

    def __init__(self, path=POLICY_WEIGHTS, weights=None):
        if weights is None:
            weights = json.loads(Path(path).read_text())["weights"]
        self.w = list(weights)

    def scores(self, g, d):
        ctx = _context(g, d.player)
        w = self.w
        return [sum(w[i] * v for i, v in move_features(g, d, o, ctx)) for o in d.options]

    def probs(self, g, d):
        s = self.scores(g, d)
        m = max(s)
        e = [math.exp(x - m) for x in s]
        t = sum(e)
        return [x / t for x in e]

    def sample(self, g, rng: random.Random):
        d = g.decision
        if len(d.options) == 1:
            return d.options[0]
        return rng.choices(d.options, self.probs(g, d))[0]
