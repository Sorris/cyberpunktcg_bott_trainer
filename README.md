# Cyberpunk TCG bot trainer

A rules engine for the Cyberpunk TCG. The aim is self-play AI that plays well,
tests decks and eventually designs its own.

Plan: see the project's "Cyberpunk TCG self-play bot: plan" doc.

## Status

| Milestone | State |
| --- | --- |
| 1. Card data in | Done: 152 cards and 286 official rulings in `data/cards.json` |
| 2. Engine with vanilla cards | Done: turn structure, paying, selling, Call a Legend, Go Solo, combat, Blocker, Quick Programs, stealing, Overtime, win and loss checks |
| 3. All card text scripted | Done: all 152 cards. Interpretations and shortcuts are listed in `docs/card-scripting-notes.md` |
| 4. Watchable games | Done: play-by-play logs, exact replays from seed and choices, and an HTML replay page |
| 5. Search agent | Done: ISMCTS agent. It beats random players almost every game, and more search beats less |
| 6. Stronger, faster play | Done: faster playouts and a position score learned from 20,000 self-play games. At equal thinking time it beats the old agent in 69% of games |
| 7+ | Deck search, self-play network |

## Layout

```
cpbot/cards.py    card database (data/cards.json)
cpbot/deck.py     deck rules (3 Legends, 40-50 cards, max 3 copies, RAM limits) and random legal decks
cpbot/decklist.py deck list import and export in the standard text format (// Legends, // Units, ..., // Sideboard)
cpbot/engine.py   game engine: plain-data state, explicit task stack, cloneable for search
cpbot/effects.py  effect framework: triggers, pending effects, steps, statics, abilities
cpbot/scripts/    one script per card: legends.py, units.py, programs.py, gear.py
cpbot/agents.py   random agents and a game loop
cpbot/search.py   ISMCTS search agent: samples hidden cards, searches, plays out
cpbot/features.py position features and the learned position score (data/value_weights.json)
cpbot/watch.py    play-by-play log, replay record and HTML replay page (replay_template.html)
cpbot/play.py     play against the bot: what one player can see, readable choices, decklist reader
cpbot/play.html   the battle page served by scripts/play.py
docs/             comprehensive rules (29 Oct 2026) and rules FAQ (28 Oct 2026), with the FAQ check
scripts/soak.py   plays many random games and checks invariants after every decision
scripts/learn_value.py  plays self-play games and refits the position score
scripts/arena.py  pits two agents against each other over many games and reports the win rate
scripts/watch.py  plays one game and writes games/<name>.txt, .json and .html
scripts/deck.py   checks deck list files and rewrites them in the standard format
decks/            deck lists
scripts/coverage.py  shows which card scripts actually ran in random games
scripts/play.py   play the bot yourself in your browser (standard library only)
scripts/card_images.py  builds data/card_images.json (card picture links) from ripperdeck.gg pages
scripts/fetch.sh, scripts/parse.py   how data/cards.json was built from ripperdeck.gg
tests/            rules tests
```

## Quick start

```
pip install pytest
python -m pytest -q tests
python scripts/soak.py 100000
python scripts/watch.py --seed 7      # then open games/seed7.html
python scripts/arena.py --a ismcts:200 --b eager --pairs 20
python scripts/deck.py decks/bbg-proactive.txt   # check a deck list
python scripts/arena.py --a ismcts:200 --b ismcts:200 --deck-a decks/bbg-proactive.txt --deck-b other.txt
```

Deck lists use the common text format: a `# Deck name` line, `// Legends (3)`,
`// Units`, `// Gear`, `// Programs` and `// Sideboard` headers, then `3 Card Name`
lines. Names are matched forgivingly (case, accents, `:` or ` - ` before the
subtitle, small typos), unknown cards are listed with suggestions, and the
sideboard is kept out of the played deck. `cpbot.decklist.parse(text)` gives a
`DeckList` with `.deck`, `.sideboard`, `.errors()` and `.to_text()`.

```python
import random
from cpbot import Game, default_db, random_deck
from cpbot.agents import RandomAgent, play_game

db = default_db()
rng = random.Random(0)
g = Game(random_deck(rng, db), random_deck(rng, db), seed=0, log=True)
play_game(g, [RandomAgent(1), RandomAgent(2)])
print("\n".join(g.log))
```

## Play against the bot

```
python scripts/play.py            # opens http://127.0.0.1:8765 in your browser
```

Pick your deck (the BBG Proactive sample, a random legal deck, or paste a decklist
in the usual `3 Card Name` format; `//` headings are fine and the sideboard is
left out), the bot's deck and how long the bot thinks per move. You play as the
bottom player. Cards you can use are outlined; click a card to read it and see
what you can do with it, or use the buttons on the right. Hover a card for a
bigger picture. The bot can't see your hand, and you can't see its hand.
Both trash piles sit beside the Legends and Eddies (click the top card or
"View all"). Eddies are face-down, so only ready or spent shows. **Undo** takes
back your last move and the bot's replies to it (press it again to go further
back), **End game** concedes, and **Quit** stops the server (so does Ctrl+C).

Card pictures: `data/card_images.json` holds a link to each card's picture on
ripperdeck.gg's image store. The pictures themselves aren't in the repo. The
first time a card is shown, the server downloads its picture into `.card_art/`
(ignored by git) and serves it from there after that, so later games don't hit
the site again. `python scripts/play.py --prefetch-images` downloads all 152 in one
slow, polite pass. `--no-images` plays with text-only cards. Card art belongs to
CD PROJEKT RED and WeirdCo; this is for personal play only, so don't publish the
pictures.

Face-down cards (hands, face-down Legends, Eddies) use a card-back picture if you
save one as `.card_art/card-back.png` (or `.jpg` / `.webp`), or pass
`--card-back path\to\back.png`. Without one they show the Cyberpunk TCG logo,
downloaded once from cyberpunktcg.com.

## Engine interface

- `g.decision` is the pending decision: `player`, `kind` and `options`. Core kinds are
  `go_first`, `mulligan`, `roll_in`, `main`, `pay`, `equip`, `react` and `steal`; card
  effects add kinds such as `target`, `adjust`, `discard`, `mode` and `may:<what>`.
- `g.step(option)` applies one option. Moves with only one option are applied automatically.
- `g.clone()` copies the game for look-ahead search (about 0.1 ms).

## Rules choices worth knowing

- The game rolls in a Gig at the start of each turn, as in rule 8.6.5. The d20 is
  only allowed once the fixer is otherwise empty.
- Calling a Legend flips a random face-down Legend, because you can't see your own
  face-down Legends (5.7.4.1).
- A Legend must be face-up to Go Solo, or to be played to the field without Go Solo
  (4.5). It may spend itself for an Eddie to pay for either (rules FAQ).
- After 100 turns the game is a draw. This is a safety valve; random games end
  by turn 26 at the latest.

## Watching games

`scripts/watch.py` plays one game and writes three files to `games/`:

- `<name>.txt` is the play-by-play. It's written for a spectator, so it shows hidden
  cards such as hands, draws and face-down Legends. Players are P1 and P2.
- `<name>.json` holds the seed, both decks and every choice. `--replay <file>`
  rebuilds the same game from it, step by step.
- `<name>.html` is a replay page. Step with the arrow keys (Shift for whole turns),
  or click a line in the play-by-play to jump there.

Card data comes from ripperdeck.gg and the rules from cyberpunktcg.com. This is a
fan project, not affiliated with CD PROJEKT RED or WeirdCo.
