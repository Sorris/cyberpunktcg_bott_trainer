"""Which card scripts actually ran during random games (catches dead scripts)."""
import os, random, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cpbot import Game, default_db, random_deck
from cpbot import effects as fx
from cpbot.agents import EagerRandomAgent, play_game

fx.load_scripts()
counts = Counter()
for name, fn in list(fx.STEPS.items()):
    def wrap(fn=fn, name=name):
        def w(g, ctx, **kw):
            counts[name] += 1
            src = ctx.get("src")
            if src is not None:
                counts["card:" + g.slug(src)] += 1
            return fn(g, ctx, **kw)
        return w
    fx.STEPS[name] = wrap()
db = default_db()
n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
for seed in range(n):
    rng = random.Random(seed)
    g = Game(random_deck(rng, db), random_deck(rng, db), seed=seed)
    play_game(g, [EagerRandomAgent(seed), EagerRandomAgent(seed + 7)], check=True)
never = [c.slug for c in db.cards if counts["card:" + c.slug] == 0]
print("steps never run:", sorted(k for k in fx.STEPS if counts[k] == 0))
print("cards whose effects never ran:", never)
