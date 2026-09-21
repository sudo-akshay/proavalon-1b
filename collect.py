#!/usr/bin/env python3
"""Snapshot ProAvalon profile stats into SQLite.

The site only exposes cumulative counters, so we poll and store snapshots;
diffing consecutive snapshots is what gives us a timeline.
"""
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scrape_rating import (PACE, bracket_for, cookie as load_cookie, get_rating,
                           manual_ratings)

BASE = "https://proavalon.com/ajax/profile/getProfileData/"
ROOT = Path(__file__).parent
DB = ROOT / "stats.db"
TIMEOUT = 15  # a nonexistent/wrong-case username never responds, so this matters
RATING_MAX_AGE = 3600  # brackets barely move; scraping them every snapshot just trips Cloudflare

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    total_games   INTEGER,
    total_wins    INTEGER,
    total_losses  INTEGER,
    res_wins      INTEGER,
    res_losses    INTEGER,
    time_played_s INTEGER,
    rating        REAL,
    bracket       TEXT,
    rating_source TEXT,
    date_joined   TEXT,
    payload       TEXT NOT NULL,
    UNIQUE (username, fetched_at)
);
CREATE TABLE IF NOT EXISTS role_stats (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    username    TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    size        TEXT NOT NULL,
    role        TEXT NOT NULL,
    wins        INTEGER NOT NULL,
    losses      INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, size, role)
);
CREATE INDEX IF NOT EXISTS idx_snap_user_time ON snapshots(username, fetched_at);
"""


def usernames():
    path = ROOT / "usernames.txt"
    names = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


def fetch(username):
    req = urllib.request.Request(
        BASE + urllib.parse.quote(username),
        headers={"User-Agent": "proavalon-dashboard/0.1"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read().decode()
    if body.strip() == "error":
        raise ValueError("server returned 'error'")
    return json.loads(body)


def time_played_seconds(iso):
    """totalTimePlayed is a duration encoded as an epoch-relative timestamp."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except ValueError:
        return None


def recent_ratings(conn):
    """Players whose rating was read within RATING_MAX_AGE — skip re-scraping them."""
    cutoff = (datetime.now(timezone.utc).timestamp() - RATING_MAX_AGE)
    out = {}
    for r in conn.execute("""SELECT username, rating, bracket, MAX(fetched_at) at
                             FROM snapshots WHERE rating IS NOT NULL OR bracket IS NOT NULL
                             GROUP BY username"""):
        try:
            seen = datetime.fromisoformat(r[3]).timestamp()
        except (TypeError, ValueError):
            continue
        if seen > cutoff:
            out[r[0]] = (r[1], r[2])
    return out


def migrate(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(snapshots)")}
    if "rating" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN rating REAL")
    if "bracket" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN bracket TEXT")
    if "rating_source" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN rating_source TEXT")


def store(conn, username, data, fetched_at, rating=None, bracket=None, source=None):
    u = data.get("userData", {})
    if u.get("hideStats"):
        print(f"  {username}: stats hidden on their profile, skipping")
        return False

    cur = conn.execute(
        """INSERT OR IGNORE INTO snapshots
           (username, fetched_at, total_games, total_wins, total_losses,
            res_wins, res_losses, time_played_s, rating, bracket, rating_source,
            date_joined, payload)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            u.get("username", username),
            fetched_at,
            u.get("totalGamesPlayed"),
            u.get("totalWins"),
            u.get("totalLosses"),
            u.get("totalResWins"),
            u.get("totalResLosses"),
            time_played_seconds(u.get("totalTimePlayed")),
            rating,
            bracket,
            source,
            u.get("dateJoined"),
            json.dumps(data),
        ),
    )
    snap_id = cur.lastrowid
    for size, roles in (u.get("roleStats") or {}).items():
        for role, wl in roles.items():
            conn.execute(
                """INSERT OR REPLACE INTO role_stats
                   (snapshot_id, username, fetched_at, size, role, wins, losses)
                   VALUES (?,?,?,?,?,?,?)""",
                (snap_id, u.get("username", username), fetched_at, size, role,
                 wl.get("wins", 0), wl.get("losses", 0)),
            )
    return True


def candidates(name, conn):
    """Casings to try for a name, best guess first.

    Players rename themselves and the API is case-sensitive, so a stale entry
    in usernames.txt costs a 15s timeout and a missing player. Every casing we
    have ever seen for this identity is worth a try before giving up.
    """
    seen = [name]
    rows = conn.execute("""SELECT username, MAX(fetched_at) FROM snapshots
                           WHERE LOWER(username) = ? GROUP BY username
                           ORDER BY 2 DESC""", (name.lower(),)).fetchall()
    for r in rows:
        if r[0] not in seen:
            seen.append(r[0])
    for variant in (name.capitalize(), name.lower(), name.upper()):
        if variant not in seen:
            seen.append(variant)
    return seen


def rename_in_config(old, new):
    """Keep usernames.txt pointing at the casing that actually resolves."""
    path = ROOT / "usernames.txt"
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.strip() == old:
            lines[i] = new
            path.write_text("\n".join(lines) + "\n")
            return True
    return False


def main():
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    migrate(conn)
    manual = manual_ratings()
    ck = load_cookie()
    fresh = recent_ratings(conn)
    if not ck:
        print("  (no .secrets/cookie.txt — ratings will be skipped)")
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok = failed = 0
    for name in usernames():
        data, resolved = None, name
        for attempt in candidates(name, conn):
            try:
                data = fetch(attempt)
                resolved = attempt
                break
            except (urllib.error.URLError, TimeoutError, ValueError,
                    json.JSONDecodeError):
                continue
        if data is None:
            print(f"  {name}: FAILED — no casing of this name responds")
            failed += 1
            continue
        if resolved != name:
            moved = rename_in_config(name, resolved)
            print(f"  {name}: renamed to {resolved}"
                  f"{' (usernames.txt updated)' if moved else ''}")
            name = resolved
        if name in fresh:
            rating, bracket = fresh[name]          # still current, no request needed
            source = "cached"
        elif ck:
            time.sleep(PACE)                       # pace the profile hits
            rating, bracket = get_rating(name, ck)
            source = "profile" if rating else None
            if bracket == "loggedout":
                print("  (session cookie expired — ratings paused, stats unaffected; "
                      "refresh .secrets/cookie.txt to resume)")
                ck = None
                rating = bracket = None
        else:
            rating, bracket = None, None
            source = None
        if not rating and name in manual:
            # Self-reported: the site will never hand us this number.
            rating = manual[name]
            bracket = bracket_for(rating) or bracket
            source = "self-reported"
        if store(conn, name, data, fetched_at, rating, bracket, source):
            u = data["userData"]
            tag = " (self-reported)" if source == "self-reported" else ""
            r = f", rating {rating:.0f}{tag}" if rating else ""
            if bracket:
                r += f" ({bracket})" if rating else f", {bracket}"
            print(f"  {name}: {u['totalGamesPlayed']} games, "
                  f"{u['totalWins']}W/{u['totalLosses']}L{r}")
            ok += 1
    conn.commit()
    conn.close()
    print(f"snapshot {fetched_at}: {ok} ok, {failed} failed -> {DB}")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
