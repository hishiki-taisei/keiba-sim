"""Write the paper-betting dashboard's data: one row per bet and one row per race.

    python3 scripts/dashboard_data.py [OUT_DIR]   # default: <shared>/betting/dashboard

bets.json   every paper bet with its result (strategy group and label spelled out)
races.json  every race bet on, with its winner
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import live.__main__ as live  # noqa: E402


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else live.OUT / "dashboard"
    out.mkdir(parents=True, exist_ok=True)
    live.sync_in()
    b = live.read_bets().reset_index(drop=True)
    b["bet_id"] = b.index.astype(str)
    b["group"] = b["strategy"].map(lambda s: live.STRATEGIES[s][0])
    b["label"] = b["strategy"].map(lambda s: live.STRATEGIES[s][1])
    b["result"] = "未決着"
    s = b["settled"]
    b.loc[s, "result"] = "外れ"
    b.loc[s & (b["payout"] > 0), "result"] = "的中"
    b.loc[s & b["finish"].astype(str).isin(["取", "除", "中止"]), "result"] = "返還"
    cols = ["bet_id", "date", "race_id", "venue", "race_no", "post_time", "race_name", "surface", "distance",
            "group", "label", "strategy", "bet_type", "number", "horse_name", "odds_at_bet", "odds_source",
            "p_model", "p_market", "stake", "settled", "result", "finish", "final_odds", "payout"]
    rows = b[cols].astype(object).where(b[cols].notna(), None).to_dict("records")
    for r in rows:
        for k in ("race_no", "number", "stake", "distance"):
            if r[k] is not None:
                r[k] = int(r[k])
        r["payout"] = None if r["payout"] is None else int(r["payout"])
        f = r["finish"]
        r["finish"] = None if f is None else (str(int(float(f))) if re.fullmatch(r"\d+(\.0)?", str(f)) else str(f))
    (out / "bets.json").write_text(json.dumps(rows, ensure_ascii=False))

    # Races and their winners; horse names come from the day's predictions.
    races = b.drop_duplicates("race_id")[["date", "race_id", "venue", "race_no", "post_time", "race_name",
                                         "surface", "distance"]]
    res = live.results_for(sorted(races["race_id"]), fetch=False)[0]
    preds = [pd.read_csv(f, dtype={"race_id": str}) for d in races["date"].unique()
             if (f := live.OUT / "predictions" / f"{d}.csv").exists()]
    p = pd.concat(preds) if preds else pd.DataFrame(columns=["race_id", "number", "horse_name"])
    names = {(r, int(n)): h for r, n, h in zip(p["race_id"], p["number"], p["horse_name"])}
    out_races = []
    for _, r in races.iterrows():
        w = res[(res["race_id"] == r["race_id"]) & (res["finish"] == 1)]
        row = {k: (None if pd.isna(v) else v) for k, v in r.items()}
        row["race_no"], row["distance"] = int(row["race_no"]), int(row["distance"])
        if not w.empty:
            n = int(w["number"].iloc[0])
            row.update(winner_number=n, winner_name=names.get((r["race_id"], n)),
                       winner_odds=None if pd.isna(w["odds"].iloc[0]) else float(w["odds"].iloc[0]))
        else:
            row.update(winner_number=None, winner_name=None, winner_odds=None)
        out_races.append(row)
    (out / "races.json").write_text(json.dumps(out_races, ensure_ascii=False))
    print(f"wrote {len(rows)} bets and {len(out_races)} races to {out}")


if __name__ == "__main__":
    main()
