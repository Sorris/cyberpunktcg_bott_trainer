"""Cyberpunk TCG rules engine.

Design
------
The whole game is plain data (lists, dicts, tuples, a random.Random), so a
game can be copied with ``Game.clone()`` for look-ahead search.

Control flow is an explicit task stack. Each task is a tuple ``(name, args)``
that runs ``Game._t_<name>(*args)``. A task may push more tasks, or stop and
ask a player for a decision. The answer is delivered by pushing the decision's
``resume`` task with the chosen option appended to its arguments. Because the
stack holds only data, cloning mid-decision works.

Players interact through three calls:
    g.decision            -> Decision(player, kind, options) or None when over
    g.legal_actions()     -> list of options for the current decision
    g.step(option)        -> apply one option

Card text is not scripted here. ``effects.py`` registers per-card scripts
against the hook points marked ``self.emit(...)``; unscripted cards play as
vanilla cards (stats and keywords only). Rule numbers in comments refer to the
comprehensive rules (docs/comprehensive-rules.md).
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field as dfield

from .cards import GEAR, LEGEND, PROGRAM, UNIT, CardDB, default_db
from .deck import Deck

DICE = (4, 6, 8, 10, 12, 20)
TURN_LIMIT = 100          # safety valve: game is a draw after this many turns
WIN_GIGS = 7


@dataclass
class Decision:
    player: int
    kind: str             # setup: go_first, mulligan; turn: roll_in, main, pay, equip,
                          # react, steal ...
    options: list
    resume: str
    ctx: tuple = ()


@dataclass
class Card:
    uid: int
    cid: int              # index into CardDB
    owner: int
    zone: str = "deck"    # deck hand field legends eddies trash removed limbo equipped
    spent: bool = False
    face_up: bool = False
    lag: bool = False
    solo_turn: int = -1   # turn a Legend went solo (can attack that turn)
    gears: list = dfield(default_factory=list)   # uids of equipped Gear
    host: int | None = None                     # uid this Gear is equipped to
    mods: list = dfield(default_factory=list)    # [power delta, duration] pairs


@dataclass
class Player:
    idx: int
    deck: list = dfield(default_factory=list)     # uids, top of deck = end of list
    hand: list = dfield(default_factory=list)
    field: list = dfield(default_factory=list)
    legends: list = dfield(default_factory=list)  # left-most first
    eddies: list = dfield(default_factory=list)
    trash: list = dfield(default_factory=list)    # top = end of list
    removed: list = dfield(default_factory=list)
    fixer: list = dfield(default_factory=lambda: list(DICE))
    gigs: list = dfield(default_factory=list)     # [sides, value]
    sold: bool = False
    called: bool = False
    mulliganed: bool = False


class Game:
    def __init__(self, deck0: Deck, deck1: Deck, seed: int | None = None,
                 db: CardDB | None = None, log: bool = False, effects=None):
        self.db = db or default_db()
        self.rng = random.Random(seed)
        self.cards: dict[int, Card] = {}
        self.players = [Player(0), Player(1)]
        self.turn_player = 0
        self.first_player = 0
        self.turn_no = 0
        self.stack: list = []
        self.decision: Decision | None = None
        self.winner = None          # 0, 1, or "draw"
        self.end_reason = ""
        self.overtime = False
        self.empty_streak = 0
        self.attack: dict | None = None
        self.history: list = []     # (player, kind, option) of every decision taken
        self.logging = log
        self.log: list[str] = []
        if effects is None:
            from . import effects as _fx
            effects = _fx.REGISTRY
        self.effects = effects
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
    def current_player(self) -> int | None:
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
        db, fx = self.db, self.effects
        self.db = self.effects = None
        try:
            g = copy.deepcopy(self)
        finally:
            self.db, self.effects = db, fx
        g.db, g.effects = db, fx
        return g

    # ------------------------------------------------------------ machinery
    def advance(self):
        while self.decision is None and self.winner is None:
            if not self.stack:
                raise RuntimeError("task stack empty without a decision")
            name, args = self.stack.pop()
            getattr(self, "_t_" + name)(*args)
            if self.overtime and self.winner is None:
                self._check_overtime_win()

    def then(self, *tasks):
        """Schedule tasks to run in the order given (before anything already queued)."""
        for t in reversed(tasks):
            self.stack.append(t)

    def ask(self, player, kind, options, resume, ctx=()):
        if not options:
            raise RuntimeError(f"no options for {kind}")
        if len(options) == 1:           # forced move: don't bother the agent
            self.stack.append((resume, tuple(ctx) + (options[0],)))
            return
        self.decision = Decision(player, kind, list(options), resume, tuple(ctx))

    def _log(self, msg):
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

    # -------------------------------------------------------------- queries
    def d(self, uid):
        return self.db[self.cards[uid].cid]

    def power(self, uid) -> int:
        """Current power (rule 3.17.2); negatives count as 0 (2.10.1)."""
        c = self.cards[uid]
        p = self.d(uid).power or 0
        p += sum(self.d(g).power or 0 for g in c.gears)
        p += sum(m[0] for m in c.mods)
        return max(0, p)

    def has_kw(self, uid, kw) -> bool:
        return kw in self.d(uid).keywords or self.effects.grants_keyword(self, uid, kw)

    def street_cred(self, p):
        g = self.players[p].gigs
        return sum(v for _, v in g) if g else None   # None = Null street cred (11.2.3)

    def ready_eddies(self, p):
        return [u for u in self.players[p].eddies if not self.cards[u].spent]

    def pay_sources(self, p, exclude=None):
        """Legends that can be spent for 1 each: face-down, or face-up with a Sell Tag (5.7.2)."""
        out = []
        for u in self.players[p].legends:
            c = self.cards[u]
            if u != exclude and not c.spent and (not c.face_up or self.d(u).sell):
                out.append(u)
        return out

    def can_pay(self, p, amount, exclude=None) -> bool:
        return amount <= len(self.ready_eddies(p)) + len(self.pay_sources(p, exclude))

    def play_cost(self, p, uid) -> int:
        cost = self.d(uid).cost or 0
        return self.effects.modify_cost(self, p, uid, cost)

    def can_attack(self, uid) -> bool:
        c = self.cards[uid]
        if c.zone != "field" or c.spent:
            return False
        if c.lag and not (self.has_kw(uid, "adrenaline") or c.solo_turn == self.turn_no):
            return False
        return self.effects.may_attack(self, uid)

    def attack_targets(self, uid):
        p = self.cards[uid].owner
        rival = self.players[1 - p]
        t = []
        if rival.gigs:
            t.append(("gigs",))
        for v in rival.field:
            if self.cards[v].spent or self.effects.can_attack_ready(self, uid, v):
                t.append(("unit", v))
        return t

    def equip_targets(self, p):
        pl = self.players[p]
        return list(pl.field) + [u for u in pl.legends if self.cards[u].face_up]

    def describe(self, opt) -> str:
        if not (isinstance(opt, tuple) and opt):
            return str(opt)
        k = opt[0]
        if k in ("sell", "play", "quick"):
            return f"{k} {self.db[opt[1]].title}"
        if k in ("solo", "block", "legend", "equip", "unit"):
            return f"{k} {self.d(opt[1]).title}"
        if k == "attack":
            return f"attack with {self.d(opt[1]).title} -> {self.describe(opt[2])}"
        if k == "gig":
            return f"d{opt[1]}={opt[2]}"
        if k == "gigs":
            return "rival Gig area"
        return " ".join(str(x) for x in opt)

    # --------------------------------------------------------------- moves
    def move(self, uid, zone, p=None, top=True):
        """Move a card between areas. Gear follows its host (4.12)."""
        c = self.cards[uid]
        owner_pl = self.players[c.owner]
        # detach from wherever it is
        if c.zone == "equipped" and c.host is not None:
            self.cards[c.host].gears.remove(uid)
            c.host = None
        else:
            for lst in ("deck", "hand", "field", "legends", "eddies", "trash", "removed"):
                for pl in self.players:
                    seq = getattr(pl, lst)
                    if uid in seq:
                        seq.remove(uid)
        # Legends are only valid in the Legends area and field (4.4)
        if self.d(uid).type == LEGEND and zone not in ("legends", "field", "limbo"):
            zone = "removed"
        old_zone = c.zone
        c.zone = zone
        pl = self.players[c.owner if p is None else p]
        if zone == "deck":
            (pl.deck.append(uid) if top else pl.deck.insert(0, uid))
        elif zone != "limbo":
            getattr(pl, zone).append(uid)
        # leaving play: reset state
        if zone not in ("field", "legends"):
            c.spent = False
            c.lag = False
            c.mods.clear()
            if zone in ("deck", "hand", "eddies"):
                c.face_up = False
            elif zone in ("trash", "removed"):
                c.face_up = True
        if c.gears and zone not in ("field", "legends"):
            # Gear moves with its host but is no longer equipped (4.12.1, 4.12.2)
            dest = "trash" if zone in ("trash", "removed") else zone
            for g in list(c.gears):
                c.gears.remove(g)
                gc = self.cards[g]
                gc.host = None
                gc.zone = dest
                gc.mods.clear()
                getattr(self.players[gc.owner], dest).append(g) if dest != "deck" else \
                    (self.players[gc.owner].deck.append(g) if top else self.players[gc.owner].deck.insert(0, g))
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

    def shuffle_deck(self, p):
        self.rng.shuffle(self.players[p].deck)

    def defeat(self, uid, by=None):
        """Defeat a Unit, Legend, or Gear (11.6)."""
        c = self.cards[uid]
        if c.zone not in ("field", "legends", "equipped"):
            return
        replaced = self.effects.replace_defeat(self, uid)
        if replaced is not None:
            return
        self._log(f"  {self.d(uid).title} is defeated")
        snapshot = {"power": self.power(uid), "gears": list(c.gears), "owner": c.owner}
        self.move(uid, "trash")
        self.emit("defeated", uid=uid, by=by, snapshot=snapshot)

    def spend(self, uid, reason="other"):
        c = self.cards[uid]
        c.spent = True
        if c.zone in ("field", "legends"):
            self.emit("spent", uid=uid, reason=reason)

    def add_mod(self, uid, delta, duration):
        """duration: 'turn' | 'attack' | 'next_turn' | 'permanent'"""
        self.cards[uid].mods.append([delta, duration])

    def emit(self, event, **ctx):
        """Hook for scripted card effects: they push pending-effect tasks."""
        self.effects.on_event(self, event, ctx)

    # ================================================================ TASKS
    # ---- setup (section 7)
    def _t_setup(self):
        chooser = self.rng.randrange(2)
        self.ask(chooser, "go_first", [True, False], "set_first", (chooser,))

    def _t_set_first(self, chooser, go_first):
        fp = chooser if go_first else 1 - chooser
        self.first_player = self.turn_player = fp
        for p in (0, 1):
            self.shuffle_deck(p)
            self.rng.shuffle(self.players[p].legends)
        for u in self.players[fp].legends[:2]:      # 7.7.4
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
        if len(self.players[tp].gigs) >= WIN_GIGS:         # 1.10 / 8.6.1
            self.win(tp, "started turn with 7 Gigs")
            return
        self.then(("start_effects", (tp,)), ("ready_step", (tp,)), ("draw_step", (tp,)),
                  ("roll_in", (tp,)), ("main", ()))

    def _t_start_effects(self, tp):
        for c in self.cards.values():
            c.mods[:] = [m for m in c.mods if not (m[1] == "next_turn" and c.owner == tp)]
        self.emit("turn_start", player=tp)

    def _t_ready_step(self, tp):
        pl = self.players[tp]
        first_turn = self.turn_no == 1
        for u in pl.field + pl.eddies:
            self.cards[u].spent = False
        for i, u in enumerate(pl.legends):
            if first_turn and i < 2 and tp == self.first_player:
                continue                                   # 7.7.4
            self.cards[u].spent = False

    def _t_draw_step(self, tp):
        self.draw(tp, 1)

    def _t_roll_in(self, tp):
        fx = self.players[tp].fixer
        if not fx:
            return
        opts = [d for d in fx if d != 20] or [20]          # 8.6.5.1.1
        self.ask(tp, "roll_in", opts, "do_roll_in", (tp,))

    def _t_do_roll_in(self, tp, sides):
        pl = self.players[tp]
        pl.fixer.remove(sides)
        value = self.rng.randint(1, sides)
        pl.gigs.append([sides, value])
        self._log(f"  P{tp} rolls in d{sides} = {value}")
        self.emit("roll_in", player=tp, gig=len(pl.gigs) - 1)

    # ---- main phase (8.9 - 8.15)
    def main_options(self):
        tp = self.turn_player
        pl = self.players[tp]
        opts = [("pass",)]
        if not pl.sold:
            for cid in sorted({self.cards[u].cid for u in pl.hand if self.d(u).sell}):
                opts.append(("sell", cid))
        if not pl.called and any(not self.cards[u].face_up for u in pl.legends) and self.can_pay(tp, 1):
            opts.append(("call",))
        seen = set()
        for u in pl.hand:
            c = self.d(u)
            if c.idx in seen:
                continue
            seen.add(c.idx)
            if c.type == GEAR and not self.equip_targets(tp):
                continue
            if not self.effects.may_play(self, tp, u):
                continue
            if self.can_pay(tp, self.play_cost(tp, u)):
                opts.append(("play", c.idx))
        for u in pl.legends:
            c = self.cards[u]
            dd = self.d(u)
            if c.face_up and dd.cost is not None and dd.power is not None:
                if self.can_pay(tp, self.play_cost(tp, u), exclude=u):
                    opts.append(("solo", u))
        for u in pl.field:
            if self.can_attack(u):
                for t in self.attack_targets(u):
                    opts.append(("attack", u, t))
        opts.extend(self.effects.activated_options(self, tp, reaction=False))
        return opts

    def _t_main(self):
        self.ask(self.turn_player, "main", self.main_options(), "main_act")

    def _t_main_act(self, act):
        tp = self.turn_player
        kind = act[0]
        if kind == "pass":
            self.then(("end_turn", ()))
            return
        self.then(("main", ()))
        if kind == "sell":
            uid = next(u for u in self.players[tp].hand if self.cards[u].cid == act[1])
            self.sell(tp, uid)
            self.players[tp].sold = True
        elif kind == "call":
            self.then(("pay", (tp, 1, -1)), ("do_call", (tp,)))
        elif kind == "play":
            uid = next(u for u in self.players[tp].hand if self.cards[u].cid == act[1])
            self.start_play(tp, uid)
        elif kind == "solo":
            uid = act[1]
            self.then(("pay", (tp, self.play_cost(tp, uid), uid)), ("do_solo", (tp, uid)))
        elif kind == "attack":
            self.then(("declare_attack", (act[1], act[2])))
        elif kind == "activate":
            self.effects.activate(self, tp, act)
        else:
            raise ValueError(act)

    def sell(self, p, uid):
        self.move(uid, "eddies")
        self.cards[uid].spent = False                       # enters ready (11.12.1.1)
        self._log(f"  P{p} sells {self.d(uid).title}")
        self.emit("sell", player=p, uid=uid)

    def start_play(self, p, uid):
        self.move(uid, "limbo")                             # revealed, outside any area (4.14.2)
        self.then(("pay", (p, self.play_cost(p, uid), -1)), ("resolve_play", (p, uid)))

    # ---- paying (11.11)
    def _t_pay(self, p, amount, exclude):
        if amount <= 0:
            return
        exclude = None if exclude == -1 else exclude
        opts = []
        if self.ready_eddies(p):
            opts.append(("eddie",))
        fd = [u for u in self.pay_sources(p, exclude) if not self.cards[u].face_up]
        if fd:
            opts.append(("legend_facedown",))
        for u in self.pay_sources(p, exclude):
            if self.cards[u].face_up:
                opts.append(("legend", u))
        if not opts:
            raise RuntimeError("cannot pay: affordability check missed something")
        # If every remaining source must be spent anyway, the choice doesn't matter.
        total = len(self.ready_eddies(p)) + len(self.pay_sources(p, exclude))
        if total == amount:
            for u in self.ready_eddies(p) + self.pay_sources(p, exclude):
                self.spend(u, "pay")
            return
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
            c.lag = True                                    # 4.7
            self.emit("play", player=p, uid=uid)
        elif dd.type == GEAR:
            self.ask(p, "equip", [("equip", t) for t in self.equip_targets(p)], "do_equip", (p, uid))
        elif dd.type == PROGRAM:
            self.then(("program_done", (p, uid)))
            self.emit("play", player=p, uid=uid)
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

    def _t_program_done(self, p, uid):
        if self.cards[uid].zone == "limbo":
            self.move(uid, "trash")

    def _t_do_call(self, p):
        pl = self.players[p]
        down = [u for u in pl.legends if not self.cards[u].face_up]
        if not down:
            return
        u = self.rng.choice(down)          # owner can't see face-down Legends (5.7.4.1)
        self.cards[u].face_up = True
        pl.called = True
        self._log(f"  P{p} calls {self.d(u).title}")
        self.emit("call", player=p, uid=u)

    def _t_do_solo(self, p, uid):
        self.move(uid, "field", p)
        c = self.cards[uid]
        c.spent = False                                     # Go Solo: ready Unit (11.29)
        c.lag = True
        c.solo_turn = self.turn_no
        self._log(f"  P{p} sends {self.d(uid).title} solo")
        self.emit("play", player=p, uid=uid)

    # ---- attacks (section 9)
    def _t_declare_attack(self, atk, target):
        ap = self.cards[atk].owner
        self.attack = {"atk": atk, "target": target, "ap": ap, "dp": 1 - ap}
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
        if t[0] == "unit" and (self.cards[t[1]].zone != "field" or self.cards[t[1]].owner != a["dp"]):
            return False
        return True

    def _t_attack_check(self):
        if not self.attack_valid():
            self.stack = [t for t in self.stack if t[0] not in ("react", "fight", "steal_step")]
            self.then(("end_attack", ()))

    def react_options(self):
        a = self.attack
        dp = a["dp"]
        pl = self.players[dp]
        opts = [("end",)]
        if not pl.called and any(not self.cards[u].face_up for u in pl.legends) and self.can_pay(dp, 1):
            opts.append(("call",))
        for u in pl.field:
            if (not self.cards[u].spent and self.has_kw(u, "blocker")
                    and a["target"] != ("unit", u)):
                opts.append(("block", u))
        seen = set()
        for u in pl.hand:
            dd = self.d(u)
            if dd.type == PROGRAM and dd.has("quick") and dd.idx not in seen:
                seen.add(dd.idx)
                if self.can_pay(dp, self.play_cost(dp, u)) and self.effects.may_play(self, dp, u):
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
        elif act[0] == "quick":
            uid = next(u for u in self.players[dp].hand if self.cards[u].cid == act[1])
            self.start_play(dp, uid)
        elif act[0] == "activate":
            self.effects.activate(self, dp, act)

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
        self.emit("fight_start", atk=atk, dfn=dfn)
        pa, pd = self.power(atk), self.power(dfn)
        self._log(f"  fight: {self.d(atk).title} {pa} vs {self.d(dfn).title} {pd}")
        losers = []
        if pa <= pd:
            losers.append((atk, dfn, pd))
        if pd <= pa:
            losers.append((dfn, atk, pa))
        winners = [u for u in (atk, dfn) if u not in [l[0] for l in losers]]
        self.emit("fight_result", atk=atk, dfn=dfn, winners=winners, losers=[l[0] for l in losers])
        for loser, by, by_power in losers:
            if by_power > 0 and not self.effects.prevent_fight_defeat(self, loser):   # 11.4.2.3.2
                self.defeat(loser, by=by)

    def _t_steal_step(self):
        a = self.attack
        dp = a["dp"]
        p = self.effects.steal_power(self, a["atk"], self.power(a["atk"]))
        n = 0 if p <= 0 else p // 10 + 1                    # 9.20.1.2
        n = min(n, len(self.players[dp].gigs))
        if n:
            self.then(("steal_pick", (n, ())))

    def _t_steal_pick(self, n, picked):
        if len(picked) == n:
            self.then(("steal_move", (picked,)))
            return
        dp = self.attack["dp"]
        gigs = self.players[dp].gigs
        remaining = [i for i in range(len(gigs)) if i not in picked]
        # identical dice (same sides and value) are interchangeable
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

    def _t_steal_move(self, picked):
        a = self.attack
        src, dst = self.players[a["dp"]].gigs, self.players[a["ap"]].gigs
        picked = [i for i in picked if self.effects.allow_steal(self, a, src[i])]
        moved = [src[i] for i in picked]
        for i in sorted(picked, reverse=True):
            del src[i]
        dst.extend(moved)
        self._log(f"  P{a['ap']} steals {['d%d=%d' % tuple(g) for g in moved]}")
        for g in moved:
            self.emit("steal", actor=a["atk"], player=a["ap"], gig=g)

    def _t_end_attack(self):
        for c in self.cards.values():
            if c.mods:
                c.mods[:] = [m for m in c.mods if m[1] != "attack"]
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
            c.lag = False                                   # 11.3.2
        self.effects.end_turn_cleanup(self)
        if self.empty_streak >= 2 and not self.overtime:   # 1.11.1 / 8.17
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

    # ---- generic tasks used by card scripts
    def _t_call(self, fn_name, *args):
        """Run a card-script function by name: effects.<fn_name>(game, *args)."""
        self.effects.run(self, fn_name, args)

    # ---------------------------------------------------------- invariants
    def check_invariants(self):
        total = {0: 0, 1: 0}
        for c in self.cards.values():
            total[c.owner] += 1
        for p, pl in enumerate(self.players):
            gigs = len(pl.gigs) + len(pl.fixer)
            assert all(1 <= v <= s for s, v in pl.gigs), pl.gigs
        assert sum(len(pl.gigs) + len(pl.fixer) for pl in self.players) == 12
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
                assert self.cards[c.host].zone in ("field", "legends")
            elif c.zone == "limbo":
                pass
            else:
                assert u in zones, (u, c.zone)
