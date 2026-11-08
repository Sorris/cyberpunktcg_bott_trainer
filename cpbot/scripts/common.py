"""Shared candidates, conditions and step helpers for card scripts."""
from __future__ import annotations

from ..effects import STOP, Ask, S, cands, cond, on, step

# ----------------------------------------------------------------- conditions
# Unit filters: fn(g, ctx, uid, *args) -> bool


@cond("power_le")
def _power_le(g, ctx, u, n):
    return g.power(u) <= n


@cond("power_lt")
def _power_lt(g, ctx, u, n):
    return g.power(u) < n


@cond("power_eq")
def _power_eq(g, ctx, u, n):
    return g.power(u) == n


@cond("cost_le")
def _cost_le(g, ctx, u, n):
    return (g.d(u).cost or 0) <= n


@cond("spent")
def _spent(g, ctx, u):
    return g.cards[u].spent


@cond("ready")
def _ready(g, ctx, u):
    return not g.cards[u].spent


@cond("equipped")
def _equipped(g, ctx, u):
    return bool(g.cards[u].gears)


@cond("unequipped")
def _unequipped(g, ctx, u):
    return not g.cards[u].gears


@cond("not_src")
def _not_src(g, ctx, u):
    return u != ctx.get("src")


@cond("tag")
def _tag(g, ctx, u, t):
    return g.has_tag(u, t)


@cond("type")
def _type(g, ctx, u, t):
    return g.d(u).type == t


@cond("program")
def _program(g, ctx, u):
    return g.d(u).type == "program"


@cond("power_lt_a_friendly")
def _power_lt_friendly(g, ctx, u):
    return any(g.power(u) < g.power(f) for f in g.units(ctx["p"]))


# Plain conditions: fn(g, ctx, *args)
@cond("cred_even")
def _cred_even(g, ctx):
    c = g.street_cred(ctx["p"])
    return c is not None and c % 2 == 0


@cond("more_cred")
def _more_cred(g, ctx):
    return g.cred_cmp(ctx["p"]) > 0


@cond("less_cred")
def _less_cred(g, ctx):
    return g.cred_cmp(ctx["p"]) < 0


@cond("has_pair")
def _has_pair(g, ctx):
    return g.value_pairs(ctx["p"]) > 0


@cond("min_gig")
def _min_gig(g, ctx):
    return bool(g.min_gigs(ctx["p"]))


@cond("gig8")
def _gig8(g, ctx):
    return bool(g.gigs_at_least(ctx["p"], 8))


@cond("rival_2_more_gigs")
def _r2(g, ctx):
    p = ctx["p"]
    return g.gig_count(1 - p) >= g.gig_count(p) + 2


@cond("ctx")
def _ctxflag(g, ctx, key):
    return bool(ctx.get(key))


# ----------------------------------------------------------------- candidates
def _owners(ctx, who):
    p = ctx["p"]
    return {"rival": (1 - p,), "friendly": (p,), "any": (0, 1)}[who]


@cands("units")
def _units(g, ctx, who, filt=()):
    out = []
    for o in _owners(ctx, who):
        for u in g.players[o].field:
            if all(g.filter_ok(ctx, u, f) for f in filt):
                out.append(("unit", u))
    return out


@cands("gears")
def _gears(g, ctx, who, filt=()):
    out = []
    for o in _owners(ctx, who):
        pl = g.players[o]
        for h in pl.field + pl.legends:
            for gu in g.cards[h].gears:
                if all(g.filter_ok(ctx, gu, f) for f in filt):
                    out.append(("unit", gu))
    return out


@cands("face_up_legends")
def _ful(g, ctx, who="friendly"):
    return [("unit", u) for o in _owners(ctx, who) for u in g.players[o].legends if g.cards[u].face_up]


@cands("hand")
def _hand(g, ctx, filt=()):
    pl = g.players[ctx["p"]]
    return sorted({("card", g.cards[u].cid) for u in pl.hand if all(g.filter_ok(ctx, u, f) for f in filt)})


@cands("trash")
def _trash(g, ctx, filt=()):
    pl = g.players[ctx["p"]]
    return sorted({("card", g.cards[u].cid) for u in pl.trash if all(g.filter_ok(ctx, u, f) for f in filt)})


@cands("hand_or_trash")
def _hand_or_trash(g, ctx, filt=()):
    pl = g.players[ctx["p"]]
    out = set()
    for zone in ("hand", "trash"):
        for u in getattr(pl, zone):
            if all(g.filter_ok(ctx, u, f) for f in filt):
                out.add((zone, g.cards[u].cid))
    return sorted(out)


@cands("among")
def _among(g, ctx, key, filt=()):
    """Cards remembered in ctx[key] (list of uids) that pass the filters."""
    return sorted({("card", g.cards[u].cid) for u in ctx.get(key, []) if all(g.filter_ok(ctx, u, f) for f in filt)})


@cands("my_gigs")
def _my_gigs(g, ctx):
    return sorted({("gig", s, v) for s, v in g.players[ctx["p"]].gigs})


@cands("rival_gigs")
def _rival_gigs(g, ctx):
    return sorted({("gig", s, v) for s, v in g.players[1 - ctx["p"]].gigs})


# ----------------------------------------------------------------- helpers
def pick_uid(g, ctx, zone_owner, zone, cid):
    pl = g.players[zone_owner]
    return next(u for u in getattr(pl, zone) if g.cards[u].cid == cid)


def choose_unit(key, who="rival", filt=(), chooser="me", optional=False, kind="target"):
    return S("choose", kind=kind, cands=("units", who, tuple(filt)), key=key,
             chooser=chooser, optional=optional)


def self_trigger(event, slug, *steps, when=None):
    """Register '[EVENT] ...' on the card itself."""
    def handler(g, me, ev):
        if ev.get("uid") == me and (when is None or when(g, me, ev)):
            g.trigger(me, steps)
    on(event, slug)(handler)


def draw(n=1, who="me"):
    return S("draw", n=n, who=who)


def discard(n=1, who="me", optional=False, filt=None, key="discarded"):
    return S("discard", n=n, who=who, optional=optional, filt=filt, key=key)


def when(c, *then, orelse=()):
    return S("if", cond=c, then=tuple(then), orelse=tuple(orelse))


@step("give_power_choice")
def _give_power_choice(g, ctx, n, who="friendly", filt=(), dur="turn", key="t"):
    return [choose_unit(key, who, filt), S("power", key=key, n=n, dur=dur)]


@step("mark_turn")
def _mark_turn(g, ctx, name):
    g.turn_flags[name] = True


@step("stop_if_flag")
def _stop_if_flag(g, ctx, name):
    if g.turn_flags.get(name):
        return STOP


@step("ready_eddies")
def _ready_eddies(g, ctx, n=1):
    spent = [u for u in g.players[ctx["p"]].eddies if g.cards[u].spent][:n]
    for u in spent:
        g.ready(u)


@step("call_choose_known")
def _call_choose_known(g, ctx):
    """Call a Legend for free when you have looked at your face-down Legends (T-Bug)."""
    p = ctx["p"]
    if not g.can_call(p):
        return None
    down = [u for u in g.players[p].legends if not g.cards[u].face_up]
    return Ask(p, "call_which", [("none",)] + [("legend", u) for u in down], "_callk")


@step("_call_known_do")
def _call_known_do(g, ctx):
    a = ctx.pop("_callk", ("none",))
    if a != ("none",) and g.can_call(ctx["p"]):
        p = ctx["p"]
        u = a[1]
        g.cards[u].face_up = True
        g.players[p].called = True
        g.emit("call", player=p, uid=u)
