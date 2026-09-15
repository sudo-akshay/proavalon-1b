#!/bin/bash
# Snapshot every player, rebuild the page, and publish it if anything moved.
# Pass --no-push to rebuild locally without touching GitHub.
# launchd runs with a minimal PATH that has neither Homebrew's python3 (the one
# this was built against) nor gh's git credential helper.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$(dirname "$0")" || exit 1
mkdir -p logs

out=$( { echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="; python3 collect.py; python3 build_dashboard.py; } 2>&1 )
echo "$out" | tee -a logs/collect.log

if [ "$1" = "--no-push" ]; then exit 0; fi

if echo "$out" | grep -q "content: changed"; then
  git add -A
  git commit -qm "refresh: $(date '+%Y-%m-%d %H:%M')" && git push -q origin main \
    && echo "published -> https://sudo-akshay.github.io/proavalon-1b/"
else
  echo "nothing changed since the last snapshot — not publishing"
fi
