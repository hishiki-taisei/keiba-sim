"""Fetch all bet-type odds for every race of a day into www/data/odds/<date>/<race_id>.json.

The page reads this file when a race opens, to show the odds of each ticket the
bet builder makes. Keys are zero-padded horse numbers joined in order
("0214" for 2-14). Wide and place values are [low, high].
"""
import json, sys, time
from pathlib import Path
import requests
from fetch_card import ODDS, HEADERS

TYPES = {1: "win", 2: "place", 4: "umaren", 5: "wide", 6: "umatan", 7: "trio", 8: "trifecta"}
RANGE = {"place", "wide"}

def num(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None

def fetch(rid):
    out = {"time": None}
    for t, name in TYPES.items():
        for attempt in range(3):
            try:
                d = requests.get(ODDS.format(rid, t), headers=HEADERS, timeout=30).json()
                break
            except Exception:
                time.sleep(2 * (attempt + 1))
        else:
            continue
        raw = ((d.get("data") or {}).get("odds") or {}).get(str(t)) or {}
        vals = {}
        for k, v in raw.items():
            lo = num(v[0])
            if lo is None:
                continue
            vals[k] = [lo, num(v[1])] if name in RANGE else lo
        out[name] = vals
        out["time"] = out["time"] or (d.get("data") or {}).get("official_datetime")
        time.sleep(0.3)
    return out

def main():
    date = sys.argv[1]
    www = Path(__file__).parent / "www"
    idx = json.loads((www / "data/index.json").read_text())
    day = next(x for x in idx["days"] if x["date"] == date)
    dst = www / "data/odds" / date
    dst.mkdir(parents=True, exist_ok=True)
    for r in day["races"]:
        o = fetch(r["race_id"])
        (dst / f"{r['race_id']}.json").write_text(json.dumps(o, separators=(",", ":")))
        print(r["race_id"], o["time"], {k: len(v) for k, v in o.items() if isinstance(v, dict)}, file=sys.stderr)

if __name__ == "__main__":
    main()
