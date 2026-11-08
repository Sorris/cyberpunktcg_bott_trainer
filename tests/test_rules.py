"""Rules tests for the vanilla engine. Rule numbers refer to docs/comprehensive-rules.md."""
import random

import pytest

from cpbot import Deck, Game, default_db, random_deck, validate
from cpbot.agents import RandomAgent, play_game
from cpbot.deck import ram_limits

db = default_db()


def vanilla_unit(power=None):
    us = [c for c in db.main_cards() if c.type == "unit" and not c.keywords]
    if power is not None:
        us = [c for c in us if c.power == power]
    return us[0]


def simple_deck(card, legends=None):
    legs = legends or [l.idx for l in db.legends()[:3]]
    return Deck(legs, [card.idx] * 40)


def to_main(g):
    """Advance through setup with no mulligans; first chooser goes first."""
    while g.decision.kind in ("go_first", "mulligan", "roll_in"):
        g.step(g.decision.options[0] if g.decision.kind != "mulligan" else False)
    return g


# ---------------------------------------------------------------- decks
def test_random_decks_are_legal():
    rng = random.Random(0)
    for _ in range(300):
        assert validate(random_deck(rng, db), db) == []


def test_deck_rules():
    legs = db.legends()[:3]
    d = Deck([l.idx for l in legs], [vanilla_unit().idx] * 40)
    assert any("copies" in e for e in validate(d, db))          # 7.3.3
    d = Deck([l.idx for l in legs], [])
    assert any("40-50" in e for e in validate(d, db))           # 7.3.2


def test_ram_example_3_20_5_1():
    goro = db.find("Goro Takemura - Hands Unclean")
    saburo = db.find("Saburo Arasaka - Stubborn Patriarch")
    yori = db.find("Yorinobu Arasaka - Embracing Destruction")
    assert ram_limits([goro, saburo, yori]) == {"red": 2, "green": 4, "blue": 0, "yellow": 0}


def test_same_name_legends_illegal():
    v1, v2 = db.find("V - Corporate Exile"), db.find("V - Streetkid")
    other = [l for l in db.legends() if "V" not in l.names][0]
    d = Deck([v1.idx, v2.idx, other.idx], [])
    assert any("duplicate Legend name" in e for e in validate(d, db))   # 7.3.1


# ---------------------------------------------------------------- setup
def test_setup():
    u = vanilla_unit()
    g = Game(simple_deck(u), simple_deck(u), seed=1)
    to_main(g)
    fp = g.first_player
    assert len(g.players[fp].hand) == 7                        # 6 + draw 1
    assert len(g.players[1 - fp].hand) == 6
    legs = g.players[fp].legends
    assert [g.cards[x].spent for x in legs] == [True, True, False]   # 7.7.4
    assert len(g.players[fp].gigs) == 1 and len(g.players[fp].fixer) == 5


def test_d20_rolled_last():
    u = vanilla_unit()
    g = Game(simple_deck(u), simple_deck(u), seed=2)
    seen = []
    while not g.over and g.turn_no < 14:
        if g.decision.kind == "roll_in":
            seen.append(list(g.decision.options))
        g.step(("pass",) if g.decision.kind == "main" else g.decision.options[0])
    for opts in seen:
        assert 20 not in opts                                   # 8.6.5.1.1 (forced d20 is auto)


# ---------------------------------------------------------------- combat
def setup_fight(pa, pd, rival_gigs=((4, 1), (6, 2), (8, 3), (10, 4))):
    """Place one ready attacker for the turn player and one spent rival defender directly."""
    u = vanilla_unit()
    g = Game(simple_deck(u), simple_deck(u), seed=5)
    to_main(g)
    tp = g.turn_player
    atk = next(c for c in g.cards.values() if c.owner == tp and c.zone == "deck")
    dfn = next(c for c in g.cards.values() if c.owner == 1 - tp and c.zone == "deck")
    g.move(atk.uid, "field")
    g.move(dfn.uid, "field")
    dfn.spent = True
    g.give_power(atk.uid, pa - g.power(atk.uid), "permanent")
    g.give_power(dfn.uid, pd - g.power(dfn.uid), "permanent")
    rival = g.players[1 - tp]
    rival.gigs[:] = [list(x) for x in rival_gigs]
    rival.fixer[:] = [d for d in (4, 6, 8, 10, 12, 20) if d not in [x[0] for x in rival_gigs]]
    g.decision = None
    g.stack.append(("main", ()))
    g.advance()
    return g, atk.uid, dfn.uid


@pytest.mark.parametrize("pa,pd,atk_dies,dfn_dies", [
    (5, 3, False, True), (3, 5, True, False), (4, 4, True, True),   # 11.4.1
    (0, 0, False, False),                                           # 11.4.2.3.2
    (0, 3, True, False), (3, 0, False, True),
])
def test_fight(pa, pd, atk_dies, dfn_dies):
    g, a, d = setup_fight(pa, pd)
    g.step(("attack", a, ("unit", d)))
    if g.decision and g.decision.kind == "react":
        g.step(("end",))
    assert (g.cards[a].zone == "trash") == atk_dies
    assert (g.cards[d].zone == "trash") == dfn_dies


@pytest.mark.parametrize("power,expected", [(0, 0), (1, 1), (9, 1), (10, 2), (19, 2), (20, 3)])
def test_steal_count(power, expected):                            # 9.20.1.2
    g, a, d = setup_fight(power, 1)
    before = len(g.players[g.turn_player].gigs)
    g.step(("attack", a, ("gigs",)))
    while g.decision and g.decision.kind in ("react", "steal"):
        g.step(("end",) if g.decision.kind == "react" else g.decision.options[0])
    assert len(g.players[g.turn_player].gigs) - before == expected


def test_lagging_unit_cannot_attack():
    u = vanilla_unit()
    g = Game(simple_deck(u), simple_deck(u), seed=7)
    to_main(g)
    tp = g.turn_player
    pl = g.players[tp]
    for _ in range(10):
        pl.eddies.append(pl.deck.pop())
        g.cards[pl.eddies[-1]].zone = "eddies"
    g.decision = None
    g.stack.append(("main", ()))
    g.advance()
    play = [o for o in g.legal_actions() if o[0] == "play"]
    if not play:
        pytest.skip("unit too expensive for this setup")
    g.step(play[0])
    while g.decision.kind == "pay":
        g.step(g.decision.options[0])
    assert not any(o[0] == "attack" for o in g.legal_actions())   # 4.7, 9.3.1.1


def test_blocker_redirects():
    blk = next(c for c in db.main_cards() if c.type == "unit" and c.has("blocker"))
    g, a, d = setup_fight(5, 1)
    dp = 1 - g.turn_player
    b = next(c for c in g.cards.values() if c.owner == dp and c.zone == "deck")
    b.cid = blk.idx
    g.move(b.uid, "field")
    g.give_power(b.uid, 9 - g.power(b.uid), "permanent")
    g.decision = None
    g.stack.append(("main", ()))
    g.advance()
    g.step(("attack", a, ("gigs",)))
    assert ("block", b.uid) in g.legal_actions()
    gigs_before = len(g.players[g.turn_player].gigs)
    g.step(("block", b.uid))
    g.step(("end",))
    assert g.cards[a].zone == "trash"                       # 9 beats 5
    assert len(g.players[g.turn_player].gigs) == gigs_before  # redirected: nothing stolen


# ---------------------------------------------------------------- whole games
def test_overtime_and_end():
    for seed in range(200):
        rng = random.Random(seed)
        g = Game(random_deck(rng, db), random_deck(rng, db), seed=seed)
        play_game(g, [RandomAgent(seed), RandomAgent(seed + 1)], check=True)
        assert g.over
        if g.end_reason == "reached 7 Gigs in overtime":
            assert g.overtime


def test_decking_loses():                                          # 1.14
    u = vanilla_unit()
    g = Game(simple_deck(u), simple_deck(u), seed=9)
    to_main(g)
    tp = g.turn_player
    for x in list(g.players[1 - tp].deck):
        g.move(x, "trash")
    g.step(("pass",))
    assert g.winner == tp and "empty deck" in g.end_reason


def test_clone_is_independent():
    rng = random.Random(4)
    g = Game(random_deck(rng, db), random_deck(rng, db), seed=4)
    for _ in range(10):
        g.step(g.legal_actions()[0])
    h = g.clone()
    hist = list(g.history)
    while not h.over:
        h.step(h.legal_actions()[-1])
    assert g.history == hist and not g.over
