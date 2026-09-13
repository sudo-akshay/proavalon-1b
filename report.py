#!/usr/bin/env python3
"""Terminal leaderboard + role analysis from the latest snapshot of each player."""
import json
import sqlite3
import sys
from math import sqrt
from pathlib import Path

from scrape_rating import sort_key

DB = Path(__file__).parent / "stats.db"

ALLIANCE = {
    "resistance": "Res", "merlin": "Res", "percival": "Res",
    "isolde": "Res", "tristan": "Res", "melron": "Res", "moregano": "Res",
    "spy": "Spy", "assassin": "Spy", "morgana": "Spy", "mordred": "Spy",
    "oberon": "Spy", "mordredassassin": "Spy", "hitberon": "Spy",
}


def wilson(w, n, z=1.96):
    """Lower/upper bound on true win rate. With ~40 games, raw % is mostly noise."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = w / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    margin = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - margin), min(1.0, centre + margin)


def latest(conn):
    rows = conn.execute("""
        SELECT s.* FROM snapshots s
        JOIN (SELECT username, MAX(fetched_at) m FROM snapshots GROUP BY username) t
          ON s.username = t.username AND s.fetched_at = t.m
    """).fetchall()
    return rows


def bar(p, width=20):
    filled = round(p * width)
    return "█" * filled + "·" * (width - filled)


def main():
    if not DB.exists():
        sys.exit("No stats.db yet — run collect.py first.")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = latest(conn)
    if not rows:
        sys.exit("No snapshots stored yet.")

    print("\n  LEADERBOARD  (by rating; 95% CI — overlapping ranges mean the gap isn't real yet)\n")
    print(f"  {'player':<18}{'rating':>7}{'games':>6}{'win%':>7}   {'range':<14}{'res%':>7}{'spy%':>7}")
    print("  " + "─" * 69)
    ranked = []
    for r in rows:
        n, w = r["total_games"] or 0, r["total_wins"] or 0
        p, lo, hi = wilson(w, n)
        rw, rl = r["res_wins"] or 0, r["res_losses"] or 0
        res_n = rw + rl
        spy_w, spy_n = w - rw, n - res_n
        ranked.append((sort_key(r["rating"], r["bracket"]), r["username"], n, p, lo, hi,
                       r["rating"], r["bracket"],
                       rw / res_n if res_n else None,
                       spy_w / spy_n if spy_n else None))
    for _, name, n, p, lo, hi, rating, bracket, res, spy in sorted(ranked, reverse=True):
        rate_s = f"{rating:.0f}" if rating else (bracket[:4].title() if bracket else "–")
        res_s = f"{res*100:5.0f}%" if res is not None else "    –"
        spy_s = f"{spy*100:5.0f}%" if spy is not None else "    –"
        print(f"  {name:<18}{rate_s:>7}{n:>6}{p*100:>6.0f}%   {lo*100:>3.0f}–{hi*100:<3.0f}%      {res_s:>6} {spy_s:>6}")

    for r in rows:
        data = json.loads(r["payload"])["userData"]
        print(f"\n\n  {r['username'].upper()} — by role (all table sizes pooled)\n")
        agg = {}
        for size, roles in (data.get("roleStats") or {}).items():
            for role, wl in roles.items():
                a = agg.setdefault(role, [0, 0])
                a[0] += wl.get("wins", 0)
                a[1] += wl.get("losses", 0)
        for role, (w, l) in sorted(agg.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
            n = w + l
            p, lo, hi = wilson(w, n)
            side = ALLIANCE.get(role.lower(), "?")
            flag = "  (too few games to read into)" if n < 8 else ""
            print(f"    {role.capitalize():<12}{side:<5}{w:>3}W/{l:<3}L  {bar(p)} {p*100:>3.0f}%"
                  f"  ±{(hi-lo)/2*100:>2.0f}{flag}")
    print()


if __name__ == "__main__":
    main()
