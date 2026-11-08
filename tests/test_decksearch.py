"""Deck search: every deck it makes is legal, and runs can be saved and resumed."""
import random

from cpbot import default_db, random_deck, validate
from cpbot.decksearch import (SearchState, breed, crossover, deck_from_key, deck_key, mutate,
                              new_state, schedule)

db = default_db()


def test_mutations_and_crossover_stay_legal():
    rng = random.Random(0)
    for _ in range(300):
        a, b = random_deck(rng, db), random_deck(rng, db)
        for _ in range(3):
            a = mutate(a, db, rng)
            assert validate(a, db, require_legal=False) == []
        b.legends = list(a.legends)
        c = crossover(a, b, db, rng)
        assert validate(c, db, require_legal=False) == []


def test_deck_keys_round_trip():
    rng = random.Random(1)
    d = random_deck(rng, db)
    e = deck_from_key(deck_key(d))
    assert sorted(e.legends) == sorted(d.legends) and sorted(e.main) == sorted(d.main)


def test_state_saves_and_breeds():
    s = new_state(db, seed=3, size=6, gatekeepers=3)
    for i, e in enumerate(s.population):
        e.wins, e.games = i, 6
    s2 = SearchState.from_json(s.to_json())
    assert [vars(e) for e in s2.population] == [vars(e) for e in s.population]
    rng = random.Random(4)
    kids = breed(s2, db, rng, 4)
    assert len(kids) == 4 and all(k.born == 1 for k in kids)
    jobs = schedule(s2, s2.population + kids, rng, 2)
    assert len(jobs) == 2 * 10 and all(j[0] != j[1] for j in jobs)
