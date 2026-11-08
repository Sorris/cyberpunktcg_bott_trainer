"""Watchable games: a readable play-by-play log, a replayable record and an HTML replay.

The narrative is written from a spectator's seat, so it shows hidden cards (hands,
draws, face-down Legends). Players are called P1 and P2 here; the engine numbers
them 0 and 1.

    rec = watch_game(game, agents, decks)   # plays the game and records every step
    rec.text()                              # play-by-play as plain text
    rec.to_json()                           # seed, decks and choices: enough to replay
    rec.html()                              # self-contained replay page
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .deck import Deck
from .engine import Game

_PNAME = re.compile(r"\bP([01])\b")
_DECISION = re.compile(r"^P[01] [\w:]+: ")


def pname(p) -> str:
    return f"P{p + 1}"


def _rename(text: str) -> str:
    return _PNAME.sub(lambda m: pname(int(m.group(1))), text)


# ------------------------------------------------------------------ snapshot
def snapshot(g: Game) -> dict:
    """Everything a spectator can see, as plain data."""
    def card(u, **extra):
        d = g.d(u)
        out = {"uid": u, "title": d.title, "type": d.type, "color": d.color}
        out.update(extra)
        return out

    players = []
    for p, pl in enumerate(g.players):
        field = []
        for u in pl.field:
            c = g.cards[u]
            field.append(card(u, power=g.power(u), base=g.base_power(u), spent=c.spent,
                              lag=c.lag, legend=g.d(u).type == "legend",
                              gears=[card(x) for x in c.gears]))
        legends = [card(u, face_up=g.cards[u].face_up, spent=g.cards[u].spent,
                        power=g.power(u), known=u in pl.known_legends,
                        gears=[card(x) for x in g.cards[u].gears])
                   for u in pl.legends]
        ready = sum(1 for u in pl.eddies if not g.cards[u].spent)
        players.append({
            "cred": g.street_cred(p),
            "gigs": [list(x) for x in pl.gigs],
            "fixer": list(pl.fixer),
            "hand": [card(u) for u in pl.hand],
            "deck": len(pl.deck),
            "eddies": [ready, len(pl.eddies)],
            "trash": [card(u) for u in pl.trash],
            "removed": [card(u) for u in pl.removed],
            "legends": legends,
            "field": field,
        })
    zones = {}
    for u, c in g.cards.items():
        z = c.zone
        if z == "equipped":
            z = "field"
        zones[u] = (z, g.controller(u))
    return {"turn": g.turn_no, "tp": g.turn_player, "overtime": g.overtime,
            "winner": g.winner, "end_reason": g.end_reason, "players": players,
            "_zones": zones}


def status_line(snap: dict, p: int) -> str:
    s = snap["players"][p]
    cred = "Null" if s["cred"] is None else s["cred"]
    gigs = " ".join(f"d{a}:{b}" for a, b in s["gigs"]) or "none"
    legs = ", ".join(L["title"].split(" - ")[0] + ("" if L["face_up"] else " (down)")
                     for L in s["legends"]) or "none"
    field = ", ".join(f"{u['title'].split(' - ')[0]} {u['power']}" + (" spent" if u["spent"] else "")
                      for u in s["field"]) or "empty"
    return (f"{pname(p)}: Street Cred {cred} [{gigs}] | hand {len(s['hand'])} | "
            f"Eddies {s['eddies'][0]}/{s['eddies'][1]} | deck {s['deck']} | "
            f"Legends: {legs} | field: {field}")


def _tidy(text: str) -> str:
    """Engine log line -> reader-facing line."""
    text = re.sub(r"steals \[(.*?)\]", lambda m: "steals " + (", ".join(
        x.strip(" '").replace("=", ":") for x in m.group(1).split(",")) or "nothing"), text)
    text = re.sub(r"steals d(\d+)=(\d+)", r"steals d\1:\2", text)
    text = re.sub(r"rolls in d(\d+) = (\d+)", r"rolls in d\1 and gets \2", text)
    text = re.sub(r"^rerolls d(\d+) = (\d+)", r"rerolls the d\1 and gets \2", text)
    text = text.replace("attacks rival Gig area", "attacks the rival Gig area")
    text = text.replace(" attacks unit ", " attacks ")
    return _rename(text)


# ----------------------------------------------------------------- phrasing
def phrase_decision(g: Game, player: int, kind: str, opt) -> str | None:
    """Say what a player chose, or None when the engine's own lines already say it."""
    who = pname(player)
    if kind == "go_first":
        return f"{who} chooses to go {'first' if opt else 'second'}"
    if kind == "mulligan":
        return f"{who} {'mulligans' if opt else 'keeps their opening hand'}"
    if kind in ("roll_in", "steal", "equip", "react"):
        return None                                   # the engine's own lines say it
    if kind == "main":
        return f"{who} ends their turn" if opt == ("pass",) else None
    if kind == "pay":
        if opt == ("eddie",):
            return None
        if opt == ("legend_facedown",):
            return f"{who} spends a face-down Legend to pay"
        return f"{who} spends {g.d(opt[1]).title} to pay"
    if kind == "order_pending":
        src = opt[2]
        return f"{who} resolves {g.db[src].title}'s effect first" if src is not None else None
    if kind.startswith("may:"):
        what = kind[4:].replace("_", " ")
        return f"{who} says {'yes' if opt else 'no'} to: {what}"
    if kind in ("discard", "trash_one"):
        return None                                   # the card movement line says it
    if kind == "adjust":
        if opt == ("none",):
            return f"{who} doesn't adjust a Gig"
        return None                                   # the Gig change line says it
    if kind == "set_gig":
        return None
    if kind == "swap":
        _, s1, v1, s2, v2 = opt
        return f"{who} swaps d{s1}:{v1} with d{s2}:{v2}"
    if kind == "mode":
        return f"{who} chooses: {str(opt).replace('_', ' ')}"
    if isinstance(opt, tuple) and opt == ("none",):
        return f"{who} chooses nothing ({kind.replace('_', ' ')})"
    desc = re.sub(r"^(card|unit|legend|hand|target|value) ", "", _rename(g.describe(opt)))
    if kind == "target":
        return f"{who} targets {desc}"
    return f"{who} chooses ({kind.replace('_', ' ')}): {desc}"


_MOVES = {
    ("deck", "hand"): "draws",
    ("deck", "trash"): "trashes from the top of their deck",
    ("hand", "trash"): "discards",
    ("hand", "deck"): "puts back into their deck",
    ("trash", "hand"): "returns from trash to hand",
    ("trash", "deck"): "shuffles from trash into their deck",
    ("field", "hand"): "returns to hand",
    ("field", "deck"): "puts from the field into their deck",
    ("trash", "field"): "puts from trash onto the field",
    ("hand", "field"): "puts from hand onto the field",
    ("deck", "field"): "puts from their deck onto the field",
    ("field", "trash"): "trashes from the field",
    ("hand", "eddies"): "turns into Eddies",
    ("deck", "eddies"): "turns into Eddies from their deck",
    ("eddies", "hand"): "returns from Eddies to hand",
    ("eddies", "trash"): "trashes from their Eddies",
}


def phrase_moves(g: Game, prev: dict, new: dict, said: str) -> list[str]:
    """Card movements the engine didn't log, grouped by player and kind of move."""
    groups: dict = {}
    order = []
    for u, (z0, c0) in prev["_zones"].items():
        z1, c1 = new["_zones"][u]                         # z0 before, z1 after
        if z1 == "limbo" or (z0 == z1 and c0 == c1):
            continue
        title = g.d(u).title
        if title in said:
            continue
        if z0 == z1 == "field":
            key = (c1, "takes control of")
        elif z1 == "removed":
            key = (g.cards[u].owner, "has removed from the game")
        elif z0 == "limbo":
            key = (c1, f"puts onto {z1}")
        else:
            key = (c1 if z1 in ("field", "eddies") else g.cards[u].owner,
                   _MOVES.get((z0, z1), f"moves from {z0} to {z1}"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(title)
    out = []
    for p, verb in order:
        titles = groups[(p, verb)]
        if verb == "draws":
            out.append(f"{pname(p)} draws {len(titles)}: {', '.join(titles)}")
        else:
            out.append(f"{pname(p)} {verb}: {', '.join(titles)}")
    return out


def phrase_gigs(prev: dict, new: dict) -> list[str]:
    out = []
    for p in (0, 1):
        a = sorted(map(tuple, prev["players"][p]["gigs"]))
        b = sorted(map(tuple, new["players"][p]["gigs"]))
        if a == b:
            continue
        sides_a = {s for s, _ in a}
        for s in sorted(sides_a & {s for s, _ in b}):
            va = sorted(v for x, v in a if x == s)
            vb = sorted(v for x, v in b if x == s)
            if va != vb and len(va) == len(vb) == 1:
                out.append(f"{pname(p)}'s d{s} changes from {va[0]} to {vb[0]}")
    return out


# ------------------------------------------------------------------ recorder
class Recorder:
    """Builds frames: one per decision, each with the lines that led to it.

    It watches the engine's log as it happens (Game.observer), and between log
    lines it diffs the board to say what card effects did (draws, discards,
    Gig changes), so the lines come out in the order things happened."""

    def __init__(self, game: Game, decks, seed, names=("P1", "P2")):
        self.g = game
        self.decks = decks
        self.seed = seed
        self.names = list(names)
        self.choices = []
        self._snap = snapshot(game)
        self._recent = ["", ""]                        # the last two engine lines
        self._lines = []
        intro = []
        for p in (0, 1):
            legs = ", ".join(game.d(u).title for u in game.players[p].legends)
            intro.append({"k": "info", "t": f"{pname(p)} ({self.names[p]}) brings {legs}"})
        self.frames = [self._frame(intro)]
        game.observer = self

    def _frame(self, lines, decision=None):
        s = {k: v for k, v in self._snap.items() if k != "_zones"}
        d = self.g.decision
        nxt = {"player": d.player, "kind": d.kind, "n": len(d.options)} if d else None
        return {"lines": lines, "state": s, "chosen": decision, "next": nxt}

    def _flush(self, g, msg=""):
        """Describe what changed on the board since the last look."""
        new = snapshot(g)
        near = "\n".join(self._recent + [msg])
        extra = phrase_moves(g, self._snap, new, near)
        last_kind = g.history[-1][1] if g.history else ""
        if last_kind not in ("swap",) and "rerolls" not in near:
            extra += phrase_gigs(self._snap, new)
        self._lines += [{"k": "effect", "t": x} for x in extra]
        self._snap = new

    def log(self, g, msg):
        """Called by the engine for every log line, before it is stored."""
        if _DECISION.match(msg):
            self._flush(g)
            player, kind, opt = g.history[-1]
            text = phrase_decision(g, player, kind, opt)
            if text:
                self._lines.append({"k": "choice", "t": text})
            return
        self._flush(g, msg)
        if msg.startswith("--- Turn"):
            self._lines.append({"k": "turn", "t": _rename(msg.strip("- "))})
            self._status_due = True
        elif msg.startswith("GAME OVER"):
            self._lines.append({"k": "end", "t": _rename(msg)})
        else:
            self._lines.append({"k": "effect", "t": _tidy(msg.strip())})
        self._recent = [self._recent[1], msg]

    def after_step(self, player, kind, opt):
        g = self.g
        self.choices.append(opt)
        self._flush(g)
        if getattr(self, "_status_due", False) and not g.over:
            # The board as the turn player is about to act (after ready, draw and roll-in).
            for p in (g.turn_player, 1 - g.turn_player):
                self._lines.append({"k": "status", "t": status_line(self._snap, p)})
            self._status_due = False
        lines, self._lines = self._lines, []
        desc = _rename(g.describe(opt)) if not isinstance(opt, bool) else str(opt)
        self.frames.append(self._frame(lines, {"player": player, "kind": kind, "desc": desc}))

    # ---- outputs
    def text(self) -> str:
        out = []
        for f in self.frames:
            for L in f["lines"]:
                if L["k"] == "turn":
                    out += ["", f"== {L['t']} =="]
                elif L["k"] == "status":
                    out.append(f"   {L['t']}")
                else:
                    out.append(f"  {L['t']}" if L["k"] == "effect" else L["t"])
        return "\n".join(out).strip() + "\n"

    def record(self) -> dict:
        return {"format": "cpbot-replay-1", "seed": self.seed, "names": self.names,
                "decks": [{"legends": list(d.legends), "main": list(d.main)} for d in self.decks],
                "choices": [_jsonable(o) for o in self.choices],
                "winner": self.g.winner, "end_reason": self.g.end_reason}

    def to_json(self) -> str:
        return json.dumps(self.record())

    def html(self, title=None, standalone=True) -> str:
        g = self.g
        legs = [" / ".join(g.d(u).title.split(" - ")[0] for u in _legend_uids(g, p)) for p in (0, 1)]
        meta = {
            "names": self.names,
            "legends": legs,
            "winner": g.winner,
            "end_reason": g.end_reason,
            "seed": self.seed,
            "turns": g.turn_no,
        }
        data = json.dumps({"meta": meta, "frames": self.frames}, separators=(",", ":"))
        data = data.replace("</", "<\\/")
        page = _TEMPLATE.read_text()
        page = page.replace("__TITLE__", title or "Match replay").replace("/*__DATA__*/null", data)
        if standalone:
            page = "<!doctype html>\n<html lang=\"en\">\n<meta charset=\"utf-8\">\n" \
                   "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n" + page
        return page


_TEMPLATE = Path(__file__).with_name("replay_template.html")


def _legend_uids(g, p):
    return sorted(u for u, c in g.cards.items() if c.owner == p and g.d(u).type == "legend")


def _jsonable(o):
    if isinstance(o, tuple):
        return [_jsonable(x) for x in o]
    return o


def _match_option(options, want):
    for o in options:
        if _jsonable(o) == want:
            return o
    raise ValueError(f"recorded choice {want!r} is not legal here: {options}")


# --------------------------------------------------------------- play / load
def watch_game(game: Game, agents, decks, seed=None, names=None, max_decisions=20000) -> Recorder:
    rec = Recorder(game, decks, seed, names or [type(a).__name__ for a in agents])
    n = 0
    while not game.over:
        d = game.decision
        opt = agents[d.player].act(game)
        game.step(opt)
        rec.after_step(d.player, d.kind, opt)
        n += 1
        if n > max_decisions:
            raise RuntimeError("decision limit exceeded")
    return rec


def replay(record: dict, db=None) -> Recorder:
    """Rebuild a recorded game step by step. Same seed + same choices = same game."""
    decks = [Deck(d["legends"], d["main"]) for d in record["decks"]]
    g = Game(decks[0], decks[1], seed=record["seed"], db=db)
    rec = Recorder(g, decks, record["seed"], record.get("names", ("P1", "P2")))
    for want in record["choices"]:
        d = g.decision
        opt = _match_option(d.options, want)
        g.step(opt)
        rec.after_step(d.player, d.kind, opt)
    return rec
