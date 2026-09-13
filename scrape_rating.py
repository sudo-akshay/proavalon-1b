#!/usr/bin/env python3
"""Scrape the season rating, which the JSON API omits.

Rating is server-rendered into the profile HTML, and that page requires any
logged-in session — so one cookie covers the whole friend group. Players with
no ranked games this season simply have no rating row.
"""
import re
import urllib.request
from pathlib import Path

COOKIE_FILE = Path(__file__).parent / ".secrets" / "cookie.txt"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
# The exact number renders only on your OWN profile; others show a bracket.
PACE = 3.0  # seconds between profile hits — faster trips Cloudflare's challenge
RATING_RE = re.compile(r'Rating:</td>\s*<td class="statsCol2">\s*([0-9.]+)')
BRACKET_RE = re.compile(r'Rank:</td>\s*<td class="statsCol2">\s*([A-Za-z]+)')

# Midpoints used to rank bracket-only players against each other.
BRACKETS = {
    "iron": (0, 1299), "bronze": (1300, 1399), "silver": (1400, 1549),
    "gold": (1550, 1699), "platinum": (1700, 1799), "diamond": (1800, 1899),
    "champion": (1900, 2100),
}
TIMEOUT = 15


MANUAL_FILE = Path(__file__).parent / "manual_ratings.txt"


def manual_ratings():
    """Ratings a player read off their own profile and passed on.

    ProAvalon shows the exact number only to the account that owns it, so for
    anyone but the cookie holder this is the only route to a real rating.
    """
    out = {}
    if not MANUAL_FILE.exists():
        return out
    for line in MANUAL_FILE.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line or "=" not in line:
            continue
        name, _, val = line.partition("=")
        try:
            out[name.strip()] = float(val.strip())
        except ValueError:
            continue
    return out


def cookie():
    if not COOKIE_FILE.exists():
        return None
    c = COOKIE_FILE.read_text().strip()
    return c or None


def get_rating(username, ck=None):
    """Return (rating, bracket). Exact rating is only ever your own profile."""
    ck = ck or cookie()
    if not ck:
        return None, None
    req = urllib.request.Request(
        f"https://www.proavalon.com/profile/{urllib.parse.quote(username)}",
        headers={"User-Agent": UA, "Cookie": ck},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            # A dead cookie redirects to / instead of rendering the profile.
            if resp.geturl().rstrip("/").endswith("proavalon.com"):
                return None, None
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return None, None
    if "statsCol2" not in html:
        # Logged out: the profile route bounced us to the landing page.
        return None, "loggedout"
    m = RATING_RE.search(html)
    if m:
        rating = float(m.group(1))
        return rating, bracket_for(rating)
    b = BRACKET_RE.search(html)
    return None, b.group(1).lower() if b else None


def bracket_for(rating):
    """Bracket a numeric rating falls into."""
    for name, (lo, hi) in BRACKETS.items():
        if lo <= rating <= hi:
            return name
    return None


def sort_key(rating, bracket):
    """Exact rating wins; otherwise use the bracket midpoint."""
    if rating:
        return rating
    if bracket in BRACKETS:
        lo, hi = BRACKETS[bracket]
        return (lo + hi) / 2
    return -1


import urllib.parse  # noqa: E402  (used above)

if __name__ == "__main__":
    import sys
    for name in sys.argv[1:] or ["axehaybond"]:
        print(f"{name}: {get_rating(name)}")
