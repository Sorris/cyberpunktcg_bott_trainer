"""Deck search: an evolutionary search over legal decks, scored by games.

Starting from random legal decks, each generation:
1. breeds new decks from the best ones (mutations: swap cards, change a Legend,
   add copies of a card already in the deck, change the deck size; and crossover
   of two parents that share a Legend trio);
2. plays every deck against a mix of opponents: other decks in the population,
   the best decks of earlier generations (the "hall of fame") and a fixed set of
   random "gatekeeper" decks, with seats swapped in each pair of games;
3. keeps the decks with the best results. A deck's record carries over between
   generations while it survives, so long-lived decks are judged on many games.

Games are played by the search agent with a small budget, so they're fast but
still sensible. Everything about a run is saved in its folder, and a run can be
resumed.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass, field

from .cards import CardDB
from .deck import MAX_COPIES, MAX_MAIN, MIN_MAIN, Deck, eligible_main_cards, random_deck, \
    random_legends, validate


# ------------------------------------------------------------------ decks
def deck_key(d: Deck) -> str:
    return ",".join(map(str, sorted(d.legends))) + "|" + ",".join(map(str, sorted(d.main)))


def deck_from_key(key: str) -> Deck:
    legs, main = key.split("|")
    return Deck([int(x) for x in legs.split(",")], [int(x) for x in main.split(",")])


def _fill(main: list[int], pool, rng, size):
    counts = Counter(main)
    while len(main) < size:
        c = rng.choice(pool)
        if counts[c.idx] < MAX_COPIES:
            counts[c.idx] += 1
            main.append(c.idx)
    return main


def _repair(legends: list[int], main: list[int], db: CardDB, rng) -> Deck:
    """Drop cards the Legends can't support (RAM), then refill to a legal size."""
    legs = [db[i] for i in legends]
    pool = eligible_main_cards(legs, db)
    ok = {c.idx for c in pool}
    counts = Counter()
    kept = []
    for i in main:
        if i in ok and counts[i] < MAX_COPIES:
            counts[i] += 1
            kept.append(i)
    size = min(MAX_MAIN, max(MIN_MAIN, len(main)))
    kept = kept[:size]
    return Deck(list(legends), _fill(kept, pool, rng, size))


def mutate(d: Deck, db: CardDB, rng: random.Random) -> Deck:
    legends, main = list(d.legends), list(d.main)
    r = rng.random()
    if r < 0.15:                                      # change one Legend
        others = [db[i] for i in legends]
        k = rng.randrange(3)
        names = set().union(*(o.names for j, o in enumerate(others) if j != k))
        choices = [l for l in db.legends() if not (l.names & names) and l.idx != legends[k]]
        legends[k] = rng.choice(choices).idx
    elif r < 0.30:                                    # more copies of a card already in the deck
        counts = Counter(main)
        can = [i for i, n in counts.items() if n < MAX_COPIES]
        if can:
            add = rng.choice(can)
            drop = rng.choice([i for i in main if i != add] or main)
            main.remove(drop)
            main.append(add)
    elif r < 0.40:                                    # change the deck size
        if rng.random() < 0.5 and len(main) > MIN_MAIN:
            main.remove(rng.choice(main))
        elif len(main) < MAX_MAIN:
            main = _fill(main, eligible_main_cards([db[i] for i in legends], db), rng, len(main) + 1)
    else:                                             # swap 1-3 cards for new ones
        k = rng.choice((1, 1, 2, 3))
        size = len(main)
        for _ in range(k):
            main.remove(rng.choice(main))
        main = _fill(main, eligible_main_cards([db[i] for i in legends], db), rng, size)
    return _repair(legends, main, db, rng)


def crossover(a: Deck, b: Deck, db: CardDB, rng: random.Random) -> Deck:
    """Legends from a; main deck drawn from both parents' cards."""
    pool = list(a.main) + list(b.main)
    rng.shuffle(pool)
    size = rng.choice((len(a.main), len(b.main)))
    counts, main = Counter(), []
    for i in pool:
        if len(main) >= size:
            break
        if counts[i] < MAX_COPIES:
            counts[i] += 1
            main.append(i)
    return _repair(list(a.legends), main, db, rng)


# ------------------------------------------------------------------ search
@dataclass
class Entry:
    key: str
    born: int
    wins: float = 0.0
    games: int = 0
    parent: str | None = None

    def score(self, prior=10) -> float:
        """Win rate, pulled towards 50% when there are few games."""
        return (self.wins + 0.5 * prior) / (self.games + prior)


@dataclass
class SearchState:
    seed: int
    generation: int = 0
    population: list = field(default_factory=list)       # [Entry]
    hall: list = field(default_factory=list)             # [deck key]
    gatekeepers: list = field(default_factory=list)      # [deck key]
    history: list = field(default_factory=list)          # per-generation summary

    def to_json(self) -> str:
        return json.dumps({
            "seed": self.seed, "generation": self.generation,
            "population": [vars(e) for e in self.population],
            "hall": self.hall, "gatekeepers": self.gatekeepers, "history": self.history}, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "SearchState":
        d = json.loads(text)
        s = cls(d["seed"], d["generation"])
        s.population = [Entry(**e) for e in d["population"]]
        s.hall, s.gatekeepers, s.history = d["hall"], d["gatekeepers"], d["history"]
        return s


def new_state(db: CardDB, seed: int, size=16, gatekeepers=8) -> SearchState:
    rng = random.Random(seed)
    s = SearchState(seed)
    s.population = [Entry(deck_key(random_deck(rng, db)), 0) for _ in range(size)]
    s.gatekeepers = [deck_key(random_deck(rng, db)) for _ in range(gatekeepers)]
    return s


def breed(s: SearchState, db: CardDB, rng: random.Random, children: int) -> list[Entry]:
    ranked = sorted(s.population, key=lambda e: -e.score())
    parents = ranked[:max(2, len(ranked) // 2)]
    out, seen = [], {e.key for e in s.population}
    tries = 0
    while len(out) < children and tries < children * 20:
        tries += 1
        a = rng.choice(parents)
        da = deck_from_key(a.key)
        if rng.random() < 0.25:
            mates = [p for p in parents if p is not a and sorted(deck_from_key(p.key).legends) == sorted(da.legends)]
            child = crossover(da, deck_from_key(rng.choice(mates).key), db, rng) if mates else mutate(da, db, rng)
        else:
            child = mutate(da, db, rng)
        if rng.random() < 0.3:
            child = mutate(child, db, rng)
        assert not validate(child, db, require_legal=False), validate(child, db, require_legal=False)
        k = deck_key(child)
        if k not in seen:
            seen.add(k)
            out.append(Entry(k, s.generation + 1, parent=a.key))
    return out


def schedule(s: SearchState, entries: list[Entry], rng: random.Random, pairs_per_deck: int) -> list:
    """Opponents for each deck: population, hall of fame and gatekeepers."""
    jobs = []
    keys = [e.key for e in entries]
    for e in entries:
        for _ in range(pairs_per_deck):
            r = rng.random()
            if r < 0.5:
                opp = rng.choice([k for k in keys if k != e.key])
            elif r < 0.75 and s.hall:
                opp = rng.choice(s.hall)
            else:
                opp = rng.choice(s.gatekeepers)
            jobs.append((e.key, opp, rng.getrandbits(31)))
    return jobs


def describe(key: str, db: CardDB) -> str:
    return deck_from_key(key).to_text(db)
