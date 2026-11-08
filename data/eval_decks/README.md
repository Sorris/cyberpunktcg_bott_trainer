# Evaluation decks

Deck lists from human players, used only as fixed opponents in `scripts/arena.py`
(`--deck-a` / `--deck-b`) to check how well the bot plays against focused decks.

They must never guide deck building: the deck search, self-play and training only
use random legal decks and decks they find themselves. `tests/test_decksearch.py`
checks that none of that code refers to this folder.
