"""Search agent and the fast clone it relies on."""
import random

from cpbot import Game, default_db, random_deck
from cpbot.agents import EagerRandomAgent, RandomAgent
from cpbot.search import ISMCTSAgent, determinize

db = default_db()


def _midgame(seed, steps=30):
    rng = random.Random(seed)
    decks = [random_deck(rng, db), random_deck(rng, db)]
    g = Game(decks[0], decks[1], seed=seed, db=db)
    a = EagerRandomAgent(seed)
    for _ in range(steps):
        if g.over:
            break
        g.step(a.act(g))
    return g


def _state(g):
    return (repr(sorted((u, vars(c)) for u, c in g.cards.items())), repr([vars(p) for p in g.players]),
            repr(g.stack), repr(g.pending), repr(g.lasting), g.turn_no, g.winner)


def test_playing_a_clone_leaves_the_original_alone():
    for seed in range(20):
        g = _midgame(seed)
        before = _state(g)
        c = g.clone()
        a = EagerRandomAgent(seed + 50)
        while not c.over:
            c.step(a.act(c))
        assert _state(g) == before


def test_clone_plays_out_like_the_original():
    for seed in range(20):
        g = _midgame(seed)
        c = g.clone()
        for x in (g, c):
            a = EagerRandomAgent(seed + 99)
            while not x.over:
                x.step(a.act(x))
        assert (g.winner, g.turn_no, g.history) == (c.winner, c.turn_no, c.history)


def test_determinize_hides_rival_hand_and_dice():
    g = _midgame(3)
    p = g.decision.player
    o = 1 - p
    hands = set()
    for i in range(20):
        d = determinize(g, p, random.Random(i))
        assert d.players[p].hand == g.players[p].hand                 # own hand known
        assert len(d.players[o].hand) == len(g.players[o].hand)
        assert sorted(d.players[o].hand + d.players[o].deck) == sorted(g.players[o].hand + g.players[o].deck)
        assert all(d.cards[u].zone == "hand" for u in d.players[o].hand)
        hands.add(tuple(sorted(d.players[o].hand)))
        assert d.rng.getstate() != g.rng.getstate()                   # future rolls unknown
    assert len(hands) > 1


def test_search_agent_beats_random():
    wins = 0
    for seed in range(4):
        rng = random.Random(seed)
        decks = [random_deck(rng, db), random_deck(rng, db)]
        g = Game(decks[0], decks[1], seed=seed, db=db)
        seat = seed % 2
        agents = [None, None]
        agents[seat] = ISMCTSAgent(iterations=40, rollout_depth=30, seed=seed)
        agents[1 - seat] = RandomAgent(seed)
        while not g.over:
            g.step(agents[g.current_player].act(g))
        wins += g.winner == seat
    assert wins >= 3
