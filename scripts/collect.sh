#!/usr/bin/env bash
# Full collection run: race days -> race pages (newest first) -> pedigrees.
# Resumable: re-running skips everything already in data/keiba.sqlite or data/raw/.
# Set SNAPSHOT=/path/keiba.sqlite to copy the DB there every SNAPSHOT_EVERY races.
set -euo pipefail
cd "$(dirname "$0")/.."
FROM=${FROM:-2015-01}
CHUNK=${SNAPSHOT_EVERY:-500}
snap() { [ -n "${SNAPSHOT:-}" ] && python3 -m scraper snapshot --out "$SNAPSHOT" || true; }

python3 -m scraper days --from "$FROM"
snap
while python3 -m scraper status | grep -q "'todo'"; do
  python3 -m scraper races --limit "$CHUNK"
  snap
done
python3 -m scraper peds
snap
python3 -m scraper status
