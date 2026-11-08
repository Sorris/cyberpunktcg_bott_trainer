"""Deck list import and export."""
import random
from pathlib import Path

from cpbot import default_db, random_deck
from cpbot.decklist import export, normalize, parse, parse_file

db = default_db()
SAMPLE = Path(__file__).resolve().parent.parent / "decks" / "bbg-proactive.txt"


def test_sample_list_is_legal_and_round_trips():
    dl = parse_file(str(SAMPLE))
    assert dl.name == "BBG Proactive"
    assert not dl.unknown and not dl.warnings
    assert dl.errors() == []
    assert len(dl.legends) == 3 and len(dl.main) == 40 and len(dl.sideboard) == 7
    assert db.find("Les Élémens").idx in dl.main
    assert db.find("Riot Shield").idx not in dl.main   # sideboard stays out of the deck
    assert dl.to_text() == SAMPLE.read_text(encoding="utf-8")


def test_forgiving_names():
    assert normalize("Les Élémens") == normalize("les elemens")
    dl = parse("""// Legends
1 alt cunningham - soulkiller architect
1 Hanako Arasaka
1 JACKIE WELLES: POUR ONE OUT FOR ME
// Units
3x Jacked In Voodoo Boy
Psycho Sqaud x2
3 Les Elemens
""")
    assert not dl.unknown
    titles = {db[i].title for i in dl.legends}
    assert "Hanako Arasaka - Daughter of the Emperor" in titles   # the only Legend named Hanako
    assert dl.main.count(db.find("Psycho Squad").idx) == 2
    assert any("Sqaud" in w for w in dl.warnings)
    assert any("program, listed under units" in w for w in dl.warnings)


def test_unknown_and_ambiguous_cards_are_reported():
    dl = parse("// Legends\n1 Jackie Welles\n// Units\n2 Totally Fake Card\n")
    assert [u.name for u in dl.unknown] == ["Jackie Welles", "Totally Fake Card"]
    assert "Jackie Welles: Pour One Out For Me" in dl.unknown[0].suggestions
    assert any("unknown card 'Totally Fake Card'" in e for e in dl.errors())


def test_header_counts_checked():
    dl = parse("// Units (5)\n3 Psycho Squad\n")
    assert any("header says 5" in w for w in dl.warnings)


def test_illegal_deck_errors():
    text = SAMPLE.read_text(encoding="utf-8").replace("1 Floor It", "4 Floor It")
    errs = parse(text).errors()
    assert any("4 copies of Floor It" in e for e in errs)


def test_random_decks_round_trip():
    for seed in range(30):
        d = random_deck(random.Random(seed), db)
        back = parse(export(d, db, name="x"))
        assert not back.unknown and not back.warnings
        assert sorted(back.legends) == sorted(d.legends) and sorted(back.main) == sorted(d.main)


def test_every_card_name_matches_itself():
    from cpbot.decklist import CardMatcher, card_line_name
    m = CardMatcher(db)
    for c in db.cards:
        assert m.match(card_line_name(c))[0] is c
        assert m.match(c.title)[0] is c
