#!/usr/bin/env bash
# Pedigrees only, in chunks, with a DB snapshot after each chunk.
set -uo pipefail
cd "$(dirname "$0")/.."
while :; do
  python3 -m scraper peds --limit 1000
  [ -n "${SNAPSHOT:-}" ] && python3 -m scraper snapshot --out "$SNAPSHOT"
  left=$(python3 -c "import sqlite3;c=sqlite3.connect('data/keiba.sqlite');print(c.execute('select count(distinct horse_id) from results where horse_id not in (select horse_id from horses)').fetchone()[0])")
  echo "left: $left"
  [ "$left" -le 20 ] && break
done
