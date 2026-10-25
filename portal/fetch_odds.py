"""Current odds for every race of a day, for the portal's live odds overlay.

    python3 portal/fetch_odds.py 2026-10-25

Reads the day's race ids from portal/www/data/index.json and writes
portal/www/data/odds/<date>.json: win, place, quinella (馬連) and wide (ワイド)
odds per race with the time netkeiba published them, plus the virtual bets the
betting thread placed that day (betting/bets.csv). The page loads this file
each time a race is opened, so re-running this and republishing is all a
refresh takes. Races that have finished keep their last odds.
"""
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
ODDS = "https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={}&type={}&action=update"
BETS = Path("/mnt/project-files/keiba-sim/betting/bets.csv")
HEADERS = {"User-Agent": "Mozilla/5.0 (keiba-sim portal)"}
TYPES = {"win": 1, "place": 2, "umaren": 4, "wide": 5}


def race_odds(race_id):
    out = {}
    for kind, typ in TYPES.items():
        r = requests.get(ODDS.format(race_id, typ), headers=HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json().get("data") or {}
        o = (d.get("odds") or {}).get(str(typ), {})
        # [odds, (upper odds for place/wide), popularity] -> numbers, dropping scratched horses
        out[kind] = {k: [float(v[0]), float(v[1]) if v[1] else None, int(v[2]) if v[2] else None]
                     for k, v in o.items() if v[0] and v[0].replace(".", "").isdigit()}
        out["time"] = d.get("official_datetime") or out.get("time")
    return out


def bets(date):
    if not BETS.exists():
        return {}
    out = {}
    with BETS.open() as f:
        for b in csv.DictReader(f):
            if b["date"] == date:
                out.setdefault(b["race_id"], []).append({
                    "strategy": b["strategy"], "type": b["bet_type"], "number": int(b["number"]),
                    "name": b["horse_name"], "odds": float(b["odds_at_bet"]) if b["odds_at_bet"] else None})
    return out


def main():
    date = sys.argv[1]
    index = json.loads((ROOT / "www" / "data" / "index.json").read_text())
    day = next(d for d in index["days"] if d["date"] == date)
    path = ROOT / "www" / "data" / "odds" / f"{date}.json"
    old = json.loads(path.read_text()) if path.exists() else {"races": {}}
    races = dict(old["races"])
    now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%H:%M")
    for r in day["races"]:
        start = r.get("start_time") or "99:99"
        h, m = map(int, start.split(":")) if start != "99:99" else (99, 0)
        if r["race_id"] in races and now > f"{h:02d}:{m:02d}" and (h * 60 + m + 20) < int(now[:2]) * 60 + int(now[3:]):
            continue  # run more than 20 minutes ago: its odds are final
        try:
            races[r["race_id"]] = race_odds(r["race_id"])
        except (requests.RequestException, ValueError) as e:
            print(r["race_id"], "kept old odds:", e, file=sys.stderr)
        time.sleep(0.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M"), "races": races, "bets": bets(date)},
                               ensure_ascii=False, separators=(",", ":")))
    print(path, len(races), "races", file=sys.stderr)


if __name__ == "__main__":
    main()
