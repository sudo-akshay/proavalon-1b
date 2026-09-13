# ProAvalon 1B

A stats dashboard for a group of [ProAvalon](https://proavalon.com) players.
Snapshots each player's public profile stats into SQLite and renders a
self-contained HTML page from them.

**Live page:** see the repository's GitHub Pages URL.

## Refreshing

```bash
./refresh.sh                 # snapshot every player, rebuild the page
git commit -am "refresh" && git push   # publish it
```

## What the data can and cannot say

ProAvalon exposes cumulative per-player counters and nothing else:

- `GET /ajax/profile/getProfileData/<username>` is public and needs no login. It
  returns totals, resistance wins/losses, and a role breakdown per table size.
  The username is **case-sensitive**, and an unknown one never responds at all —
  hence the timeouts in `collect.py`.
- A player's **exact rating** renders only on their own profile, to them. For
  everyone else the site shows a bracket (Silver, Gold, …). `scrape_rating.py`
  reads the number for whoever's session cookie is in `.secrets/cookie.txt`, and
  the bracket for everyone else. `manual_ratings.txt` is for numbers friends read
  off their own profiles and passed on.
- **Per-game history does not exist outside their server.** Mission and vote
  history are stored but no route exposes them, so teammate synergy and
  head-to-head records are impossible, not merely unimplemented.

Because the counters are cumulative, a timeline only exists if snapshots are
taken over time — that is what `refresh.sh` on a schedule is for.

## Files

| File | Purpose |
|------|---------|
| `collect.py` | Snapshot every player in `usernames.txt` into `stats.db` |
| `scrape_rating.py` | Rating (own profile) and bracket (everyone) from the HTML |
| `build_dashboard.py` | Render `stats.db` into `dashboard.html` / `index.html` |
| `titles.py` | Award each player one earned title |
| `report.py` | Terminal leaderboard |
| `refresh.sh` | Snapshot + rebuild, logged to `logs/` |
| `com.axehay.proavalon.plist` | Optional launchd job, every 15 minutes |

## Statistics

Every rate carries a 95% Wilson interval, and anything under 8 games is drawn
faded. With 20–60 games per player, almost nothing at role level is significant:
the funnel plot exists to make that visible rather than to bury it in a footnote.

## Setup

`usernames.txt` — one exact-case username per line.
`.secrets/cookie.txt` — a `connect.sid` cookie, optional, for your own rating.
Both `.secrets/` and `stats.db` are gitignored.
