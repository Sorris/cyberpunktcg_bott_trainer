"""Program scripts (34 cards). A Program's text resolves when it is played (4.14)."""
from __future__ import annotations

from ..effects import STOP, Ask, S, lasting_static, note, on_global, program, static, step
from .common import choose_unit, discard, draw, pick_uid, when


def _units_all(g):
    return [u for pl in g.players for u in pl.field]


# ---- Don't Fear the Reaper: Spend all rival Units. Then, defeat a spent Unit.
@step("reaper")
def _reaper(g, ctx):
    for u in g.units(1 - ctx["p"]):
        g.spend(u, "effect")
    return [choose_unit("t", "any", [("spent",)]), S("defeat", key="t")]


program("don-t-fear-the-reaper", S("reaper"))

# ---- Afterparty at Lizzie's
program("afterparty-at-lizzie-s", S("adjust", amount=1), S("afterparty2"))


@step("afterparty2")
def _afterparty2(g, ctx):
    if len({v for _, v in g.players[ctx["p"]].gigs}) >= 2:
        g.draw(ctx["p"], 1)


# ---- All is Lost
program("all-is-lost", S("trash_n_pick", n=3, ctype="unit"))


# ---- Appetite for Destruction
@step("appetite")
def _appetite(g, ctx):
    g.add_lasting({"kind": "appetite", "p": ctx["p"], "until": "eot", "used": False})


program("appetite-for-destruction", S("appetite"))


@on_global("fight_result")
def appetite_hook(g, ev):
    for L in g.lasting:
        if L["kind"] == "appetite" and not L["used"]:
            for w in ev["winners"]:
                if g.controller(w) == L["p"] and ev["margin"][w] >= 3 and g.players[1 - L["p"]].gigs:
                    L["used"] = True
                    g.trigger(w, [S("appetite_steal")], p=L["p"])
                    return


@step("appetite_steal")
def _appetite_steal(g, ctx):
    p = ctx["p"]
    actor = ctx["src"]
    gigs = g.players[1 - p].gigs
    opts = sorted({("gig", s, v) for s, v in gigs})
    if not opts:
        return None
    return [S("_ask_opts", kind="steal", opts=tuple(opts), key="sg"), S("_steal_chosen")]


@step("_steal_chosen")
def _steal_chosen(g, ctx, actor_key="src"):
    _, s, v = ctx["sg"]
    p = ctx["p"]
    g.steal_by_effect(ctx[actor_key], p, g.find_gig(1 - p, s, v))


# ---- Bonnie and Clyde
@step("bonnie")
def _bonnie(g, ctx):
    steps = [choose_unit("t1", "rival", [("power_le", 4)]), S("defeat", key="t1")]
    if g.gig_count(1 - ctx["p"]) >= g.gig_count(ctx["p"]) + 2:
        steps += [S("_may", what="second", key="two"),
                  when(("ctx", "two"), choose_unit("t2", "rival", [("power_le", 4)]), S("defeat", key="t2"))]
    return steps


program("bonnie-and-clyde", S("bonnie"))


# ---- Bootleg Black Sapphire Show
@step("sell_top")
def _sell_top(g, ctx):
    deck = g.players[ctx["p"]].deck
    if deck:
        g.sell(ctx["p"], deck[-1])


@step("even_and_odd_draw2")
def _eo(g, ctx):
    vals = [v for _, v in g.players[ctx["p"]].gigs]
    if any(v % 2 == 0 for v in vals) and any(v % 2 for v in vals):
        g.draw(ctx["p"], 2)


program("bootleg-black-sapphire-show", S("sell_top"), S("even_and_odd_draw2"))
note("bootleg-black-sapphire-show", "Selling by effect does not use the once-per-turn Sell action "
     "(5.8.2.3, confirmed by Henry).")


# ---- Carnage at the Colosseum
@static("self_cost", "carnage-at-the-colosseum")
def _carnage_cost(g, me, p, cost):
    return cost - len(g.gigs_at_least(p, 8))


program("carnage-at-the-colosseum", choose_unit("t", "rival", [("power_lt_a_friendly",)]), S("defeat", key="t"))


# ---- Chrome Reverie
@step("cant_attack_until")
def _cant_attack_until(g, ctx, key="t"):
    t = ctx.get(key)
    if t:
        g.add_lasting({"kind": "cant_attack", "p": ctx["p"], "unit": t[1], "until": "next_turn"})


@lasting_static("cant_attack", "cant_attack")
def _ca(g, L, uid):
    return L["unit"] == uid


program("chrome-reverie", choose_unit("t", "rival"), S("cant_attack_until"), when("min_gig", S("call_free")))

# ---- Corporate Surveillance
program("corporate-surveillance", choose_unit("t", "rival", [("cost_le", 4), ("ready",)]), S("spend_target", key="t"))


# ---- Cyberpsychosis
@step("cyberpsychosis")
def _cyber(g, ctx):
    t = ctx.get("t")
    if t:
        g.give_power(t[1], 3 * len(g.cards[t[1]].gears))
        g.add_lasting({"kind": "cyberpsychosis", "p": ctx["p"], "unit": t[1], "until": "eot"})


program("cyberpsychosis", choose_unit("t", "any", [("equipped",)]), S("cyberpsychosis"))


@on_global("turn_end")
def cyberpsychosis_end(g, ev):
    for L in list(g.lasting):
        if L["kind"] == "cyberpsychosis":
            u = L["unit"]
            if g.cards[u].zone == "field" and (g.turn_flags.get(("stole", u)) or g.turn_flags.get(("fought", u))):
                g.trigger(u, g.defeat_steps(u), p=L["p"])


# ---- Detonate
program("detonate", S("choose", kind="target", cands=("gears", "rival", (("power_le", 2),)), key="t"),
        S("defeat_gear"))


@step("defeat_gear")
def _defeat_gear(g, ctx, key="t"):
    t = ctx.get(key)
    if t and t != ("none",):
        g.defeat_now(t[1])


# ---- Floor It
program("floor-it", choose_unit("t", "rival"), S("power", key="t", n=-1), draw(1))


# ---- Fool on the Hill
@step("fool")
def _fool(g, ctx):
    p = ctx["p"]
    top = list(g.players[p].deck[-2:])
    ctx["_top"] = top
    if not top:
        return None
    return [S("_ask_opts", kind="fool", opts=("hand", "trash"), key="f", who=1 - p), S("_fool_do")]


@step("_fool_do")
def _fool_do(g, ctx):
    p = ctx["p"]
    if ctx["f"] == "hand":
        for u in ctx["_top"]:
            g.move(u, "hand")
    else:
        for u in ctx["_top"]:
            g.move(u, "trash")
        g.draw(p, 2)


program("fool-on-the-hill", S("fool"))


# ---- Gunpoint Diplomacy
@step("gunpoint")
def _gunpoint(g, ctx):
    t = ctx.get("t")
    if not t:
        return None
    if g.cred_cmp(ctx["p"]) < 0:
        return [S("_ask_opts", kind="mode", opts=("ready_attack", "power"), key="m", who=1 - ctx["p"]),
                S("_gunpoint_do")]
    ctx["m"] = "both"
    return [S("_gunpoint_do")]


@step("_gunpoint_do")
def _gunpoint_do(g, ctx):
    u = ctx["t"][1]
    m = ctx["m"]
    if m in ("both", "ready_attack"):
        g.add_lasting({"kind": "attack_ready_once", "p": ctx["p"], "unit": u, "until": "eot"})
    if m in ("both", "power"):
        g.give_power(u, 3)


@lasting_static("can_attack_ready", "attack_ready_once")
def _aro(g, L, uid, target):
    return L["unit"] == uid


program("gunpoint-diplomacy", choose_unit("t", "friendly"), S("gunpoint"))
note("gunpoint-diplomacy", "'The next time this Unit attacks' lasts until it attacks or the turn ends.")


# ---- Industrial Assembly
program("industrial-assembly", S("adjust", amount=4, mode="up"), when("gig8", draw(1)))


# ---- Les É Lé Mens: bottom-deck a Rival's lowest-power Unit
@step("lowest_power")
def _lowest(g, ctx):
    us = g.units(1 - ctx["p"])
    if not us:
        return None
    lo = min(g.power(u) for u in us)
    return [choose_unit("t", "rival", [("power_eq", lo)]), S("bottom_target", key="t")]


program("les-e-le-mens", S("lowest_power"))


# ---- Live with the Aftermath
@step("aftermath")
def _aftermath(g, ctx):
    p = ctx["p"]
    tp = g.turn_player
    steps = []
    for who in (tp, 1 - tp):                       # turn player chooses first (10.33)
        if g.units(who):
            key = f"a{who}"
            steps += [S("_ask_opts", kind="defeat_own", opts=tuple(("unit", u) for u in g.units(who)), key=key,
                        who=who), S("defeat", key=key)]
    return steps


program("live-with-the-aftermath", S("aftermath"))


# ---- Memory Relapse
program("memory-relapse", choose_unit("t", "rival", [("ready",)]), S("spend_target", key="t"),
        S("no_ready"), when("cred_even", draw(1)))

# ---- Nocturne Op55 N1


@static("self_cost", "nocturne-op55-n1")
def _nocturne_cost(g, me, p, cost):
    return 1 if not g.players[p].fixer else cost


@step("nocturne_solo")
def _nocturne_solo(g, ctx):
    g.add_lasting({"kind": "solo_discount", "p": ctx["p"], "until": "eot"})


@lasting_static("cost", "solo_discount")
def _solo_disc(g, L, p, uid, cost):
    if p == L["p"] and g.d(uid).type == "legend":
        return cost - 2
    return cost


program("nocturne-op55-n1",
        S("mode", labels=("draw2", "no_attack", "solo")),
        S("branch", key="mode", cases=(
            ("draw2", (draw(2),)),
            ("no_attack", (choose_unit("t", "any"), S("cant_attack_until"))),
            ("solo", (S("nocturne_solo"),)))))


# ---- Over the Edge
@step("over_edge")
def _over_edge(g, ctx):
    d20 = [v for s, v in g.players[ctx["p"]].gigs if s == 20]
    if not d20:
        return None
    return [choose_unit("t", "any", [("power_le", max(d20))]), S("defeat", key="t")]


program("over-the-edge", S("over_edge"))


# ---- Peace Offering
@step("peace")
def _peace(g, ctx):
    gigs = [(o, s, v) for o in (0, 1) for s, v in g.players[o].gigs]
    opts = set()
    for o, s, v in gigs:
        for o2, s2, v2 in gigs:
            if (o, s, v) != (o2, s2, v2) and v2 != v and v2 <= s:
                opts.add(("set", o, s, v, v2))
    if not opts:
        return None
    return [S("_ask_opts", kind="set_gig", opts=tuple([("none",)] + sorted(opts)), key="st"), S("_peace_do")]


@step("_peace_do")
def _peace_do(g, ctx):
    st = ctx["st"]
    if st != ("none",):
        _, o, s, v, nv = st
        g.set_gig(o, g.find_gig(o, s, v), nv, by=ctx["p"])
    if g.value_pairs(ctx["p"]):
        g.draw(ctx["p"], 1)


program("peace-offering", S("peace"))


# ---- Pyramid Song
@step("pyramid")
def _pyramid(g, ctx):
    both = any(s == 4 and v == 1 for s, v in g.players[ctx["p"]].gigs)
    weaken = [choose_unit("t", "rival"), S("power", key="t", n=-4)]
    bottom = [choose_unit("b", "rival", [("power_eq", 0)]), S("bottom_target", key="b")]
    if both:
        return weaken + bottom
    return [S("mode", labels=("weaken", "bottom")),
            S("branch", key="mode", cases=(("weaken", tuple(weaken)), ("bottom", tuple(bottom))))]


program("pyramid-song", S("pyramid"))


# ---- Reboot Optics: the next time a rival Unit fights this turn, it doesn't defeat the opposing friendly Unit
@step("reboot")
def _reboot(g, ctx):
    g.add_lasting({"kind": "reboot", "p": ctx["p"], "until": "eot", "used": False})


@lasting_static("no_fight_defeat", "reboot")
def _reboot_static(g, L, loser, other):
    if L["used"] or g.controller(loser) != L["p"] or g.controller(other) == L["p"]:
        return False
    L["used"] = True
    return True


@on_global("fight_result")
def _reboot_used_up(g, ev):
    # The next fight between a rival Unit and a friendly Unit uses it up, even if the
    # friendly Unit would have survived anyway (Henry, 8 Nov 2026).
    a, d = ev["atk"], ev["dfn"]
    for L in g.lasting:
        if L.get("kind") == "reboot" and not L["used"]:
            if (g.controller(a) == L["p"]) != (g.controller(d) == L["p"]):
                L["used"] = True


program("reboot-optics", S("reboot"))
note("reboot-optics", "Used up by the next fight between a rival Unit and a friendly Unit this turn, "
     "whether or not the friendly Unit would have been defeated.")


# ---- Safety Override: the next time a friendly Unit loses a fight this turn, defeat the opposing rival Unit
@step("safety")
def _safety(g, ctx):
    g.add_lasting({"kind": "safety", "p": ctx["p"], "until": "eot", "used": False})


program("safety-override", S("safety"))


@on_global("fight_result")
def safety_hook(g, ev):
    for L in g.lasting:
        if L["kind"] == "safety" and not L["used"]:
            for loser in ev["losers"]:
                if g.controller(loser) == L["p"]:
                    other = ev["dfn"] if loser == ev["atk"] else ev["atk"]
                    L["used"] = True
                    if g.controller(other) != L["p"]:
                        g.pending.append([L["p"], tuple(g.defeat_steps(other, by=loser)), {"p": L["p"], "src": None}])
                    return


# ---- Shattered Memories
@step("shattered")
def _shattered(g, ctx):
    total = 0
    tp = g.turn_player
    for who in (tp, 1 - tp):
        for u in list(g.players[who].hand):
            g.move(u, "trash")
            total += 1
    ctx["total"] = total
    steps = []
    for who in (tp, 1 - tp):
        steps += [S("_ask_opts", kind="may:draw5", opts=(True, False), key=f"d{who}", who=who),
                  S("_shattered_draw", who=who)]
    steps.append(S("_shattered_bonus"))
    return steps


@step("_shattered_draw")
def _shattered_draw(g, ctx, who):
    if ctx.get(f"d{who}"):
        g.draw(who, 5)


@step("_shattered_bonus")
def _shattered_bonus(g, ctx):
    if any(v == ctx["total"] for _, v in g.players[ctx["p"]].gigs):
        g.draw(ctx["p"], 2)


program("shattered-memories", S("shattered"))


# ---- Synapse Burnout
@step("synapse")
def _synapse(g, ctx):
    t = ctx.get("t")
    if t:
        g.add_lasting({"kind": "synapse", "p": ctx["p"], "unit": t[1], "until": "eot"})


@lasting_static("power", "synapse")
def _synapse_power(g, L, uid):
    a = g.attack
    if L["unit"] != uid or not a or not a.get("fighting"):
        return 0
    if a["atk"] == uid or a["target"] == ("unit", uid):
        return sum(1 for u in g.players[L["p"]].legends if g.cards[u].face_up)
    return 0


program("synapse-burnout", choose_unit("t", "friendly"), S("synapse"))


# ---- Take Control
@step("take_control")
def _take_control(g, ctx):
    t = ctx.get("t")
    if t:
        g.add_lasting({"kind": "steal_minus", "p": ctx["p"], "unit": t[1], "until": "eot"})
        if any(g.has_tag(t[1], x) for x in ("AI", "DRONE", "VEHICLE")):
            g.draw(ctx["p"], 1)


@lasting_static("steal_count", "steal_minus")
def _steal_minus(g, L, atk):
    return -1 if L["unit"] == atk else 0


program("take-control", choose_unit("t", "rival"), S("take_control"))


# ---- The Heist
@step("heist")
def _heist(g, ctx):
    return [S("trash_n_pick", n=4, ctype="gear"), S("_heist2")]


@step("_heist2")
def _heist2(g, ctx):
    u = ctx.get("taken")
    p = ctx["p"]
    if u is None:
        return None
    if any(v == (g.d(u).cost or 0) for _, v in g.players[p].gigs) and g.equip_targets(p):
        ctx["heist_card"] = u
        return [S("_may", what="play_free", key="ok"), S("_heist_play")]


@step("_heist_play")
def _heist_play(g, ctx):
    if ctx.get("ok") and g.cards[ctx["heist_card"]].zone == "hand":
        g.play_free(ctx["p"], ctx["heist_card"])


program("the-heist", S("heist"))
note("the-heist", "Adds the Gear to hand, then offers to play it for free.")


# ---- Three Mouths, One Desire
@step("three_mouths")
def _three(g, ctx):
    p = ctx["p"]
    top = list(g.players[p].deck[-3:])
    ctx["_top"] = top
    ctx["_n"] = min(len(top), 1 + len(g.min_gigs(p)))
    ctx["_taken"] = []
    return [S("_three_pick")]


@step("_three_pick")
def _three_pick(g, ctx):
    left = [u for u in ctx["_top"] if u not in ctx["_taken"]]
    if len(ctx["_taken"]) >= ctx["_n"] or not left:
        g.bottom_deck(left)
        return None
    opts = sorted({("card", g.cards[u].cid) for u in left})
    if ctx["_taken"]:
        opts = [("none",)] + opts
    return [S("_ask_opts", kind="target", opts=tuple(opts), key="tm"), S("_three_take")]


@step("_three_take")
def _three_take(g, ctx):
    a = ctx["tm"]
    left = [u for u in ctx["_top"] if u not in ctx["_taken"]]
    if a == ("none",):
        ctx["_n"] = len(ctx["_taken"])
    else:
        u = next(u for u in left if g.cards[u].cid == a[1])
        g.move(u, "hand")
        ctx["_taken"].append(u)
    return [S("_three_pick")]


program("three-mouths-one-desire", S("three_mouths"))


# ---- Towerfall
@step("towerfall")
def _towerfall(g, ctx):
    both = g.cred_cmp(ctx["p"]) < 0
    weaken = [S("all_rival_power", n=-5)]
    bottom = [S("bottom_rival_zero")]
    if both:
        return weaken + bottom
    return [S("mode", labels=("weaken", "bottom")),
            S("branch", key="mode", cases=(("weaken", tuple(weaken)), ("bottom", tuple(bottom))))]


@step("all_rival_power")
def _arp(g, ctx, n):
    for u in g.units(1 - ctx["p"]):
        g.give_power(u, n)


@step("bottom_rival_zero")
def _brz(g, ctx):
    us = [u for u in g.units(1 - ctx["p"]) if g.power(u) == 0]
    if us:
        g.bottom_deck(us)


program("towerfall", S("towerfall"))

# ---- Trust No One
program("trust-no-one", S("adjust", amount=3, mode="down"), when("min_gig", draw(1)))


# ---- Unlikely Bond
@step("unlikely")
def _unlikely(g, ctx):
    return [choose_unit("f", "friendly", [("ready",)]), S("_unlikely2")]


@step("_unlikely2")
def _unlikely2(g, ctx):
    f = ctx.get("f")
    if f:
        g.bottom_deck([f[1]])
        return [choose_unit("t", "rival", [("spent",)]), S("bottom_target", key="t")]


program("unlikely-bond", S("unlikely"))


# ---- We Gotta Live Together
@static("self_cost", "we-gotta-live-together")
def _wglt_cost(g, me, p, cost):
    return 3 if g.gig_count(1 - p) >= g.gig_count(p) + 2 else cost


@step("wglt")
def _wglt(g, ctx):
    return [S("choose", kind="target", cands=("trash", (("type", "unit"), ("cost_le", 3))), key="t1",
              optional=True), S("_wglt_play", key="t1"),
            S("choose", kind="target", cands=("trash", (("type", "unit"), ("cost_le", 3))), key="t2",
              optional=True), S("_wglt_play", key="t2")]


@step("_wglt_play")
def _wglt_play(g, ctx, key):
    t = ctx.get(key)
    if t and t != ("none",):
        uid = pick_uid(g, ctx, ctx["p"], "trash", t[1])
        g.move(uid, "field", ctx["p"])
        c = g.cards[uid]
        c.spent = False
        c.lag = True
        g.emit("play", player=ctx["p"], uid=uid)
        g.emit("played_unit", player=ctx["p"], uid=uid)


program("we-gotta-live-together", S("wglt"))

# ---- Wild in the Streets
program("wild-in-the-streets", choose_unit("t", "any", [("spent",)]), S("defeat", key="t"))

