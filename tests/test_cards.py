"""Card-script tests: build a board by hand, act, check the result."""
import random

import pytest

from cpbot import Deck, Game, default_db, random_deck
from cpbot.agents import RandomAgent, play_game
from cpbot.effects import S

db = default_db()
FILLER = next(c for c in db.main_cards() if c.type == "unit" and not c.text.strip("[] ").startswith("{")
              and c.slug == "psycho-squad")
LEGS = [db.find("Lucyna Kushinada - Fresh Beginnings"), db.find("Padre - Man of the Cross"),
        db.find("Wakako Okada - Peace and Harmony")]


class Board:
    """A game paused in P0's main phase with an empty board and controllable state."""

    def __init__(self, legends=None):
        legs = [db.find(x).idx for x in legends] if legends else [l.idx for l in LEGS]
        deck = Deck(legs, [FILLER.idx] * 40)
        g = Game(deck, Deck([l.idx for l in LEGS], [FILLER.idx] * 40), seed=1)
        while g.decision.kind in ("go_first", "mulligan", "roll_in"):
            g.step(True if g.decision.kind == "go_first" else (False if g.decision.kind == "mulligan"
                                                                else g.decision.options[0]))
        self.g = g
        self.p = g.turn_player
        for pl in g.players:
            for u in list(pl.hand):
                g.move(u, "deck")
            pl.fixer[:] = list(pl.fixer) + [s for s, _ in pl.gigs]
            pl.gigs[:] = []
        for u in g.players[self.p].legends:
            g.cards[u].spent = False

    def card(self, p, title, zone, spent=False, face_up=True):
        g = self.g
        if zone == "legends":
            u = next(u for u in g.players[p].legends if g.d(u).title == db.find(title).title)
            g.cards[u].face_up = face_up
            g.cards[u].spent = spent
            return u
        u = next(u for u in g.players[p].deck)
        g.cards[u].cid = db.find(title).idx
        g.move(u, zone, p)
        g.cards[u].spent = spent
        return u

    def gear(self, p, title, host):
        g = self.g
        u = next(u for u in g.players[p].deck)
        g.cards[u].cid = db.find(title).idx
        g.move(u, "limbo")
        g.cards[u].zone = "equipped"
        g.cards[u].host = host
        g.cards[host].gears.append(u)
        return u

    def gigs(self, p, *gigs):
        pl = self.g.players[p]
        pl.gigs[:] = [list(x) for x in gigs]
        pl.fixer[:] = [d for d in (4, 6, 8, 10, 12, 20) if d not in [x[0] for x in gigs]]

    def eddies(self, p, n):
        for _ in range(n):
            self.card(p, FILLER.title, "eddies")

    def go(self):
        g = self.g
        g.decision = None
        g.stack = [("main", ())]
        g.advance()
        return g

    def answer(self, *pairs):
        """Answer decisions: pairs of (kind-prefix, option or callable)."""
        g = self.g
        for kind, opt in pairs:
            assert g.decision is not None and g.decision.kind.startswith(kind), (kind, g.decision)
            if callable(opt):
                opt = next(o for o in g.decision.options if opt(o))
            g.step(opt)


def play(b, title):
    g = b.g
    cid = db.find(title).idx
    g.step(("play", cid))
    while g.decision and g.decision.kind == "pay":
        g.step(g.decision.options[0])


def test_every_card_is_scripted():
    from cpbot import effects as fx
    fx.load_scripts()
    assert [c.slug for c in db.cards if c.slug not in fx.SCRIPTED] == []


def test_delamain_rideshare_draws_two():
    b = Board()
    u = b.card(b.p, "Delamain - Rideshare AI", "hand")
    b.eddies(b.p, 3)
    g = b.go()
    hand = len(g.players[b.p].hand)
    play(b, "Delamain - Rideshare AI")
    assert len(g.players[b.p].hand) == hand - 1 + 2


def test_royce_simon_defeats_small_unit():
    b = Board()
    b.card(b.p, "Royce - Don't Call Me Simon", "hand")
    small = b.card(1 - b.p, "Japantown Jonin", "field")     # power 0
    big = b.card(1 - b.p, "Psycho Squad", "field")           # power 6
    b.eddies(b.p, 5)
    g = b.go()
    play(b, "Royce - Don't Call Me Simon")
    assert g.cards[small].zone == "trash"
    assert g.cards[big].zone == "field"


def test_saburo_gives_arasaka_attackers_power():
    b = Board(["Saburo Arasaka - Stubborn Patriarch", "Padre - Man of the Cross", "Wakako Okada - Peace and Harmony"])
    b.card(b.p, "Saburo Arasaka - Stubborn Patriarch", "legends", face_up=True)
    goro = b.card(b.p, "Field Operator", "field")             # ARASAKA, power 2
    g = b.g
    assert g.power(goro) == 2
    g.attack = {"atk": goro, "target": ("gigs",), "ap": b.p, "dp": 1 - b.p}
    assert g.power(goro) == 3
    g.attack = None


def test_corpo_security_cannot_attack_but_blocks():
    b = Board()
    cs = b.card(b.p, "Corpo Security", "field")
    b.gigs(1 - b.p, (6, 3))
    g = b.go()
    assert not any(o[0] == "attack" and o[1] == cs for o in g.legal_actions())


def test_deadman_transmitter_saves_host():
    b = Board()
    host = b.card(b.p, "Psycho Squad", "field")
    dm = b.gear(b.p, "Deadman Transmitter", host)
    g = b.g
    g.defeat_now(host)
    assert g.cards[host].zone == "field"
    assert g.cards[dm].zone == "trash"


def test_maxtac_heavy_cost_reduction():
    b = Board()
    u = b.card(b.p, "MaxTac Heavy", "hand")
    for _ in range(3):
        b.card(1 - b.p, "Psycho Squad", "field")
    assert b.g.play_cost(b.p, u) == 7 - 3


def test_cost_reduction_floor_is_one():
    b = Board()
    u = b.card(b.p, "MaxTac Heavy", "hand")
    for _ in range(9):
        b.card(1 - b.p, "Psycho Squad", "field")
    assert b.g.play_cost(b.p, u) == 1                       # 11.11.3


def test_johnny_wins_against_corpo():
    b = Board()
    j = b.card(b.p, "Johnny Silverhand - Never Stop Fighting", "field")
    corpo = b.card(1 - b.p, "Sandayu Oda - Hanako's Guardian", "field", spent=True)   # CORPO, power 8
    g = b.go()
    g.cards[j].lag = False
    g.decision = None
    g.stack = [("main", ())]
    g.advance()
    g.step(("attack", j, ("unit", corpo)))
    if g.decision and g.decision.kind == "react":
        g.step(("end",))
    assert g.cards[corpo].zone == "trash"
    assert g.cards[j].zone == "field"
    assert not g.cards[j].spent                               # readied after its first win


def test_take_control_reduces_steal():
    b = Board()
    atk = b.card(b.p, "Animals Wrecker", "field")             # power 10 -> steals 2
    b.gigs(1 - b.p, (4, 1), (6, 2), (8, 3))
    b.card(1 - b.p, "Take Control", "hand")
    b.eddies(1 - b.p, 2)
    g = b.go()
    g.cards[atk].lag = False
    g.decision = None
    g.stack = [("main", ())]
    g.advance()
    g.step(("attack", atk, ("gigs",)))
    g.step(("quick", db.find("Take Control").idx))
    while g.decision.kind in ("pay", "target"):
        g.step(g.decision.options[0])
    g.step(("end",))
    while g.decision and g.decision.kind == "steal":
        g.step(g.decision.options[0])
    assert len(g.players[b.p].gigs) == 1


def test_appetite_for_destruction_steals_on_big_win():
    b = Board()
    atk = b.card(b.p, "Animals Wrecker", "field")             # 10 power
    dfn = b.card(1 - b.p, "Japantown Jonin", "field", spent=True)
    b.gigs(1 - b.p, (6, 4))
    b.card(b.p, "Appetite for Destruction", "hand")
    b.eddies(b.p, 3)
    g = b.go()
    g.cards[atk].lag = False
    play(b, "Appetite for Destruction")
    g.step(("attack", atk, ("unit", dfn)))
    if g.decision and g.decision.kind == "react":
        g.step(("end",))
    assert g.cards[dfn].zone == "trash"
    assert [6, 4] in g.players[b.p].gigs


def test_chrome_fang_limits_steals():
    b = Board()
    b.card(b.p, "Chrome Fang", "hand")
    b.eddies(b.p, 5)
    b.gigs(b.p, (20, 15), (4, 2))
    g = b.go()
    play(b, "Chrome Fang")
    atk = b.card(1 - b.p, "Psycho Squad", "field")            # power 6
    assert g.stealable(atk, b.p) == [1]                      # only the value-2 Gig


def test_go_solo_legend_attacks_same_turn():
    b = Board(["V - Corporate Exile", "Padre - Man of the Cross", "Wakako Okada - Peace and Harmony"])
    v = b.card(b.p, "V - Corporate Exile", "legends", face_up=True)
    b.eddies(b.p, 5)
    b.gigs(1 - b.p, (6, 3))
    g = b.go()
    g.step(("solo", v))
    while g.decision.kind == "pay":
        g.step(g.decision.options[0])
    assert ("attack", v, ("gigs",)) in g.legal_actions()
    g.defeat_now(v)
    assert g.cards[v].zone == "removed"                       # 4.4.1


def test_maxtac_suppression_blocks_fresh_attackers():
    b = Board()
    b.card(1 - b.p, "MaxTac Suppression Team", "field")
    b.card(b.p, "Riding Nomad", "hand")                       # Adrenaline
    b.eddies(b.p, 5)
    b.gigs(1 - b.p, (6, 3))
    g = b.go()
    play(b, "Riding Nomad")
    assert not any(o[0] == "attack" for o in g.legal_actions())   # 2.6 can't beats can


def test_mt0d12_unblockable_when_behind():
    b = Board()
    f = b.card(b.p, "MT0D12 Flathead", "field")
    b.card(1 - b.p, "Corpo Security", "field")
    b.gigs(b.p, (4, 1))
    b.gigs(1 - b.p, (6, 5))
    g = b.go()
    g.cards[f].lag = False
    g.decision = None
    g.stack = [("main", ())]
    g.advance()
    g.step(("attack", f, ("gigs",)))
    assert not any(o[0] == "block" for o in g.legal_actions())


def test_nocturne_cheap_when_fixer_empty():
    b = Board()
    u = b.card(b.p, "Nocturne Op55 N1", "hand")
    b.gigs(b.p, (4, 1), (6, 1), (8, 1), (10, 1), (12, 1), (20, 1))
    assert b.g.play_cost(b.p, u) == 1


def test_random_games_with_scripts():
    for seed in range(300):
        rng = random.Random(seed)
        g = Game(random_deck(rng, db), random_deck(rng, db), seed=seed)
        play_game(g, [RandomAgent(seed), RandomAgent(seed + 1)], check=True)
        assert g.over


def test_clone_mid_effect():
    rng = random.Random(11)
    for seed in range(50):
        g = Game(random_deck(rng, db), random_deck(rng, db), seed=seed)
        a = RandomAgent(seed)
        while not g.over:
            if g.decision.resume == "effect_answer":
                h = g.clone()
                hist = list(g.history)
                play_game(h, [RandomAgent(1), RandomAgent(2)])
                assert g.history == hist
                break
            g.step(a.act(g))


# ---- Henry's rulings, 8 Nov 2026
def _kerry_board():
    b = Board(["Kerry Eurodyne - Axe, Attitude, Audience", "Padre - Man of the Cross",
               "Wakako Okada - Peace and Harmony"])
    b.card(b.p, "Kerry Eurodyne - Axe, Attitude, Audience", "legends", face_up=True)
    g = b.go()
    return b, g


def _kerry_roll(b, g, sides, first, reroll, keep_reroll):
    """Roll in a d`sides` showing `first`; the reroll (if taken) shows `reroll`."""
    pl = g.players[b.p]
    gig = [sides, first]
    pl.gigs.append(gig)
    g.emit("roll_in", player=b.p, gig=gig)
    hand = len(pl.hand)
    g.rng.randint = lambda lo, hi: reroll
    g.decision = None
    g.stack.append(("main", ()))
    g.advance()
    b.answer(("may", keep_reroll))
    return len(pl.hand) - hand


def test_kerry_draws_on_kept_first_roll_max():
    b, g = _kerry_board()
    assert _kerry_roll(b, g, 6, 6, 3, False) == 1


def test_kerry_no_draw_if_max_is_rerolled_away():
    b, g = _kerry_board()
    assert _kerry_roll(b, g, 6, 6, 3, True) == 0


def test_kerry_draws_on_reroll_min():
    b, g = _kerry_board()
    assert _kerry_roll(b, g, 8, 4, 1, True) == 1


def test_kerry_d20_draws_three():
    b, g = _kerry_board()
    assert _kerry_roll(b, g, 20, 20, 5, False) == 3


def test_yorinobu_only_first_arasaka_defeat_of_turn_counts():
    b = Board()
    g = b.g
    a1 = b.card(b.p, "Field Operator", "field")             # ARASAKA
    a2 = b.card(b.p, "Field Operator", "field")
    g.defeat_now(a1)                                        # before Yorinobu is in play
    b.card(b.p, "Yorinobu Arasaka - Steel Dragon", "field")
    g.defeat_now(a2)
    assert g.pending == []


def test_yorinobu_draws_for_first_arasaka_defeat():
    b = Board()
    g = b.g
    b.card(b.p, "Yorinobu Arasaka - Steel Dragon", "field")
    a1 = b.card(b.p, "Field Operator", "field")
    a2 = b.card(1 - b.p, "Field Operator", "field")
    g.defeat_now(a1)
    assert len(g.pending) == 1
    g.defeat_now(a2)
    assert len(g.pending) == 1


def test_controller_orders_own_pending_effects():
    b = Board()
    g = b.go()
    src = b.card(b.p, "Psycho Squad", "field")
    g.trigger(src, [S("draw", n=1)])
    g.trigger(src, [S("draw", n=2)])
    g.decision = None
    g.stack.append(("main", ()))
    g.advance()
    assert g.decision.kind == "order_pending" and g.decision.player == b.p
    assert len(g.decision.options) == 2


def test_yorinobu_draws_when_he_is_first_arasaka_defeated():
    b = Board()
    g = b.g
    y = b.card(b.p, "Yorinobu Arasaka - Steel Dragon", "field")
    g.defeat_now(y)
    assert len(g.pending) == 1 and g.pending[0][0] == b.p
    hand = len(g.players[b.p].hand)
    g.decision = None
    g.stack = [("main", ())]
    g.advance()
    assert len(g.players[b.p].hand) == hand + 1


def test_yorinobu_no_draw_when_defeated_second():
    b = Board()
    g = b.g
    a1 = b.card(b.p, "Field Operator", "field")
    y = b.card(b.p, "Yorinobu Arasaka - Steel Dragon", "field")
    g.defeat_now(a1)
    g.pending.clear()
    g.defeat_now(y)
    assert g.pending == []


# ---- Rules FAQ (cyberpunktcg.com/rules-faq, 28 Oct 2026)
def _v_board(v_spent=False):
    b = Board(["V - Corporate Exile", "Padre - Man of the Cross", "Wakako Okada - Peace and Harmony"])
    v = b.card(b.p, "V - Corporate Exile", "legends", face_up=True, spent=v_spent)
    for u in b.g.players[b.p].legends:
        if u != v:
            b.g.cards[u].spent = True
    return b, v


def test_legend_can_spend_itself_to_pay_for_its_own_go_solo():
    b, v = _v_board()
    b.eddies(b.p, 4)                                          # 4 Eddies + V itself = 5
    g = b.go()
    assert ("solo", v) in g.legal_actions()
    g.step(("solo", v))
    assert g.cards[v].zone == "field" and not g.cards[v].spent


def test_legend_played_without_go_solo_keeps_orientation_and_lag():
    b, v = _v_board(v_spent=True)
    b.eddies(b.p, 6)
    b.card(b.p, "Psycho Squad", "hand")                       # keeps the main phase open
    b.gigs(1 - b.p, (6, 3))
    g = b.go()
    g.step(("deploy", v))
    c = g.cards[v]
    assert c.zone == "field" and c.spent and c.lag
    assert not any(o[0] == "attack" and o[1] == v for o in g.legal_actions())


def test_valentino_street_racer_cannot_target_itself():
    b = Board()
    v_old = b.card(b.p, "Valentino Street Racer", "field")
    b.card(b.p, "Valentino Street Racer", "hand")
    b.eddies(b.p, 8)
    g = b.go()
    before = set(g.players[b.p].field)
    play(b, "Valentino Street Racer")
    v_new = next(u for u in g.players[b.p].field if u not in before)
    grants = [L["unit"] for L in g.lasting if L.get("kw") == "adrenaline"]
    assert grants == [v_old] and not g.has_kw(v_new, "adrenaline")


def test_valentino_street_racer_alone_gives_nothing():
    b = Board()
    b.card(b.p, "Valentino Street Racer", "hand")
    b.eddies(b.p, 8)
    g = b.go()
    play(b, "Valentino Street Racer")
    assert not any(L.get("kw") == "adrenaline" for L in g.lasting)


def test_keywords_given_to_others_are_not_the_cards_own():
    assert not db.find("Valentino Street Racer").has("adrenaline")
    assert not db.find("Valentino Guerrera").has("blocker")
    assert not db.find("Goro Takemura - Vengeful Bodyguard").has("blocker")
    assert not db.find("Arasaka Emergency Radioport").has("go solo")
    assert db.find("Riding Nomad").has("adrenaline") and db.find("Riot Shield").has("blocker")
