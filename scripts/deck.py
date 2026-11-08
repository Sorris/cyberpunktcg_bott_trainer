"""Check deck lists, or rewrite them in the standard format.

    python scripts/deck.py decks/bbg-proactive.txt          # check one or more lists
    python scripts/deck.py --export decks/my-list.txt        # print the list cleaned up
    python scripts/deck.py --random 3                        # print a random legal deck

Exit status is 1 when any list is not a legal deck.
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cpbot import default_db, random_deck  # noqa: E402
from cpbot.decklist import export, parse_file, report  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--export", action="store_true", help="print each list in the standard format")
    ap.add_argument("--random", type=int, metavar="SEED", default=None, help="print a random legal deck")
    a = ap.parse_args()
    db = default_db()
    if a.random is not None:
        print(export(random_deck(random.Random(a.random), db), db, name=f"Random {a.random}"), end="")
    bad = False
    for path in a.files:
        dl = parse_file(path, db)
        bad |= bool(dl.errors(db))
        if a.export:
            print(dl.to_text(db), end="")
            for line in report(dl, db).splitlines()[1:]:
                print(f"// {line.strip()}", file=sys.stderr)
        else:
            print(report(dl, db))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
