"""Simple agents. Search-based and learned agents come in later milestones."""
from __future__ import annotations

import random


class RandomAgent:
    """Uniformly random legal option. Used to shake out engine bugs."""
    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def act(self, game):
        return self.rng.choice(game.decision.options)


class EagerRandomAgent(RandomAgent):
    """Random, but only passes when nothing else is possible; reaches more game states."""
    def act(self, game):
        opts = game.decision.options
        if game.decision.kind == "main":
            non_pass = [o for o in opts if o[0] != "pass"]
            if non_pass and self.rng.random() < 0.9:
                return self.rng.choice(non_pass)
        if game.decision.kind == "react":
            if self.rng.random() < 0.5:
                return ("end",)
        return self.rng.choice(opts)


def play_game(game, agents, max_decisions=20000, check=False):
    n = 0
    while not game.over:
        a = agents[game.current_player]
        game.step(a.act(game))
        n += 1
        if check:
            game.check_invariants()
        if n > max_decisions:
            raise RuntimeError("decision limit exceeded (engine loop?)")
    return game.winner
