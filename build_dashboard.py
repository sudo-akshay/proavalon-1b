#!/usr/bin/env python3
"""Render stats.db into a self-contained dashboard.html.

Artifact CSP blocks fetch(), so all data is inlined at build time and the
markup is rendered here rather than in JS — the page reads correctly even if
its one tooltip script never runs.
"""
import json
import sqlite3
from datetime import datetime
from string import Template

import titles as titles_mod
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "stats.db"
OUT = ROOT / "dashboard.html"

RES_ROLES = {"resistance", "merlin", "percival", "isolde", "tristan", "melron", "moregano"}
BRACKETS = [("champion", 1900, None), ("diamond", 1800, 1899), ("platinum", 1700, 1799),
            ("gold", 1550, 1699), ("silver", 1400, 1549), ("bronze", 1300, 1399),
            ("iron", 0, 1299)]
BRACKET_ORDER = {name: i for i, (name, _, _) in enumerate(reversed(BRACKETS))}
MIN_N = 8  # below this a win rate is noise, and the page says so


def wilson(w, n, z=1.96):
    if not n:
        return 0.0, 0.0, 1.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - m), min(1.0, c + m)


def rank_key(p):
    """Exact rating outranks a bracket midpoint; unranked sinks to the bottom."""
    if p["rating"]:
        return (2, p["rating"])
    if p["bracket"] in BRACKET_ORDER:
        return (1, BRACKET_ORDER[p["bracket"]])
    return (0, p["games"])


def last_known(conn, column):
    """Most recent non-null value per player, with the date it was seen.

    Rating and bracket come from a login-gated page, so a lapsed cookie leaves
    them null on new snapshots. Stats keep updating; the standing is carried
    forward and labelled with its own date rather than silently disappearing.
    """
    rows = conn.execute(f"""
        SELECT username, {column} AS v, MAX(fetched_at) AS at
        FROM snapshots WHERE {column} IS NOT NULL GROUP BY username
    """).fetchall()
    return {r["username"]: (r["v"], r["at"]) for r in rows}


def load():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    last_rating = last_known(conn, "rating")
    last_bracket = last_known(conn, "bracket")
    rows = conn.execute("""
        SELECT s.* FROM snapshots s
        JOIN (SELECT username, MAX(fetched_at) m FROM snapshots GROUP BY username) t
          ON s.username = t.username AND s.fetched_at = t.m
    """).fetchall()
    players = []
    for r in rows:
        u = json.loads(r["payload"])["userData"]
        n, w = u["totalGamesPlayed"], u["totalWins"]
        res_w, res_l = u.get("totalResWins", 0), u.get("totalResLosses", 0)
        res_n = res_w + res_l
        spy_w, spy_n = w - res_w, n - res_n

        roles, sizes = {}, {}
        for size, rs in (u.get("roleStats") or {}).items():
            sw = sl = 0
            for role, wl in rs.items():
                # A zero side is omitted entirely: {"losses": 2} means 0 wins,
                # and a bare {} is a role seat with no decided game (voided).
                rw, rl = wl.get("wins", 0), wl.get("losses", 0)
                a = roles.setdefault(role, [0, 0])
                a[0] += rw; a[1] += rl
                sw += rw; sl += rl
            sizes[size] = (sw, sl)

        players.append({
            "name": u["username"], "games": n, "wins": w, "losses": u["totalLosses"],
            "overall": wilson(w, n),
            "res": (res_w, res_l, wilson(res_w, res_n)),
            "spy": (spy_w, spy_n - spy_w, wilson(spy_w, spy_n)),
            # A side never played has no rate — and therefore no lean.
            "res_n": res_n, "spy_n": spy_n,
            "lean": ((spy_w / spy_n) - (res_w / res_n)) if res_n and spy_n else None,
            "roles": sorted(((r, wl) for r, wl in roles.items() if sum(wl)),
                            key=lambda kv: -(kv[1][0] + kv[1][1])),
            "sizes": sorted((kv for kv in sizes.items() if sum(kv[1]))),
            "rating": r["rating"] or last_rating.get(r["username"], (None, None))[0],
            "bracket": (r["bracket"] or last_bracket.get(r["username"], (None,))[0]
                        or "unranked"),
            "rating_at": (r["fetched_at"] if r["rating"] or r["bracket"]
                          else (last_rating.get(r["username"])
                                or last_bracket.get(r["username"])
                                or (None, None))[1]),
            "hours": (r["time_played_s"] or 0) / 3600,
            "joined": u["dateJoined"][:10], "fetched": r["fetched_at"],
        })
    players.sort(key=rank_key, reverse=True)
    return players


def pct(x):
    return f"{x * 100:.0f}%"


def tier_board(players):
    rows = ""
    for name, lo, hi in BRACKETS:
        span = f"{lo}+" if hi is None else f"{lo}–{hi}"
        here = [p for p in players if p["bracket"] == name]
        chips = "".join(
            f'<span class="tchip">{p["name"]}'
            + (f'<em>{p["rating"]:.0f}</em>' if p["rating"] else "")
            + "</span>" for p in here)
        rows += (f'<div class="tier-row{"" if here else " empty"}">'
                 f'<div class="tier-name">{name}</div>'
                 f'<div class="tier-span">{span}</div>'
                 f'<div class="tier-chips">{chips}</div></div>')
    unranked = [p for p in players if p["bracket"] == "unranked"]
    if unranked:
        chips = "".join(f'<span class="tchip">{p["name"]}<em>{p["games"]}g</em></span>'
                        for p in unranked)
        rows += ('<div class="tier-row unranked"><div class="tier-name">unranked</div>'
                 '<div class="tier-span">no bracket yet</div>'
                 f'<div class="tier-chips">{chips}</div></div>')
    return rows


def rating_value(p):
    """A single sortable number for a column that mixes exact ratings and brackets."""
    if p["rating"]:
        return p["rating"]
    for name, lo, hi in BRACKETS:
        if name == p["bracket"]:
            return (lo + (hi if hi else lo + 100)) / 2
    return -1


def board_rows(players, awarded):
    out = ""
    for i, p in enumerate(players, 1):
        pp, lo, hi = p["overall"]
        rw, rl, rs = p["res"]
        sw, sl, ss = p["spy"]
        # The column shows the bracket everyone has; an exact rating, which only
        # the logged-in player's own profile reveals, rides along as a tooltip.
        rank = p["bracket"].title()
        rank_tip = (f'{p["name"]} — {p["rating"]:.0f}' if p["rating"]
                    else f'{p["name"]} — {rank}, exact rating not public')
        title = awarded.get(p["name"], ("—",))[0]
        thin = " thin" if p["games"] < 15 else ""
        out += f"""
      <tr class="{thin.strip()}">
        <td class="rank">{i}</td>
        <td class="who" data-v="{p["name"].lower()}">{p["name"]}</td>
        <td class="title" data-v="{title.lower()}">{title}</td>
        <td class="tier" data-v="{rating_value(p)}" data-tip="{rank_tip}" tabindex="0"><span class="chip {p["bracket"]}">{rank}</span></td>
        <td class="num" data-v="{p["games"]}">{p["games"]}</td>
        <td class="barcell" data-v="{pp:.4f}" data-tip="{p["name"]}: {p["wins"]}W {p["losses"]}L — {pct(pp)} (95% CI {pct(lo)}–{pct(hi)})" tabindex="0">
          <div class="mini">
            <div class="mini-ci" style="left:{lo*100:.1f}%;width:{(hi-lo)*100:.1f}%"></div>
            <div class="mini-fill" style="width:{pp*100:.1f}%"></div>
            <div class="coinflip"></div>
          </div>
        </td>
        <td class="num strong" data-v="{pp:.4f}">{pct(pp)}</td>
        <td class="num res" data-v="{rs[0] if p["res_n"] else -1:.4f}" data-tip="Resistance: {rw}W {rl}L" tabindex="0">{pct(rs[0]) if p["res_n"] else "—"}</td>
        <td class="num spy" data-v="{ss[0] if p["spy_n"] else -1:.4f}" data-tip="Spy: {sw}W {sl}L" tabindex="0">{pct(ss[0]) if p["spy_n"] else "—"}</td>
      </tr>"""
    return out


def lean_str(p):
    if p["lean"] is None:
        return "—"
    return f'{"+" if p["lean"] >= 0 else "−"}{abs(p["lean"]) * 100:.0f}'


def dumbbell(players):
    rows = ""
    # Players with a side unplayed have no lean; they sort last.
    for p in sorted(players, key=lambda q: (q["lean"] is not None, q["lean"] or 0),
                    reverse=True):
        rw, rl, rs = p["res"]
        sw, sl, ss = p["spy"]
        thin = " thin" if p["games"] < 15 else ""
        marks = ""
        if p["res_n"] and p["spy_n"]:
            a, b = min(rs[0], ss[0]), max(rs[0], ss[0])
            marks += (f'<div class="db-link" style="left:{a*100:.1f}%;'
                      f'width:{(b-a)*100:.1f}%"></div>')
        for side, (w, l, st), n in (("res", (rw, rl, rs), p["res_n"]),
                                    ("spy", (sw, sl, ss), p["spy_n"])):
            if not n:
                continue
            label = "Resistance" if side == "res" else "Spy"
            marks += (
                f'<div class="db-ci {side}" style="left:{st[1]*100:.1f}%;'
                f'width:{(st[2]-st[1])*100:.1f}%"></div>'
                f'<div class="db-dot {side}" style="left:{st[0]*100:.1f}%" tabindex="0"'
                f' data-tip="{p["name"]} as {label}: {w}W {l}L — {pct(st[0])}'
                f' (95% CI {pct(st[1])}–{pct(st[2])})"></div>')
        rows += f"""
        <div class="db-row{thin}">
          <div class="db-name">{p["name"]}</div>
          <div class="db-track">
            <div class="coinflip"></div>
            {marks}
          </div>
          <div class="db-gap">{lean_str(p)}</div>
        </div>"""
    return rows


def rate_row(label, w, l, stats, side):
    n = w + l
    p, lo, hi = stats
    thin = " thin" if n < MIN_N else ""
    tip = f"{label}: {w}W {l}L in {n} games — {pct(p)} (95% CI {pct(lo)}–{pct(hi)})"
    return f"""
      <div class="rate{thin}" data-side="{side}" data-tip="{tip}" tabindex="0">
        <div class="rate-label">{label}</div>
        <div class="rate-track">
          <div class="ci" style="left:{lo*100:.1f}%;width:{(hi-lo)*100:.1f}%"></div>
          <div class="fill" style="width:{p*100:.1f}%"></div>
          <div class="coinflip"></div>
        </div>
        <div class="rate-val">{pct(p)}</div>
        <div class="rate-n">{w}W {l}L</div>
      </div>"""


def title_cards(players, awarded):
    out = ""
    for p in players:
        t = awarded.get(p["name"])
        if not t:
            continue
        name, evidence, thin, leads = t
        marks = ""
        if leads:
            marks += ('<span class="seal" data-tip="No one in the group sits further '
                      'out on this measure.">undisputed</span>')
        if thin:
            marks += ('<span class="seal soft" data-tip="Earned on a small number of '
                      'seats — treat it as provisional.">provisional</span>')
        out += f"""
        <article class="tcard">
          <h4>{name}</h4>
          <p class="tholder">{p["name"]}</p>
          <p class="tev">{evidence}</p>
          <p class="tmarks">{marks}</p>
        </article>"""
    return out


def player_card(p, awarded=None):
    roles = "".join(
        rate_row(role.capitalize(), w, l, wilson(w, w + l),
                 "res" if role.lower() in RES_ROLES else "spy")
        for role, (w, l) in p["roles"])
    sizes = ""
    for size, (w, l) in p["sizes"]:
        n = w + l
        rate = w / n if n else 0
        thin = " thin" if n < MIN_N else ""
        note = " — too few games to read into" if n < MIN_N else ""
        sizes += f"""
          <div class="size{thin}" data-tip="{size} tables: {w}W {l}L — {pct(rate)}{note}" tabindex="0">
            <div class="size-bar"><div style="height:{rate*100:.0f}%"></div></div>
            <div class="size-n">{size}</div>
            <div class="size-games">{n}g</div>
          </div>"""
    tier = (f'{p["rating"]:.0f} · {p["bracket"].title()}' if p["rating"]
            else p["bracket"].title())
    return f"""
      <article class="pcard">
        <header>
          <div>
            <h3 class="pname">{p["name"]}</h3>
            {f'<p class="pepithet">{awarded[p["name"]][0]}</p>' if awarded and p["name"] in awarded else ""}
          </div>
          <div class="phero">
            <span class="phero-num">{pct(p["overall"][0])}</span>
            <span class="phero-cap">{p["wins"]}W {p["losses"]}L<br>
              <span class="ci-text">CI {pct(p["overall"][1])}–{pct(p["overall"][2])}</span></span>
          </div>
        </header>
        <p class="pmeta"><span class="chip {p["bracket"]}">{tier}</span>
           {p["games"]} games · {p["hours"]:.1f} h · joined {p["joined"]}</p>
        <div class="rates">{roles}</div>
        <div class="sizes">{sizes}</div>
      </article>"""


def group_aggregates(players):
    """Pool every seat the group has played, by role and by table size."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.payload FROM snapshots s
        JOIN (SELECT username, MAX(fetched_at) m FROM snapshots GROUP BY username) t
          ON s.username = t.username AND s.fetched_at = t.m
    """).fetchall()
    roles, sizes = {}, {}
    for r in rows:
        u = json.loads(r["payload"])["userData"]
        for size, rs in (u.get("roleStats") or {}).items():
            for role, wl in rs.items():
                w, l = wl.get("wins", 0), wl.get("losses", 0)
                a = roles.setdefault(role, [0, 0])
                a[0] += w; a[1] += l
                side = "res" if role.lower() in RES_ROLES else "spy"
                d = sizes.setdefault(size, {"res": [0, 0], "spy": [0, 0]})
                d[side][0] += w; d[side][1] += l
    return roles, sizes


def group_role_rows(roles):
    out = ""
    for role, (w, l) in sorted(roles.items(), key=lambda kv: -(kv[1][0] / max(1, sum(kv[1])))):
        n = w + l
        if n < 5:  # a role the group has barely ever been dealt
            continue
        side = "res" if role.lower() in RES_ROLES else "spy"
        p, lo, hi = wilson(w, n)
        out += f"""
        <div class="rate wide" data-side="{side}" tabindex="0"
             data-tip="{role.capitalize()}: {w}W {l}L over {n} seats — {pct(p)} (95% CI {pct(lo)}–{pct(hi)})">
          <div class="rate-label">{role.capitalize()}</div>
          <div class="rate-track">
            <div class="ci" style="left:{lo*100:.1f}%;width:{(hi-lo)*100:.1f}%"></div>
            <div class="fill" style="width:{p*100:.1f}%"></div>
            <div class="coinflip"></div>
          </div>
          <div class="rate-val">{pct(p)}</div>
          <div class="rate-n">{n} seats</div>
        </div>"""
    return out


def size_rows(sizes):
    """The per-player dumbbell form, reused for table sizes."""
    out = ""
    for size in sorted(sizes, key=lambda k: int(k.rstrip("p"))):
        rw, rl = sizes[size]["res"]
        sw, sl = sizes[size]["spy"]
        rn, sn = rw + rl, sw + sl
        if not rn or not sn:
            continue
        rs, ss = wilson(rw, rn), wilson(sw, sn)
        thin = " thin" if min(rn, sn) < 8 else ""
        a, b = min(rs[0], ss[0]), max(rs[0], ss[0])
        gap = (ss[0] - rs[0]) * 100
        out += f"""
        <div class="db-row{thin}">
          <div class="db-name">{size} tables <em>{rn + sn} seats</em></div>
          <div class="db-track">
            <div class="coinflip"></div>
            <div class="db-link" style="left:{a*100:.1f}%;width:{(b-a)*100:.1f}%"></div>
            <div class="db-ci res" style="left:{rs[1]*100:.1f}%;width:{(rs[2]-rs[1])*100:.1f}%"></div>
            <div class="db-ci spy" style="left:{ss[1]*100:.1f}%;width:{(ss[2]-ss[1])*100:.1f}%"></div>
            <div class="db-dot res" style="left:{rs[0]*100:.1f}%" tabindex="0"
                 data-tip="{size} Resistance: {rw}W {rl}L over {rn} seats — {pct(rs[0])} (95% CI {pct(rs[1])}–{pct(rs[2])})"></div>
            <div class="db-dot spy" style="left:{ss[0]*100:.1f}%" tabindex="0"
                 data-tip="{size} Spy: {sw}W {sl}L over {sn} seats — {pct(ss[0])} (95% CI {pct(ss[1])}–{pct(ss[2])})"></div>
          </div>
          <div class="db-gap">{"+" if gap >= 0 else "−"}{abs(gap):.0f}</div>
        </div>"""
    return out


def funnel(players):
    """Win rate against games played, inside the 95% band a coin flip produces.

    Anyone inside the funnel is, on this evidence, indistinguishable from 50%.
    """
    W, H = 800, 430
    ml, mr, mt, mb = 52, 96, 18, 44
    pw, ph = W - ml - mr, H - mt - mb
    max_n = max(70, max(p["games"] for p in players) + 6)

    def X(n):
        return ml + n / max_n * pw

    def Y(r):
        return mt + (1 - r) * ph

    up, dn = [], []
    for i in range(120):
        n = 2 + i * (max_n - 2) / 119
        half = 1.96 * sqrt(0.25 / n)
        up.append(f"{X(n):.1f},{Y(min(1, 0.5 + half)):.1f}")
        dn.append(f"{X(n):.1f},{Y(max(0, 0.5 - half)):.1f}")
    band = f'M{" L".join(up)} L{" L".join(reversed(dn))} Z'

    grid = ""
    for r in (0, .25, .5, .75, 1):
        y = Y(r)
        grid += (f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                 f'stroke="var(--rule)" stroke-width="1"/>'
                 f'<text x="{ml-10}" y="{y+4:.1f}" text-anchor="end" font-size="11" '
                 f'fill="var(--ink-mute)" font-family="IBM Plex Mono, monospace">{r*100:.0f}%</text>')
    for n in range(0, max_n + 1, 20):
        grid += (f'<text x="{X(n):.1f}" y="{mt+ph+24}" text-anchor="middle" font-size="11" '
                 f'fill="var(--ink-mute)" font-family="IBM Plex Mono, monospace">{n}</text>')

    marks, labels, placed = "", "", []
    for p in sorted(players, key=lambda q: -q["games"]):
        n, w = p["games"], p["wins"]
        r = w / n
        x, y = X(n), Y(r)
        outside = abs(r - .5) > 1.96 * sqrt(0.25 / n)
        fill = "var(--ink)" if outside else "var(--surface)"
        marks += (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{fill}" '
                  f'stroke="var(--ink)" stroke-width="1.6" tabindex="0" '
                  f'data-tip="{p["name"]}: {w}W {p["losses"]}L in {n} games — {pct(r)}'
                  f'{" — clears the coin-flip band" if outside else " — inside the coin-flip band"}"/>')
        ly = y + 4
        while any(abs(px - (x + 10)) < 104 and abs(py - ly) < 13 for px, py in placed):
            ly += 13
        placed.append((x + 10, ly))
        weight = "600" if outside else "400"
        labels += (f'<text x="{x+10:.1f}" y="{ly:.1f}" font-size="11.5" font-weight="{weight}" '
                   f'fill="var(--ink-soft)" font-family="IBM Plex Sans, sans-serif">{p["name"]}</text>')

    return f"""
    <svg viewBox="0 0 {W} {H}" class="funnel" role="img"
         aria-label="Win rate against games played, with the 95% band expected from a coin flip.">
      {grid}
      <path d="{band}" fill="var(--neutral)" fill-opacity=".14"/>
      <line x1="{ml}" y1="{Y(.5):.1f}" x2="{ml+pw}" y2="{Y(.5):.1f}"
            stroke="var(--ink-mute)" stroke-width="1" stroke-dasharray="3 3"/>
      {marks}{labels}
      <text x="{ml+pw/2:.0f}" y="{H-6}" text-anchor="middle" font-size="11"
            fill="var(--ink-mute)" font-family="IBM Plex Mono, monospace">games played</text>
    </svg>"""


def build():
    players = load()
    grp_rw = sum(p["res"][0] for p in players)
    grp_rl = sum(p["res"][1] for p in players)
    grp_sw = sum(p["spy"][0] for p in players)
    grp_sl = sum(p["spy"][1] for p in players)
    grp_res = grp_rw / (grp_rw + grp_rl)
    grp_spy = grp_sw / (grp_sw + grp_sl)
    rated = [p for p in players if p["lean"] is not None]
    spy_lean = sum(1 for p in rated if p["lean"] > 0)

    awarded = titles_mod.assign(players)
    roles, sizes = group_aggregates(players)
    outside = [p for p in players
               if abs(p["wins"] / p["games"] - .5) > 1.96 * sqrt(0.25 / p["games"])]
    stamp = datetime.fromisoformat(players[0]["fetched"]).astimezone()
    rating_dates = {p["rating_at"][:10] for p in players if p["rating_at"]}
    stale = rating_dates and max(rating_dates) < players[0]["fetched"][:10]
    html = TEMPLATE.substitute(
        tiers=tier_board(players),
        board=board_rows(players, awarded),
        dumbbell=dumbbell(players),
        cards="".join(player_card(p, awarded) for p in players),
        titles=title_cards(players, awarded),
        group_roles=group_role_rows(roles),
        size_rows=size_rows(sizes),
        funnel=funnel(players),
        n_outside=len(outside),
        rating_note=(f' · ratings as of {max(rating_dates)}' if stale else ""),
        outside_names=" and ".join(p["name"] for p in outside) or "nobody",
        stamp=stamp.strftime("%d %b %Y, %H:%M"),
        n_players=len(players),
        total_games=sum(p["games"] for p in players),
        grp_res=pct(grp_res), grp_spy=pct(grp_spy),
        grp_gap=f"{(grp_spy - grp_res) * 100:.0f}",
        spy_lean=spy_lean, n_rated=len(rated),
        res_seats=grp_rw + grp_rl, spy_seats=grp_sw + grp_sl,
    )
    OUT.write_text(html)
    (ROOT / "index.html").write_text(html)   # what GitHub Pages serves
    print(f"wrote {OUT} and index.html ({len(html):,} bytes, {len(players)} players)")


TEMPLATE = Template((ROOT / "template.html").read_text())

if __name__ == "__main__":
    build()
