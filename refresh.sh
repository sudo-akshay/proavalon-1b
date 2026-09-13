#!/bin/bash
# Take a fresh snapshot and rebuild dashboard.html from it.
# Publishing the result to the shared link is a separate step — ask Claude.
cd "$(dirname "$0")" || exit 1
mkdir -p logs
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  python3 collect.py
  python3 build_dashboard.py
} 2>&1 | tee -a logs/collect.log
