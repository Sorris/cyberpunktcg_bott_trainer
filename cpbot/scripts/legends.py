"""Legend scripts (28 cards)."""
from __future__ import annotations

from ..effects import STOP, Ask, S, ability, lasting_static, note, on, static, step, vanilla
from .common import choose_unit, discard, draw, pick_uid, self_trigger, when

# Pure keyword Legends (Go Solo / Blocker handled by the engine)
vanilla("goro-takemura-hands-unclean", "v-corporate-exile", "rebecca-having-a-moment")


def call_trigger(slug, *steps):
    self_trigger("call", slug, *steps)


def face_up_or_field(g, me):
    c = g.cards[me]
    return c.zone == "field" or (c.zone == "legends" and c.face_up)


# ---- Adam Smasher - Ender of Legends: {Go Solo} {Play} Defeat a rival Unit.
self_trigger("play", "adam-smasher-ender-of-legends",
             choose_unit("t", "rival"), S("defeat", key="t"))


# ---- Alt Cunningham - Soulkiller Architect
@step("alt_next_program")
def _alt_next(g, ctx):
    g.add_lasting({"kind": "next_program_cheaper", "p": ctx["p"], "until": "eot", "used": False})


@lasting_static("cost", "next_program_cheaper")
def _alt_cost(g, L, p, uid, cost):
    if L["used"] or p != L["p"] or g.d(uid).type != "program":
        return cost
    return cost - len(g.min_gigs(p))


def _alt_has_program(g, me):
    p = g.controller(me)
    return any(g.d(u).type == "program" and g.can_pay(p, 1 + g.play_cost(p, u), exclude=me)
               for u in g.players[p].trash)


@step("alt_play_from_trash")
def _alt_play(g, ctx):
    p = ctx["p"]
    opts = sorted({("card", g.cards[u].cid) for u in g.players[p].trash
                   if g.d(u).type == "program" and g.can_pay(p, g.play_cost(p, u))})
    if not opts:
        return None
    return [S("_ask_opts", kind="target", opts=tuple(opts), key="t"), S("_alt_play_do")]


@step("_alt_play_do")
def _alt_play_do(g, ctx):
    p = ctx["p"]
    uid = pick_uid(g, ctx, p, "trash", ctx["t"][1])
    g.play_free(p, uid, free=False, bottom_after=True)


@step("_ask_opts")
def _ask_opts(g, ctx, kind, opts, key, who=None):
    return Ask(ctx["p"] if who is None else who, kind, list(opts), key)


ability("alt-cunningham-soulkiller-architect", "next program cheaper", [S("alt_next_program")])
ability("alt-cunningham-soulkiller-architect", "program from trash", [S("alt_play_from_trash")],
        eddies=1, targets=_alt_has_program)


# ---- Dexter DeShawn - Off the Grid
call_trigger("dexter-deshawn-off-the-grid",
             S("mode", labels=("power", "draw")),
             S("branch", key="mode", cases=(
                 ("power", (S("give_power_choice", n=2),)),
                 ("draw", (draw(1),)))))
ability("dexter-deshawn-off-the-grid", "increase gig", [S("adjust", amount=2, mode="up")],
        targets=lambda g, me: any(v < s for pl in g.players for s, v in pl.gigs))


# ---- Dum Dum - Maelstrom Triggerman
@step("dumdum_call")
def _dumdum_call(g, ctx):
    return [S("choose", kind="defeat_gear", cands=("gears", "friendly"), key="t", optional=True),
            S("_dumdum_after")]


@step("_dumdum_after")
def _dumdum_after(g, ctx):
    t = ctx.get("t")
    if t and t != ("none",):
        g.defeat_now(t[1])
        g.draw(ctx["p"], 2)
    else:
        g.draw(ctx["p"], 1)


call_trigger("dum-dum-maelstrom-triggerman", S("dumdum_call"))


@step("dumdum_power")
def _dumdum_power(g, ctx):
    t = ctx.get("t")
    if t and g.cards[t[1]].zone == "field":
        g.give_power(t[1], len(g.cards[t[1]].gears))


ability("dum-dum-maelstrom-triggerman", "power per gear",
        [choose_unit("t", "friendly", [("equipped",)]), S("dumdum_power")], eddies=1, quick=True,
        targets=lambda g, me: any(g.cards[u].gears for u in g.units(g.controller(me))))


# ---- Evelyn Parker - Beautiful Enigma
@on("steal_group", "evelyn-parker-beautiful-enigma")
def _evelyn_steal(g, me, ev):
    if not face_up_or_field(g, me):
        return
    a = ev["actor"]
    if ev["player"] == g.controller(me) and (g.has_tag(a, "CORPO") or g.has_tag(a, "GANGER")):
        g.trigger(me, [S("ready_eddies", n=1)])


@step("must_attack")
def _must_attack(g, ctx, key):
    t = ctx.get(key)
    if t and t != ("none",):
        g.add_lasting({"kind": "must_attack", "p": ctx["p"], "unit": t[1], "expires": g.turn_no + 1})


ability("evelyn-parker-beautiful-enigma", "must attack",
        [choose_unit("t", "rival"), S("must_attack", key="t")], eddies=1,
        targets=lambda g, me: bool(g.units(1 - g.controller(me))))


# ---- Goro Takemura - Vengeful Bodyguard
@step("goro_blocker")
def _goro_blocker(g, ctx):
    t = ctx.get("t")
    if t:
        g.add_lasting({"kind": "grant_kw", "p": ctx["p"], "unit": t[1], "kw": "blocker", "until": "eot"})
        if g.value_pairs(ctx["p"]):
            g.give_power(t[1], 1)


@lasting_static("keyword", "grant_kw")
def _grant_kw(g, L, uid, kw):
    return L["unit"] == uid and L["kw"] == kw


ability("goro-takemura-vengeful-bodyguard", "grant blocker",
        [choose_unit("t", "friendly", [("cost_le", 4)]), S("goro_blocker")], eddies=1, quick=True,
        targets=lambda g, me: any((g.d(u).cost or 0) <= 4 for u in g.units(g.controller(me))))


@on("blocker_used", "goro-takemura-vengeful-bodyguard")
def _goro_blocked(g, me, ev):
    if face_up_or_field(g, me) and ev["player"] == g.controller(me):
        g.trigger(me, [discard(1, optional=True), when(("ctx", "discarded"), draw(1))])


@step("drop_none")
def _drop_none(g, ctx, key="discarded"):
    ctx[key] = [x for x in ctx.get(key, []) if x is not None]


# ---- Hanako Arasaka - Daughter of the Emperor
@step("swap_choice")
def _swap_choice(g, ctx):
    p = ctx["p"]
    mine = sorted({(s, v) for s, v in g.players[p].gigs})
    theirs = sorted({(s, v) for s, v in g.players[1 - p].gigs})
    opts = [("swap", a[0], a[1], b[0], b[1]) for a in mine for b in theirs]
    if not opts:
        return None
    return [S("_ask_opts", kind="swap", opts=tuple(opts), key="sw"), S("_swap_do")]


@step("_swap_do")
def _swap_do(g, ctx):
    _, s1, v1, s2, v2 = ctx["sw"]
    p = ctx["p"]
    g.swap_gigs(p, g.find_gig(p, s1, v1), g.find_gig(1 - p, s2, v2))


ability("hanako-arasaka-daughter-of-the-emperor", "swap", [S("swap_choice")],
        targets=lambda g, me: bool(g.players[0].gigs and g.players[1].gigs))


@on("turn_start", "hanako-arasaka-daughter-of-the-emperor")
def _hanako_start(g, me, ev):
    p = g.controller(me)
    if face_up_or_field(g, me) and ev["player"] == p:
        g.trigger(me, [S("draw_pairs")])


@step("draw_pairs")
def _draw_pairs(g, ctx):
    g.draw(ctx["p"], g.value_pairs(ctx["p"]))


# ---- Jackie Welles - Mama's Favorite: Go Solo + optional defeat replacement (engine).
note("jackie-welles-mama-s-favorite", "Replacement is offered whenever a friendly Unit would be "
     "defeated; payment uses ready Eddies first, then Legends.")
vanilla("jackie-welles-mama-s-favorite")


# ---- Jackie Welles - Pour One Out For Me
def _jackie_blue(g, me, ev):
    p = g.controller(me)
    if not face_up_or_field(g, me) or ev["player"] != p or g.d(ev["uid"]).color != "blue":
        return
    if g.turn_flags.get(("jackie_pour", me)):
        return
    g.turn_flags[("jackie_pour", me)] = True
    g.trigger(me, [S("adjust", amount=2, mode="down", who="friendly", key="adj"), S("jackie_min")])


on("played_unit", "jackie-welles-pour-one-out-for-me")(_jackie_blue)
on("played_gear", "jackie-welles-pour-one-out-for-me")(_jackie_blue)


@step("jackie_min")
def _jackie_min(g, ctx):
    a = ctx.get("adj")
    if a and a[2] == 1:
        g.draw(ctx["p"], 1)


# ---- Johnny Silverhand - Rocking Renegade
@step("johnny_go")
def _johnny_go(g, ctx):
    t = ctx.get("t")
    if t:
        g.add_lasting({"kind": "lag_attack_spent", "p": ctx["p"], "unit": t[1], "until": "eot"})
        if g.has_tag(t[1], "ROCKER"):
            g.give_power(t[1], 2)


@lasting_static("lag_attack_ok", "lag_attack_spent")
def _lag_spent(g, L, uid, target):
    return L["unit"] == uid and target[0] == "unit" and g.cards[target[1]].spent


ability("johnny-silverhand-rocking-renegade", "johnny", [choose_unit("t", "friendly"), S("johnny_go")],
        eddies=2, targets=lambda g, me: bool(g.units(g.controller(me))))
note("johnny-silverhand-rocking-renegade", "Cost reduction applied when the ability is activated.")


# ---- Judy Álvarez - Braindance Maestro
@on("played_program", "judy-a-lvarez-braindance-maestro")
def _judy_bd(g, me, ev):
    if face_up_or_field(g, me) and ev["player"] == g.controller(me) and g.has_tag(ev["uid"], "BRAINDANCE"):
        g.trigger(me, [S("give_power_choice", n=1)])


@step("judy_trash")
def _judy_trash(g, ctx):
    out = g.trash_top(ctx["p"], 1)
    if out and g.d(out[0]).type == "program":
        ctx["judy_card"] = out[0]
        return [S("_may", what="add_to_hand", key="ok"), S("_judy_add")]


@step("_judy_add")
def _judy_add(g, ctx):
    if ctx.get("ok") and g.cards[ctx["judy_card"]].zone == "trash":
        g.move(ctx["judy_card"], "hand")


ability("judy-a-lvarez-braindance-maestro", "trash top", [S("judy_trash")],
        targets=lambda g, me: bool(g.players[g.controller(me)].deck))


# ---- Kerry Eurodyne - Axe, Attitude, Audience
@on("roll_in", "kerry-eurodyne-axe-attitude-audience")
def _kerry_roll(g, me, ev):
    p = g.controller(me)
    if face_up_or_field(g, me) and ev["player"] == p:
        g.trigger(me, [S("_may", what="reroll", key="rr"), S("kerry_reroll"), S("kerry_minmax")],
                  gig=ev["gig"])


@step("kerry_reroll")
def _kerry_reroll(g, ctx):
    if not ctx.get("rr"):
        return
    gig = ctx["gig"]
    if not any(x is gig for x in g.players[ctx["p"]].gigs):
        return
    gig[1] = g.rng.randint(1, gig[0])
    g._log(f"  rerolls d{gig[0]} = {gig[1]}")


@step("kerry_minmax")
def _kerry_minmax(g, ctx):
    """Draw if the roll you keep is a min or max (ruling from Henry, 8 Nov 2026)."""
    gig = ctx["gig"]
    if not any(x is gig for x in g.players[ctx["p"]].gigs):
        return
    s, v = gig
    if v in (1, s):
        g.draw(ctx["p"], 3 if s == 20 else 1)


note("kerry-eurodyne-axe-attitude-audience", "Draws only if the kept roll (first or reroll) is a min or max.")


# ---- Lucyna Kushinada - Fresh Beginnings
@step("lucyna")
def _lucyna(g, ctx):
    g.draw(ctx["p"], 2 if len(g.min_gigs(ctx["p"])) >= 2 else 1)


call_trigger("lucyna-kushinada-fresh-beginnings", S("lucyna"))


# ---- Muamar Reyes - El Capitán
@step("no_fight_defeat")
def _nfd(g, ctx, key="t"):
    t = ctx.get(key)
    if t:
        g.add_lasting({"kind": "no_fight_defeat", "p": ctx["p"], "unit": t[1], "until": "eot"})


@lasting_static("no_fight_defeat", "no_fight_defeat")
def _nfd_static(g, L, loser, other):
    return L["unit"] == loser


call_trigger("muamar-reyes-el-capita-n",
             S("mode", labels=("protect", "draw")),
             S("branch", key="mode", cases=(
                 ("protect", (choose_unit("t", "friendly"), S("no_fight_defeat"))),
                 ("draw", (draw(1),)))))
ability("muamar-reyes-el-capita-n", "adjust 1", [S("adjust", amount=1, upto=False, exact=True)],
        targets=lambda g, me: bool(g.players[0].gigs or g.players[1].gigs))


# ---- Padre - Man of the Cross
call_trigger("padre-man-of-the-cross",
             S("mode", labels=("spend", "draw")),
             S("branch", key="mode", cases=(
                 ("spend", (choose_unit("t", "rival", [("ready",)]), S("spend_target", key="t"))),
                 ("draw", (draw(1),)))))


@step("padre_set")
def _padre_set(g, ctx):
    opts = set()
    for o in (0, 1):
        for s, v in g.players[o].gigs:
            for _, v2 in g.players[1 - o].gigs:
                if v2 != v and v2 <= s:
                    opts.add(("set", o, s, v, v2))
    if not opts:
        return None
    return [S("_ask_opts", kind="set_gig", opts=tuple(sorted(opts)), key="st"), S("_padre_do")]


@step("_padre_do")
def _padre_do(g, ctx):
    _, o, s, v, nv = ctx["st"]
    g.set_gig(o, g.find_gig(o, s, v), nv, by=ctx["p"])


ability("padre-man-of-the-cross", "set gig", [S("padre_set")],
        targets=lambda g, me: bool(g.players[0].gigs and g.players[1].gigs))


# ---- Panam Palmer - Nomad Cavalry
@step("panam_move")
def _panam_move(g, ctx):
    me = ctx["src"]
    p = ctx["p"]
    gears = list(g.cards[me].gears)
    units = [u for u in g.units(p) if not g.cards[u].gears]
    if not gears or not units:
        return None
    opts = [("move", gu, u) for gu in gears for u in units]
    return [S("_ask_opts", kind="move_gear", opts=tuple(opts), key="mv"), S("_panam_do")]


@step("_panam_do")
def _panam_do(g, ctx):
    _, gu, u = ctx["mv"]
    if g.cards[gu].host is not None and g.cards[u].zone == "field":
        g.cards[g.cards[gu].host].gears.remove(gu)
        g.cards[gu].host = u
        g.cards[u].gears.append(gu)
        g.ready(u)


ability("panam-palmer-nomad-cavalry", "move gear", [S("panam_move")], eddies=2,
        targets=lambda g, me: bool(g.cards[me].gears) and any(not g.cards[u].gears for u in g.units(g.controller(me))))


@on("turn_end", "panam-palmer-nomad-cavalry")
def _panam_end(g, me, ev):
    p = g.controller(me)
    if face_up_or_field(g, me) and ev["player"] == p:
        g.trigger(me, [S("panam_ready")])


@step("panam_ready")
def _panam_ready(g, ctx):
    p = ctx["p"]
    pl = g.players[p]
    eq = [u for u in pl.field + pl.legends if g.cards[u].gears]
    if len(eq) >= 5:
        for u in eq:
            g.ready(u)


# ---- River Ward - Detective on the Hunt
@step("river_play_gear")
def _river(g, ctx):
    p = ctx["p"]
    opts = sorted({("card", g.cards[u].cid) for u in g.players[p].hand
                   if g.d(u).type == "gear" and (g.d(u).cost or 0) <= 2})
    if not opts or not g.equip_targets(p):
        return None
    return [S("_ask_opts", kind="target", opts=tuple(opts), key="t"), S("_river_do")]


@step("_river_do")
def _river_do(g, ctx):
    p = ctx["p"]
    g.play_free(p, pick_uid(g, ctx, p, "hand", ctx["t"][1]))


ability("river-ward-detective-on-the-hunt", "free gear", [S("river_play_gear")], quick=True,
        targets=lambda g, me: any(g.d(u).type == "gear" and (g.d(u).cost or 0) <= 2
                                  for u in g.players[g.controller(me)].hand))


@on("defeated", "river-ward-detective-on-the-hunt")
def _river_def(g, me, ev):
    snap = ev.get("snapshot", {})
    if (face_up_or_field(g, me) and ev["uid"] != me and snap.get("gears") and snap.get("zone") == "field"
            and snap.get("controller") == g.controller(me)):
        g.trigger(me, [S("search_trash1", n=2)])


@step("search_trash1")
def _search_trash1(g, ctx, n):
    """Search the top n cards of your deck and trash 1 (others stay on top in order)."""
    deck = g.players[ctx["p"]].deck
    top = deck[-n:]
    if not top:
        return None
    opts = sorted({("card", g.cards[u].cid) for u in top})
    ctx["_top"] = list(top)
    return [S("_ask_opts", kind="trash_one", opts=tuple(opts), key="tt"), S("_search_trash1_do")]


@step("_search_trash1_do")
def _search_trash1_do(g, ctx):
    u = next(u for u in ctx["_top"] if g.cards[u].cid == ctx["tt"][1] and g.cards[u].zone == "deck")
    g.move(u, "trash")


# ---- Rogue Amendiares - Preem Solo
@on("steal", "rogue-amendiares-preem-solo")
def _rogue_steal(g, me, ev):
    p = g.controller(me)
    a = ev["actor"]
    if face_up_or_field(g, me) and ev["player"] == p and g.d(a).type == "legend":
        if ev["gig"][1] % 2 == 0:
            g.trigger(me, [draw(1)])
        else:
            g.trigger(me, [discard(1, who="rival")])


# ---- Royce - Psycho on the Edge
@static("power", "royce-psycho-on-the-edge")
def _royce(g, me, uid):
    if uid == me and g.cards[me].zone == "field" and g.turn_player == g.controller(me):
        return 2 * len(g.cards[me].gears)
    return 0


# ---- Saburo Arasaka - Stubborn Patriarch
@static("power", "saburo-arasaka-stubborn-patriarch")
def _saburo(g, me, uid):
    a = g.attack
    if a and a["atk"] == uid and g.controller(uid) == g.controller(me) and g.has_tag(uid, "ARASAKA"):
        return 1
    return 0


# ---- Sasha Yakovleva - Won't Let You Down
@step("sasha_attack")
def _sasha(g, ctx):
    p = ctx["p"]
    deck = g.players[p].deck
    if not deck:
        return None
    u = deck[-1]
    g.move(u, "hand")
    if g.cards[ctx["src"]].zone == "field":
        g.give_power(ctx["src"], g.d(u).cost or 0)


self_trigger("attack", "sasha-yakovleva-won-t-let-you-down", S("sasha_attack"))
self_trigger("defeated", "sasha-yakovleva-won-t-let-you-down", discard(1, who="rival"))


# ---- V - Streetkid
@step("v_streetkid")
def _v_streetkid(g, ctx):
    g.trash_top(ctx["p"], 3)
    return [S("choose", kind="target", cands=("trash", (("tag", "BRAINDANCE"), ("program",))), key="t"),
            S("_to_hand_from_trash")]


@step("_to_hand_from_trash")
def _to_hand_from_trash(g, ctx, key="t"):
    t = ctx.get(key)
    if t and t != ("none",):
        g.move(pick_uid(g, ctx, ctx["p"], "trash", t[1]), "hand")


call_trigger("v-streetkid", S("v_streetkid"))


# ---- Viktor Vektor - Sit Down and Relax
@step("viktor_call")
def _viktor_call(g, ctx):
    p = ctx["p"]
    deck = g.players[p].deck
    top = list(reversed(deck[-5:]))
    gears = [u for u in top if g.d(u).type == "gear" and (g.d(u).cost or 0) <= 2]
    take = gears[:2]       # taking cheap Gear is never worse than leaving it
    for u in take:
        g.move(u, "hand")
    g.bottom_deck([u for u in top if u not in take])


call_trigger("viktor-vektor-sit-down-and-relax", S("viktor_call"))
note("viktor-vektor-sit-down-and-relax", "Automatically takes the first 2 eligible Gears.")


# ---- Wakako Okada - Peace and Harmony
call_trigger("wakako-okada-peace-and-harmony",
             S("mode", labels=("weaken", "draw")),
             S("branch", key="mode", cases=(
                 ("weaken", (choose_unit("t", "rival"), S("power", key="t", n=-2))),
                 ("draw", (draw(1),)))))
ability("wakako-okada-peace-and-harmony", "decrease", [S("adjust", amount=2, mode="down")],
        targets=lambda g, me: any(v > 1 for pl in g.players for s, v in pl.gigs))


# ---- Yorinobu Arasaka - Embracing Destruction
@on("attack", "yorinobu-arasaka-embracing-destruction")
def _yori_attack(g, me, ev):
    p = g.controller(me)
    a = ev["uid"]
    if face_up_or_field(g, me) and g.controller(a) == p and g.has_tag(a, "ARASAKA"):
        if not g.turn_flags.get(("yori", me)):
            g.turn_flags[("yori", me)] = True
            g.trigger(me, [draw(1), S("yori_discard")])


@step("yori_discard")
def _yori_discard(g, ctx):
    c = g.street_cred(ctx["p"])
    if c is None or c < 20:
        return [discard(1)]
