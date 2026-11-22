"""data/odds/<date>.json for the page's live refresh, from portal/cache (fetch_card.py)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
date = sys.argv[1]
ix = json.loads((ROOT / "www/data/index.json").read_text())
day = next(d for d in ix["days"] if d["date"] == date)
races, going, t = {}, {}, ""
for r in day["races"]:
    c = ROOT / "cache" / r["race_id"]
    if not (c / "odds.json").exists():
        continue
    o = json.loads((c / "odds.json").read_text())
    conv = lambda d: {k: [float(v[0]) if v[0] else None, float(v[1]) if len(v) > 1 and v[1] else None, int(v[2]) if len(v) > 2 and v[2] else None] for k, v in d.items()}
    races[r["race_id"]] = {"win": conv(o.get("win", {})), "place": conv(o.get("place", {})), "time": o.get("time")}
    t = max(t, o.get("time") or "")
    if (c / "baba.json").exists():
        for x in json.loads((c / "baba.json").read_text()).get("same_day", []):
            going[f"{r['race_id'][:10]}{x['r']:02d}"] = x
out = {"fetched": t[:16], "races": races, "going": going}
(ROOT / "www/data/odds").mkdir(parents=True, exist_ok=True)
(ROOT / "www/data/odds" / f"{date}.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
print(len(races), "races", t, len(going), "going")
