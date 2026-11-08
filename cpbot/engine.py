"""Cyberpunk TCG rules engine.

Design
------
The whole game is plain data (lists, dicts, tuples, a random.Random), so a
game can be copied with ``Game.clone()`` for look-ahead search.

Control flow is an explicit task stack. Each task is a tuple ``(name, args)``
that runs ``Game._t_<name>(*args)``. A task may push more tasks, or stop and
ask a player for a decision. The answer is delivered by pushing the decision's
``resume`` task with the chosen option appended to its arguments. Card effects
run as data-only step lists (see effects.py), so cloning works mid-effect.

Players interact through three calls:
    g.decision            -> Decision(player, kind, options) or None when over
    g.legal_actions()     -> list of options for the current decision
    g.step(option)        -> apply one option

Rule numbers in comments refer to docs/comprehensive-rules.md.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field as dfield

from . import effects as fx
from .cards import GEAR, LEGEND, PROGRAM, UNIT, CardDB, default_db
from .deck import Deck

DICE = (4, 6, 8, 10, 12, 20)
TURN_LIMIT = 100          # safety valve: game is a draw after this many turns
WIN_GIGS = 7

# Tasks at which pending effects must be resolved first (open game states, 10.11.1)
OPEN_TASKS = {"main", "react", "attack_check", "attack_resolve", "fight", "steal_step",
              "end_attack", "end_turn", "cleanup", "ready_step", "draw_step", "roll_in",
              "start_turn", "main_after"}


@dataclass
class Decision:
    player: int
    kind: str
    options: list
    resume: str
    ctx: tuple = ()


@dataclass
class Card:
    uid: int
    cid: int
    owner: int
    zone: str = "deck"    # deck hand field legends eddies trash removed limbo equipped
    spent: bool = False
    face_up: bool = False
    lag: bool = False
    entered_turn: int = -1  # turn it entered the field
    solo_turn: int = -1
    gears: list = dfield(default_factory=list)
    host: int | None = None
    mods: list = dfield(default_factory=list)    # [power delta, duration]


@dataclass
class Player:
    idx: int
    deck: list = dfield(default_factory=list)     # top of deck = end of list
    hand: list = dfield(default_factory=list)
    field: list = dfield(default_factory=list)
    legends: list = dfield(default_factory=list)
    eddies: list = dfield(default_factory=list)
    trash: list = dfield(default_factory=list)
    removed: list = dfield(default_factory=list)
    fixer: list = dfield(default_factory=lambda: list(DICE))
    gigs: list = dfield(default_factory=list)     # [sides, value]
    sold: bool = False
    called: bool = False
    mulliganed: bool = False
    known_legends: list = dfield(default_factory=list)


class Game:
    def __init__(self, deck0: Deck, deck1: Deck, seed: int | None = None,
                 db: CardDB | None = None, log: bool = False, registry=None):
        self.db = db or default_db()
        if registry is None:
            fx.load_scripts()
            registry = fx.REGISTRY
        self.effects = registry
        self.rng = random.Random(seed)
        self.cards: dict[int, Card] = {}
        self.players = [Player(0), Player(1)]
        self.turn_player = 0
        self.first_player = 0
        self.turn_no = 0
        self.stack: list = []
        self.decision: Decision | None = None
        self.winner = None
        self.end_reason = ""
        self.overtime = False
        self.empty_streak = 0
        self.attack: dict | None = None
        self.pending: list = []      # [controller, steps, ctx]
        self.lasting: list = []      # dicts, see effects.py
        self.turn_flags: dict = {}   # cleared at end of each turn
        self.history: list = []
        self.logging = log
        self.log: list[str] = []
        self.observer = None         # optional watcher with .log(game, msg); see watch.py
        self._active = None          # cached active cards while listing options (read-only)
        uid = 0
        for p, deck in ((0, deck0), (1, deck1)):
            for cid in deck.main:
                self.cards[uid] = Card(uid, cid, p)
                self.players[p].deck.append(uid)
                uid += 1
            for cid in deck.legends:
                self.cards[uid] = Card(uid, cid, p, zone="legends")
                self.players[p].legends.append(uid)
                uid += 1
        self.stack.append(("setup", ()))
        self.advance()

    # ------------------------------------------------------------------ API
    def legal_actions(self) -> list:
        return list(self.decision.options) if self.decision else []

    @property
    def current_player(self):
        return self.decision.player if self.decision else None

    @property
    def over(self) -> bool:
        return self.winner is not None

    def step(self, option) -> None:
        d = self.decision
        if d is None:
            raise RuntimeError("game is over")
        if option not in d.options:
            raise ValueError(f"illegal option {option!r} for {d.kind}: {d.options}")
        self.decision = None
        self.history.append((d.player, d.kind, option))
        self._log(f"P{d.player} {d.kind}: {self.describe(option)}")
        self.stack.append((d.resume, d.ctx + (option,)))
        self.advance()

    def clone(self) -> "Game":
        """Copy the game for look-ahead search. The log and observer aren't copied.

        Cards, players and Gigs are copied by hand (fast); the task stack, pending
        effects and other loose state are deep-copied with a memo that maps every
        hand-copied object to its copy, so references between them (for example an
        effect that holds a Gig) still point at the same object in the clone."""
        g = Game.__new__(Game)
        g.__dict__.update(self.__dict__)
        memo = {}
        cards = {}
        for u, c in self.cards.items():
            n = Card(c.uid, c.cid, c.owner, c.zone, c.spent, c.face_up, c.lag,
                     c.entered_turn, c.solo_turn, list(c.gears), c.host, [])
            for m in c.mods:
                m2 = list(m) if isinstance(m, list) else m
                memo[id(m)] = m2
                n.mods.append(m2)
            memo[id(c)] = n
            memo[id(c.gears)] = n.gears
            memo[id(c.mods)] = n.mods
            cards[u] = n
        players = []
        for pl in self.players:
            n = Player(pl.idx)
            for name in ("deck", "hand", "field", "legends", "eddies", "trash", "removed",
                         "fixer", "known_legends"):
                old = getattr(pl, name)
                new = list(old)
                memo[id(old)] = new
                setattr(n, name, new)
            n.gigs = []
            for gig in pl.gigs:
                g2 = list(gig)
                memo[id(gig)] = g2
                n.gigs.append(g2)
            memo[id(pl.gigs)] = n.gigs
            n.sold, n.called, n.mulliganed = pl.sold, pl.called, pl.mulliganed
            memo[id(pl)] = n
            players.append(n)
        memo[id(self.cards)] = cards
        memo[id(self.players)] = players
        g.cards, g.players = cards, players
        loose = (self.stack, self.decision, self.attack, self.pending, self.lasting, self.turn_flags)
        g.stack, g.decision, g.attack, g.pending, g.lasting, g.turn_flags = copy.deepcopy(loose, memo)
        g.rng = random.Random()
        g.rng.setstate(self.rng.getstate())
        g.history = list(self.history)
        g.log = []
        g.logging = False
        g.observer = None
        return g

    # ------------------------------------------------------------ machinery
    def advance(self):
        while self.decision is None and self.winner is None:
            if not self.stack:
                raise RuntimeError("task stack empty without a decision")
            if self.pending and self.stack[-1][0] in OPEN_TASKS:
                self._t_resolve_pending()
                continue
            name, args = self.stack.pop()
            getattr(self, "_t_" + name)(*args)
            if self.overtime and self.winner is None:
                self._check_overtime_win()

    def then(self, *tasks):
        for t in reversed(tasks):
            self.stack.append(t)

    def ask(self, player, kind, options, resume, ctx=()):
        if not options:
            raise RuntimeError(f"no options for {kind}")
        if len(options) == 1:
            self.stack.append((resume, tuple(ctx) + (options[0],)))
            return
        self.decision = Decision(player, kind, list(options), resume, tuple(ctx))

    def _log(self, msg):
        if self.observer is not None:
            self.observer.log(self, msg)
        if self.logging:
            self.log.append(f"[T{self.turn_no}] {msg}")

    def win(self, p, reason):
        if self.winner is None:
            self.winner = p
            self.end_reason = reason
            self.decision = None
            self._log(f"GAME OVER: {'draw' if p == 'draw' else f'P{p} wins'} ({reason})")

    def lose(self, p, reason):
        self.win(1 - p, reason)

    # ---------------------------------------------------- effects plumbing
    def trigger(self, me, steps, **ctx):
        """Make a triggered effect pending (10.16). Controller = controller of `me`."""
        p = ctx.pop("p", None)
        if p is None:
            p = self.controller(me)
        ctx.update(p=p, src=me)
        self.pending.append([p, tuple(steps), ctx])

    def run_effect(self, p, steps, src=None, **ctx):
        """Resolve an effect right now (Programs, activated abilities)."""
        ctx.update(p=p, src=src)
        self.then(("effect", (tuple(steps), ctx, 0)))

    def _t_resolve_pending(self):
        """Turn player resolves all their pending effects first (10.13), in any order
        they choose (10.12); then the Rival does the same."""
        tp = self.turn_player
        for who in (tp, 1 - tp):
            mine = [i for i, pe in enumerate(self.pending) if pe[0] == who]
            if not mine:
                continue
            if len(mine) == 1:
                self._t_resolve_pick(("pending", 0, None))
                return
            opts = []
            for k, i in enumerate(mine):
                src = self.pending[i][2].get("src")
                opts.append(("pending", k, self.cards[src].cid if src is not None else None))
            self.decision = Decision(who, "order_pending", opts, "resolve_pick", ())
            return

    def _t_resolve_pick(self, opt):
        tp = self.turn_player
        for who in (tp, 1 - tp):
            mine = [i for i, pe in enumerate(self.pending) if pe[0] == who]
            if mine:
                i = mine[opt[1]]
                _, steps, ctx = self.pending.pop(i)
                self.then(("effect", (steps, ctx, 0)))
                return

    def _t_effect(self, steps, ctx, i):
        steps = list(steps)
        while i < len(steps):
            name, params = steps[i]
            i += 1
            res = fx.STEPS[name](self, ctx, **params)
            if self.winner is not None:
                return
            if res is None:
                continue
            if res == fx.STOP:
                return
            if isinstance(res, list):
                steps = steps[:i] + res + steps[i:]
                continue
            if isinstance(res, fx.Ask):
                self.stack.append(("effect", (tuple(steps), ctx, i)))
                opts = res.options
                if len(opts) == 1:
                    ctx[res.key] = opts[0]
                    return
                self.decision = Decision(res.player, res.kind, list(opts), "effect_answer", (res.key, ctx))
                return
            raise TypeError(f"step {name} returned {res!r}")

    def _t_effect_answer(self, key, ctx, answer):
        ctx[key] = answer

    def add_lasting(self, L):
        L = dict(L)
        L.setdefault("turn", self.turn_no)
        self.lasting.append(L)

    def flag(self, kind, *args) -> bool:
        return self.effects.flag(self, kind, *args)

    def cond(self, ctx, c):
        name, *args = c if isinstance(c, tuple) else (c,)
        return fx.CONDS[name](self, ctx, *args)

    def candidates(self, ctx, c):
        name, *args = c if isinstance(c, tuple) else (c,)
        return fx.CANDS[name](self, ctx, *args)

    # -------------------------------------------------------------- queries
    def d(self, uid):
        return self.db[self.cards[uid].cid]

    def slug(self, uid):
        return self.db[self.cards[uid].cid].slug

    def controller(self, uid):
        c = self.cards[uid]
        if c.zone == "equipped" and c.host is not None:
            return self.controller(c.host)
        for p, pl in enumerate(self.players):
            if uid in pl.field or uid in pl.legends or uid in pl.eddies:
                return p
        return c.owner

    def rival(self, p):
        return 1 - p

    def units(self, p):
        return list(self.players[p].field)

    def is_unit(self, uid):
        return self.cards[uid].zone == "field"

    def base_power(self, uid):
        return self.d(uid).power or 0

    def raw_power(self, uid) -> int:
        c = self.cards[uid]
        p = self.d(uid).power or 0
        if c.zone == "equipped":
            return p
        p += sum(self.d(g).power or 0 for g in c.gears)
        p += sum(m[0] for m in c.mods)
        p += self.effects.static_power(self, uid)
        return p

    def power(self, uid) -> int:
        """Current power (3.17.2); negatives count as 0 (2.10.1)."""
        return max(0, self.raw_power(uid))

    def has_kw(self, uid, kw) -> bool:
        if kw in self.d(uid).keywords:
            return True
        for gu in self.cards[uid].gears:
            gd = self.d(gu)
            if kw in gd.keywords and kw in ("blocker",):
                return True
        return self.effects.grants_keyword(self, uid, kw)

    def has_tag(self, uid, tag):
        return tag.upper() in self.d(uid).tags

    def street_cred(self, p):
        g = self.players[p].gigs
        return sum(v for _, v in g) if g else None   # None = Null (11.2.3)

    def cred_cmp(self, p):
        """-1 if p has less Street Cred than the Rival, 0 equal, 1 more. Null < 0 (5.11.4.2)."""
        a, b = self.street_cred(p), self.street_cred(1 - p)
        a = -1 if a is None else a
        b = -1 if b is None else b
        return (a > b) - (a < b)

    def gig_count(self, p):
        return len(self.players[p].gigs)

    def min_gigs(self, p):
        return [g for g in self.players[p].gigs if g[1] == 1]

    def max_gigs(self, p):
        return [g for g in self.players[p].gigs if g[1] == g[0]]

    def value_pairs(self, p) -> int:
        from collections import Counter
        return sum(n // 2 for n in Counter(v for _, v in self.players[p].gigs).values())

    def gigs_at_least(self, p, v):
        return [g for g in self.players[p].gigs if g[1] >= v]

    def ready_eddies(self, p):
        return [u for u in self.players[p].eddies if not self.cards[u].spent]

    def pay_sources(self, p, exclude=None):
        out = []
        for u in self.players[p].legends:
            c = self.cards[u]
            if u != exclude and not c.spent and (not c.face_up or self.d(u).sell):
                out.append(u)
        return out

    def can_pay(self, p, amount, exclude=None) -> bool:
        return amount <= len(self.ready_eddies(p)) + len(self.pay_sources(p, exclude))

    def play_cost(self, p, uid) -> int:
        return self.effects.modify_cost(self, p, uid, self.d(uid).cost)

    def can_call(self, p):
        pl = self.players[p]
        return not pl.called and any(not self.cards[u].face_up for u in pl.legends)

    def call_cost(self, p):
        return 0 if self.flag("free_call", p) else 1

    def may_attack_target(self, uid, target) -> bool:
        c = self.cards[uid]
        if self.flag("cant_attack", uid) or self.flag("cant_attack_target", uid, target):
            return False
        if c.lag and not (self.has_kw(uid, "adrenaline") or c.solo_turn == self.turn_no):
            # 'can attack the turn it's played' permissions limited to some targets
            if not self.flag("lag_attack_ok", uid, target):
                return False
        return True

    def attack_targets(self, uid):
        c = self.cards[uid]
        if c.zone != "field" or c.spent:
            return []
        p = self.controller(uid)
        rival = self.players[1 - p]
        t = []
        if rival.gigs:
            t.append(("gigs",))
        for v in rival.field:
            if self.cards[v].spent or self.flag("can_attack_ready", uid, v):
                t.append(("unit", v))
        return [x for x in t if self.may_attack_target(uid, x)]

    def equip_targets(self, p, gear_uid=None):
        pl = self.players[p]
        cands = list(pl.field) + [u for u in pl.legends if self.cards[u].face_up]
        if gear_uid is not None:
            only = self.turn_flags.get(("equip_only_other", gear_uid))
            if only is not None:
                cands = [u for u in cands if u != only and self.cards[u].zone == "field"]
        return cands

    def filter_ok(self, ctx, uid, filt):
        name, *args = filt
        return fx.CONDS[name](self, ctx, uid, *args)

    def describe(self, opt) -> str:
        if not (isinstance(opt, tuple) and opt):
            return str(opt)
        k = opt[0]
        try:
            if k in ("sell", "play", "quick", "card"):
                return f"{k} {self.db[opt[1]].title}"
            if k in ("solo", "deploy", "block", "legend", "equip", "unit", "target"):
                return f"{k} {self.d(opt[1]).title}"
            if k == "attack":
                return f"attack with {self.d(opt[1]).title} -> {self.describe(opt[2])}"
            if k == "activate":
                return f"activate {self.d(opt[1]).title} #{opt[2]}"
            if k == "gig":
                return f"d{opt[1]}={opt[2]}"
            if k == "gigs":
                return "rival Gig area"
        except (KeyError, IndexError, TypeError):
            pass
        return " ".join(str(x) for x in opt)

    # --------------------------------------------------------------- moves
    def _detach(self, uid):
        c = self.cards[uid]
        if c.zone == "equipped" and c.host is not None:
            self.cards[c.host].gears.remove(uid)
            c.host = None
            return
        if c.zone in ("limbo",):
            return
        for pl in self.players:
            seq = getattr(pl, c.zone, None)
            if isinstance(seq, list) and uid in seq:
                seq.remove(uid)
                return

    def move(self, uid, zone, p=None, top=True):
        """Move a card between areas. Gear follows its host (4.12)."""
        c = self.cards[uid]
        self._detach(uid)
        if self.d(uid).type == LEGEND and zone not in ("legends", "field", "limbo"):
            zone = "removed"                                    # 4.4.1
        old_zone = c.zone
        c.zone = zone
        pl = self.players[c.owner if p is None else p]
        if zone == "deck":
            (pl.deck.append(uid) if top else pl.deck.insert(0, uid))
        elif zone not in ("limbo", "equipped"):
            getattr(pl, zone).append(uid)
        if zone not in ("field", "legends"):
            c.spent = False
            c.lag = False
            c.mods.clear()
            c.solo_turn = -1
            c.face_up = zone in ("trash", "removed", "limbo")
        if zone == "field" and old_zone != "field":
            c.entered_turn = self.turn_no
        if c.gears and zone not in ("field", "legends"):
            dest = "trash" if zone in ("trash", "removed") else zone
            for gu in list(c.gears):
                c.gears.remove(gu)
                gc = self.cards[gu]
                gc.host = None
                gc.zone = dest
                gc.mods.clear()
                gc.face_up = dest in ("trash",)
                gpl = self.players[gc.owner]
                if dest == "deck":
                    (gpl.deck.append(gu) if top else gpl.deck.insert(0, gu))
                elif dest != "limbo":
                    getattr(gpl, dest).append(gu)
        return old_zone

    def draw(self, p, n=1):
        pl = self.players[p]
        for _ in range(n):
            if not pl.deck:
                self.lose(p, "drew from an empty deck")
                return
            uid = pl.deck.pop()
            self.cards[uid].zone = "hand"
            pl.hand.append(uid)

    def trash_top(self, p, n):
        out = []
        pl = self.players[p]
        for _ in range(n):
            if not pl.deck:
                break
            u = pl.deck[-1]
            self.move(u, "trash")
            out.append(u)
        return out

    def bottom_deck(self, uids, random_order=True):
        groups = {}
        for u in uids:
            groups.setdefault(self.cards[u].owner, []).append(u)
        for owner, us in groups.items():
            allc = []
            for u in us:
                allc.append(u)
                allc.extend(self.cards[u].gears)
            if random_order:
                self.rng.shuffle(allc)
            for u in allc:
                if self.cards[u].zone != "deck":
                    self.move(u, "deck", owner, top=False)

    def shuffle_deck(self, p):
        self.rng.shuffle(self.players[p].deck)

    def give_power(self, uid, n, dur="turn"):
        self.cards[uid].mods.append([n, dur])

    def ready(self, uid):
        if not self.flag("cant_ready", uid):
            self.cards[uid].spent = False

    def spend(self, uid, reason="other"):
        c = self.cards[uid]
        if c.spent:
            return
        c.spent = True
        if c.zone in ("field", "legends"):
            self.emit("spent", uid=uid, reason=reason)

    def emit(self, event, **ev):
        self.effects.on_event(self, event, ev)

    # ---- defeat (11.6)
    def defeat_steps(self, uid, by=None):
        """Steps that defeat a card, offering optional replacement effects (10.26)."""
        return [fx.S("_defeat_offer", uid=uid, by=by), fx.S("_defeat_do", uid=uid, by=by)]

    def defeat_now(self, uid, by=None):
        """Defeat with only mandatory replacements (used where no choice can be asked)."""
        c = self.cards[uid]
        if c.zone not in ("field", "legends", "equipped"):
            return
        repl = self.mandatory_defeat_replacement(uid)
        if repl is not None:
            self.defeat_now(repl, by)
            return
        self._log(f"  {self.d(uid).title} is defeated")
        snapshot = {"power": self.power(uid), "gears": list(c.gears), "owner": c.owner,
                    "controller": self.controller(uid), "tags": list(self.d(uid).tags),
                    "zone": c.zone, "host": c.host}
        self.move(uid, "trash")
        self.emit("defeated", uid=uid, by=by, snapshot=snapshot)

    def mandatory_defeat_replacement(self, uid):
        """Deadman Transmitter: 'If this Unit would be defeated, defeat its DEADMAN TRANSMITTER instead.'"""
        for gu in self.cards[uid].gears:
            if self.slug(gu) == "deadman-transmitter":
                return gu
        return None

    # ---- gigs (section 6)
    def find_gig(self, owner, sides, value):
        for i, g in enumerate(self.players[owner].gigs):
            if g[0] == sides and g[1] == value:
                return i
        raise KeyError((owner, sides, value))

    def set_gig(self, owner, idx, new, by=None):
        g = self.players[owner].gigs[idx]
        if new == g[1] or not 1 <= new <= g[0]:
            return False                                       # 6.4.3, 6.5.1
        g[1] = new
        self.emit("gig_changed", owner=owner, gig=g, by=by)
        return True

    def gig_adjust_options(self, p, amount, mode="any", upto=True, who="any", exact=False):
        owners = {"any": (0, 1), "friendly": (p,), "rival": (1 - p,)}[who]
        opts, seen = [], set()
        for o in owners:
            for s, v in self.players[o].gigs:
                if (o, s, v) in seen:
                    continue
                seen.add((o, s, v))
                lo, hi = 1, s
                news = set()
                rng = [amount] if exact else range(1, amount + 1)
                for d in rng:
                    if mode in ("any", "up") and v + d <= hi:
                        news.add(v + d)
                    if mode in ("any", "down") and v - d >= lo:
                        news.add(v - d)
                    if mode in ("up",) and v + d > hi and not exact:
                        news.add(hi)
                    if mode in ("down",) and v - d < lo and not exact:
                        news.add(lo)
                news.discard(v)
                for nv in sorted(news):
                    opts.append(("gig", o, s, v, nv))
        return opts

    def swap_gigs(self, p, fi, ri):
        a, b = self.players[p].gigs, self.players[1 - p].gigs
        ga, gb = a[fi], b[ri]
        a[fi], b[ri] = gb, ga
        self.emit("gig_swapped", p=p)

    def take_gig(self, from_p, idx, to_p):
        g = self.players[from_p].gigs.pop(idx)
        self.players[to_p].gigs.append(g)
        return g

    # ---- calling
    def call_legend(self, p, free=True):
        pl = self.players[p]
        down = [u for u in pl.legends if not self.cards[u].face_up]
        if not down or pl.called:
            return None
        u = self.rng.choice(down)                              # 5.7.4.1
        self.cards[u].face_up = True
        pl.called = True
        self._log(f"  P{p} calls {self.d(u).title}")
        self.emit("call", player=p, uid=u)
        return u

    # ---- playing from effects
    def play_free(self, p, uid, free=True, **flags):
        """Play a card through an effect (11.7.3). Flags: bottom_after, attack_units_this_turn,
        equip_only_other (uid)."""
        for k, v in flags.items():
            self.turn_flags[(k, uid)] = v
        self.move(uid, "limbo")
        if free:
            self.then(("resolve_play", (p, uid)))
        else:
            self.then(("pay", (p, self.play_cost(p, uid), -1)), ("resolve_play", (p, uid)))

    def can_activate(self, p, host, src, ab) -> bool:
        hc = self.cards[host]
        if ab.spend:
            if hc.spent:
                return False
            if hc.zone == "field" and hc.lag:                   # 11.3.1.2
                return False
        cost = ab.eddies
        if ab.name == "johnny":
            cost = max(0, cost - len(self.gigs_at_least(p, 8)))
        if cost and not self.can_pay(p, cost, exclude=host if ab.spend else None):
            return False
        if ab.condition and not ab.condition(self, src):
            return False
        if ab.targets and not ab.targets(self, src):
            return False
        return True

    # ================================================================ TASKS
    def _t_setup(self):
        chooser = self.rng.randrange(2)
        self.ask(chooser, "go_first", [True, False], "set_first", (chooser,))

    def _t_set_first(self, chooser, go_first):
        fp = chooser if go_first else 1 - chooser
        self.first_player = self.turn_player = fp
        for p in (0, 1):
            self.shuffle_deck(p)
            self.rng.shuffle(self.players[p].legends)
        for u in self.players[fp].legends[:2]:                 # 7.7.4
            self.cards[u].spent = True
        for p in (0, 1):
            self.draw(p, 6)
        self.then(("mulligan", (fp,)), ("mulligan", (1 - fp,)), ("start_turn", ()))

    def _t_mulligan(self, p):
        self.ask(p, "mulligan", [False, True], "do_mulligan", (p,))

    def _t_do_mulligan(self, p, yes):
        if yes:
            pl = self.players[p]
            for u in list(pl.hand):
                self.move(u, "deck")
            self.shuffle_deck(p)
            self.draw(p, 6)
            pl.mulliganed = True

    # ---- start phase (8.6)
    def _t_start_turn(self):
        self.turn_no += 1
        tp = self.turn_player
        if self.turn_no > TURN_LIMIT:
            self.win("draw", "turn limit")
            return
        both_empty = not self.players[0].fixer and not self.players[1].fixer
        self.empty_streak = self.empty_streak + 1 if both_empty else 0
        for pl in self.players:
            pl.called = False
        self.players[tp].sold = False
        self._log(f"--- Turn {self.turn_no}: P{tp} ---")
        if len(self.players[tp].gigs) >= WIN_GIGS:              # 1.10 / 8.6.1
            self.win(tp, "started turn with 7 Gigs")
            return
        self.then(("start_effects", (tp,)), ("ready_step", (tp,)), ("draw_step", (tp,)),
                  ("roll_in", (tp,)), ("main", ()))

    def _t_start_effects(self, tp):
        for c in self.cards.values():                           # 8.6.2.1
            if c.mods:
                c.mods[:] = [m for m in c.mods if not (m[1] == "next_turn" and self.controller(c.uid) == 1 - tp)]
        self.lasting = [L for L in self.lasting if not (L.get("until") == "next_turn" and L["p"] == tp)]
        self.emit("turn_start", player=tp)

    def _t_ready_step(self, tp):
        pl = self.players[tp]
        for u in pl.field + pl.eddies:
            self.ready(u)
        for i, u in enumerate(pl.legends):
            if self.turn_no == 1 and i < 2 and tp == self.first_player:
                continue                                        # 7.7.4
            self.ready(u)

    def _t_draw_step(self, tp):
        self.draw(tp, 1)

    def _t_roll_in(self, tp):
        fxr = self.players[tp].fixer
        if not fxr:
            return
        opts = [d for d in fxr if d != 20] or [20]              # 8.6.5.1.1
        self.ask(tp, "roll_in", opts, "do_roll_in", (tp,))

    def _t_do_roll_in(self, tp, sides):
        pl = self.players[tp]
        pl.fixer.remove(sides)
        g = [sides, self.rng.randint(1, sides)]
        pl.gigs.append(g)
        self._log(f"  P{tp} rolls in d{sides} = {g[1]}")
        self.emit("roll_in", player=tp, gig=g)

    # ---- main phase (8.9 - 8.15)
    def main_options(self):
        """Listing options only reads the state, so the active cards are cached."""
        self._active = None
        self._active = self.effects.active_cards(self)
        try:
            return self._main_options()
        finally:
            self._active = None

    def _main_options(self):
        tp = self.turn_player
        pl = self.players[tp]
        opts = []
        must = [L["unit"] for L in self.lasting if L["kind"] == "must_attack"
                and self.cards[L["unit"]].zone == "field" and self.controller(L["unit"]) == tp
                and L["turn"] < self.turn_no]
        forced = [u for u in must if self.attack_targets(u)]
        if not forced:
            opts.append(("pass",))
        if not pl.sold:
            for cid in sorted({self.cards[u].cid for u in pl.hand if self.d(u).sell}):
                opts.append(("sell", cid))
        if self.can_call(tp) and self.can_pay(tp, self.call_cost(tp)):
            opts.append(("call",))
        seen = set()
        for u in pl.hand:
            c = self.d(u)
            if c.idx in seen:
                continue
            seen.add(c.idx)
            if self.can_play(tp, u):
                opts.append(("play", c.idx))
        for u in pl.legends:
            c = self.cards[u]
            dd = self.d(u)
            if c.face_up and dd.cost is not None and dd.power is not None:
                # A Legend may spend itself for an Eddie to pay for its own play (rules FAQ).
                if self.can_pay(tp, self.play_cost(tp, u)) and not self.flag("cant_play", tp, u):
                    opts.append(("deploy", u))                  # 4.5: enters with lag
                    if dd.has("go solo"):
                        opts.append(("solo", u))                # 11.29: ready, can attack
        for u in pl.field:
            for t in self.attack_targets(u):
                opts.append(("attack", u, t))
        opts.extend(self.effects.activated_options(self, tp, reaction=False))
        return opts

    def can_play(self, p, uid) -> bool:
        dd = self.d(uid)
        if dd.type == LEGEND:
            return False
        if dd.type == GEAR and not self.equip_targets(p):
            return False
        if self.flag("cant_play", p, uid):
            return False
        return self.can_pay(p, self.play_cost(p, uid))

    def _t_main(self):
        self.ask(self.turn_player, "main", self.main_options(), "main_act")

    def _t_main_after(self):
        pass

    def _t_main_act(self, act):
        tp = self.turn_player
        kind = act[0]
        if kind == "pass":
            self.then(("end_turn", ()))
            return
        self.then(("main_after", ()), ("main", ()))
        if kind == "sell":
            uid = next(u for u in self.players[tp].hand if self.cards[u].cid == act[1])
            self.sell(tp, uid)
            self.players[tp].sold = True
        elif kind == "call":
            self.then(("pay", (tp, self.call_cost(tp), -1)), ("do_call", (tp,)))
        elif kind == "play":
            uid = next(u for u in self.players[tp].hand if self.cards[u].cid == act[1])
            self.start_play(tp, uid)
        elif kind == "solo":
            uid = act[1]
            self.then(("pay", (tp, self.play_cost(tp, uid), -1)), ("do_solo", (tp, uid)))
        elif kind == "deploy":
            uid = act[1]
            self.then(("pay", (tp, self.play_cost(tp, uid), -1)), ("do_deploy", (tp, uid)))
        elif kind == "attack":
            self.then(("declare_attack", (act[1], act[2])))
        elif kind == "activate":
            self.start_activate(tp, act[1], act[2])
        else:
            raise ValueError(act)

    def sell(self, p, uid):
        self.move(uid, "eddies", p)
        self.cards[uid].spent = False                           # 11.12.1.1
        self._log(f"  P{p} sells {self.d(uid).title}")
        self.emit("sell", player=p, uid=uid)

    def start_play(self, p, uid):
        self.move(uid, "limbo")                                 # 4.14.2
        cost = self.play_cost(p, uid)
        self.effects_on_pay_for(p, uid)
        self.then(("pay", (p, cost, -1)), ("resolve_play", (p, uid)))

    def effects_on_pay_for(self, p, uid):
        """One-shot cost reductions are used up when you play the card."""
        for L in self.lasting:
            if L["kind"] == "next_program_cheaper" and L["p"] == p and self.d(uid).type == PROGRAM:
                L["used"] = True
        if self.d(uid).type == GEAR and "CYBERWARE" in self.d(uid).tags:
            self.turn_flags[("cyberware_played", p)] = True

    def start_activate(self, p, src, i):
        ab = self.effects.ability(self, src, i)
        host = self.cards[src].host if self.cards[src].zone == "equipped" else src
        cost = ab.eddies
        if ab.name == "johnny":
            cost = max(0, cost - len(self.gigs_at_least(p, 8)))
        self._log(f"  P{p} activates {self.d(src).title}")
        if ab.spend:
            self.spend(host, "ability")
        ctx = {"p": p, "src": src, "host": host}
        self.then(("pay", (p, cost, host if ab.spend else -1)), ("effect", (tuple(ab.steps), ctx, 0)))

    # ---- paying (11.11)
    def _t_pay(self, p, amount, exclude):
        if amount <= 0:
            return
        exclude = None if exclude == -1 else exclude
        eds = self.ready_eddies(p)
        srcs = self.pay_sources(p, exclude)
        if len(eds) + len(srcs) < amount:
            raise RuntimeError("cannot pay: affordability check missed something")
        if len(eds) + len(srcs) == amount:
            for u in eds + srcs:
                self.spend(u, "pay")
            return
        opts = []
        if eds:
            opts.append(("eddie",))
        if any(not self.cards[u].face_up for u in srcs):
            opts.append(("legend_facedown",))
        for u in srcs:
            if self.cards[u].face_up:
                opts.append(("legend", u))
        self.ask(p, "pay", opts, "pay_one", (p, amount, -1 if exclude is None else exclude))

    def _t_pay_one(self, p, amount, exclude, src):
        exclude_u = None if exclude == -1 else exclude
        if src[0] == "eddie":
            u = self.ready_eddies(p)[0]
        elif src[0] == "legend_facedown":
            u = next(u for u in self.pay_sources(p, exclude_u) if not self.cards[u].face_up)
        else:
            u = src[1]
        self.spend(u, "pay")
        self.then(("pay", (p, amount - 1, exclude)))

    # ---- playing cards (section 4, 11.7)
    def _t_resolve_play(self, p, uid):
        dd = self.d(uid)
        self._log(f"  P{p} plays {dd.title}")
        if dd.type == UNIT:
            self.move(uid, "field", p)
            c = self.cards[uid]
            c.spent = False
            c.lag = True                                        # 4.7
            self.emit("play", player=p, uid=uid)
            self.emit("played_unit", player=p, uid=uid)
        elif dd.type == GEAR:
            targets = self.equip_targets(p, uid)
            if not targets:
                self.move(uid, "trash")
                return
            self.ask(p, "equip", [("equip", t) for t in targets], "do_equip", (p, uid))
        elif dd.type == PROGRAM:
            self.turn_flags[("programs_played", p)] = self.turn_flags.get(("programs_played", p), 0) + 1
            self.then(("program_done", (p, uid)))
            steps = self.effects.program_steps(self, uid)
            if steps:
                self.run_effect(p, steps, src=uid)
            self.emit("play", player=p, uid=uid)
            self.emit("played_program", player=p, uid=uid)
        else:
            raise ValueError(dd.type)

    def _t_do_equip(self, p, uid, opt):
        host = opt[1]
        c = self.cards[uid]
        c.zone = "equipped"
        c.host = host
        self.cards[host].gears.append(uid)
        self._log(f"  equips {self.d(uid).title} to {self.d(host).title}")
        self.emit("play", player=p, uid=uid)
        self.emit("played_gear", player=p, uid=uid, host=host)

    def _t_program_done(self, p, uid):
        if self.cards[uid].zone == "limbo":
            if self.turn_flags.pop(("bottom_after", uid), False):
                self.move(uid, "deck", top=False)
            else:
                self.move(uid, "trash")

    def _t_do_call(self, p):
        self.call_legend(p)

    def _t_do_deploy(self, p, uid):
        """Play a Legend from the Legends area without Go Solo (4.5)."""
        c = self.cards[uid]
        spent = c.spent
        self.move(uid, "field", p)
        c.spent = spent                                         # 4.5.1: same orientation
        c.lag = True                                            # 4.5.2
        self._log(f"  P{p} plays {self.d(uid).title} from the Legends area")
        self.emit("play", player=p, uid=uid)
        self.emit("played_unit", player=p, uid=uid)

    def _t_do_solo(self, p, uid):
        self.move(uid, "field", p)
        c = self.cards[uid]
        c.spent = False                                         # Go Solo: ready Unit (11.29)
        c.lag = True
        c.solo_turn = self.turn_no
        self._log(f"  P{p} sends {self.d(uid).title} solo")
        self.emit("play", player=p, uid=uid)
        self.emit("played_unit", player=p, uid=uid)

    # ---- attacks (section 9)
    def _t_declare_attack(self, atk, target):
        ap = self.controller(atk)
        self.attack = {"atk": atk, "target": target, "ap": ap, "dp": 1 - ap}
        self.lasting = [L for L in self.lasting if not (L["kind"] == "must_attack" and L["unit"] == atk)]
        self._log(f"  {self.d(atk).title} (power {self.power(atk)}) attacks {self.describe(target)}")
        self.spend(atk, "attack")
        self.emit("attack", uid=atk, target=target)
        self.then(("attack_check", ()), ("react", ()))

    def attack_valid(self) -> bool:
        a = self.attack
        if a is None or a.get("ended"):
            return False
        if self.cards[a["atk"]].zone != "field":
            return False
        t = a["target"]
        if t[0] == "unit" and (self.cards[t[1]].zone != "field" or self.controller(t[1]) != a["dp"]):
            return False
        return True

    def _t_attack_check(self):
        if not self.attack_valid():
            self.stack = [t for t in self.stack if t[0] not in ("react",)]
            self.then(("end_attack", ()))

    def react_options(self):
        """Listing options only reads the state, so the active cards are cached."""
        self._active = None
        self._active = self.effects.active_cards(self)
        try:
            return self._react_options()
        finally:
            self._active = None

    def _react_options(self):
        a = self.attack
        dp = a["dp"]
        pl = self.players[dp]
        opts = [("end",)]
        if self.can_call(dp) and self.can_pay(dp, 1):
            opts.append(("call",))
        if not self.flag("unblockable", a["atk"]):
            for u in pl.field:
                if (not self.cards[u].spent and self.has_kw(u, "blocker")
                        and a["target"] != ("unit", u)):
                    opts.append(("block", u))
        seen = set()
        for u in pl.hand:
            dd = self.d(u)
            if dd.type == PROGRAM and dd.has("quick") and dd.idx not in seen:
                seen.add(dd.idx)
                if self.can_play(dp, u):
                    opts.append(("quick", dd.idx))
        opts.extend(self.effects.activated_options(self, dp, reaction=True))
        return opts

    def _t_react(self):
        if not self.attack_valid():
            self.then(("end_attack", ()))
            return
        self.ask(self.attack["dp"], "react", self.react_options(), "react_act")

    def _t_react_act(self, act):
        a = self.attack
        dp = a["dp"]
        if act[0] == "end":
            self.then(("attack_resolve", ()))
            return
        self.then(("react", ()))
        if act[0] == "call":
            self.then(("pay", (dp, 1, -1)), ("do_call", (dp,)))
        elif act[0] == "block":
            u = act[1]
            self.spend(u, "blocker")
            a["target"] = ("unit", u)
            a["blocked"] = True
            self._log(f"  {self.d(u).title} blocks")
            self.emit("blocker_used", uid=u, player=dp)
        elif act[0] == "quick":
            uid = next(u for u in self.players[dp].hand if self.cards[u].cid == act[1])
            self.start_play(dp, uid)
        elif act[0] == "activate":
            self.start_activate(dp, act[1], act[2])

    def _t_attack_resolve(self):
        if not self.attack_valid():
            self.then(("end_attack", ()))
            return
        if self.attack["target"][0] == "unit":
            self.then(("fight", ()), ("end_attack", ()))
        else:
            self.then(("steal_step", ()), ("end_attack", ()))

    def _t_fight(self):
        a = self.attack
        atk, dfn = a["atk"], a["target"][1]
        a["fighting"] = True
        pa, pd = self.power(atk), self.power(dfn)
        self._log(f"  fight: {self.d(atk).title} {pa} vs {self.d(dfn).title} {pd}")
        lose_a, lose_d = pa <= pd, pd <= pa
        if self.flag("wins_fight", atk, dfn):                  # 11.4.1.4
            lose_a, lose_d = False, True
        elif self.flag("wins_fight", dfn, atk):
            lose_a, lose_d = True, False
        if lose_a and lose_d:
            winners = []
        else:
            winners = [atk] if lose_d else [dfn]
        losers = ([atk] if lose_a else []) + ([dfn] if lose_d else [])
        margin = {atk: pa - pd, dfn: pd - pa}
        for u in (atk, dfn):
            self.turn_flags.setdefault(("fought", u), True)
        a["fighting"] = False
        defeats = []
        for loser in losers:
            other = dfn if loser == atk else atk
            opp_power = pd if loser == atk else pa
            if opp_power > 0 and not self.flag("no_fight_defeat", loser, other):   # 11.4.2.3.2
                defeats.append((loser, other))
        self.emit("fight_result", atk=atk, dfn=dfn, winners=winners, losers=losers,
                  margin=margin, defeats=[d[0] for d in defeats])
        steps = []
        for loser, other in defeats:
            steps.extend(self.defeat_steps(loser, by=other))
        if steps:
            self.run_effect(self.turn_player, steps)

    def _t_steal_step(self):
        a = self.attack
        dp = a["dp"]
        pw = self.power(a["atk"])
        n = 0 if pw <= 0 else pw // 10 + 1                      # 9.20.1.2
        if n:
            n = max(0, n + self.effects.steal_count_mod(self, a["atk"]))
        a["steal_n"] = n
        if n:
            self.then(("steal_pick", (n, ())))

    def stealable(self, atk, dp, picked=()):
        gigs = self.players[dp].gigs
        return [i for i in range(len(gigs)) if i not in picked
                and self.effects.may_steal_gig(self, atk, gigs[i])]

    def _t_steal_pick(self, n, picked):
        dp = self.attack["dp"]
        gigs = self.players[dp].gigs
        remaining = self.stealable(self.attack["atk"], dp, picked)
        if len(picked) == n or not remaining:
            self.then(("steal_prevent", (picked, 0)))
            return
        opts, seen = [], set()
        for i in remaining:
            key = tuple(gigs[i])
            if key not in seen:
                seen.add(key)
                opts.append(("gig", key[0], key[1]))
        self.ask(self.attack["ap"], "steal", opts, "steal_choose", (n, picked))

    def _t_steal_choose(self, n, picked, opt):
        gigs = self.players[self.attack["dp"]].gigs
        i = next(i for i in range(len(gigs)) if i not in picked and tuple(gigs[i]) == (opt[1], opt[2]))
        self.then(("steal_pick", (n, picked + (i,))))

    def _t_steal_prevent(self, picked, k):
        """'When a rival Unit would steal a Gig, you may discard 1 with cost equal to that Gig's value.'"""
        a = self.attack
        dp = a["dp"]
        if k >= len(picked):
            self.then(("steal_move", (picked,)))
            return
        g = self.players[dp].gigs[picked[k]]
        has_alt = any(self.slug(u) == "alt-cunningham-mother-of-daemons" for u in self.players[dp].field)
        opts = []
        if has_alt:
            cids = sorted({self.cards[u].cid for u in self.players[dp].hand if (self.d(u).cost or 0) == g[1]})
            opts = [("card", c) for c in cids]
        if not opts:
            self.then(("steal_prevent", (picked, k + 1)))
            return
        self.ask(dp, "prevent_steal", [("none",)] + opts, "steal_prevent_ans", (picked, k))

    def _t_steal_prevent_ans(self, picked, k, ans):
        if ans != ("none",):
            dp = self.attack["dp"]
            uid = next(u for u in self.players[dp].hand if self.cards[u].cid == ans[1])
            self.move(uid, "trash")
            self.emit("discard", player=dp, uid=uid)
            picked = picked[:k] + picked[k + 1:]
            self.then(("steal_prevent", (picked, k)))
        else:
            self.then(("steal_prevent", (picked, k + 1)))

    def _t_steal_move(self, picked):
        a = self.attack
        src, dst = self.players[a["dp"]].gigs, self.players[a["ap"]].gigs
        moved = [src[i] for i in picked]
        for i in sorted(picked, reverse=True):
            del src[i]
        dst.extend(moved)
        self._log(f"  P{a['ap']} steals {['d%d=%d' % tuple(g) for g in moved]}")
        if moved:
            self.turn_flags[("stole", a["atk"])] = True
            self.emit("steal_group", actor=a["atk"], player=a["ap"], gigs=moved)
        for g in moved:
            self.emit("steal", actor=a["atk"], player=a["ap"], gig=g)

    def steal_by_effect(self, actor, p, gig_idx):
        """An effect makes `actor` steal a specific rival Gig (11.5)."""
        g = self.take_gig(1 - p, gig_idx, p)
        self._log(f"  P{p} steals d{g[0]}={g[1]} (effect)")
        self.turn_flags[("stole", actor)] = True
        self.emit("steal", actor=actor, player=p, gig=g)
        return g

    def _t_end_attack(self):
        for c in self.cards.values():
            if c.mods:
                c.mods[:] = [m for m in c.mods if m[1] != "attack"]
        self.lasting = [L for L in self.lasting if L.get("until") != "attack"]
        self.attack = None

    # ---- end of turn (8.16 - 8.18)
    def _t_end_turn(self):
        tp = self.turn_player
        self.emit("turn_end", player=tp)
        self.then(("cleanup", (tp,)))

    def _t_cleanup(self, tp):
        for c in self.cards.values():
            if c.mods:
                c.mods[:] = [m for m in c.mods if m[1] != "turn"]
            c.lag = False                                       # 11.3.2
        self.lasting = [L for L in self.lasting if L.get("until") not in ("eot",)
                        and L.get("expires", 10**9) > self.turn_no]
        self.turn_flags = {}
        if self.empty_streak >= 2 and not self.overtime:       # 1.11.1 / 8.17
            self.overtime = True
            self._log("  OVERTIME begins")
            self._check_overtime_win()
            if self.winner is not None:
                return
        self.turn_player = 1 - tp
        self.then(("start_turn", ()))

    def _check_overtime_win(self):
        w = [len(self.players[p].gigs) >= WIN_GIGS for p in (0, 1)]
        if w[0] and w[1]:
            self.win("draw", "both reached 7 Gigs in overtime")
        elif w[0] or w[1]:
            self.win(0 if w[0] else 1, "reached 7 Gigs in overtime")

    # ---------------------------------------------------------- invariants
    def check_invariants(self):
        assert sum(len(pl.gigs) + len(pl.fixer) for pl in self.players) == 12
        for pl in self.players:
            assert all(1 <= v <= s for s, v in pl.gigs), pl.gigs
        zones = {}
        for pl in self.players:
            for z in ("deck", "hand", "field", "legends", "eddies", "trash", "removed"):
                for u in getattr(pl, z):
                    assert u not in zones, f"card {u} in two places"
                    zones[u] = z
                    assert self.cards[u].zone == z, (u, self.cards[u].zone, z)
        for u, c in self.cards.items():
            if c.zone == "equipped":
                assert c.host is not None and u in self.cards[c.host].gears
                assert self.cards[c.host].zone in ("field", "legends"), (u, self.cards[c.host].zone)
            elif c.zone == "limbo":
                pass
            else:
                assert u in zones, (u, c.zone)
            if c.zone in ("deck", "hand", "eddies"):
                assert not c.gears, (u, c.zone)


# ---- generic defeat steps (need Game internals)
@fx.step("_defeat_offer")
def _defeat_offer(g, ctx, uid, by=None):
    """Optional replacement: Jackie Welles - Mama's Favorite."""
    c = g.cards[uid]
    if c.zone not in ("field",) or g.d(uid).type == GEAR:
        return None
    if g.mandatory_defeat_replacement(uid) is not None:
        return None
    p = g.controller(uid)
    for j in g.players[p].legends + g.players[p].field:
        jc = g.cards[j]
        if (g.slug(j) == "jackie-welles-mama-s-favorite" and j != uid
                and (jc.face_up or jc.zone == "field") and g.can_pay(p, 1)):
            ctx["_jackie"] = j
            return fx.Ask(p, "may:jackie_replace", [True, False], "_jackie_ans")
    return None


@fx.step("_defeat_do")
def _defeat_do(g, ctx, uid, by=None):
    if ctx.pop("_jackie_ans", False):
        j = ctx.pop("_jackie")
        p = g.controller(j)
        ctx["_paying"] = True
        return [fx.S("_pay_n", n=1, who=p), fx.S("_defeat_now", uid=j, by=by)]
    ctx.pop("_jackie", None)
    g.defeat_now(uid, by)


@fx.step("_defeat_now")
def _defeat_now(g, ctx, uid, by=None):
    c = g.cards[uid]
    if c.zone == "legends":
        g.move(uid, "removed")
        g.emit("defeated", uid=uid, by=by, snapshot={"gears": [], "owner": c.owner, "controller": c.owner,
                                                     "power": 0, "tags": list(g.d(uid).tags), "zone": "legends",
                                                     "host": None})
    else:
        g.defeat_now(uid, by)


@fx.step("_pay_n")
def _pay_n(g, ctx, n, who):
    """Pay inside an effect: spends ready Eddies first, then Legends (no choice offered)."""
    srcs = g.ready_eddies(who) + g.pay_sources(who)
    for u in srcs[:n]:
        g.spend(u, "pay")
