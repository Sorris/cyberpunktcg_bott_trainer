"""Watchable games: the log, the replay record and the replay page."""
import json
import random

from cpbot import Game, default_db, random_deck
from cpbot.agents import EagerRandomAgent
from cpbot.watch import replay, watch_game

db = default_db()


def _game(seed):
    rng = random.Random(seed)
    decks = [random_deck(rng, db), random_deck(rng, db)]
    g = Game(decks[0], decks[1], seed=seed, db=db)
    return watch_game(g, [EagerRandomAgent(seed), EagerRandomAgent(seed + 1)], decks, seed=seed)


def test_replay_rebuilds_the_same_game():
    for seed in range(25):
        rec = _game(seed)
        again = replay(json.loads(rec.to_json()), db)
        assert again.g.winner == rec.g.winner
        assert again.text() == rec.text()


def test_log_reads_like_a_game():
    rec = _game(3)
    text = rec.text()
    assert "== Turn 1:" in text
    assert "draws 6:" in text                                  # opening hands are listed
    assert "P0" not in text                                    # players are P1 and P2
    assert rec.g.winner is not None and "GAME OVER" in text


def test_replay_page_embeds_every_frame():
    rec = _game(4)
    page = rec.html()
    assert page.startswith("<!doctype html>")
    assert "/*__DATA__*/" not in page and "</script>" in page
    assert len(rec.frames) == len(rec.choices) + 1


def test_clone_drops_the_observer():
    rec = _game(5)
    assert rec.g.observer is rec
    assert rec.g.clone().observer is None
