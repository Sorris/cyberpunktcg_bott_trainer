"""Gear scripts (17 cards). A Gear's bottom text acts as if printed on its host (4.11.3)."""
from __future__ import annotations

from ..effects import Ask, S, ability, note, on, static, step, vanilla
from .common import choose_unit, discard, draw, pick_uid, when

vanilla("mantis-blades", "mandibular-upgrade", "deadman-transmitter")
note("deadman-transmitter", "Mandatory replacement, handled in the engine's defeat code.")
note("mandibular-upgrade", "Blocker is inherited from the Gear's keyword.")


def host(g, me):
    c = g.cards[me]
    return c.host if c.zone == "equipped" else None


def on_host_spent(slug, *steps):
    @on("spent", slug)
    def _h(g, me, ev):
        h = host(g, me)
        if h is not None and ev["uid"] == h:
            g.trigger(me, steps, host=h)


# ---- Adrenaline Converter
@static("keyword", "adrenaline-converter")
def _adr(g, me, uid, kw):
    if kw != "adrenaline" or host(g, me) != uid:
        return False
    p = g.controller(me)
    return g.gig_count(1 - p) >= g.gig_count(p) + 2


# ---- Arasaka Emergency Radioport
@step("radioport")
def _radioport(g, ctx):
    p = ctx["p"]
    down = [u for u in g.players[p].legends if not g.cards[u].face_up]
    if not down:
        return None
    looked = g.rng.choice(down)
    if looked not in g.players[p].known_legends:
        g.players[p].known_legends.append(looked)
    d = g.d(looked)
    if ("ARASAKA" in d.tags or d.has("go solo")) and g.can_call(p):
        ctx["looked"] = looked
        return [S("_may", what="call_free", key="ok"), S("_radioport_call")]


@step("_radioport_call")
def _radioport_call(g, ctx):
    u = ctx.get("looked")
    p = ctx["p"]
    if ctx.get("ok") and u is not None and not g.cards[u].face_up and g.can_call(p):
        g.cards[u].face_up = True
        g.players[p].called = True
        g._log(f"  P{p} calls {g.d(u).title} (Radioport)")
        g.emit("call", player=p, uid=u)


on_host_spent("arasaka-emergency-radioport", S("_may", what="look", key="look"),
              when(("ctx", "look"), S("radioport")))
note("arasaka-emergency-radioport", "Looks at a random face-down Legend (they are indistinguishable).")


# ---- Dying Night - V's Pistol
@on("attack", "dying-night-v-s-pistol")
def _pistol_attack(g, me, ev):
    if ev["uid"] == host(g, me):
        g.trigger(me, [S("adjust", amount=2, mode="down")])


@on("turn_end", "dying-night-v-s-pistol")
def _pistol_end(g, me, ev):
    h = host(g, me)
    if h is not None and ev["player"] == g.controller(me) and "V" in g.d(h).names:
        g.trigger(me, [S("ready_eddies", n=2)])


# ---- Gorilla Arms
@on("steal_group", "gorilla-arms")
def _gorilla(g, me, ev):
    h = host(g, me)
    if h is not None and ev["actor"] == h and not g.turn_flags.get(("gorilla", me)):
        g.turn_flags[("gorilla", me)] = True
        g.trigger(me, [S("gorilla_steal")], host=h)


@step("gorilla_steal")
def _gorilla_steal(g, ctx):
    p = ctx["p"]
    mine = {v for _, v in g.players[p].gigs}
    opts = sorted({("gig", s, v) for s, v in g.players[1 - p].gigs if v not in mine})
    if not opts:
        return None
    return [S("_ask_opts", kind="steal", opts=tuple(opts), key="sg"), S("_steal_chosen", actor_key="host")]


# ---- Kiroshi Optics: knowledge only
@on("attack", "kiroshi-optics")
def _kiroshi(g, me, ev):
    h = host(g, me)
    if ev["uid"] == h:
        p = g.controller(me)
        down = [u for u in g.players[p].legends if not g.cards[u].face_up and u not in g.players[p].known_legends]
        if down:
            g.players[p].known_legends.append(g.rng.choice(down))


note("kiroshi-optics", "Looking at a Legend is tracked but agents don't use the knowledge yet.")


# ---- NetWatch Netdriver
on_host_spent("netwatch-netdriver", draw(1))


# ---- Overwatch - Panam's Gift
@step("overwatch")
def _overwatch(g, ctx):
    return [discard(1, key="od"), S("_overwatch2")]


@step("_overwatch2")
def _overwatch2(g, ctx):
    d = [x for x in ctx.get("od", []) if x is not None]
    if d:
        c = g.d(d[0]).cost or 0
        return [choose_unit("t", "rival", [("spent",), ("cost_le", c)]), S("defeat", key="t")]


ability("overwatch-panam-s-gift", "snipe", [S("overwatch")], eddies=1, quick=True,
        targets=lambda g, me: bool(g.players[g.controller(me)].hand)
        and any(g.cards[u].spent for u in g.units(1 - g.controller(me))))


# ---- Riot Shield
@static("cost", "riot-shield")
def _riot(g, me, p, uid, cost):
    if g.controller(me) != p and g.d(uid).type == "legend":
        return cost + 2
    return cost


# ---- Sandevistan
@on("turn_end", "sandevistan")
def _sandevistan(g, me, ev):
    h = host(g, me)
    if h is not None and ev["player"] == g.controller(me):
        g.trigger(me, [S("ready_host")], host=h)


@step("ready_host")
def _ready_host(g, ctx):
    h = ctx.get("host")
    if h is not None and g.cards[h].zone in ("field", "legends"):
        g.ready(h)


# ---- Satori - Sword of Saburo
@on("fight_result", "satori-sword-of-saburo")
def _satori(g, me, ev):
    h = host(g, me)
    if h is not None and h in ev["winners"]:
        g.trigger(me, [draw(1)])


# ---- Tetratronic Rippler
@step("rippler")
def _rippler(g, ctx):
    deck = g.players[ctx["p"]].deck
    if not deck:
        return None
    ctx["top"] = deck[-1]
    return [S("_may", what="trash_top", key="ok"), S("_rippler_do")]


@step("_rippler_do")
def _rippler_do(g, ctx):
    if ctx.get("ok") and g.cards[ctx["top"]].zone == "deck":
        g.move(ctx["top"], "trash")


on_host_spent("tetratronic-rippler", S("rippler"))


# ---- The Relic - Experimental Biochip
@on("defeated", "the-relic-experimental-biochip")
def _relic(g, me, ev):
    if me in ev.get("snapshot", {}).get("gears", []) and g.d(ev["uid"]).type != "gear":
        g.trigger(me, [S("relic")], p=ev["snapshot"]["controller"], host=ev["uid"])


@step("relic")
def _relic_step(g, ctx):
    return [S("choose", kind="target", cands=("trash", (("type", "unit"), ("cost_le", 9), ("not_host",))),
              key="t"), S("_relic_play")]


@step("_relic_play")
def _relic_play(g, ctx):
    t = ctx.get("t")
    p = ctx["p"]
    if t:
        uid = next(u for u in g.players[p].trash if g.cards[u].cid == t[1] and u != ctx["host"])
        g.move(uid, "field", p)
        c = g.cards[uid]
        c.spent = False
        c.lag = True
        g.emit("play", player=p, uid=uid)
        g.emit("played_unit", player=p, uid=uid)
    h = ctx["host"]
    if g.cards[h].zone == "trash":
        g.bottom_deck([h])


from ..effects import cond  # noqa: E402


@cond("not_host")
def _not_host(g, ctx, u):
    return u != ctx.get("host")


# ---- Zetatech Berserk
@static("self_cost", "zetatech-berserk")
def _berserk(g, me, p, cost):
    return cost - sum(1 for u in g.players[p].legends if g.cards[u].face_up)


# ---- Zetatech Faceplate
@step("faceplate2")
def _faceplate2(g, ctx):
    if len({v for _, v in g.players[ctx["p"]].gigs}) >= 3:
        g.draw(ctx["p"], 1)


on_host_spent("zetatech-faceplate", S("adjust", amount=1), S("faceplate2"))
