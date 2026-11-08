"""Information Set Monte Carlo Tree Search (single-observer ISMCTS).

Each iteration samples one way the hidden cards could be (a "determinization"),
walks a shared tree of the searching player's and the rival's choices, plays a
short rollout and scores the position. Choices are keyed by the option itself,
so the same tree node collects statistics across all the sampled worlds.

What the agent is allowed to know:
- its own hand, its own known Legends and everything face-up;
- by default, the rival's decklist (as a player who has seen the deck would), but
  not which of those cards are in the rival's hand or where they are in the deck;
  with infer_rival=True it doesn't know the list either and guesses it from the
  revealed Legends (their RAM) and the cards it has seen;
- not the order of either deck and not future dice rolls (the random number
  generator is reseeded for every sample).

Simplification: the rival's face-down Legends keep their real identities in the
samples. Calling flips a random face-down Legend, so this only matters for the
few effects that look at a particular face-down Legend.
"""
from __future__ import annotations

import math
import random
import time

from .engine import Game

WIN_GIGS = 7


# --------------------------------------------------------------- evaluation
def heuristic(g: Game, p: int) -> float:
    """A rough score of how well player p is doing, positive = better."""
    me, op = g.players[p], g.players[1 - p]

    def side(pl, q):
        gigs = len(pl.gigs)
        cred = g.street_cred(q) or 0
        power = sum(g.power(u) for u in pl.field)
        ready_units = sum(1 for u in pl.field if not g.cards[u].spent)
        legends_up = sum(1 for u in pl.legends if g.cards[u].face_up)
        return (3.0 * gigs + 0.08 * cred + 0.25 * power + 0.3 * ready_units
                + 0.35 * len(pl.hand) + 0.3 * len(pl.eddies) + 0.4 * legends_up
                + (0.5 * gigs * gigs if gigs >= 5 else 0.0))

    return side(me, p) - side(op, 1 - p)


def value(g: Game, p: int, scale=0.35) -> float:
    """Win chance estimate for player p in [0, 1]."""
    if g.over:
        if g.winner == p:
            return 1.0
        if g.winner == "draw":
            return 0.5
        return 0.0
    return 1.0 / (1.0 + math.exp(-scale * heuristic(g, p)))


# ---------------------------------------------------------- determinization
def determinize(g: Game, p: int, rng: random.Random, infer_rival=False) -> Game:
    """A copy of g in which everything p can't see is resampled.

    With infer_rival=False the rival's hidden cards are their real decklist in a
    random order (p is assumed to know the list). With infer_rival=True p only
    uses what it has seen: the rival's face-down Legends become random Legends that
    fit with the revealed ones, and their hand and deck are redrawn from the cards
    those Legends' RAM allows, favouring cards and colours already seen.
    infer_rival="blind" is a baseline for testing that: hidden cards are drawn from
    every main deck card, ignoring RAM and what has been seen."""
    d = g.clone()
    d.rng = random.Random(rng.getrandbits(64))
    o = 1 - p
    op = d.players[o]
    if infer_rival:
        _infer_rival(d, o, rng, blind=infer_rival == "blind")
    pool = op.hand + op.deck
    rng.shuffle(pool)
    n = len(op.hand)
    op.hand[:] = pool[:n]
    op.deck[:] = pool[n:]
    for u in op.hand:
        d.cards[u].zone = "hand"
    for u in op.deck:
        d.cards[u].zone = "deck"
    rng.shuffle(d.players[p].deck)
    return d


def _infer_rival(d: Game, o: int, rng: random.Random, blind=False):
    from collections import Counter

    from .deck import MAX_COPIES, eligible_main_cards
    db = d.db
    op = d.players[o]
    cards = d.cards
    all_legends = [u for u, c in cards.items() if c.owner == o and db[c.cid].type == "legend"]
    shown_legends = [u for u in all_legends if cards[u].face_up or cards[u].zone in ("field", "removed")]
    hidden_legends = [u for u in all_legends if u not in shown_legends]
    names = set()
    for u in shown_legends:
        names |= db[cards[u].cid].names
    for u in hidden_legends:                       # random Legends that fit with the shown ones
        choices = [l for l in db.legends() if not (l.names & names)]
        pick = rng.choice(choices)
        cards[u].cid = pick.idx
        names |= pick.names
    legs = [db[cards[u].cid] for u in all_legends]
    hidden = op.hand + op.deck
    seen = Counter(cards[u].cid for u, c in cards.items()
                   if c.owner == o and u not in hidden and db[c.cid].type != "legend")
    seen_colors = {db[c].color for c in seen}
    if blind:
        pool = list(db.main_cards())
        weights = [1.0] * len(pool)
    else:
        pool = eligible_main_cards(legs, db)
        weights = [1.0 + (6.0 if seen.get(c.idx) else 0.0) + (1.5 if c.color in seen_colors else 0.0)
                   for c in pool]
    counts = Counter(seen)
    for u in hidden:
        for _ in range(50):
            c = rng.choices(pool, weights)[0]
            if counts[c.idx] < MAX_COPIES:
                break
        counts[c.idx] += 1
        cards[u].cid = c.idx


# ------------------------------------------------------------- tree search
class Node:
    __slots__ = ("parent", "move", "player", "children", "n", "w", "avail")

    def __init__(self, parent=None, move=None, player=None):
        self.parent = parent
        self.move = move          # the option that led here
        self.player = player      # who chose that option
        self.children = {}
        self.n = 0
        self.w = 0.0              # summed reward from `player`'s point of view
        self.avail = 0


def rollout_move(g: Game, rng: random.Random):
    """Cheap playout policy: random, but rarely pass while there's something to do."""
    d = g.decision
    opts = d.options
    if d.kind == "main":
        acts = [o for o in opts if o[0] != "pass"]
        attacks = [o for o in acts if o[0] == "attack"]
        if attacks and rng.random() < 0.6:
            return rng.choice(attacks)
        if acts and rng.random() < 0.85:
            return rng.choice(acts)
    if d.kind == "react" and rng.random() < 0.6:
        return ("end",)
    if d.kind == "mulligan":
        return False
    return rng.choice(opts)


class ISMCTSAgent:
    """Search for `iterations` samples (or `seconds`, if given) per decision."""

    def __init__(self, iterations=300, seconds=None, c=0.7, rollout_depth=20, seed=None,
                 scale=0.35, value_fn="learned", infer_rival=False):
        """value_fn(g, p) -> win chance in [0, 1] scores the end of each rollout.
        "learned" (the default) uses the score fitted on self-play games
        (cpbot.features.LearnedValue); "hand" uses the hand-made `value`, which
        works best with longer rollouts (about 60)."""
        if value_fn == "learned":
            from .features import LearnedValue
            value_fn = LearnedValue()
        elif value_fn == "hand":
            value_fn = (lambda g, p: value(g, p, scale))
        self.value_fn = value_fn
        self.infer_rival = infer_rival
        self.iterations = iterations
        self.seconds = seconds
        self.c = c
        self.rollout_depth = rollout_depth
        self.scale = scale
        self.rng = random.Random(seed)
        self.last_stats = None

    def act(self, game: Game):
        d = game.decision
        if len(d.options) == 1:
            return d.options[0]
        if d.kind == "go_first":
            return True
        root_player = d.player
        root = Node()
        deadline = time.time() + self.seconds if self.seconds else None
        it = 0
        while True:
            if deadline is not None:
                if time.time() >= deadline:
                    break
            elif it >= self.iterations:
                break
            self._iterate(game, root, root_player)
            it += 1
        legal = set(d.options)
        best = max((ch for m, ch in root.children.items() if m in legal),
                   key=lambda ch: (ch.n, ch.w))
        self.last_stats = {"iterations": it, "kind": d.kind,
                           "moves": sorted(((ch.n, round(ch.w / max(ch.n, 1), 3), m)
                                            for m, ch in root.children.items()), reverse=True)}
        return best.move

    def _iterate(self, game, root, root_player):
        rng = self.rng
        g = determinize(game, root_player, rng, self.infer_rival)
        node = root
        # Selection and expansion
        while not g.over:
            dec = g.decision
            opts = dec.options
            who = dec.player
            for o in opts:
                ch = node.children.get(o)
                if ch is not None:
                    ch.avail += 1
            untried = [o for o in opts if o not in node.children]
            if untried:
                move = rng.choice(untried)
                child = Node(node, move, who)
                child.avail = 1
                node.children[move] = child
                g.step(move)
                node = child
                break
            best, best_s = None, -1.0
            for o in opts:
                ch = node.children[o]
                s = ch.w / ch.n + self.c * math.sqrt(math.log(ch.avail) / ch.n)
                if s > best_s:
                    best, best_s = ch, s
            g.step(best.move)
            node = best
        # Rollout
        k = 0
        while not g.over and k < self.rollout_depth:
            g.step(rollout_move(g, rng))
            k += 1
        v0 = self.value_fn(g, 0)
        # Backpropagation
        while node is not None and node.player is not None:
            node.n += 1
            node.w += v0 if node.player == 0 else 1.0 - v0
            node = node.parent
        root.n += 1
