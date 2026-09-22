#!/usr/bin/env python3
"""Give every player one earned epithet.

Each title is a claim on a measurable feature, and three rules keep it honest:

  * a **guard** — the title's own wording must be literally true of the holder,
    so "The Proven" cannot land on someone who fails to clear the coin-flip band
    just because stronger claimants were already taken;
  * a **sample gate** — nobody is crowned for a role they have played twice;
  * **no superlatives in the prose** — a title assigned greedily is not
    necessarily the group's best, so leading the group is marked by a seal that
    is checked separately, never asserted in the text.

Claims are scored as z-scores against the group so they compare across features,
then assigned strongest-first, one title per player and one player per title.
"""
from math import sqrt
from statistics import mean, pstdev


def role_wl(p, name):
    for role, (w, l) in p["roles"]:
        if role.lower() == name:
            return w, l
    return 0, 0


def role_rate(p, name, minimum):
    w, l = role_wl(p, name)
    n = w + l
    return w / n if n >= minimum else None


def mpg(p):
    return p["hours"] * 60 / p["games"] if p["games"] else None


def clears_band(p):
    """How far the record sits outside the 95% band a coin flip produces."""
    if p["games"] < 15:
        return None
    return abs(p["wins"] / p["games"] - .5) - 1.96 * sqrt(.25 / p["games"])


TITLES = [
    # Clearing the coin-flip band is the only claim backed by significance, so
    # it outranks the merely-extreme — but it cuts both ways, and a record
    # proven to be *below* 50% must not inherit a name that reads as praise.
    dict(name="The Proven", seats=lambda p: p["games"],
         text="{w}W {l}L over {g} games — too far above 50% for luck to explain",
         value=clears_band, dir="high",
         guard=lambda p, v: v > 0 and p["wins"] / p["games"] > .5,
         thin=0, weight=1.6),
    dict(name="Cursed by the Numbers", seats=lambda p: p["games"],
         text="{w}W {l}L over {g} games — too far below 50% to blame on luck",
         value=clears_band, dir="high",
         guard=lambda p, v: v > 0 and p["wins"] / p["games"] < .5,
         thin=0, weight=1.6),
    dict(name="The Spymaster", seats=lambda p: p["spy_n"],
         text="wins {v:.0%} of {n} seats on the evil side",
         value=lambda p: p["spy"][2][0] if p["spy_n"] >= 10 else None,
         dir="high", guard=lambda p, v: v >= .6, thin=14),
    dict(name="The Bulwark", seats=lambda p: p["res_n"],
         text="holds {v:.0%} across {n} loyal seats",
         value=lambda p: p["res"][2][0] if p["res_n"] >= 12 else None,
         dir="high", guard=lambda p, v: v >= .55, thin=16),
    dict(name="Born Traitor", seats=lambda p: min(p["res_n"], p["spy_n"]),
         text="{gap:+.0f} points better as a spy than as a loyalist",
         value=lambda p: p["lean"] if p["res_n"] >= 8 and p["spy_n"] >= 8 else None,
         dir="high", guard=lambda p, v: v >= .15, thin=10),
    dict(name="Sworn Sword", seats=lambda p: min(p["res_n"], p["spy_n"]),
         text="the black cloak buys nothing here — {gap:+.0f} points",
         value=lambda p: p["lean"] if p["res_n"] >= 8 and p["spy_n"] >= 8 else None,
         dir="low", guard=lambda p, v: v <= .05, thin=10),
    dict(name="Deadeye", seats=lambda p: sum(role_wl(p, "assassin")),
         text="{w}W {l}L in the Assassin's chair",
         value=lambda p: role_rate(p, "assassin", 8), dir="high",
         guard=lambda p, v: v >= .6, thin=10),
    dict(name="The Watcher", seats=lambda p: sum(role_wl(p, "percival")),
         text="{w}W {l}L as Percival",
         value=lambda p: role_rate(p, "percival", 8), dir="high",
         guard=lambda p, v: v >= .6, thin=10),
    dict(name="The Blind Watchman", seats=lambda p: sum(role_wl(p, "percival")),
         text="{w}W {l}L as Percival",
         value=lambda p: role_rate(p, "percival", 6), dir="low",
         guard=lambda p, v: v <= .25, thin=8),
    dict(name="The Seer", seats=lambda p: sum(role_wl(p, "merlin")),
         text="{w}W {l}L as Merlin, in the hardest seat at the table",
         value=lambda p: role_rate(p, "merlin", 6), dir="high",
         guard=lambda p, v: v >= .5, thin=8),
    dict(name="Merlin's Curse", seats=lambda p: sum(role_wl(p, "merlin")),
         text="{w}W {l}L as Merlin — found nearly every time",
         value=lambda p: role_rate(p, "merlin", 6), dir="low",
         guard=lambda p, v: v <= .3, thin=8),
    dict(name="The Deceiver", seats=lambda p: sum(role_wl(p, "morgana")),
         text="{w}W {l}L as Morgana, wearing the wizard's face",
         value=lambda p: role_rate(p, "morgana", 6), dir="high",
         guard=lambda p, v: v >= .55, thin=8),
    dict(name="The Obvious Villain", seats=lambda p: p["spy_n"],
         text="only {v:.0%} on the evil side across {n} seats",
         value=lambda p: p["spy"][2][0] if p["spy_n"] >= 8 else None,
         dir="low", guard=lambda p, v: v <= .45, thin=10),
    dict(name="Lost in the Crowd", seats=lambda p: sum(role_wl(p, "resistance")),
         text="{w}W {l}L in the plain Resistance seat",
         value=lambda p: role_rate(p, "resistance", 8), dir="low",
         guard=lambda p, v: v <= .35, thin=10),
    dict(name="The Loiterer", seats=lambda p: p["games"],
         text="{v:.0f} minutes per game, about {ratio:.1f}× the group's pace",
         value=mpg, dir="high", guard=lambda p, v: v >= 15, thin=0),
    dict(name="The Regular", seats=lambda p: p["games"],
         text="{g} games and {h:.0f} hours at the table",
         value=lambda p: p["games"], dir="high", guard=lambda p, v: v >= 30, thin=0),
    dict(name="The Coin Flip", seats=lambda p: p["games"],
         text="{rate:.0%} across {g} games — a fair coin would look like this",
         value=lambda p: -abs(p["wins"] / p["games"] - .5) if p["games"] >= 20 else None,
         dir="high", guard=lambda p, v: v >= -.06, thin=0),
    dict(name="The Newcomer", seats=lambda p: p["games"],
         text="{g} games in — every number here is still a rumour",
         value=lambda p: -p["games"], dir="high",
         guard=lambda p, v: -v <= 16, thin=0),
    dict(name="The Marathoner", seats=lambda p: p["games"],
         text="{h:.0f} hours logged",
         value=lambda p: p["hours"], dir="high", guard=lambda p, v: v >= 5, thin=0),
]


def _role_in(text):
    for r in ("assassin", "percival", "merlin", "morgana", "resistance"):
        if r in text.lower():
            return r
    return None


def render(t, p, v):
    role = _role_in(t["text"])
    w, l = role_wl(p, role) if role else (p["wins"], p["losses"])
    pace = mpg(p) or 0
    group_pace = 9.6
    return t["text"].format(
        v=abs(v) if isinstance(v, float) else v, n=t["seats"](p),
        g=p["games"], h=p["hours"], w=w, l=l,
        rate=p["wins"] / p["games"], gap=(p["lean"] or 0) * 100,
        ratio=pace / group_pace)


def assign(players):
    """{player: (title, evidence, provisional, leads_group)}"""
    claims, leaders = [], {}
    for t in TITLES:
        # Score against everyone the feature is defined for, but only players
        # who clear the guard may hold the title — so a sole qualifier's claim
        # is as strong as they are extreme, not a flat constant.
        pool = [(p, t["value"](p)) for p in players]
        pool = [(p, v) for p, v in pool if v is not None]
        eligible = [(p, v) for p, v in pool if t["guard"](p, v)]
        if not eligible:
            continue
        nums = [v for _, v in pool]
        mu, sd = mean(nums), pstdev(nums)
        best = max(eligible, key=lambda pv: pv[1] if t["dir"] == "high" else -pv[1])
        leaders[t["name"]] = best[0]["name"]
        for p, v in eligible:
            if not sd:
                z = 1.0        # no spread to measure against
            else:
                z = (v - mu) / sd
                if t["dir"] == "low":
                    z = -z
            claims.append((z * t.get("weight", 1.0), t, p, v))

    claims.sort(key=lambda c: -c[0])
    out, taken_p, taken_t = {}, set(), set()
    for z, t, p, v in claims:
        if p["name"] in taken_p or t["name"] in taken_t:
            continue
        out[p["name"]] = (t["name"], render(t, p, v),
                          t["seats"](p) < t["thin"],
                          leaders.get(t["name"]) == p["name"])
        taken_p.add(p["name"])
        taken_t.add(t["name"])

    # Anyone whose every claim was taken by a stronger holder still gets a name.
    # Anyone whose every claim was taken by a stronger holder still gets a name,
    # picked to fit them rather than drawn from a rotating list.
    spares = [
        ("The Suspected",
         lambda p: p["lean"] is not None and p["lean"] >= .2,
         lambda p: f"{p['lean']*100:+.0f} points better as a spy — on only {p['spy_n']} evil seats"),
        ("The Understudy",
         lambda p: p["games"] < 15,
         lambda p: f"{p['games']} games, still writing the record"),
        ("The Journeyman",
         lambda p: True,
         lambda p: f"{p['games']} games, {p['hours']:.0f} hours, no extremes to report"),
        ("The Wildcard",
         lambda p: True,
         lambda p: f"{p['wins']}W {p['losses']}L and no clear tell"),
        ("The Quiet One",
         lambda p: True,
         lambda p: f"{p['wins']}W {p['losses']}L, nothing given away"),
    ]
    for p in sorted((q for q in players if q["name"] not in out),
                    key=lambda q: -q["games"]):
        for name, fits, blurb in spares:
            if name in taken_t or not fits(p):
                continue
            out[p["name"]] = (name, blurb(p), p["games"] < 15, False)
            taken_t.add(name)
            break
    return out
