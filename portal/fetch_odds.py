"""Current odds for every race of a day, for the portal's live odds overlay.

    python3 portal/fetch_odds.py 2026-10-25

Reads the day's race ids from portal/www/data/index.json and writes
portal/www/data/odds/<date>.json: win, place, quinella (馬連) and wide (ワイド)
odds per race with the time netkeiba published them, the going and weather
announced for every race of the day (netkeiba's race pages) and JRA's Kyoto
track report, plus the virtual bets the betting thread placed that day
(betting/bets.csv). The page loads this file
each time a race is opened, so re-running this and republishing is all a
refresh takes. Races that have finished keep their last odds.
"""
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from fetch_card import BABA, baba, day_going

ROOT = Path(__file__).resolve().parent
ODDS = "https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={}&type={}&action=update"
OVERRIDE = ROOT / "going_override.json"  # going reported before netkeiba shows it
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


def going(day):
    """{race_id: {surface, distance, weather, going}} for every race of the day
    whose going has been announced, read from each venue's race pages."""
    def venue(prefix):
        try:
            return {f"{prefix}{x['r']:02d}": x for x in day_going(prefix + "01", 0)}
        except requests.RequestException as e:
            print(prefix, "going not read:", e, file=sys.stderr)
            return {}
    with ThreadPoolExecutor(3) as ex:
        out = {k: v for d in ex.map(venue, sorted({r["race_id"][:10] for r in day["races"]})) for k, v in d.items()}
    for k, v in (json.loads(OVERRIDE.read_text()) if OVERRIDE.exists() else {}).items():
        # only while netkeiba still shows what it showed when the report came in
        if k in out and out[k]["going"] == v["was"]:
            out[k] = {**out[k], "going": v["going"], "reported": v["reported"]}
    return out


def jra_kyoto():
    try:
        r = requests.get(BABA, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print("JRA track page not read:", e, file=sys.stderr)
        return None
    return baba(r.content.decode("shift_jis", "replace"))


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
    todo = []
    for r in day["races"]:
        start = r.get("start_time") or "99:99"
        h, m = map(int, start.split(":")) if start != "99:99" else (99, 0)
        if r["race_id"] in races and now > f"{h:02d}:{m:02d}" and (h * 60 + m + 20) < int(now[:2]) * 60 + int(now[3:]):
            continue  # run more than 20 minutes ago: its odds are final
        todo.append(r["race_id"])

    def one(race_id):
        try:
            return race_id, race_odds(race_id)
        except (requests.RequestException, ValueError) as e:
            print(race_id, "kept old odds:", e, file=sys.stderr)
            return race_id, None

    with ThreadPoolExecutor(6) as ex:
        live = ex.submit(going, day), ex.submit(jra_kyoto)
        races.update({k: v for k, v in ex.map(one, todo) if v})
        live_going, jra = live[0].result(), live[1].result()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M"), "races": races,
                               "going": live_going or old.get("going", {}), "jra": jra or old.get("jra"), "bets": bets(date)},
                               ensure_ascii=False, separators=(",", ":")))
    print(path, len(races), "races", file=sys.stderr)


if __name__ == "__main__":
    main()
