#!/usr/bin/env bash
# Rebuild everything for the featured race in one go: prediction -> race replay -> site.
#
#   scripts/build_site.sh                         # Kikuka Sho 2026, entries as of now
#   scripts/build_site.sh --odds odds.csv         # after the odds are out (horse_name,odds)
#   scripts/build_site.sh --going 稍重             # expected ground
#
# Steps (each can also be run on its own):
#   1. scripts/predict.py          -> data/preds/<race_id>.csv  (win probability per horse)
#   2. theater/tools/build_field.py -> theater/data/<name>.field.json (style, kick, stamina ... per horse)
#   3. theater/tools/calibrate.mjs  -> theater/data/<name>.json (strength set so the replay's win rates
#                                      match step 1; top-3 rates from thousands of simulated races)
#   4. portal/build.py              -> portal/www/ (reads step 3, so the site and the replay agree)
#
# Needs data/keiba.sqlite (or KEIBA_DB) and data/features_turf.pkl
# (python3 scripts/backtest.py --rebuild makes it).
set -euo pipefail
cd "$(dirname "$0")/.."

RACE_ID=${RACE_ID:-202608040911}
NAME=${NAME:-kikka2026}
DB=${KEIBA_DB:-data/keiba.sqlite}
GOING=良
PREDICT_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --odds) PREDICT_ARGS+=(--odds "$2"); shift 2 ;;
    --going) GOING=$2; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

python3 scripts/predict.py "$RACE_ID" --going "$GOING" "${PREDICT_ARGS[@]}"
python3 theater/tools/build_field.py --db "$DB" --predictions "data/preds/$RACE_ID.csv" --going "$GOING" \
  --out "theater/data/$NAME.field.json"
node theater/tools/calibrate.mjs "theater/data/$NAME.field.json" "theater/data/$NAME.json"
python3 portal/build.py --db "$DB" --featured "theater/data/$NAME.json" --days "${DAYS:-4}"
echo "done: portal/www (serve with: cd portal/www && python3 -m http.server)"
