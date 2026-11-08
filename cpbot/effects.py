"""Card-effect registry.

The engine calls into ``REGISTRY`` at fixed hook points. With nothing
registered, every card plays as a vanilla card: stats and printed keywords
(Blocker, Quick on Programs, Adrenaline, Go Solo) only.

Milestone 3 fills this in with one script per card. A script registers
handlers keyed by card slug, for example::

    @REGISTRY.on("play", "some-card-slug")
    def _(game, ctx): ...
"""
from __future__ import annotations

from collections import defaultdict


class EffectRegistry:
    def __init__(self):
        self.handlers = defaultdict(list)   # (event, slug) -> [fn]
        self.funcs = {}                      # name -> fn, for ("call", name, ...) tasks
        self.scripted: set[str] = set()

    # ---- registration
    def on(self, event, slug):
        def deco(fn):
            self.handlers[(event, slug)].append(fn)
            self.scripted.add(slug)
            return fn
        return deco

    def func(self, name):
        def deco(fn):
            self.funcs[name] = fn
            return fn
        return deco

    # ---- engine hooks (all no-ops / defaults until cards are scripted)
    def on_event(self, game, event, ctx):
        if not self.handlers:
            return
        for c in list(game.cards.values()):
            fns = self.handlers.get((event, game.db[c.cid].slug))
            if fns:
                for fn in fns:
                    fn(game, c.uid, ctx)

    def run(self, game, name, args):
        self.funcs[name](game, *args)

    def grants_keyword(self, game, uid, kw) -> bool:
        return False

    def modify_cost(self, game, player, uid, cost) -> int:
        return cost

    def may_play(self, game, player, uid) -> bool:
        return True

    def may_attack(self, game, uid) -> bool:
        return True

    def can_attack_ready(self, game, atk, target) -> bool:
        return False

    def activated_options(self, game, player, reaction: bool) -> list:
        return []

    def activate(self, game, player, act):
        raise NotImplementedError(act)

    def replace_defeat(self, game, uid):
        return None

    def prevent_fight_defeat(self, game, uid) -> bool:
        return False

    def steal_power(self, game, atk, power) -> int:
        return power

    def allow_steal(self, game, attack, gig) -> bool:
        return True

    def end_turn_cleanup(self, game):
        pass


REGISTRY = EffectRegistry()
