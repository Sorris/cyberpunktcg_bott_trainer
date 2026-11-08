"""Card database: loads data/cards.json into immutable CardDef records."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

LEGEND, UNIT, GEAR, PROGRAM = "legend", "unit", "gear", "program"
COLORS = ("red", "green", "blue", "yellow")


def own_keywords(listed, text):
    """The keywords a card has itself. The source lists every keyword its text
    mentions, including ones it gives to other cards ("Give another friendly Unit
    {Adrenaline}"), so only keep those printed at the start of a line."""
    own = set()
    for k in listed or []:
        k = k.lower()
        pat = r"^\{" + re.escape(k) + r"\}"
        if re.search(pat, text or "", re.I | re.M):
            own.add(k)
    return frozenset(own)


@dataclass(frozen=True)
class CardDef:
    idx: int                 # index in CardDB.cards
    id: str                  # e.g. "wtnc-001"
    slug: str
    title: str               # full printed title "Name - Subtitle"
    name: str                # name only (subtitle is not part of the name, rule 3.9.4)
    subtitle: str | None
    names: frozenset         # all names incl. ampersand parts (rule 3.9.3)
    type: str
    color: str | None
    cost: int | None         # None = null cost (rule 3.11.2)
    power: int | None
    ram_cost: int | None     # RAM needed for non-Legends
    ram_provided: int | None # RAM given by Legends
    sell: bool               # has a Sell Tag
    tags: frozenset
    keywords: frozenset      # lower-case: "blocker", "quick", "go solo", "adrenaline"
    triggers: frozenset      # lower-case: "play", "attack", "call", "defeated"
    has_spend: bool
    text: str
    legal: bool
    rulings: tuple = field(default=(), compare=False)

    def has(self, kw: str) -> bool:
        return kw in self.keywords

    def __repr__(self):
        return f"<{self.title}>"


def _split_title(title: str):
    if " - " in title:
        name, sub = title.split(" - ", 1)
    else:
        name, sub = title, None
    parts = {name}
    if "&" in name:
        parts |= {p.strip() for p in name.split("&")}
    return name, sub, frozenset(parts)


class CardDB:
    def __init__(self, path: str | None = None):
        path = path or os.path.join(DATA_DIR, "cards.json")
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.cards: list[CardDef] = []
        for i, r in enumerate(sorted(raw, key=lambda r: r["id"])):
            name, sub, names = _split_title(r["name"])
            ctype = r["card_type"]
            cost = r["eddie_cost"]
            # Legends that can't go to the field print a null cost; the source
            # stores it as 0 with null power. Treat as null (rule 4.5.3).
            if ctype == LEGEND and r["power"] is None:
                cost = None
            self.cards.append(CardDef(
                idx=i, id=r["id"], slug=r["slug"], title=r["name"], name=name,
                subtitle=sub, names=names, type=ctype, color=r["color"], cost=cost,
                power=r["power"], ram_cost=r["ram_cost"], ram_provided=r["ram_provided"],
                sell=bool(r["has_sell_tag"]),
                tags=frozenset(t.upper() for t in (r["classification"] or [])),
                keywords=own_keywords(r["keywords"], r["ability_text"]),
                triggers=frozenset(t.lower() for t in (r["triggers"] or [])),
                has_spend=bool(r["has_spend_ability"]), text=r["ability_text"] or "",
                legal=r["legality"] == "legal",
                rulings=tuple((x["q"], x["a"]) for x in r.get("rulings", [])),
            ))
        self.by_slug = {c.slug: c for c in self.cards}
        self.by_id = {c.id: c for c in self.cards}
        self.by_title = {c.title: c for c in self.cards}

    def __getitem__(self, i: int) -> CardDef:
        return self.cards[i]

    def __len__(self):
        return len(self.cards)

    def find(self, key: str) -> CardDef:
        for d in (self.by_slug, self.by_id, self.by_title):
            if key in d:
                return d[key]
        hits = [c for c in self.cards if key.lower() in c.title.lower()]
        if len(hits) == 1:
            return hits[0]
        raise KeyError(f"no unique card for {key!r}: {[h.title for h in hits]}")

    def legends(self, legal_only=True):
        return [c for c in self.cards if c.type == LEGEND and (c.legal or not legal_only)]

    def main_cards(self, legal_only=True):
        return [c for c in self.cards if c.type != LEGEND and (c.legal or not legal_only)]


_DEFAULT: CardDB | None = None


def default_db() -> CardDB:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = CardDB()
    return _DEFAULT
