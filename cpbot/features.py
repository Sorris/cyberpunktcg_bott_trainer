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


def card_features(g, p) -> list[float]:
    """Which cards are in play: one slot per card in the database for p's board
    (field Units, their Gear and face-up Legends), the rival's board and p's hand."""
    n = len(g.db.cards)
    out = [0.0] * (3 * n)
    cards = g.cards
    for k, q in ((0, p), (1, 1 - p)):
        pl = g.players[q]
        for u in pl.field:
            out[k * n + cards[u].cid] += 1
            for x in cards[u].gears:
                out[k * n + cards[x].cid] += 1
        for u in pl.legends:
            if cards[u].face_up:
                out[k * n + cards[u].cid] += 1
                for x in cards[u].gears:
                    out[k * n + cards[x].cid] += 1
    for u in g.players[p].hand:
        out[2 * n + cards[u].cid] += 1
    return out


def card_names(db):
    return ([f"board:{c.title}" for c in db.cards] + [f"rival_board:{c.title}" for c in db.cards]
            + [f"hand:{c.title}" for c in db.cards])


class LearnedValue:
    """Win chance for player p from a logistic model over `features`."""

    def __init__(self, weights=None, path=WEIGHTS, pairs=None):
        data = {}
        if weights is None:
            data = json.loads(Path(path).read_text())
            weights = data["weights"]
        self.w = list(weights)
        names = data.get("names", [])
        self.pairs = pairs if pairs is not None else bool(names) and names[len(NAMES):len(NAMES) + len(PATTERN_NAMES)] == PATTERN_NAMES
        self.tactics = bool(names) and TACTIC_NAMES[0] in names
        known = len(NAMES) + (len(PATTERN_NAMES) if self.pairs else 0) + (len(TACTIC_NAMES) if self.tactics else 0)
        self.cards = len(self.w) > known                    # card-aware weights

    def __call__(self, g, p) -> float:
        if g.over:
            return 1.0 if g.winner == p else 0.5 if g.winner == "draw" else 0.0
        x = features(g, p)
        if self.pairs:
            x = x + pattern_features(g, p)
        if self.tactics:
            x = x + tactic_features(g, p)
        if self.cards:
            x = x + card_features(g, p)
        z = sum(a * b for a, b in zip(self.w, x))
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))


# ------------------------------------------------------------------ version 2
# Adds what Henry pointed out matters: Gig value patterns for both players, what's
# left in your own deck, and everything the rival has revealed (face-up Legends,
# so their colours and RAM, plus cards played and trashed). A small neural network
# (NetValue) can then learn combinations such as "even Gigs are good when I hold
# green even/odd payoffs", which a linear score can't.
from .cards import COLORS  # noqa: E402
from .deck import ram_limits  # noqa: E402


def _gig_pattern(g, q):
    pl = g.players[q]
    vals = [v for _, v in pl.gigs]
    n = len(vals)
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    return [
        n, (g.street_cred(q) or 0) / 10.0,
        sum(1 for v in vals if v % 2 == 0), sum(1 for v in vals if v % 2 == 1),
        sum(1 for s, v in pl.gigs if v == s), sum(1 for v in vals if v == 1),
        sum(c - 1 for c in counts.values()),                 # matching values
        sum(1 for v in vals if v >= 8), sum(1 for v in vals if v <= 3),
        max(vals, default=0) / 10.0, min(vals, default=0) / 10.0,
        len(pl.fixer), sum(pl.fixer) / 20.0, float(20 in pl.fixer),
    ]


GIG_NAMES = ["gigs", "cred/10", "even", "odd", "at_max", "at_min", "matching", "high8+", "low3-",
             "max/10", "min/10", "fixer_dice", "fixer_sides/20", "d20_left"]


def _ram(g, q, revealed_only):
    legs = [g.d(u) for u in g.players[q].legends + g.players[q].field + g.players[q].removed
            if g.d(u).type == "legend" and (g.cards[u].face_up or not revealed_only)]
    lim = ram_limits(legs)
    return [lim[c] / 3.0 for c in COLORS]


def features_v2_head(g, p) -> list[float]:
    """The counts at the start of features_v2, without the card blocks."""
    o = 1 - p
    head = [1.0, float(g.turn_player == p), float(g.overtime), g.turn_no / 10.0]
    head += _gig_pattern(g, p) + _gig_pattern(g, o)
    head += _side(g, p) + _side(g, o)
    head += _ram(g, p, revealed_only=False) + _ram(g, o, revealed_only=True)
    return head


def features_v2(g, p) -> list[float]:
    n = len(g.db.cards)
    cards = g.cards
    o = 1 - p
    head = features_v2_head(g, p)
    blocks = [0.0] * (5 * n)
    for k, q in ((0, p), (1, o)):
        pl = g.players[q]
        for u in pl.field:
            blocks[k * n + cards[u].cid] += 1
            for x in cards[u].gears:
                blocks[k * n + cards[x].cid] += 1
        for u in pl.legends:
            if cards[u].face_up:
                blocks[k * n + cards[u].cid] += 1
                for x in cards[u].gears:
                    blocks[k * n + cards[x].cid] += 1
    me, op = g.players[p], g.players[o]
    for u in me.hand:
        blocks[2 * n + cards[u].cid] += 1
    for u in me.deck:
        blocks[3 * n + cards[u].cid] += 1                  # you know your own decklist
    for u in op.trash + op.removed:
        blocks[4 * n + cards[u].cid] += 1                  # cards the rival has shown
    return head + blocks


def names_v2(db):
    head = ["bias", "my_turn", "overtime", "turn/10"]
    head += ["me:" + x for x in GIG_NAMES] + ["rival:" + x for x in GIG_NAMES]
    head += ["me:" + x for x in SIDE_NAMES] + ["rival:" + x for x in SIDE_NAMES]
    head += [f"me:ram_{c}" for c in COLORS] + [f"rival:revealed_ram_{c}" for c in COLORS]
    for blk in ("board", "rival_board", "hand", "my_deck", "rival_shown"):
        head += [f"{blk}:{c.title}" for c in db.cards]
    return head


NET_WEIGHTS = WEIGHTS.with_name("value_net.npz")


class NetValue:
    """Win chance from a one-hidden-layer network over features_v2."""

    def __init__(self, path=NET_WEIGHTS):
        import numpy as np
        z = np.load(path)
        self.np = np
        self.W1, self.b1, self.W2, self.b2 = z["W1"], z["b1"], z["W2"], float(z["b2"])
        self.mu, self.sd = z["mu"], z["sd"]
        self.cols = z["cols"] if "cols" in z.files else None        # a subset of features_v2
        self.patterns = bool(z["patterns"]) if "patterns" in z.files else False
        self.head = None

    def __call__(self, g, p) -> float:
        if g.over:
            return 1.0 if g.winner == p else 0.5 if g.winner == "draw" else 0.0
        np = self.np
        if self.head is None:
            self.head = len(names_v2(g.db)) - 5 * len(g.db.cards)
        if self.cols is not None and self.cols.max() < self.head:
            x = np.asarray(features_v2_head(g, p), dtype=np.float32)[self.cols]
        else:
            x = np.asarray(features_v2(g, p), dtype=np.float32)
            if self.cols is not None:
                x = x[self.cols]
        if self.patterns:
            x = np.concatenate([x, np.asarray(pattern_features(g, p), dtype=np.float32)])
        x = (x - self.mu) / self.sd
        h = np.maximum(x @ self.W1 + self.b1, 0.0)
        z = float(h @ self.W2) + self.b2
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))


# ------------------------------------------------------------------ Gig patterns
# Which Gigs are good depends on who can use them (Henry): blue wants min Gigs, red
# Gigs of 8+, green value-pairs, and yellow a range of different values. So each
# colour's pattern is scored together with what the player is known to have of that
# colour: its RAM (for the rival, from revealed Legends only) and its pay-off cards
# (for yourself your whole deck, for the rival only cards they've shown).
# Everything here can also be read back from features_v2 rows
# (pattern_features_from_v2), so old self-play data can be refitted with it.
PAYOFFS = {
    "blue": ("alt-cunningham-soulkiller-architect", "chrome-reverie", "jackie-welles-pour-one-out-for-me",
             "lucyna-kushinada-fresh-beginnings", "pyramid-song", "three-mouths-one-desire", "trust-no-one"),
    "red": ("carnage-at-the-colosseum", "industrial-assembly", "johnny-silverhand-rocking-renegade",
            "kerry-eurodyne-the-last-rockerboy", "octant", "v-roamer-of-the-badlands"),
    "green": ("hanako-arasaka-daughter-of-the-emperor", "pepe-najarro-working-doubles",
              "sandayu-oda-hanako-s-guardian", "goro-takemura-vengeful-bodyguard", "peace-offering"),
    "yellow": ("afterparty-at-lizzie-s", "bootleg-black-sapphire-show", "jackie-welles-ride-or-die-choom",
               "zetatech-faceplate"),
}
PATTERN = {"blue": "min_gigs", "red": "gigs_8+", "green": "pairs", "yellow": "different_values"}
PATTERN_NAMES = [f"{side}:{PATTERN[c]}*{what}" for side in ("me", "rival") for c in COLORS
                 for what in (c, "payoffs")]


def _patterns(pl):
    vals = [v for _, v in pl.gigs]
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    matching = sum(c - 1 for c in counts.values())
    return {"blue": sum(1 for v in vals if v == 1), "red": sum(1 for v in vals if v >= 8),
            "green": matching, "yellow": len(vals) - matching}


def _payoff_ids(db):
    ids = db.__dict__.get("_payoff_ids")
    if ids is None:
        ids = {c: frozenset(d.idx for d in db.cards if d.slug in PAYOFFS[c]) for c in COLORS}
        db.__dict__["_payoff_ids"] = ids
    return ids


def _board_cids(g, pl):
    cards = g.cards
    for u in pl.field:
        yield cards[u].cid
        for x in cards[u].gears:
            yield cards[x].cid
    for u in pl.legends:
        if cards[u].face_up:
            yield cards[u].cid
            for x in cards[u].gears:
                yield cards[x].cid


def _terms(pat, ram, pay):
    out = []
    for k, c in enumerate(COLORS):
        out += [pat[c] * float(ram[k] > 0), pat[c] * min(pay[c], 3) / 3.0]
    return out


def pattern_features(g, p) -> list[float]:
    ids = _payoff_ids(g.db)
    cards = g.cards
    me, op = g.players[p], g.players[1 - p]
    mine = list(_board_cids(g, me)) + [cards[u].cid for u in me.hand + me.deck]
    theirs = list(_board_cids(g, op)) + [cards[u].cid for u in op.trash + op.removed]
    pay_me = {c: sum(1 for x in mine if x in ids[c]) for c in COLORS}
    pay_op = {c: sum(1 for x in theirs if x in ids[c]) for c in COLORS}
    return (_terms(_patterns(me), _ram(g, p, revealed_only=False), pay_me)
            + _terms(_patterns(op), _ram(g, 1 - p, revealed_only=True), pay_op))


def pattern_features_from_v2(V, db):
    """The same numbers, computed from features_v2 rows (an n x 838 array)."""
    import numpy as np
    names = names_v2(db)
    n = len(db.cards)
    head = len(names) - 5 * n
    col = {x: i for i, x in enumerate(names[:head])}
    V = np.asarray(V, dtype=np.float32)
    ids = _payoff_ids(db)
    cols = []
    for side, ram, blocks in (("me", "ram", (0, 2, 3)), ("rival", "revealed_ram", (1, 4))):
        f = lambda x: V[:, col[f"{side}:{x}"]]  # noqa: E731
        matching = f("matching")
        pat = {"blue": f("at_min"), "red": f("high8+"), "green": matching, "yellow": f("gigs") - matching}
        for c in COLORS:
            idx = sorted(ids[c])
            pay = sum(V[:, head + k * n:head + (k + 1) * n][:, idx].sum(1) for k in blocks)
            cols += [pat[c] * (f(f"{ram}_{c}") > 0), pat[c] * np.minimum(pay, 3) / 3]
    return np.stack(cols, 1)


# ------------------------------------------------------------------ tactics
# Henry's attack-planning points as numbers the score can weigh: how many Gigs each
# side threatens to steal on its coming (or current) turn once the other side's ready
# Blockers soak up its biggest attacks, whether that steal would reach 7 Gigs, how
# many attackers would lose a fight to the best ready Blocker, and how many of the
# other side's rested Units it could defeat (Gig control vs defeating Units).
TACTIC_SIDE = ["steal_threat", "net_steal", "lethal", "blockers_faced", "max_blocker_faced/5",
               "outclassed", "killable"]
TACTIC_NAMES = ([f"me:{n}" for n in TACTIC_SIDE] + [f"rival:{n}" for n in TACTIC_SIDE]
                + ["me:gear_in_hand", "me:programs_in_hand", "me:quick_in_hand"])
WIN_GIGS = 7


def _tactic_side(g, q):
    cards = g.cards
    pq, pr = g.players[q], g.players[1 - q]
    now = g.turn_player == q
    att = []
    for u in pq.field:
        c = cards[u]
        if now and (c.spent or (c.lag and not g.has_kw(u, "adrenaline") and c.solo_turn != g.turn_no)):
            continue
        att.append(g.power(u))
    blk = [g.power(u) for u in pr.field if not cards[u].spent and g.has_kw(u, "blocker")]
    steals = sorted((p // 10 + 1 for p in att if p > 0), reverse=True)
    gross = min(sum(steals), len(pr.gigs))
    net = min(sum(steals[len(blk):]), len(pr.gigs))
    best_blk = max(blk, default=0)
    outclassed = sum(1 for p in att if p <= best_blk) if blk else 0
    top = max(att, default=0)
    killable = sum(1 for u in pr.field if cards[u].spent and g.power(u) < top)
    return [gross, net, float(len(pq.gigs) + net >= WIN_GIGS), len(blk), best_blk / 5.0,
            outclassed, killable]


def tactic_features(g, p) -> list[float]:
    """Attack-planning numbers for both sides, plus the pump cards in p's own hand."""
    gear = prog = quick = 0
    for u in g.players[p].hand:
        d = g.d(u)
        if d.type == "gear":
            gear += 1
        elif d.type == "program":
            prog += 1
            quick += d.has("quick")
    return _tactic_side(g, p) + _tactic_side(g, 1 - p) + [gear, prog, quick]
