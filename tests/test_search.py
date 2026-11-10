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
        agents[seat] = ISMCTSAgent(iterations=40, rollout_depth=30, seed=seed, value_fn="hand")
        agents[1 - seat] = RandomAgent(seed)
        while not g.over:
            g.step(agents[g.current_player].act(g))
        wins += g.winner == seat
    assert wins >= 3


def test_learned_value_is_symmetric_and_in_range():
    from cpbot.features import NAMES, PATTERN_NAMES, LearnedValue, features
    lv = LearnedValue()
    assert lv.pairs and len(lv.w) == len(NAMES) + len(PATTERN_NAMES)
    for seed in range(10):
        g = _midgame(seed, steps=40)
        assert len(features(g, 0)) == len(NAMES)
        v0, v1 = lv(g, 0), lv(g, 1)
        assert 0.0 <= v0 <= 1.0
        if not g.over:
            # The model is fitted on both players' views, so the two views roughly agree.
            assert abs(v0 + v1 - 1.0) < 0.35


def test_search_agent_with_learned_value_beats_random():
    from cpbot.features import LearnedValue
    wins = 0
    for seed in range(4):
        rng = random.Random(seed + 10)
        decks = [random_deck(rng, db), random_deck(rng, db)]
        g = Game(decks[0], decks[1], seed=seed, db=db)
        seat = seed % 2
        agents = [None, None]
        agents[seat] = ISMCTSAgent(iterations=40, rollout_depth=10, seed=seed, value_fn=LearnedValue())
        agents[1 - seat] = RandomAgent(seed)
        while not g.over:
            g.step(agents[g.current_player].act(g))
        wins += g.winner == seat
    assert wins >= 3


def test_inferred_rival_cards_are_plausible():
    from collections import Counter

    from cpbot.deck import ram_limits
    for seed in range(8):
        g = _midgame(seed, steps=60)
        if g.over:
            continue
        p = g.decision.player
        o = 1 - p
        shown = {u: g.cards[u].cid for u in g.players[o].field + g.players[o].trash}
        for i in range(5):
            d = determinize(g, p, random.Random(i), infer_rival=True)
            assert len(d.players[o].hand) == len(g.players[o].hand)
            assert all(d.cards[u].cid == c for u, c in shown.items())     # seen cards unchanged
            assert d.players[p].hand == g.players[p].hand
            legs = [d.d(u) for u, c in d.cards.items() if c.owner == o and d.d(u).type == "legend"]
            lim = ram_limits(legs)
            counts = Counter(d.cards[u].cid for u, c in d.cards.items()
                             if c.owner == o and d.d(u).type != "legend")
            assert max(counts.values()) <= 3
            for u in d.players[o].hand + d.players[o].deck:
                c = d.d(u)
                assert (c.ram_cost or 0) <= lim.get(c.color, 0)


def test_gig_pattern_features_match_their_offline_version():
    import numpy as np
    from cpbot import Game, default_db, random_deck
    from cpbot.features import features_v2, pattern_features, pattern_features_from_v2
    from cpbot.search import rollout_move
    db = default_db()
    rng = random.Random(3)
    for s in range(20):
        g = Game(random_deck(rng, db), random_deck(rng, db), seed=s)
        while not g.over:
            if rng.random() < 0.2:
                for p in (0, 1):
                    a = pattern_features(g, p)
                    b = pattern_features_from_v2(np.array([features_v2(g, p)], dtype=np.float16), db)[0]
                    assert np.allclose(a, b)
            g.step(rollout_move(g, rng))


def test_learned_value_reads_pattern_weights(tmp_path):
    import json
    from cpbot.features import NAMES, PATTERN_NAMES, LearnedValue
    from cpbot import Game, default_db, random_deck
    db = default_db()
    names = NAMES + PATTERN_NAMES
    w = [0.0] * len(names)
    w[names.index("me:pairs*green")] = 1.0
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"names": names, "weights": w}))
    v = LearnedValue(path=f)
    assert v.pairs and not v.cards
    rng = random.Random(0)
    g = Game(random_deck(rng, db), random_deck(rng, db), seed=0)
    assert 0 <= v(g, 0) <= 1


def test_bot_skips_wasted_programs_and_gear():
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_cards import Board
    from cpbot.search import sensible_options
    db = default_db()
    b = Board(["Viktor Vektor - Sit Down and Relax", "Padre - Man of the Cross", "Wakako Okada - Peace and Harmony"])
    b.card(b.p, "Viktor Vektor - Sit Down and Relax", "legends", face_up=True)
    for t in ("Detonate", "Mantis Blades", "Zetatech Faceplate"):
        b.card(b.p, t, "hand")
    b.eddies(b.p, 5)
    g = b.go()
    plays = lambda: [db[o[1]].title for o in sensible_options(g) if o[0] == "play"]  # noqa: E731
    assert plays() == ["Zetatech Faceplate"]       # no rival Gear; Blades do nothing on Viktor
    r = b.card(1 - b.p, "Psycho Squad", "field")
    b.gear(1 - b.p, "Mantis Blades", r)
    g.decision = None
    g.stack = [("main", ())]
    g.advance()
    assert "Detonate" in plays()


def test_bot_pays_for_a_call_without_resting_a_face_down_legend():
    """A face-down Legend with a rest ability (Padre, Wakako) should be called ready, so pay
    with an Eddie instead of resting a face-down Legend."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_cards import Board
    from cpbot.search import sensible_options
    b = Board(["Viktor Vektor - Sit Down and Relax", "Padre - Man of the Cross", "Wakako Okada - Peace and Harmony"])
    for t in ("Viktor Vektor - Sit Down and Relax", "Padre - Man of the Cross", "Wakako Okada - Peace and Harmony"):
        b.card(b.p, t, "legends", face_up=False)
    b.eddies(b.p, 2)
    g = b.go()
    g.step(("call",))
    assert g.decision.kind == "pay"
    assert ("legend_facedown",) in g.decision.options
    assert [o[0] for o in sensible_options(g)] == ["eddie"]


def test_tactic_features_see_blockers_and_lethal():
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_cards import Board
    from cpbot.features import TACTIC_NAMES, tactic_features
    b = Board()
    me, rv = b.p, 1 - b.p
    b.card(me, "Psycho Squad", "field")                    # power 6: steals 1
    b.card(me, "Animals Wrecker", "field")                 # power 10: steals 2
    b.gigs(me, *[[d, 1] for d in (4, 6, 8, 10)])            # 4 Gigs
    b.gigs(rv, [12, 3], [20, 5], [4, 2])
    g = b.go()
    t = dict(zip(TACTIC_NAMES, tactic_features(g, me)))
    assert t["me:steal_threat"] == 3 and t["me:net_steal"] == 3 and t["me:lethal"] == 1
    b.card(rv, "Meredith Stout - Stone Cold Corpo", "field")   # power-5 Blocker
    t = dict(zip(TACTIC_NAMES, tactic_features(g, me)))
    assert t["me:blockers_faced"] == 1 and t["me:net_steal"] == 1 and t["me:lethal"] == 0
    assert t["me:outclassed"] == 0                          # both attackers beat a 5
    b.card(rv, "Placide - Voodoo Sentinel", "field", spent=True)
    t = dict(zip(TACTIC_NAMES, tactic_features(g, me)))
    assert t["me:killable"] == 0                            # 10 doesn't beat 10
