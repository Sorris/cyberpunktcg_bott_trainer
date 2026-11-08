"""Read and write deck lists in the common text format.

    # BBG Proactive

    // Legends (3)
    1 Alt Cunningham: Soulkiller Architect
    ...
    // Units (14)
    3 Jacked-In Voodoo Boy
    ...
    // Sideboard (7)
    2 Modded Kusanagi

The first ``#`` line is the deck name. ``//`` (or ``#``) lines naming a section
start that section; the number in brackets is optional and is checked against
the cards listed. Card lines are ``3 Name``, ``3x Name`` or ``Name x3``.

Names are matched to card records forgivingly: case, accents ("Les Elemens"),
the subtitle separator (":" or " - "), dashes, quotes and stray punctuation are
ignored. A name with no subtitle matches when only one card has that name.
Near misses are matched with a warning; anything else is reported as unknown.

The Legend/main split comes from each card's type, not from its section, so a
Legend listed under Units still lands in the Legend slots (with a warning).
Everything under Sideboard is kept apart and never goes into the deck.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .cards import GEAR, LEGEND, PROGRAM, UNIT, CardDB, CardDef, default_db
from .deck import MAX_COPIES, Deck, ram_limits, validate

SECTIONS = {  # header word -> section key
    "legend": "legends", "legends": "legends",
    "unit": "units", "units": "units",
    "program": "programs", "programs": "programs",
    "gear": "gear", "gears": "gear",
    "main": "main", "main deck": "main", "maindeck": "main", "deck": "main",
    "sideboard": "sideboard", "side": "sideboard", "side deck": "sideboard", "sidedeck": "sideboard",
}
SECTION_TYPE = {"legends": LEGEND, "units": UNIT, "programs": PROGRAM, "gear": GEAR}
EXPORT_ORDER = [("Legends", LEGEND), ("Units", UNIT), ("Gear", GEAR), ("Programs", PROGRAM)]

_HEADER = re.compile(r"^(?://|#)\s*(.*?)\s*(?:\((\d+)\))?\s*$")
_COUNT_FIRST = re.compile(r"^(\d+)\s*[xX]?\s+(.+)$")
_COUNT_LAST = re.compile(r"^(.+?)\s+[xX]\s*(\d+)$")
FUZZY_CUTOFF = 0.88


def normalize(name: str) -> str:
    """Lower-case, accent-free, punctuation-free form used for matching."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[‘’`´']", "", s)       # apostrophes vanish: mama's -> mamas
    s = re.sub(r"[^a-z0-9]+", " ", s)    # everything else separates words
    return " ".join(s.split())


class CardMatcher:
    """Finds the card record for a name as people write it in deck lists."""

    def __init__(self, db: CardDB):
        self.db = db
        self.by_title: dict[str, CardDef] = {}
        by_name: dict[str, list[CardDef]] = {}
        for c in db.cards:
            self.by_title[normalize(c.title)] = c
            by_name.setdefault(normalize(c.name), []).append(c)
        self.by_name = by_name

    def match(self, written: str, prefer_type: str | None = None
              ) -> tuple[CardDef | None, str | None, list[str]]:
        """Return (card, warning, suggestions). card is None when nothing fits.
        prefer_type (the section's card type) settles a name shared by several cards."""
        key = normalize(written)
        if key in self.by_title:
            return self.by_title[key], None, []
        named = self.by_name.get(key, [])
        if len(named) > 1 and prefer_type:
            named = [c for c in named if c.type == prefer_type] or named
        if len(named) == 1:
            c = named[0]
            return c, f"{written!r} has no subtitle; read it as {card_line_name(c)}", []
        if len(named) > 1:
            return None, None, [card_line_name(c) for c in named]
        close = difflib.get_close_matches(key, list(self.by_title), n=3, cutoff=0.6)
        if close and difflib.SequenceMatcher(None, key, close[0]).ratio() >= FUZZY_CUTOFF:
            second = (difflib.SequenceMatcher(None, key, close[1]).ratio() if len(close) > 1 else 0)
            if second < FUZZY_CUTOFF:
                c = self.by_title[close[0]]
                return c, f"{written!r} is not an exact card name; read it as {card_line_name(c)}", []
        return None, None, [card_line_name(self.by_title[k]) for k in close]


@dataclass
class Unknown:
    line_no: int
    line: str
    name: str
    count: int
    suggestions: list[str]

    def __str__(self):
        hint = f" (did you mean: {', '.join(self.suggestions)}?)" if self.suggestions else ""
        return f"line {self.line_no}: unknown card {self.name!r}{hint}"


@dataclass
class DeckList:
    name: str | None = None
    legends: list[int] = field(default_factory=list)
    main: list[int] = field(default_factory=list)
    sideboard: list[int] = field(default_factory=list)
    unknown: list[Unknown] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def deck(self) -> Deck:
        """The playable deck (Legends + main). The sideboard is not included."""
        return Deck(list(self.legends), list(self.main))

    def errors(self, db: CardDB | None = None, require_legal=True) -> list[str]:
        """Rule violations for the deck plus every unknown card. Empty = ready to play."""
        db = db or default_db()
        return [str(u) for u in self.unknown] + validate(self.deck, db, require_legal)

    def sideboard_notes(self, db: CardDB | None = None) -> list[str]:
        """Things to watch when siding in. The rules don't cover sideboards, so these are advice."""
        db = db or default_db()
        notes = []
        lim = ram_limits([db[i] for i in self.legends])
        both = Counter(self.main) + Counter(self.sideboard)
        for i in sorted(set(self.sideboard), key=lambda i: db[i].title):
            c = db[i]
            if c.type == LEGEND:
                continue
            if (c.ram_cost or 0) > lim.get(c.color, 0):
                notes.append(f"sideboard {c.title} needs {c.ram_cost} {c.color} RAM, these Legends give "
                             f"{lim.get(c.color, 0)}")
            if both[i] > MAX_COPIES:
                notes.append(f"{both[i]} copies of {c.title} across main deck and sideboard")
        return notes

    def is_legal(self, db: CardDB | None = None) -> bool:
        return not self.errors(db)

    def to_text(self, db: CardDB | None = None, name: str | None = None) -> str:
        return export(self.deck, db, name=name or self.name, sideboard=self.sideboard)


def parse(text: str, db: CardDB | None = None) -> DeckList:
    """Parse a deck list. Never raises on bad lines: they go to .unknown or .warnings."""
    db = db or default_db()
    m = CardMatcher(db)
    out = DeckList()
    section = "main"
    declared: dict[str, int] = {}
    listed: Counter = Counter()

    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        h = _HEADER.match(line)
        if h:
            word, n = h.group(1).strip().rstrip(":").lower(), h.group(2)
            if word in SECTIONS:
                section = SECTIONS[word]
                if n is not None:
                    declared[section] = declared.get(section, 0) + int(n)
            elif line.startswith("#") and out.name is None and word:
                out.name = h.group(1).strip()
            continue  # any other comment line is ignored
        cm = _COUNT_FIRST.match(line)
        if cm:
            count, written = int(cm.group(1)), cm.group(2).strip()
        else:
            cl = _COUNT_LAST.match(line)
            if cl:
                written, count = cl.group(1).strip(), int(cl.group(2))
            else:
                written, count = line, 1
                out.warnings.append(f"line {no}: no count on {line!r}; assumed 1")
        listed[section] += count
        card, warn, sugg = m.match(written, SECTION_TYPE.get(section))
        if warn:
            out.warnings.append(f"line {no}: {warn}")
        if card is None:
            out.unknown.append(Unknown(no, raw, written, count, sugg))
            continue
        if section == "sideboard":
            out.sideboard.extend([card.idx] * count)
            continue
        want = SECTION_TYPE.get(section)
        if want and card.type != want:
            out.warnings.append(f"line {no}: {card.title} is a {card.type}, listed under {section}")
        (out.legends if card.type == LEGEND else out.main).extend([card.idx] * count)

    for sec, n in declared.items():
        if listed[sec] != n:
            out.warnings.append(f"{sec} header says {n} cards, {listed[sec]} listed")
    return out


def parse_file(path: str, db: CardDB | None = None) -> DeckList:
    with open(path, encoding="utf-8-sig") as f:
        return parse(f.read(), db)


def card_line_name(c: CardDef) -> str:
    """The name as deck lists write it: 'Name: Subtitle'."""
    return f"{c.name}: {c.subtitle}" if c.subtitle else c.name


def export(deck: Deck, db: CardDB | None = None, name: str | None = None,
           sideboard: list[int] | None = None) -> str:
    """Write a deck in the same text format parse() reads."""
    db = db or default_db()
    lines = [f"# {name}", ""] if name else []
    cards = list(deck.legends) + list(deck.main)
    for label, ctype in EXPORT_ORDER:
        counts = Counter(i for i in cards if db[i].type == ctype)
        if counts:
            lines += _section(label, counts, db)
    if sideboard:
        lines += _section("Sideboard", Counter(sideboard), db)
    return "\n".join(lines).rstrip() + "\n"


def _section(label: str, counts: Counter, db: CardDB) -> list[str]:
    rows = sorted(counts.items(), key=lambda kv: normalize(card_line_name(db[kv[0]])))
    return ([f"// {label} ({sum(counts.values())})"]
            + [f"{n} {card_line_name(db[i])}" for i, n in rows] + [""])


def report(dl: DeckList, db: CardDB | None = None) -> str:
    """A short human-readable check of a parsed list."""
    db = db or default_db()
    errs = dl.errors(db)
    head = dl.name or "Deck"
    status = "legal" if not errs else f"NOT legal ({len(errs)} problem{'s' * (len(errs) != 1)})"
    lines = [f"{head}: {len(dl.legends)} Legends, {len(dl.main)} main deck cards, "
             f"{len(dl.sideboard)} sideboard cards. {status}"]
    lines += [f"  error: {e}" for e in errs]
    lines += [f"  warning: {w}" for w in dl.warnings]
    lines += [f"  sideboard: {n}" for n in dl.sideboard_notes(db)]
    return "\n".join(lines)
