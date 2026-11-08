"""The play-against-the-bot layer: decklist reading, hidden information, whole games."""
import json
import random

import pytest

from cpbot import default_db, random_deck
from cpbot.agents import EagerRandomAgent
from cpbot.play import BOT, HUMAN, SAMPLE_DECK, Match, label, parse_decklist, player_view

db = default_db()


def test_sample_decklist_reads_and_is_legal():
    d = parse_decklist(SAMPLE_DECK, db)
    assert len(d.legends) == 3
    assert len(d.main) == 40                      # 14 units + 26 programs; sideboard left out
    assert db[d.legends[0]].title == "Alt Cunningham - Soulkiller Architect"


def test_decklist_errors_are_reported():
    with pytest.raises(ValueError, match="unknown card"):
        parse_decklist("1 Not A Real Card\n", db)
    with pytest.raises(ValueError, match="40-50"):
        parse_decklist("1 Alt Cunningham: Soulkiller Architect\n3 Psycho Squad\n", db)


def _play(seed):
    rng = random.Random(seed)
    m = Match(random_deck(rng, db), random_deck(rng, db), bot=EagerRandomAgent(seed), seed=seed, db=db)
    me = random.Random(seed + 100)
    n = 0
    while not m.g.over:
        m.run_bot()
        if m.g.over:
            break
        v = m.view()
        d = v["decision"]
        assert d["mine"] and d["options"]
        for o in d["options"]:
            assert o["label"]
        # the human's view never shows the bot's hand or unseen face-down Legends
        assert isinstance(v["rival"]["hand"], int)
        for L in v["rival"]["legends"]:
            assert L.get("hidden") or L["face_up"]
        json.dumps(v)
        m.choose(me.randrange(len(d["options"])))
        n += 1
        assert n < 5000
    return m


@pytest.mark.parametrize("seed", range(12))
def test_whole_games_against_the_bot(seed):
    m = _play(seed)
    v = m.view()
    assert v["result"]
    assert v["decision"] is None
    assert any(L["k"] == "end" for L in v["log"])


def test_bot_hand_never_named_in_log():
    for seed in range(6):
        m = _play(seed)
        text = "\n".join(L["t"] for L in m.lines)
        # The log can mention cards the bot plays or reveals, but never says what it draws.
        assert "Bot draws" not in text


def test_labels_cover_engine_options():
    rng = random.Random(3)
    m = Match(random_deck(rng, db), random_deck(rng, db), bot=EagerRandomAgent(1), seed=3, db=db)
    g = m.g
    for o in g.decision.options:
        assert label(g, g.decision.kind, o, HUMAN)
    pv = player_view(g, HUMAN)
    assert pv["you"]["me"] and not pv["rival"]["me"]
    assert BOT == 1


def _match(seed):
    rng = random.Random(seed)
    return Match(random_deck(rng, db), random_deck(rng, db), bot=EagerRandomAgent(seed), seed=seed, db=db)


def _advance(m, me, n):
    for _ in range(n):
        m.run_bot()
        if m.g.over:
            return
        m.choose(me.randrange(len(m.g.decision.options)))


@pytest.mark.parametrize("seed", range(6))
def test_undo_returns_to_the_same_position(seed):
    m = _match(seed)
    me = random.Random(seed)
    _advance(m, me, 25)
    m.run_bot()
    if m.g.over:
        return
    before = json.dumps(m.view(), sort_keys=True)
    log_len = len(m.lines)
    m.choose(0)
    m.run_bot()
    m.undo()
    assert json.dumps(m.view(), sort_keys=True) == before
    assert len(m.lines) == log_len
    # undo again and again back to the start
    while m.can_undo():
        m.undo()
    assert m.choices == [] or all(i not in m.mine for i in range(len(m.choices)))


def test_resign_ends_the_game():
    m = _match(1)
    _advance(m, random.Random(1), 5)
    m.resign()
    v = m.view()
    assert m.g.winner == BOT and "resigned" in v["result"]
    assert v["decision"] is None and not v["can_undo"]


def test_eddies_stay_face_down():
    m = _match(2)
    _advance(m, random.Random(2), 40)
    for side in ("you", "rival"):
        for c in m.view()[side]["eddie_cards"]:
            assert c["hidden"] and "title" not in c
