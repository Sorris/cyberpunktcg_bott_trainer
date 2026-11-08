"""Card-effect framework.

Card scripts (``cpbot/scripts/*.py``) plug into the engine in four ways:

1. **Triggers** — ``@on("play", "card-slug")``. The handler runs when the
   event happens and usually calls ``g.trigger(me, steps, ctx)`` to make an
   effect *pending* (rules 10.11-10.16). Pending effects resolve at the next
   open game state, turn player's first (10.13).

2. **Effects as steps** — an effect is a tuple of steps ``(name, params)``.
   The engine runs them in order with a shared ``ctx`` dict. A step may
   return:
       None           continue with the next step
       Ask(...)       pause for a player decision; the answer lands in ctx[key]
       STOP           end the effect early
       [steps...]     run these steps next (for loops and branches)
   Steps and ctx are plain data, so a game can be cloned mid-effect.

3. **Statics** — persistent effects (10.22) queried by the engine, e.g.
   ``@static("power", slug)`` returns a power bonus a card gives to a Unit.

4. **Activated abilities** — ``ability(slug, ...)`` registers a Spend-icon
   or paid effect, optionally Quick (usable in the React Step).

Lasting effects created by Programs and triggers ("this turn", "until your
next turn") are dicts in ``g.lasting``; ``@lasting_static(kind, lkind)``
teaches the engine what each one does.
"""
from __future__ import annotations

from collections import defaultdict, namedtuple

Ask = namedtuple("Ask", "player kind options key")
STOP = "STOP"

STEPS: dict = {}
TRIGGERS = defaultdict(list)       # (event, slug) -> [fn(g, me, ev)]
GLOBAL = defaultdict(list)         # event -> [fn(g, ev)] for lasting effects from Programs
STATICS = defaultdict(list)        # (kind, slug) -> [fn]
LASTING = defaultdict(list)        # (kind, lasting kind) -> [fn(g, L, *args)]
STATIC_KINDS = defaultdict(set)    # kind -> slugs with a static of that kind (fast skip)
ABILITIES = defaultdict(list)      # slug -> [Ability]
PROGRAMS = {}                      # slug -> steps for the Program's own text
SCRIPTED: set = set()
CANDS: dict = {}                   # name -> fn(g, ctx, *args) -> iterable of options
CONDS: dict = {}                   # name -> fn(g, ctx, *args) -> bool
NOTES: dict = {}                   # slug -> interpretation notes for humans


class Ability:
    def __init__(self, slug, name, steps, eddies=0, spend=True, quick=False,
                 condition=None, zone=None, targets=None):
        self.slug, self.name, self.steps = slug, name, tuple(steps)
        self.eddies, self.spend, self.quick = eddies, spend, quick
        self.condition = condition          # fn(g, me) -> bool, extra activation conditions
        self.zone = zone                    # None = wherever the card's text is active
        self.targets = targets              # fn(g, me) -> bool: has a legal target (10.8)


# ------------------------------------------------------------- registration
def step(name):
    def deco(fn):
        assert name not in STEPS, name
        STEPS[name] = fn
        return fn
    return deco


def on(event, *slugs):
    def deco(fn):
        for s in slugs:
            TRIGGERS[(event, s)].append(fn)
            SCRIPTED.add(s)
        return fn
    return deco


def on_global(event):
    def deco(fn):
        GLOBAL[event].append(fn)
        return fn
    return deco


def static(kind, *slugs):
    def deco(fn):
        for s in slugs:
            STATICS[(kind, s)].append(fn)
            STATIC_KINDS[kind].add(s)
            SCRIPTED.add(s)
        return fn
    return deco


def cands(name):
    def deco(fn):
        CANDS[name] = fn
        return fn
    return deco


def cond(name):
    def deco(fn):
        CONDS[name] = fn
        return fn
    return deco


def lasting_static(kind, lkind):
    def deco(fn):
        LASTING[(kind, lkind)].append(fn)
        return fn
    return deco


def ability(slug, name, steps, **kw):
    ABILITIES[slug].append(Ability(slug, name, steps, **kw))
    SCRIPTED.add(slug)


def program(slug, *steps, note=None):
    PROGRAMS[slug] = tuple(steps)
    SCRIPTED.add(slug)
    if note:
        NOTES[slug] = note


def vanilla(*slugs):
    """Cards with no effect text (flavour only) or keywords the engine handles."""
    SCRIPTED.update(slugs)


def note(slug, text):
    NOTES[slug] = text


def S(name, **params):
    """Build one step."""
    return (name, params)


# ------------------------------------------------------------ the registry
class Registry:
    """What the engine calls. Separate object so tests can swap it."""

    def active_cards(self, g):
        """Cards whose text is currently active: field cards, face-up Legends in
        the Legends area, and Gear equipped to either (3.4.1, 10.22.3)."""
        cached = g.__dict__.get("_active")
        if cached is not None:
            return cached
        out = []
        for pl in g.players:
            for u in pl.field:
                out.append(u)
                out.extend(g.cards[u].gears)
            for u in pl.legends:
                c = g.cards[u]
                if c.face_up:
                    out.append(u)
                    out.extend(c.gears)
                else:
                    out.extend(c.gears)   # Gear on a face-down Legend can't happen, harmless
        return out

    # ---- triggers
    def on_event(self, g, event, ev):
        for fn in GLOBAL.get(event, ()):
            fn(g, ev)
        seen = set()
        cands = self.active_cards(g)
        extra = []
        for k in ("uid", "src"):
            if k in ev and ev[k] is not None:
                extra.append(ev[k])
        if event == "defeated":
            extra.extend(ev.get("snapshot", {}).get("gears", []))
        for u in cands + extra:
            if u in seen:
                continue
            seen.add(u)
            fns = TRIGGERS.get((event, g.db[g.cards[u].cid].slug))
            if fns:
                for fn in fns:
                    fn(g, u, ev)

    # ---- statics
    def _statics(self, g, kind):
        slugs = STATIC_KINDS.get(kind)
        if not slugs:
            return ()
        out = []
        db, cards = g.db, g.cards
        for u in self.active_cards(g):
            s = db[cards[u].cid].slug
            if s in slugs:
                for fn in STATICS[(kind, s)]:
                    out.append((u, fn))
        return out

    def _lasting(self, g, kind):
        for L in g.lasting:
            for fn in LASTING.get((kind, L["kind"]), ()):
                yield L, fn

    def static_power(self, g, uid) -> int:
        total = 0
        for me, fn in self._statics(g, "power"):
            total += fn(g, me, uid) or 0
        for L, fn in self._lasting(g, "power"):
            total += fn(g, L, uid) or 0
        return total

    def grants_keyword(self, g, uid, kw) -> bool:
        for me, fn in self._statics(g, "keyword"):
            if fn(g, me, uid, kw):
                return True
        for L, fn in self._lasting(g, "keyword"):
            if fn(g, L, uid, kw):
                return True
        return False

    def flag(self, g, kind, *args) -> bool:
        """Generic yes/no persistent effects, e.g. 'cant_attack', 'cant_ready'."""
        for me, fn in self._statics(g, kind):
            if fn(g, me, *args):
                return True
        for L, fn in self._lasting(g, kind):
            if fn(g, L, *args):
                return True
        return False

    def modify_cost(self, g, p, uid, cost) -> int:
        if cost is None:
            return 0
        base = cost
        slug = g.db[g.cards[uid].cid].slug
        # the card's own text ("Play this Unit for -1 for each ...")
        for fn in STATICS.get(("self_cost", slug), ()):
            cost = fn(g, uid, p, cost)
        for me, fn in self._statics(g, "cost"):
            cost = fn(g, me, p, uid, cost)
        for L, fn in self._lasting(g, "cost"):
            cost = fn(g, L, p, uid, cost)
        if cost < base:
            cost = max(1, cost)                     # 11.11.3
        return max(0, cost)

    def steal_count_mod(self, g, atk) -> int:
        n = 0
        for L, fn in self._lasting(g, "steal_count"):
            n += fn(g, L, atk) or 0
        return n

    def may_steal_gig(self, g, atk, gig) -> bool:
        return not self.flag(g, "cant_steal_gig", atk, gig)

    # ---- activated abilities
    def activated_options(self, g, p, reaction: bool):
        opts = []
        pl = g.players[p]
        cands = [u for u in pl.field] + [u for u in pl.legends if g.cards[u].face_up]
        for host in cands:
            for src in [host] + g.cards[host].gears:
                for i, ab in enumerate(ABILITIES.get(g.db[g.cards[src].cid].slug, ())):
                    if reaction and not ab.quick:
                        continue
                    if g.can_activate(p, host, src, ab):
                        opts.append(("activate", src, i))
        return opts

    def ability(self, g, src, i) -> Ability:
        return ABILITIES[g.db[g.cards[src].cid].slug][i]

    def program_steps(self, g, uid):
        return PROGRAMS.get(g.db[g.cards[uid].cid].slug, ())


REGISTRY = Registry()


def load_scripts():
    from .scripts import gear, legends, programs, units  # noqa: F401


# ================================================================ generic steps
# These cover the common wordings so card scripts stay short.

def _who(g, ctx, who):
    p = ctx["p"]
    return {"me": p, "rival": 1 - p}[who]


@step("draw")
def _draw(g, ctx, n=1, who="me", n_key=None):
    n = ctx.get(n_key, n) if n_key else n
    g.draw(_who(g, ctx, who), n)


@step("discard")
def _discard(g, ctx, who="me", n=1, filt=None, key="discarded", optional=False):
    """Ask a player to discard n cards (one at a time)."""
    p = _who(g, ctx, who)
    done = ctx.setdefault(key, [])
    if len(done) >= n or ctx.get(key + "_declined"):
        return None
    hand = [u for u in g.players[p].hand if filt is None or g.filter_ok(ctx, u, filt)]
    if not hand:
        return None
    opts = sorted({("card", g.cards[u].cid) for u in hand})
    if optional:
        opts = [("none",)] + opts
    return [S("_discard_ask", who=who, key=key, opts=tuple(opts)), S("_discard_do", who=who, key=key),
            S("discard", who=who, n=n, filt=filt, key=key, optional=optional)]


@step("_discard_ask")
def _discard_ask(g, ctx, who, key, opts):
    return Ask(_who(g, ctx, who), "discard", list(opts), "_ans")


@step("_discard_do")
def _discard_do(g, ctx, who, key):
    a = ctx.pop("_ans")
    if a == ("none",):
        ctx[key + "_declined"] = True
        return None
    p = _who(g, ctx, who)
    uid = next(u for u in g.players[p].hand if g.cards[u].cid == a[1])
    g.move(uid, "trash")
    g.emit("discard", player=p, uid=uid)
    ctx[key].append(uid)


@step("choose")
def _choose(g, ctx, kind, cands, key, chooser="me", optional=False):
    """Pick one option from a list computed by a candidate function name."""
    opts = list(g.candidates(ctx, cands))
    if not opts:
        ctx[key] = None
        return None
    if optional:
        opts = [("none",)] + opts
    return Ask(_who(g, ctx, chooser), kind, opts, key)


@step("power")
def _power(g, ctx, key, n, dur="turn"):
    t = ctx.get(key)
    if t and t != ("none",):
        u = t[1]
        if g.cards[u].zone == "field" or g.cards[u].zone == "legends":
            g.give_power(u, n, dur)


@step("defeat")
def _defeat_step(g, ctx, key=None, uid=None):
    t = ctx.get(key) if key else ("unit", uid)
    if t and t != ("none",):
        return g.defeat_steps(t[1])


@step("spend_target")
def _spend_target(g, ctx, key):
    t = ctx.get(key)
    if t and t != ("none",):
        g.spend(t[1], "effect")


@step("bottom_target")
def _bottom_target(g, ctx, key):
    t = ctx.get(key)
    if t and t != ("none",) and g.cards[t[1]].zone in ("field", "legends"):
        g.bottom_deck([t[1]])


@step("adjust")
def _adjust(g, ctx, amount, mode="any", upto=True, who="any", key="adjusted", exact=False):
    """'Increase/Decrease/Adjust a Gig by (up to) N'. One choice: which Gig and its new value."""
    opts = g.gig_adjust_options(ctx["p"], amount, mode, upto, who, exact)
    if not opts:
        ctx[key] = None
        return None
    if upto:
        opts = [("none",)] + opts
    return [S("_adjust_ask", opts=tuple(opts)), S("_adjust_do", key=key)]


@step("_adjust_ask")
def _adjust_ask(g, ctx, opts):
    return Ask(ctx["p"], "adjust", list(opts), "_ans")


@step("_adjust_do")
def _adjust_do(g, ctx, key):
    a = ctx.pop("_ans")
    if a == ("none",):
        ctx[key] = None
        return
    _, owner, sides, value, new = a
    idx = g.find_gig(owner, sides, value)
    g.set_gig(owner, idx, new, by=ctx["p"])
    ctx[key] = (owner, sides, new)


@step("call_free")
def _call_free(g, ctx, optional=True):
    p = ctx["p"]
    if g.can_call(p):
        if optional:
            return [S("_may", what="call_free", key="_ans"), S("_call_free_do")]
        g.call_legend(p)


@step("_call_free_do")
def _call_free_do(g, ctx):
    if ctx.pop("_ans", False) and g.can_call(ctx["p"]):
        g.call_legend(ctx["p"])


@step("_may")
def _may(g, ctx, what, key, who="me"):
    return Ask(_who(g, ctx, who), "may:" + what, [True, False], key)


@step("lasting")
def _lasting(g, ctx, **L):
    L = dict(L)
    L.setdefault("p", ctx["p"])
    for k, v in list(L.items()):
        if isinstance(v, str) and v.startswith("$"):
            t = ctx.get(v[1:])
            L[k] = t[1] if isinstance(t, tuple) and len(t) > 1 else t
    g.add_lasting(L)


@step("if")
def _if(g, ctx, cond, then=(), orelse=()):
    return list(then) if g.cond(ctx, cond) else list(orelse)


@step("mode")
def _mode(g, ctx, labels, key="mode"):
    return Ask(ctx["p"], "mode", list(labels), key)


@step("branch")
def _branch(g, ctx, key, cases):
    v = ctx.get(key)
    for label, steps in cases:
        if label == v:
            return list(steps)
    return None
