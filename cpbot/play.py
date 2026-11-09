"""Play a game yourself against a bot: what one player can see, and readable choices.

    m = Match(human_deck, bot_deck, bot=ISMCTSAgent(...), seed=0)
    m.view()            # the board from the human's seat, plus their choices
    m.choose(i)         # pick option i of the human's current decision
    m.run_bot()         # let the bot act until it is the human's turn again

The human is always engine player 0 and the bot player 1. Who goes first is
still decided in game (the go_first choice), so either can start.

Hidden information stays hidden: the bot's hand and face-down Legends, both
decks, and your own face-down Legends you haven't seen (5.7.4.1).
"""
from __future__ import annotations

import re
import threading
from collections import Counter
from pathlib import Path

from .cards import LEGEND, CardDB
from .deck import Deck, validate
from .engine import Game

HUMAN, BOT = 0, 1

# A sample deck for a quick start: "BBG Proactive", sideboard left out.
SAMPLE_DECK = """\
# BBG Proactive

// Legends (3)
1 Alt Cunningham: Soulkiller Architect
1 Hanako Arasaka: Daughter of the Emperor
1 Jackie Welles: Pour One Out For Me

// Units (14)
3 Jacked-In Voodoo Boy
2 Lizzy Wizzy: Delicate Weapon
3 Maman Brigitte: Spirit of Death
3 Pepe Najarro: Working Doubles
1 Psycho Squad
2 Valentino Street Racer

// Programs (26)
3 Chrome Reverie
1 Floor It
3 Les Élémens
3 Nocturne OP55 N1
3 Peace Offering
3 Pyramid Song
1 Synapse Burnout
3 Three Mouths, One Desire
3 Towerfall
3 Trust No One

// Sideboard (7)
2 Modded Kusanagi
2 Placide: Voodoo Sentinel
3 Riot Shield
"""


def parse_decklist(text: str, db: CardDB) -> Deck:
    """A simple reader for pasted decklists: "N Card Name" lines.

    Lines starting with # or // are headings; a "Sideboard" heading ends the deck.
    "Name: Subtitle" is read as the printed "Name - Subtitle". Raises ValueError
    with every problem found (unknown cards, deck rule breaks)."""
    legends, main, errs = [], [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("#", "//")):
            if "sideboard" in line.lower():
                break
            continue
        m = re.match(r"^(\d+)\s*x?\s+(.+)$", line)
        if not m:
            errs.append(f"can't read line: {line!r}")
            continue
        n, title = int(m.group(1)), m.group(2).strip()
        try:
            c = db.find(title)
        except KeyError:
            try:
                c = db.find(title.replace(": ", " - "))
            except KeyError:
                errs.append(f"unknown card: {title!r}")
                continue
        (legends if c.type == LEGEND else main).extend([c.idx] * n)
    deck = Deck(legends, main)
    if not errs:
        errs = validate(deck, db)
    if errs:
        raise ValueError("; ".join(errs))
    return deck


# ------------------------------------------------------------------ cards
def card_info(d) -> dict:
    """Static facts about a card definition, for showing it."""
    return {"cid": d.idx, "id": d.id, "title": d.title, "type": d.type, "color": d.color,
            "cost": d.cost, "power": d.power, "ram": d.ram_cost, "ram_provided": d.ram_provided,
            "sell": d.sell, "text": d.text, "tags": sorted(d.tags),
            "keywords": sorted(d.keywords)}


def _short(title: str) -> str:
    return title.split(" - ")[0]


# ----------------------------------------------------------------- choices
def _who(p, me):
    return "You" if p == me else "Bot"


def prompt(g: Game, me: int = HUMAN) -> str:
    """What the current decision is asking, in words."""
    d = g.decision
    if d is None:
        return ""
    src = None
    if d.resume == "effect_answer" and len(d.ctx) > 1 and isinstance(d.ctx[1], dict):
        s = d.ctx[1].get("src")
        if s is not None and s in g.cards:
            src = g.d(s).title
    k = d.kind
    base = {
        "go_first": "Do you want to go first?",
        "mulligan": "Keep this opening hand, or mulligan?",
        "roll_in": "Roll in a Gig: pick a die from your fixer.",
        "main": "Your main phase: play cards, attack, or end your turn.",
        "pay": "Pay the cost: choose what to spend next.",
        "react": "Your rival is attacking. Block, react, or let it through.",
        "steal": "Choose a Gig to steal.",
        "equip": "Choose who to equip this Gear to.",
        "order_pending": "Several effects trigger at once. Choose which resolves first.",
        "target": "Choose a target.",
        "adjust": "Choose a Gig to change, if any.",
        "set_gig": "Choose a Gig to set.",
        "discard": "Choose a card to discard.",
        "trash_one": "Choose a card to trash.",
        "defeat_own": "Choose one of your units to defeat.",
        "defeat_gear": "Choose a Gear to defeat.",
        "move_gear": "Choose a Gear to move, and where.",
        "swap": "Choose Gigs to swap.",
        "mode": "Choose one.",
        "card_type": "Name a card type.",
        "fool": "Choose where the card goes.",
        "increase": "Choose the new Gig value.",
    }.get(k)
    if base is None and k.startswith("may:"):
        what = _MAY.get(k[4:], "use this optional effect (" + _words(k[4:]) + ")")
        base = f"Do you want to {what}?"
    if base is None:
        base = f"Choose ({k.replace('_', ' ')})."
    if k == "react" and g.attack:
        a = g.attack
        tgt = "your Gigs" if a["target"] == ("gigs",) else _short(g.d(a["target"][1]).title)
        base = f"{_short(g.d(a['atk']).title)} attacks {tgt}. Block, react, or let it through."
    if k == "pay" and len(d.ctx) > 1:
        base = f"Pay the cost: {d.ctx[1]} left. Choose what to spend next."
    return f"{src}: {base}" if src else base


_MAY = {
    "reroll": "reroll the die", "swap": "swap Gigs", "look": "look",
    "add_to_hand": "add the card to your hand", "call_free": "Call a Legend for free",
    "trash_top": "trash from the top of your deck", "pay2": "pay 2",
    "jackie_replace": "use Jackie Welles' effect instead", "draw5": "use the draw effect",
}


def _words(s: str) -> str:
    return re.sub(r"(?<=[a-z])(?=\d)", " ", s.replace("_", " "))


def source_card(g: Game):
    """The card whose effect is asking, if any."""
    d = g.decision
    if d and d.resume == "effect_answer" and len(d.ctx) > 1 and isinstance(d.ctx[1], dict):
        s = d.ctx[1].get("src")
        if s is not None and s in g.cards:
            return s
    return None


def _gig(s, v):
    return f"d{s} showing {v}"


def label(g: Game, kind: str, opt, me: int = HUMAN) -> str:
    """A readable label for one option."""
    if isinstance(opt, bool):
        if kind == "go_first":
            return "Go first" if opt else "Go second"
        if kind == "mulligan":
            return "Mulligan" if opt else "Keep hand"
        return "Yes" if opt else "No"
    if isinstance(opt, int):
        return f"Roll in d{opt}" if kind == "roll_in" else str(opt)
    if isinstance(opt, str):
        return _words(opt).capitalize()
    if not isinstance(opt, tuple) or not opt:
        return str(opt)
    k = opt[0]
    try:
        if k == "pass":
            return "End turn"
        if k == "end":
            return "No reaction" if kind == "react" else "Done"
        if k == "none":
            return "None" if kind not in ("adjust", "set_gig") else "Don't change a Gig"
        if k == "call":
            return f"Call a Legend (cost {g.call_cost(g.decision.player)})"
        if k == "sell":
            return f"Sell {g.db[opt[1]].title}"
        if k in ("play", "quick"):
            d = g.db[opt[1]]
            u = next((u for u in g.players[g.decision.player].hand if g.cards[u].cid == opt[1]), None)
            cost = g.play_cost(g.decision.player, u) if u is not None else d.cost
            return f"Play {d.title} (cost {cost})"
        if k == "card":
            return g.db[opt[1]].title
        if k == "deploy":
            return f"Put {g.d(opt[1]).title} on the field (cost {g.play_cost(g.decision.player, opt[1])})"
        if k == "solo":
            return f"Go Solo with {g.d(opt[1]).title} (cost {g.play_cost(g.decision.player, opt[1])})"
        if k == "attack":
            t = opt[2]
            tgt = "the rival Gigs" if t == ("gigs",) else _short(g.d(t[1]).title)
            return f"{_short(g.d(opt[1]).title)} attacks {tgt}"
        if k == "block":
            return f"Block with {g.d(opt[1]).title}"
        if k == "activate":
            return f"Use {g.d(opt[1]).title}'s ability"
        if k == "eddie":
            return "Spend an Eddie"
        if k == "legend_facedown":
            return "Spend a face-down Legend"
        if k == "legend":
            return f"Spend {g.d(opt[1]).title}"
        if k == "equip":
            return f"Equip to {g.d(opt[1]).title}"
        if k in ("unit", "target"):
            u = opt[1]
            side = "your" if g.controller(u) == me else "rival"
            return f"{g.d(u).title} ({side})"
        if k == "gig":
            if len(opt) == 3:
                return _gig(opt[1], opt[2])
            _, o, s, v, nv = opt
            whose = "Your" if o == me else "Rival"
            return f"{whose} d{s}: {v} → {nv}"
        if k == "set":
            _, o, s, v, nv = opt
            whose = "Your" if o == me else "Rival"
            return f"Set {whose.lower()} d{s} from {v} to {nv}"
        if k == "swap":
            _, s1, v1, s2, v2 = opt
            return f"Swap your d{s1}:{v1} with rival d{s2}:{v2}"
        if k == "move":
            return f"Move {g.d(opt[1]).title} to {_short(g.d(opt[2]).title)}"
        if k == "pending":
            return f"Resolve {g.db[opt[2]].title} first" if opt[2] is not None else "Resolve the next effect"
        if k == "value":
            return str(opt[1])
    except (KeyError, IndexError, TypeError, StopIteration):
        pass
    return g.describe(opt)


def refs(g: Game, opt) -> dict:
    """Which cards on the table an option is about, so the page can highlight them."""
    out = {"uids": [], "cids": []}
    if not isinstance(opt, tuple) or not opt:
        return out
    k = opt[0]
    if k in ("sell", "play", "quick", "card"):
        out["cids"].append(opt[1])
    elif k in ("solo", "deploy", "block", "legend", "equip", "unit", "target", "activate"):
        out["uids"].append(opt[1])
    elif k == "attack":
        out["uids"].append(opt[1])
        if opt[2][0] == "unit":
            out["uids"].append(opt[2][1])
    elif k == "move":
        out["uids"] += [opt[1], opt[2]]
    elif k == "pending" and opt[2] is not None:
        out["cids"].append(opt[2])
    return out


# -------------------------------------------------------------------- view
def player_view(g: Game, me: int = HUMAN) -> dict:
    """The board as player `me` sees it."""
    def card(u, **extra):
        out = card_info(g.d(u))
        out["uid"] = u
        out.update(extra)
        return out

    def hidden(u, **extra):
        out = {"uid": u, "hidden": True}
        out.update(extra)
        return out

    sides = []
    for p, pl in enumerate(g.players):
        field = [card(u, now_power=g.power(u), spent=g.cards[u].spent, lag=g.cards[u].lag,
                      gears=[card(x) for x in g.cards[u].gears])
                 for u in pl.field]
        legends = []
        for u in pl.legends:
            c = g.cards[u]
            if c.face_up or (p == me and u in pl.known_legends):
                legends.append(card(u, face_up=c.face_up, spent=c.spent, now_power=g.power(u),
                                    gears=[card(x) for x in c.gears]))
            else:
                legends.append(hidden(u, face_up=False, spent=c.spent))
        ready = sum(1 for u in pl.eddies if not g.cards[u].spent)
        sides.append({
            "me": p == me,
            "cred": g.street_cred(p),
            "gigs": [list(x) for x in pl.gigs],
            "fixer": list(pl.fixer),
            "hand": [card(u) for u in pl.hand] if p == me else len(pl.hand),
            "deck": len(pl.deck),
            "eddies": [ready, len(pl.eddies)],
            # Eddies are face-down and nobody may look at them (5.8.3.1): only ready or spent.
            "eddie_cards": [hidden(u, spent=g.cards[u].spent) for u in pl.eddies],
            "trash": [card(u) for u in pl.trash],
            "removed": [card(u) for u in pl.removed],
            "legends": legends,
            "field": field,
        })
    atk = None
    if g.attack:
        a = g.attack
        atk = {"atk": a.get("atk"), "target": list(a["target"]) if a.get("target") else None}
    return {"turn": g.turn_no, "turn_player": g.turn_player, "overtime": g.overtime,
            "winner": g.winner, "end_reason": g.end_reason, "attack": atk,
            "you": sides[me], "rival": sides[1 - me]}


# ------------------------------------------------------------------- match
_PLINE = re.compile(r"\bP([01])\b")
_DEC = re.compile(r"^P([01]) ([\w:]+): (.*)$")
# Decisions whose engine line adds nothing to the effect line that follows it.
_QUIET = {"main", "pay", "roll_in", "react", "steal", "equip", "order_pending"}


_VERBS = {"discard": "discards", "trash_one": "trashes", "target": "targets", "defeat_own": "defeats",
          "defeat_gear": "defeats", "go_first": "", "mulligan": "", "adjust": "", "set_gig": "",
          "swap": "", "move_gear": "", "card_type": "names", "call_which": "chooses"}


_YOU_VERB = {"discards": "discard", "trashes": "trash", "targets": "target", "defeats": "defeat",
             "names": "name", "chooses": "choose"}


def _you_verbs(t: str) -> str:
    """'You plays X' -> 'You play X'."""
    t = t.replace(" and gets ", " and get ") if t.startswith("You ") else t
    return re.sub(r"\bYou (\w+?)s\b", lambda m: "You " + (m.group(1) if m.group(1) not in ("i", "ha") else m.group(0)[4:]), t)


class Match:
    """One game between a person (player 0) and a bot (player 1)."""

    def __init__(self, deck_you: Deck, deck_bot: Deck, bot, seed=None, db=None,
                 bot_name="Bot"):
        self.db = db
        self.g = Game(deck_you, deck_bot, seed=seed, db=db, log=True)
        self.bot = bot
        self.bot_name = bot_name
        self.seed = seed
        self.decks = (deck_you, deck_bot)
        self.lock = threading.RLock()
        self.thinking = False
        self.error = None
        self.resigned = False
        self.choices: list = []          # every option stepped, by both players, in order
        self.mine: list[int] = []        # positions in self.choices where you chose
        self.gen = 0                     # bumped by undo/resign so a thinking bot's move is dropped
        self.lines: list[dict] = []
        self._seen = 0
        self._hist = 0
        self._tp = 0                                     # whose turn the log is in
        self._collect()

    # ---- the log, as the human may see it
    def _name(self, p: int) -> str:
        return "You" if p == HUMAN else self.bot_name

    def _collect(self):
        log = self.g.log
        for raw in log[self._seen:]:
            msg = re.sub(r"^\[T\d+\] ", "", raw)
            m = _DEC.match(msg)
            if m:
                p, kind, opt = self.g.history[self._hist]
                self._hist += 1
                if kind in _QUIET:
                    continue
                if (p == BOT and isinstance(opt, tuple) and opt and opt[0] == "card"
                        and kind not in ("discard", "trash_one", "target")):
                    text = "a card"                      # e.g. a card picked from their deck
                else:
                    try:
                        text = label(self.g, kind, opt, HUMAN)
                    except Exception:  # noqa: BLE001 - the log must never break the game
                        text = _PLINE.sub(lambda m: self._name(int(m.group(1))), m.group(3))
                if p == BOT:                             # labels are worded for you; turn them round
                    text = re.sub(r"\b[Rr]ival d", "its own d", re.sub(r"\bYour d", "your d", text))
                if kind == "swap" and p == BOT and isinstance(opt, tuple):
                    _, s1, v1, s2, v2 = opt
                    text = f"swaps its d{s1}:{v1} with your d{s2}:{v2}"
                text = re.sub(r" \(cost \d+\)$", "", text)
                verb = _VERBS.get(kind, "chooses")
                if kind.startswith("may:"):
                    verb = f"says {text.lower()} to"
                    text = _MAY.get(kind[4:], _words(kind[4:]))
                if p == HUMAN:
                    verb = _YOU_VERB.get(verb, verb.replace("says ", "say "))
                self.lines.append({"k": "choice", "p": p, "t": f"{self._name(p)} {verb}: {text}".replace(" : ", ": ")})
                continue
            if msg.startswith("--- Turn"):
                self._tp = int(_PLINE.search(msg).group(1))
                t = _PLINE.sub(lambda m: self._name(int(m.group(1))), msg.strip("- "))
                self.lines.append({"k": "turn", "t": t})
            elif msg.startswith("GAME OVER"):
                self.lines.append({"k": "end", "t": self._result()})
            else:
                t = _PLINE.sub(lambda m: self._name(int(m.group(1))), msg.strip())
                t = re.sub(r"rolls in d(\d+) = (\d+)", r"rolls in a d\1 and gets \2", t)
                gigs = "your Gigs" if self._tp == BOT else f"{self.bot_name}'s Gigs"
                t = t.replace("attacks rival Gig area", f"attacks {gigs}").replace(" attacks unit ", " attacks ")
                t = re.sub(r"rerolls d(\d+) = (\d+)", r"rerolls the d\1 and gets \2", t)
                t = re.sub(r"steals \[(.*?)\]", lambda m: "steals " + (", ".join(
                    x.strip(" '").replace("=", ":") for x in m.group(1).split(",")) or "nothing"), t)
                self.lines.append({"k": "effect", "t": _you_verbs(t)})
        self._seen = len(log)

    def _result(self) -> str:
        g = self.g
        if g.winner is None:
            return ""
        if g.winner == "draw":
            return f"Draw ({g.end_reason})"
        return f"{'You win' if g.winner == HUMAN else self.bot_name + ' wins'} ({g.end_reason})"

    # ---- actions
    def human_to_act(self) -> bool:
        return not self.g.over and self.g.decision.player == HUMAN

    def choose(self, i: int):
        with self.lock:
            if not self.human_to_act():
                raise ValueError("it isn't your decision")
            opts = self.g.decision.options
            if not 0 <= i < len(opts):
                raise ValueError("no such option")
            self.mine.append(len(self.choices))
            self.choices.append(opts[i])
            self.g.step(opts[i])
            self._collect()

    def run_bot(self, on_step=None, gen=None):
        """Let the bot act until the human has a decision or the game ends.

        If undo or resign happens while the bot is thinking (gen changes), its
        move is dropped and it stops."""
        gen = self.gen if gen is None else gen
        n = 0
        while True:
            with self.lock:
                g = self.g
                if gen != self.gen or g.over or g.decision.player != BOT:
                    break
                snap = g.clone()
            opt = self.bot.act(snap)                     # think without holding the lock
            with self.lock:
                if gen != self.gen:
                    break
                self.choices.append(opt)
                self.g.step(opt)
                self._collect()
            n += 1
            if on_step:
                on_step()
            if n > 5000:
                raise RuntimeError("bot decision limit exceeded")

    def can_undo(self) -> bool:
        return bool(self.mine) and not self.resigned

    def undo(self):
        """Take back your last choice, and everything the bot did after it.

        The game is rebuilt from the seed and the earlier choices, which gives the
        exact same position (the engine is deterministic for a seed)."""
        with self.lock:
            if not self.can_undo():
                raise ValueError("nothing to undo")
            keep = self.choices[:self.mine.pop()]
            self.gen += 1
            self.thinking = False
            self.g = Game(self.decks[0], self.decks[1], seed=self.seed, db=self.db, log=True)
            self.choices = []
            for opt in keep:
                self.choices.append(opt)
                self.g.step(opt)
            self.lines, self._seen, self._hist, self._tp = [], 0, 0, 0
            self._collect()

    def resign(self):
        """End the game now: you concede."""
        with self.lock:
            if self.g.over:
                return
            self.gen += 1
            self.thinking = False
            self.resigned = True
            self.g.win(BOT, "you resigned")
            self._collect()

    # ---- a replay of the game so far
    def record(self) -> dict:
        """The game in the replay format of cpbot.watch (seed, decks and every choice),
        so `python scripts/watch.py --replay FILE` rebuilds it exactly, bot hand included."""
        from .watch import _jsonable
        with self.lock:
            return {"format": "cpbot-replay-1", "seed": self.seed, "names": ["You", self.bot_name],
                    "decks": [{"legends": list(d.legends), "main": list(d.main)} for d in self.decks],
                    "choices": [_jsonable(o) for o in self.choices],
                    "winner": self.g.winner, "end_reason": self.g.end_reason,
                    "resigned": self.resigned, "bot": getattr(self, "level_name", None)}

    # ---- what the page shows
    def view(self) -> dict:
        with self.lock:
            g = self.g
            v = player_view(g, HUMAN)
            v["log"] = self.lines
            v["result"] = self._result()
            v["thinking"] = self.thinking
            v["error"] = self.error
            v["bot_name"] = self.bot_name
            v["can_undo"] = self.can_undo()
            dec = None
            if not g.over:
                d = g.decision
                dec = {"player": d.player, "mine": d.player == HUMAN, "kind": d.kind}
                if d.player == HUMAN:
                    dec["prompt"] = prompt(g, HUMAN)
                    opts = [dict(i=i, label=label(g, d.kind, o, HUMAN), key=_okey(o), **refs(g, o))
                            for i, o in enumerate(d.options)]
                    count = Counter(o["label"] for o in opts)
                    nth = Counter()
                    for o in opts:                       # e.g. two copies of the same Gear
                        if count[o["label"]] > 1:
                            nth[o["label"]] += 1
                            o["label"] += f" (#{nth[o['label']]})"
                    dec["options"] = opts
                    dec["peek"] = _peek_cards(g, d)
                    src = source_card(g)
                    dec["source"] = dict(card_info(g.d(src)), uid=src) if src is not None else None
            v["decision"] = dec
            return v


def _okey(o):
    """The option's kind, so the page can group buttons."""
    if isinstance(o, tuple) and o:
        return o[0]
    return type(o).__name__


def _peek_cards(g: Game, d) -> list:
    """Cards named by "card" options that aren't visible on the table (e.g. picked
    from the top of the deck), so the page can show their pictures."""
    ctx = d.ctx[1] if d.resume == "effect_answer" and len(d.ctx) > 1 and isinstance(d.ctx[1], dict) else {}
    if ctx.get("_top"):
        # A search of the top of the deck: show every card looked at, duplicates included
        # (the choices name each different card once, since copies are interchangeable).
        taken = set(ctx.get("_taken") or ())
        return [dict(card_info(g.d(u)), uid=u, note="taken" if u in taken else None)
                for u in reversed(ctx["_top"])]                # top card first
    out, seen = [], set()
    for o in d.options:
        if isinstance(o, tuple) and len(o) > 1 and o[0] in ("card", "pending") :
            cid = o[1] if o[0] == "card" else o[2]
            if cid is not None and cid not in seen:
                seen.add(cid)
                out.append(card_info(g.db[cid]))
    return out


def deck_summary(deck: Deck, db: CardDB) -> dict:
    c = Counter(deck.main)
    return {"legends": [db[i].title for i in deck.legends],
            "main": [[n, db[i].title] for i, n in sorted(c.items(), key=lambda kv: (db[kv[0]].type, db[kv[0]].title))]}


IMAGES_FILE = Path(__file__).resolve().parent.parent / "data" / "card_images.json"
