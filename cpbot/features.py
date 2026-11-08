"""Position features and a learned position score.

`features(g, p)` describes the position from player p's side as a short vector of
numbers. `LearnedValue` turns that into a win chance with a logistic model fitted
on self-play games (scripts/learn_value.py). The weights live in
data/value_weights.json, so retraining doesn't touch code.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

WEIGHTS = Path(__file__).resolve().parent.parent / "data" / "value_weights.json"


def _side(g, q):
    pl = g.players[q]
    cards = g.cards
    gigs = len(pl.gigs)
    cred = g.street_cred(q) or 0
    powers = [g.power(u) for u in pl.field]
    ready = [x for u, x in zip(pl.field, powers) if not cards[u].spent]
    eddies_ready = sum(1 for u in pl.eddies if not cards[u].spent)
    up = sum(1 for u in pl.legends if cards[u].face_up)
    down = len(pl.legends) - up
    gears = sum(len(cards[u].gears) for u in pl.field) + sum(len(cards[u].gears) for u in pl.legends)
    low_gigs = sum(1 for s, v in pl.gigs if v <= 3)
    return [
        gigs, float(gigs >= 4), float(gigs >= 5), float(gigs >= 6),
        cred / 10.0,
        len(pl.field), sum(powers) / 5.0, (max(powers) if powers else 0) / 5.0,
        len(ready), sum(ready) / 5.0,
        len(pl.hand), len(pl.eddies), eddies_ready,
        up, down, gears,
        len(pl.fixer), low_gigs,
        len(pl.deck) / 10.0,
    ]


SIDE_NAMES = ["gigs", "gigs>=4", "gigs>=5", "gigs>=6", "cred/10", "units", "power/5",
              "max_power/5", "ready_units", "ready_power/5", "hand", "eddies", "eddies_ready",
              "legends_up", "legends_down", "gears", "fixer_dice", "low_gigs", "deck/10"]
NAMES = (["bias", "my_turn", "overtime"] + ["me:" + n for n in SIDE_NAMES]
         + ["rival:" + n for n in SIDE_NAMES])


def features(g, p) -> list[float]:
    """Player p's view of the position (both sides' public counts)."""
    return ([1.0, float(g.turn_player == p), float(g.overtime)]
            + _side(g, p) + _side(g, 1 - p))


class LearnedValue:
    """Win chance for player p from a logistic model over `features`."""

    def __init__(self, weights=None, path=WEIGHTS):
        if weights is None:
            data = json.loads(Path(path).read_text())
            weights = data["weights"]
        self.w = list(weights)

    def __call__(self, g, p) -> float:
        if g.over:
            return 1.0 if g.winner == p else 0.5 if g.winner == "draw" else 0.0
        x = features(g, p)
        z = sum(a * b for a, b in zip(self.w, x))
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))
