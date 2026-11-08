"""Unit scripts (73 cards)."""
from __future__ import annotations

from ..effects import STOP, Ask, S, ability, lasting_static, note, on, on_global, static, step, vanilla
from .common import choose_unit, discard, draw, pick_uid, self_trigger, when

vanilla("animals-wrecker", "emergency-atlus", "psycho-squad", "riding-nomad", "rockn-rockerboy",
        "secondhand-bombus")


def on_field(g, me):
    return g.cards[me].zone == "field"


def mine(g, me, p):
    return g.controller(me) == p


def play_trigger(slug, *steps):
    self_trigger("play", slug, *steps)


def attack_trigger(slug, *steps):
    self_trigger("attack", slug, *steps)


def defeated_trigger(slug, *steps):
    self_trigger("defeated", slug, *steps)


def end_of_turn(slug, *steps):
    @on("turn_end", slug)
    def _h(g, me, ev):
        if on_field(g, me) and ev["player"] == g.controller(me):
            g.trigger(me, steps)


@step("ready_src")
def _ready_src(g, ctx):
    if g.cards[ctx["src"]].zone in ("field", "legends"):
        g.ready(ctx["src"])


# ---- 6th Street Recruits
@on("steal", "6th-street-recruits")
def _sixth(g, me, ev):
    if on_field(g, me) and ev["player"] == g.controller(me) and ev["gig"][0] == 6:
        g.trigger(me, [S("adjust", amount=6, mode="up")])


# ---- Adam Smasher - Metal Over Meat
@step("defeat_all_other")
def _defeat_all_other(g, ctx):
    steps = []
    for pl in g.players:
        for u in list(pl.field):
            if u != ctx["src"]:
                steps.extend(g.defeat_steps(u))
    return steps


play_trigger("adam-smasher-metal-over-meat", S("defeat_all_other"))


# ---- Alt Cunningham - Mother of Daemons (steal prevention is in the engine)
@on("spent", "alt-cunningham-mother-of-daemons")
def _alt_spent(g, me, ev):
    u = ev["uid"]
    p = g.controller(me)
    if on_field(g, me) and g.controller(u) == p and g.cards[u].gears and g.d(u).type in ("unit", "legend"):
        g.trigger(me, [draw(1)])


# ---- Augmented Negotiators
@on("blocker_used", "augmented-negotiators")
def _aug(g, me, ev):
    if ev["uid"] == me:
        g.trigger(me, [discard(1, who="rival")])


# ---- Caliber - Totentanz's Top Dog
play_trigger("caliber-totentanz-s-top-dog", choose_unit("t", "rival", [("cost_le", 2)]), S("defeat", key="t"))


@step("caliber_defeated")
def _caliber(g, ctx):
    return [discard(1, who="rival", key="d1"), S("_caliber2")]


@step("_caliber2")
def _caliber2(g, ctx):
    d = [x for x in ctx.get("d1", []) if x is not None]
    if d and any(v == (g.d(d[0]).cost or 0) for _, v in g.players[ctx["p"]].gigs):
        return [discard(1, who="rival", key="d2")]


defeated_trigger("caliber-totentanz-s-top-dog", S("caliber_defeated"))


# ---- Chrome Fang
@step("chrome_fang")
def _chrome_fang(g, ctx):
    g.add_lasting({"kind": "steal_cap_power", "p": ctx["p"], "until": "next_turn"})


@lasting_static("cant_steal_gig", "steal_cap_power")
def _cf(g, L, atk, gig):
    return g.controller(atk) != L["p"] and gig[1] > g.power(atk) and any(x is gig for x in g.players[L["p"]].gigs)


play_trigger("chrome-fang", S("chrome_fang"))


# ---- Corpo Security / Misty: can't attack
@static("cant_attack", "corpo-security", "misty-olszewski-mender-of-broken-spirits")
def _cant_attack(g, me, uid):
    return uid == me


# ---- Delamain Rideshare AI
play_trigger("delamain-rideshare-ai", draw(2))


# ---- Delamain Cab
@step("if_stole_ready_eddie")
def _cab(g, ctx):
    if g.turn_flags.get(("stole", ctx["src"])):
        return [S("ready_eddies", n=1)]


end_of_turn("delamain-cab", S("if_stole_ready_eddie"))


# ---- Dexter DeShawn - One Last Chance
play_trigger("dexter-deshawn-one-last-chance", S("adjust", amount=1))
attack_trigger("dexter-deshawn-one-last-chance", S("adjust", amount=1))


@step("dexter_defeated")
def _dexter_def(g, ctx):
    a, b = g.street_cred(ctx["p"]), g.street_cred(1 - ctx["p"])
    if abs((a or 0) - (b or 0)) >= 10:
        g.draw(ctx["p"], 2)


defeated_trigger("dexter-deshawn-one-last-chance", S("dexter_defeated"))
note("dexter-deshawn-one-last-chance", "Null Street Cred is treated as 0 for the difference.")


# ---- El Sombrerón - La Venganza Lenta
@step("sombreron")
def _sombreron(g, ctx):
    p = ctx["p"]
    mx = g.max_gigs(p)
    if not mx or not g.can_pay(p, 2):
        return None
    return [S("_may", what="pay2", key="ok"), S("_sombreron_do")]


@step("_sombreron_do")
def _sombreron_do(g, ctx):
    if ctx.get("ok"):
        p = ctx["p"]
        for u in (g.ready_eddies(p) + g.pay_sources(p))[:2]:
            g.spend(u, "pay")
        best = max(v for _, v in g.max_gigs(p)) if g.max_gigs(p) else 0
        if on_field(g, ctx["src"]):
            g.give_power(ctx["src"], best)


attack_trigger("el-sombrero-n-la-venganza-lenta", S("sombreron"))


# ---- Evelyn Parker - Scheming Siren
attack_trigger("evelyn-parker-scheming-siren", draw(1), when("more_cred", discard(1)))


# ---- Field Operator
play_trigger("field-operator", when("cred_even", draw(1)))


# ---- Gilded Matón
play_trigger("gilded-mato-n",
             S("choose", kind="defeat_gear", cands=("gears", "friendly"), key="g", optional=True),
             S("gilded_do"))


@step("gilded_do")
def _gilded(g, ctx):
    t = ctx.get("g")
    if t and t != ("none",):
        g.defeat_now(t[1])
        return [choose_unit("t", "rival", [("cost_le", 3)]), S("defeat", key="t")]


# ---- Goro Takemura - Losing His Way
@step("goro_lhw")
def _goro_lhw(g, ctx):
    p = ctx["p"]
    if all(g.cards[u].face_up for u in g.players[p].legends) and on_field(g, ctx["src"]):
        g.give_power(ctx["src"], 5)


attack_trigger("goro-takemura-losing-his-way", S("goro_lhw"))


# ---- Hacked Corpo / All is Lost style: trash N, add one of a type from among them
@step("trash_n_pick")
def _trash_n_pick(g, ctx, n, ctype):
    got = g.trash_top(ctx["p"], n)
    ctx["_among"] = got
    opts = sorted({("card", g.cards[u].cid) for u in got if g.d(u).type == ctype})
    if not opts:
        return None
    return [S("_ask_opts", kind="target", opts=tuple(opts), key="t"), S("_take_among")]


@step("_take_among")
def _take_among(g, ctx):
    t = ctx.get("t")
    if t:
        u = next(u for u in ctx["_among"] if g.cards[u].cid == t[1] and g.cards[u].zone == "trash")
        g.move(u, "hand")
        ctx["taken"] = u


play_trigger("hacked-corpo", S("trash_n_pick", n=3, ctype="program"))


# ---- Hanako Arasaka - In a Gilded Cage
@step("hanako_cage")
def _hanako_cage(g, ctx):
    p = ctx["p"]
    deck = g.players[p].deck
    top = list(deck[-4:])
    vals = {v for _, v in g.players[p].gigs}
    take = [u for u in top if (g.d(u).cost or 0) in vals]
    for u in take:
        g.move(u, "hand")
    g.bottom_deck([u for u in top if u not in take])


play_trigger("hanako-arasaka-in-a-gilded-cage", S("hanako_cage"))
note("hanako-arasaka-in-a-gilded-cage", "Takes every matching card automatically.")


# ---- Heywood Ripperdoc
play_trigger("heywood-ripperdoc",
             S("choose", kind="defeat_gear", cands=("gears", "any"), key="g", optional=True),
             S("heywood_do"))


@step("heywood_do")
def _heywood(g, ctx):
    t = ctx.get("g")
    if t and t != ("none",):
        cost = g.d(t[1]).cost or 0
        g.defeat_now(t[1])
        if any(v == cost for _, v in g.players[ctx["p"]].gigs):
            g.draw(ctx["p"], 1)


# ---- Jacked-In Voodoo Boy
@static("cant_attack", "jacked-in-voodoo-boy")
def _voodoo(g, me, uid):
    return uid == me and not g.turn_flags.get(("programs_played", g.controller(me)))


# ---- Jackie Welles - Ride or Die Choom
@step("jackie_rod_attack")
def _jrod(g, ctx):
    n = sum(1 for _, v in g.players[ctx["p"]].gigs if v % 2 == 0)
    if on_field(g, ctx["src"]):
        g.give_power(ctx["src"], 2 * n)


@step("jackie_rod_defeated")
def _jrod_def(g, ctx):
    g.draw(ctx["p"], sum(1 for _, v in g.players[ctx["p"]].gigs if v % 2 == 1))


attack_trigger("jackie-welles-ride-or-die-choom", S("jackie_rod_attack"))
defeated_trigger("jackie-welles-ride-or-die-choom", S("jackie_rod_defeated"))


# ---- Japantown Jonin
play_trigger("japantown-jonin", S("give_power_choice", n=2))


# ---- Johnny Silverhand - Never Stop Fighting
@static("wins_fight", "johnny-silverhand-never-stop-fighting")
def _johnny_wins(g, me, uid, other):
    return uid == me and g.has_tag(other, "CORPO")


@on("fight_result", "johnny-silverhand-never-stop-fighting")
def _johnny_ready(g, me, ev):
    if me in ev["winners"] and not g.turn_flags.get(("johnny_ready", me)):
        g.turn_flags[("johnny_ready", me)] = True
        g.trigger(me, [S("ready_src")])


# ---- Judy Álvarez - Nothing to Doubt
@step("judy_reveal")
def _judy_reveal(g, ctx):
    p = ctx["p"]
    deck = g.players[p].deck
    if not deck:
        return None
    u = deck[-1]
    ctx["judy"] = u
    dd = g.d(u)
    playable = dd.type in ("unit", "program") or (dd.type == "gear" and g.equip_targets(p))
    if playable:
        return [S("_may", what="play_free", key="ok"), S("_judy_do")]
    g.draw(p, 1)


@step("_judy_do")
def _judy_do(g, ctx):
    u = ctx["judy"]
    if ctx.get("ok"):
        g.play_free(ctx["p"], u)
    else:
        g.draw(ctx["p"], 1)


ability("judy-a-lvarez-nothing-to-doubt", "reveal", [S("judy_reveal")], eddies=1,
        targets=lambda g, me: bool(g.players[g.controller(me)].deck))


# ---- Kerry Eurodyne - The Last Rockerboy
ability("kerry-eurodyne-the-last-rockerboy", "draw 2", [when("gig8", draw(2))])


# ---- La Llorona
@on("blocker_used", "la-llorona-ghost-of-the-past")
def _llorona(g, me, ev):
    if ev["uid"] == me:
        g.trigger(me, [S("adjust", amount=3, mode="up")])


# ---- Lizzy Wizzy
@step("lizzy")
def _lizzy(g, ctx):
    return [S("choose", kind="target", cands=("hand_or_trash", (("program",), ("cost_le", 3))), key="t",
              optional=True), S("_lizzy_do")]


@step("_lizzy_do")
def _lizzy_do(g, ctx):
    t = ctx.get("t")
    if t and t != ("none",):
        zone, cid = t
        g.play_free(ctx["p"], pick_uid(g, ctx, ctx["p"], zone, cid), bottom_after=True)


play_trigger("lizzy-wizzy-delicate-weapon", S("lizzy"))


# ---- MT0D12 Flathead
@static("unblockable", "mt0d12-flathead")
def _flathead(g, me, uid):
    return uid == me and g.cred_cmp(g.controller(me)) < 0


# ---- Maelstrom Goons
@on("steal", "maelstrom-goons")
def _goons(g, me, ev):
    if ev["actor"] == me and g.cards[me].gears:
        g.trigger(me, [discard(1, who="rival")])


# ---- Maelstrom Zealots
@on("fight_result", "maelstrom-zealots")
def _zealots(g, me, ev):
    if me in ev["losers"]:
        other = ev["dfn"] if ev["atk"] == me else ev["atk"]
        if g.controller(other) != g.controller(me):
            g.trigger(me, g.defeat_steps(other, by=me))


# ---- Maman Brigitte
@step("maman")
def _maman(g, ctx):
    p = ctx["p"]
    progs = [u for u in g.players[p].hand if g.d(u).type == "program"]
    targets = [u for u in g.units(1 - p) if not g.cards[u].gears]
    if len(progs) < 2 or not targets:
        return None
    return [S("_may", what="discard2", key="ok"), S("_maman_do")]


@step("_maman_do")
def _maman_do(g, ctx):
    if ctx.get("ok"):
        return [S("discard", n=2, filt=("program",), key="mm"),
                choose_unit("t", "rival", [("unequipped",)]), S("bottom_target", key="t")]


play_trigger("maman-brigitte-spirit-of-death", S("maman"))


# ---- MaxTac AV
@step("maybe_swap")
def _maybe_swap(g, ctx):
    p = ctx["p"]
    if g.players[p].gigs and g.players[1 - p].gigs:
        return [S("_may", what="swap", key="ok"), when(("ctx", "ok"), S("swap_choice"))]


play_trigger("maxtac-av", S("maybe_swap"))


# ---- self cost reductions
@static("self_cost", "maxtac-heavy")
def _heavy(g, me, p, cost):
    return cost - len(g.units(1 - p))


@static("self_cost", "octant")
def _octant(g, me, p, cost):
    return cost - len(g.gigs_at_least(p, 8))


@static("self_cost", "trauma-team-operatives")
def _ttops(g, me, p, cost):
    return cost - sum(1 for u in g.players[p].trash if g.d(u).type == "unit")


# ---- MaxTac Squadron
@step("squadron")
def _squadron(g, ctx):
    if g.cards[ctx["src"]].spent:
        return [S("choose", kind="target", cands=("face_up_legends",), key="t"), S("_ready_t")]


@step("_ready_t")
def _ready_t(g, ctx, key="t"):
    t = ctx.get(key)
    if t and t != ("none",):
        g.ready(t[1])


end_of_turn("maxtac-squadron", S("squadron"))


# ---- MaxTac Suppression Team
@static("cant_attack", "maxtac-suppression-team")
def _suppression(g, me, uid):
    c = g.cards[uid]
    return g.controller(uid) != g.controller(me) and c.entered_turn == g.turn_no


# ---- Meredith Stout
@static("power", "meredith-stout-stone-cold-corpo")
def _meredith(g, me, uid):
    a = g.attack
    if uid != me or not a or not a.get("fighting"):
        return 0
    other = a["target"][1] if a["atk"] == me else a["atk"]
    if a["target"] == ("unit", me) or a["atk"] == me:
        return 2 if g.d(other).type == "legend" else 0
    return 0


@on("gig_changed", "meredith-stout-stone-cold-corpo")
def _meredith_adj(g, me, ev):
    p = g.controller(me)
    if on_field(g, me) and ev["owner"] == p and ev.get("by") == 1 - p:
        g.trigger(me, [S("choose", kind="target", cands=("trash",), key="t", optional=True),
                       S("_to_hand_from_trash")])


@on("gig_swapped", "meredith-stout-stone-cold-corpo")
def _meredith_swap(g, me, ev):
    p = g.controller(me)
    if on_field(g, me) and ev["p"] == 1 - p:
        g.trigger(me, [S("choose", kind="target", cands=("trash",), key="t", optional=True),
                       S("_to_hand_from_trash")])


# ---- Minotaur
play_trigger("minotaur", when("more_cred", choose_unit("t", "rival", [("power_le", 5)]), S("defeat", key="t")))


# ---- Misty Olszewski
@step("misty")
def _misty(g, ctx):
    return [S("_ask_opts", kind="card_type", opts=("unit", "gear", "program"), key="ty"), S("_misty_do")]


@step("_misty_do")
def _misty_do(g, ctx):
    p = ctx["p"]
    deck = g.players[p].deck
    if not deck:
        return None
    u = deck[-1]
    if g.d(u).type == ctx["ty"]:
        g.move(u, "hand")
        return [S("ready_eddies", n=1)]
    g.move(u, "trash")


end_of_turn("misty-olszewski-mender-of-broken-spirits", S("misty"))


# ---- Modded Kusanagi
@step("return_src_to_hand")
def _ret(g, ctx):
    if on_field(g, ctx["src"]):
        g.move(ctx["src"], "hand")


end_of_turn("modded-kusanagi", S("return_src_to_hand"))


# ---- Modded Muramasa
end_of_turn("modded-muramasa", when("less_cred", S("ready_src")))


# ---- Mox Inciters
play_trigger("mox-inciters", choose_unit("t", "rival"), S("must_attack", key="t"))


# ---- Nadia
@static("lag_attack_ok", "nadia-fighting-through-grief")
def _nadia(g, me, uid, target):
    p = g.controller(me)
    return uid == me and target == ("gigs",) and g.gig_count(1 - p) > g.gig_count(p)


# ---- Offduty Malfini
@step("malfini")
def _malfini(g, ctx):
    if on_field(g, ctx["src"]):
        g.spend(ctx["src"], "effect")
    return [choose_unit("t", "rival", [("ready",)]), S("spend_target", key="t")]


play_trigger("offduty-malfini", S("malfini"))


# ---- Pacifica Netrunner
@step("no_ready")
def _no_ready(g, ctx, key="t"):
    t = ctx.get(key)
    if t:
        g.add_lasting({"kind": "cant_ready", "p": ctx["p"], "unit": t[1], "until": "next_turn"})


@lasting_static("cant_ready", "cant_ready")
def _cant_ready(g, L, uid):
    return L["unit"] == uid


play_trigger("pacifica-netrunner", when("cred_even", choose_unit("t", "rival"), S("no_ready")))


# ---- Panam Palmer - Strength Through Family
@static("free_call", "panam-palmer-strength-through-family")
def _panam_free(g, me, p):
    return g.controller(me) == p and g.turn_player == p


@step("panam_attack")
def _panam_attack(g, ctx):
    return [discard(1), S("_panam_attack2")]


@step("_panam_attack2")
def _panam_attack2(g, ctx):
    if [x for x in ctx.get("discarded", []) if x is not None]:
        g.draw(ctx["p"], sum(1 for u in g.players[ctx["p"]].legends if g.cards[u].face_up))


attack_trigger("panam-palmer-strength-through-family", S("panam_attack"))


# ---- Pepe Najarro
@step("pepe")
def _pepe(g, ctx):
    p = ctx["p"]
    if not g.value_pairs(p):
        return None
    mercs = [u for u in g.players[p].legends if g.cards[u].face_up and g.has_tag(u, "MERC") and g.cards[u].spent]
    for u in mercs[:2]:
        g.ready(u)


attack_trigger("pepe-najarro-working-doubles", S("pepe"))
note("pepe-najarro-working-doubles", "Only face-up Legends count as MERC (face-down cards have no tags).")


# ---- Placide
@step("placide")
def _placide(g, ctx):
    p = ctx["p"]
    if not any(g.d(u).type == "program" for u in g.players[p].hand) or not g.units(1 - p):
        return None
    return [S("discard", n=1, filt=("program",), optional=True, key="pd"), S("_placide2")]


@step("_placide2")
def _placide2(g, ctx):
    if [x for x in ctx.get("pd", []) if x is not None]:
        return [choose_unit("t", "rival"), S("bottom_target", key="t")]


play_trigger("placide-voodoo-sentinel", S("placide"))
attack_trigger("placide-voodoo-sentinel", S("placide"))


# ---- Rita Wheeler
@on("spent", "rita-wheeler-no-stupid-questions")
def _rita(g, me, ev):
    if ev["uid"] == me and not g.turn_flags.get(("rita", me)):
        g.turn_flags[("rita", me)] = True
        g.trigger(me, [draw(1), discard(1)])


# ---- Rogue Amendiares - Queen of the Afterlife
@on("steal", "rogue-amendiares-queen-of-the-afterlife")
def _rogue_q(g, me, ev):
    a = ev["actor"]
    if (on_field(g, me) and a != me and g.controller(a) == g.controller(me)
            and ev["gig"][1] < g.power(a) and not g.turn_flags.get(("rogueq", me))):
        g.turn_flags[("rogueq", me)] = True
        g.trigger(me, [S("ready_eddies", n=2)])


@step("rogue_drain")
def _rogue_drain(g, ctx):
    t = ctx.get("t")
    if t:
        g.give_power(t[1], -g.power(ctx["src"]))


ability("rogue-amendiares-queen-of-the-afterlife", "drain", [choose_unit("t", "rival"), S("rogue_drain")],
        eddies=2, quick=True, targets=lambda g, me: bool(g.units(1 - g.controller(me))))


# ---- Royce - Don't Call Me Simon
@step("royce_simon")
def _royce_simon(g, ctx):
    n = 3 if g.cred_cmp(ctx["p"]) > 0 else 2
    return [choose_unit("t", "rival", [("power_le", n)]), S("defeat", key="t")]


play_trigger("royce-don-t-call-me-simon", S("royce_simon"))


# ---- Ruthless Lowlife
@static("cant_attack_target", "ruthless-lowlife")
def _lowlife(g, me, uid, target):
    return uid == me and target == ("gigs",)


# ---- Sandayu Oda
@step("sandayu")
def _sandayu(g, ctx):
    n = g.value_pairs(ctx["p"])
    steps = []
    for i in range(n):
        steps += [choose_unit(f"s{i}", "rival", [("ready",)]), S("spend_target", key=f"s{i}")]
    return steps


play_trigger("sandayu-oda-hanako-s-guardian", S("sandayu"))


@static("lag_attack_ok", "sandayu-oda-hanako-s-guardian")
def _sandayu_lag(g, me, uid, target):
    return uid == me and target[0] == "unit"


# ---- Saul Bright
@static("power", "saul-bright-stormrider")
def _saul(g, me, uid):
    a = g.attack
    if a and a["atk"] == uid and uid != me and g.controller(uid) == g.controller(me):
        return 2
    return 0


@step("saul_ready")
def _saul_ready(g, ctx):
    spent = [u for u in g.units(ctx["p"]) if g.cards[u].spent]
    spent.sort(key=lambda u: -g.power(u))
    for u in spent[:3]:
        g.ready(u)


end_of_turn("saul-bright-stormrider", S("saul_ready"))
note("saul-bright-stormrider", "Readies the 3 highest-power spent Units automatically.")


# ---- Screw
defeated_trigger("screw-lovelorn-fool",
                 S("choose", kind="target", cands=("trash", (("type", "unit"), ("not_src",))), key="t",
                   optional=False), S("_to_hand_from_trash"))


# ---- Sketchy Ripper
@step("sketchy")
def _sketchy(g, ctx):
    p = ctx["p"]
    top = list(g.players[p].deck[-3:])
    ctx["_top"] = top
    opts = sorted({("card", g.cards[u].cid) for u in top if g.d(u).type == "gear"})
    if not opts:
        g.bottom_deck(top)
        return None
    return [S("_ask_opts", kind="target", opts=tuple([("none",)] + opts), key="t"), S("_sketchy_do")]


@step("_sketchy_do")
def _sketchy_do(g, ctx):
    t = ctx["t"]
    top = ctx["_top"]
    take = None
    if t != ("none",):
        take = next(u for u in top if g.cards[u].cid == t[1])
        g.move(take, "hand")
    g.bottom_deck([u for u in top if u != take])


attack_trigger("sketchy-ripper", S("sketchy"))


# ---- Swordwise Huscle
@step("swordwise")
def _swordwise(g, ctx):
    if on_field(g, ctx["src"]) and g.power(ctx["src"]) >= 5:
        g.draw(ctx["p"], 1)


attack_trigger("swordwise-huscle", S("swordwise"))


# ---- T-Bug
defeated_trigger("t-bug-amateur-philosopher", S("call_choose_known"), S("_call_known_do"))


# ---- Tyger's Whisper
play_trigger("tyger-s-whisper", S("call_free"))


# ---- V - Roamer of the Badlands
@on("steal", "v-roamer-of-the-badlands")
def _vroamer(g, me, ev):
    if ev["actor"] == me:
        g.trigger(me, [S("increase_gig", n=5)], gig=ev["gig"])


@step("increase_gig")
def _increase_gig(g, ctx, n):
    gig = ctx["gig"]
    p = ctx["p"]
    owner = next((o for o in (0, 1) if any(x is gig for x in g.players[o].gigs)), None)
    if owner is None or gig[1] >= gig[0]:
        return None
    opts = [("value", v) for v in range(gig[1], min(gig[0], gig[1] + n) + 1)]
    return [S("_ask_opts", kind="increase", opts=tuple(opts), key="iv"), S("_increase_do")]


@step("_increase_do")
def _increase_do(g, ctx):
    gig = ctx["gig"]
    nv = ctx["iv"][1]
    owner = next((o for o in (0, 1) if any(x is gig for x in g.players[o].gigs)), None)
    if owner is not None and nv != gig[1]:
        idx = next(i for i, x in enumerate(g.players[owner].gigs) if x is gig)
        g.set_gig(owner, idx, nv, by=ctx["p"])


@step("vroamer_end")
def _vroamer_end(g, ctx):
    if len(g.gigs_at_least(ctx["p"], 8)) >= 2:
        g.draw(ctx["p"], 1)


end_of_turn("v-roamer-of-the-badlands", S("vroamer_end"))


# ---- Valentino Guerrera
@static("can_attack_ready", "valentino-guerrera")
def _guerrera(g, me, uid, target):
    return uid == me and g.has_kw(target, "blocker") and g.cred_cmp(g.controller(me)) > 0


# ---- Valentino Street Racer
@step("grant_adrenaline")
def _grant_adr(g, ctx, key="t"):
    t = ctx.get(key)
    if t:
        g.add_lasting({"kind": "grant_kw", "p": ctx["p"], "unit": t[1], "kw": "adrenaline", "until": "eot"})


play_trigger("valentino-street-racer", choose_unit("t", "friendly", [("not_src",), ("cost_le", 5)]),
             S("grant_adrenaline"))


# ---- Viktor Vektor - Drop Your Illusions
@static("cost", "viktor-vektor-drop-your-illusions")
def _viktor_cost(g, me, p, uid, cost):
    if (g.controller(me) == p and g.d(uid).type == "gear" and "CYBERWARE" in g.d(uid).tags
            and not g.turn_flags.get(("cyberware_played", p))):
        return cost - 3
    return cost


# ---- Viktor Vektor - You Might Feel a Little Pinch
@step("viktor_pinch")
def _pinch(g, ctx):
    p = ctx["p"]
    others = [u for u in g.units(p) if u != ctx["src"]]
    opts = sorted({("card", g.cards[u].cid) for u in g.players[p].trash
                   if g.d(u).type == "gear" and "CYBERWARE" in g.d(u).tags and (g.d(u).cost or 0) <= 2})
    if not opts or not others:
        return None
    return [S("_ask_opts", kind="target", opts=tuple(opts), key="t"), S("_pinch_do")]


@step("_pinch_do")
def _pinch_do(g, ctx):
    uid = pick_uid(g, ctx, ctx["p"], "trash", ctx["t"][1])
    g.play_free(ctx["p"], uid, equip_only_other=ctx["src"])


play_trigger("viktor-vektor-you-might-feel-a-little-pinch", S("viktor_pinch"))


# ---- Westbrook Netrunner
@step("westbrook")
def _westbrook(g, ctx):
    g.add_lasting({"kind": "legend_steal_floor", "p": ctx["p"], "until": "next_turn"})


@lasting_static("cant_steal_gig", "legend_steal_floor")
def _wb(g, L, atk, gig):
    return (g.controller(atk) != L["p"] and g.d(atk).type == "legend" and gig[1] < g.power(atk)
            and any(x is gig for x in g.players[L["p"]].gigs))


play_trigger("westbrook-netrunner", S("westbrook"))


# ---- Wraith Marauders
@on("steal", "wraith-marauders")
def _wraith(g, me, ev):
    if ev["actor"] == me:
        g.trigger(me, [choose_unit("t", "friendly", [("not_src",), ("power_eq", ev["gig"][1])]), S("_ready_t")])


# ---- Yorinobu Arasaka - Steel Dragon
@step("yori_dragon")
def _yori_dragon(g, ctx):
    return [S("choose", kind="target", cands=("hand_or_trash", (("type", "unit"), ("cost_le", 4))), key="t",
              optional=True), S("_yori_dragon_do")]


@step("_yori_dragon_do")
def _yori_dragon_do(g, ctx):
    t = ctx.get("t")
    if t and t != ("none",):
        uid = pick_uid(g, ctx, ctx["p"], t[0], t[1])
        g.add_lasting({"kind": "lag_attack_units", "p": ctx["p"], "unit": uid, "until": "eot"})
        g.play_free(ctx["p"], uid)


@lasting_static("lag_attack_ok", "lag_attack_units")
def _lau(g, L, uid, target):
    return L["unit"] == uid and target[0] == "unit"


play_trigger("yorinobu-arasaka-steel-dragon", S("yori_dragon"))


@on_global("defeated")
def _count_arasaka_defeats(g, ev):
    snap = ev.get("snapshot", {})
    if snap.get("zone") == "field" and "ARASAKA" in snap.get("tags", []):
        g.turn_flags["arasaka_defeats"] = g.turn_flags.get("arasaka_defeats", 0) + 1


@on("defeated", "yorinobu-arasaka-steel-dragon")
def _yori_draw(g, me, ev):
    # Only the first ARASAKA Unit defeated in the whole turn counts, even if it was
    # defeated before Yorinobu entered play (ruling from Henry, 8 Nov 2026).
    # Yorinobu himself counts: if he is that first ARASAKA Unit, he still draws.
    snap = ev.get("snapshot", {})
    if (snap.get("zone") == "field" and "ARASAKA" in snap.get("tags", [])
            and g.turn_flags.get("arasaka_defeats") == 1):
        if ev["uid"] == me:
            g.trigger(me, [draw(1)], p=snap["controller"])
        elif on_field(g, me):
            g.trigger(me, [draw(1)])
