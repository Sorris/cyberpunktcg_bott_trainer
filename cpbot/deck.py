"""Deck construction rules (comp rules 3.20 and 7.3) and random legal decks."""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from .cards import COLORS, LEGEND, CardDB, CardDef

MIN_MAIN, MAX_MAIN, MAX_COPIES = 40, 50, 3


@dataclass
class Deck:
    legends: list[int]   # 3 card indices
    main: list[int]      # 40-50 card indices

    def to_text(self, db: CardDB) -> str:
        lines = ["# Legends"] + [f"1 {db[i].title}" for i in self.legends] + ["# Main"]
        for i, n in sorted(Counter(self.main).items(), key=lambda kv: (db[kv[0]].type, db[kv[0]].title)):
            lines.append(f"{n} {db[i].title}")
        return "\n".join(lines)

    @classmethod
    def from_text(cls, text: str, db: CardDB) -> "Deck":
        legends, main = [], []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            n, title = line.split(" ", 1)
            c = db.find(title)
            (legends if c.type == LEGEND else main).extend([c.idx] * int(n))
        return cls(legends, main)


def ram_limits(legends: list[CardDef]) -> dict[str, int]:
    lim = {c: 0 for c in COLORS}
    for l in legends:
        if l.color and l.ram_provided:
            lim[l.color] += l.ram_provided
    return lim


def validate(deck: Deck, db: CardDB, require_legal=True) -> list[str]:
    """Return a list of rule violations (empty list = legal deck)."""
    errs = []
    legs = [db[i] for i in deck.legends]
    if len(legs) != 3:
        errs.append(f"need exactly 3 Legends, got {len(legs)} (7.3)")
    if any(l.type != LEGEND for l in legs):
        errs.append("non-Legend in Legend slots")
    seen = set()
    for l in legs:
        if seen & l.names:
            errs.append(f"duplicate Legend name: {l.name} (7.3.1)")
        seen |= l.names
    if not MIN_MAIN <= len(deck.main) <= MAX_MAIN:
        errs.append(f"main deck has {len(deck.main)} cards, needs 40-50 (7.3.2)")
    lim = ram_limits(legs)
    for i, n in Counter(deck.main).items():
        c = db[i]
        if c.type == LEGEND:
            errs.append(f"Legend {c.title} in main deck")
        if n > MAX_COPIES:
            errs.append(f"{n} copies of {c.title} (max 3, 7.3.3)")
        if (c.ram_cost or 0) > lim.get(c.color, 0):
            errs.append(f"{c.title} needs {c.ram_cost} {c.color} RAM, limit {lim.get(c.color, 0)} (7.3.4)")
    if require_legal:
        for i in set(deck.legends) | set(deck.main):
            if not db[i].legal:
                errs.append(f"{db[i].title} is not legal (7.3.6)")
    return errs


def eligible_main_cards(legends: list[CardDef], db: CardDB) -> list[CardDef]:
    lim = ram_limits(legends)
    return [c for c in db.main_cards() if (c.ram_cost or 0) <= lim.get(c.color, 0)]


def random_legends(rng: random.Random, db: CardDB) -> list[CardDef]:
    pool = db.legends()
    while True:
        legs = rng.sample(pool, 3)
        names = [l.names for l in legs]
        if not (names[0] & names[1] or names[0] & names[2] or names[1] & names[2]):
            return legs


def random_deck(rng: random.Random, db: CardDB, size: int | None = None,
                legends: list[CardDef] | None = None) -> Deck:
    """Uniformly random legal deck: random Legend trio, then random cards within RAM limits."""
    legs = legends or random_legends(rng, db)
    pool = eligible_main_cards(legs, db)
    size = size or rng.randint(MIN_MAIN, MAX_MAIN)
    main: list[int] = []
    counts: Counter = Counter()
    while len(main) < size:
        c = rng.choice(pool)
        if counts[c.idx] < MAX_COPIES:
            counts[c.idx] += 1
            main.append(c.idx)
    return Deck([l.idx for l in legs], main)
