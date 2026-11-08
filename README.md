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
| 5+ | ISMCTS agent, deck search, self-play network |

## Layout

```
cpbot/cards.py    card database (data/cards.json)
cpbot/deck.py     deck rules (3 Legends, 40-50 cards, max 3 copies, RAM limits) and random legal decks
cpbot/engine.py   game engine: plain-data state, explicit task stack, cloneable for search
cpbot/effects.py  effect framework: triggers, pending effects, steps, statics, abilities
cpbot/scripts/    one script per card: legends.py, units.py, programs.py, gear.py
cpbot/agents.py   random agents and a game loop
cpbot/watch.py    play-by-play log, replay record and HTML replay page (replay_template.html)
docs/             comprehensive rules (29 Oct 2026) and rules FAQ (28 Oct 2026), with the FAQ check
scripts/soak.py   plays many random games and checks invariants after every decision
scripts/watch.py  plays one game and writes games/<name>.txt, .json and .html
scripts/coverage.py  shows which card scripts actually ran in random games
scripts/fetch.sh, scripts/parse.py   how data/cards.json was built from ripperdeck.gg
tests/            rules tests
```

## Quick start

```
pip install pytest
python -m pytest -q tests
python scripts/soak.py 100000
python scripts/watch.py --seed 7      # then open games/seed7.html
```

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

## Engine interface

- `g.decision` is the pending decision: `player`, `kind` and `options`. Core kinds are
  `go_first`, `mulligan`, `roll_in`, `main`, `pay`, `equip`, `react` and `steal`; card
  effects add kinds such as `target`, `adjust`, `discard`, `mode` and `may:<what>`.
- `g.step(option)` applies one option. Moves with only one option are applied automatically.
- `g.clone()` deep-copies the game for look-ahead search.

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
