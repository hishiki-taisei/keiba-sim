"""Three ideas on the odds-free model, tested on the same years as experiments/strategies.md
(train 2018-2022, valid 2023, test 2024-):

1. Pace prediction: field-level features from the runners' usual early position and pace
   (how many front-runners, how fast the likely leaders usually go, and how each horse's
   style fits that).
2. Ranking: learn the whole top three instead of the winner only (Plackett-Luce, written as
   three softmax stages: winner among all, second among the rest, third among the rest).
3. Exotic bets: quinella (馬連) and wide (ワイド) pairs where the model's pair probability is
   several times the market's (both from Harville on win probabilities), paid with the real
   payouts.

    python3 scripts/rank_pace_exotic.py [芝|ダ]

Writes experiments/rank_pace_exotic_<surface>.json and data/rpe_<surface>.pkl (test predictions).
"""
import itertools
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import evaluate, features  # noqa: E402
from model.data import DB  # noqa: E402
from model.gbdt import GBDT  # noqa: E402
from model.data import load_runs  # noqa: E402

SURFACE = sys.argv[1] if len(sys.argv) > 1 else "芝"
KEY = "turf" if SURFACE == "芝" else "dirt"
BASE = features.INDEP_FEATURES
PACE = ["n_front", "lead_pos", "lead_pace", "early_rank", "lone_lead", "style_x_front", "style_x_pace", "style_x_lone"]


def add_pace(F: pd.DataFrame) -> pd.DataFrame:
    g = F.groupby("race_id")
    ep = F["early_pos5"]
    F["n_front"] = (ep < 0.25).groupby(F["race_id"]).transform("sum") / F["field"]
    F["early_rank"] = (g["early_pos5"].rank(method="average") - 1) / (F["field"] - 1).clip(lower=1)
    lead3 = F[F.groupby("race_id")["early_pos5"].rank(method="first") <= 3]
    lp = lead3.groupby("race_id").agg(lead_pos=("early_pos5", "mean"), lead_pace=("pace5", "mean"))
    F = F.join(lp, on="race_id")
    srt = F.sort_values(["race_id", "early_pos5"])
    first = srt.groupby("race_id")["early_pos5"].nth(0)
    second = srt.groupby("race_id")["early_pos5"].nth(1)
    gap = pd.Series(second.to_numpy() - first.to_numpy(), index=srt.groupby("race_id").head(1)["race_id"].to_numpy())
    F["lone_lead"] = ((F["early_rank"] == 0) & (F["race_id"].map(gap) > 0.12)).astype(float)
    st = ep - 0.5
    F["style_x_front"] = st * F["n_front"]
    F["style_x_pace"] = st * F["lead_pace"].fillna(0)
    F["style_x_lone"] = F["lone_lead"] * 1.0
    return F


def stages(F: pd.DataFrame) -> pd.DataFrame:
    """Plackett-Luce top three as three softmax 'races' with the earlier finishers removed."""
    out = [F]
    fin = pd.to_numeric(F["finish"], errors="coerce")
    for k in (2, 3):
        s = F[(fin >= k) | fin.isna()].copy()
        s["finish"] = np.where(pd.to_numeric(s["finish"], errors="coerce") == k, 1, 99)
        s["race_id"] = s["race_id"] + f"_{k}"
        out.append(s)
    return pd.concat(out, ignore_index=True)


def payouts(race_ids) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    p = pd.read_sql("SELECT race_id, bet_type, combo, payout FROM payouts WHERE bet_type IN ('単勝','複勝','馬連','ワイド')", con)
    con.close()
    return p[p["race_id"].isin(set(race_ids))]


def pair_tables(D: pd.DataFrame, col: str) -> pd.DataFrame:
    rows = []
    for rid, d in D.groupby("race_id", sort=False):
        p = d[col].to_numpy(float)
        p = p / p.sum()
        nums = d["number"].to_numpy(int)
        n = len(p)
        q2 = np.zeros((n, n))
        q3 = np.zeros((n, n))
        for a, b, c in itertools.permutations(range(n), 3):
            pr = p[a] * p[b] / (1 - p[a]) * p[c] / (1 - p[a] - p[b])
            q2[a, b] += pr
            q3[a, b] += pr
            q3[a, c] += pr
            q3[b, c] += pr
        for a in range(n):
            for b in range(a + 1, n):
                rows.append((rid, min(nums[a], nums[b]), max(nums[a], nums[b]),
                             q2[a, b] + q2[b, a], q3[a, b] + q3[b, a]))
    return pd.DataFrame(rows, columns=["race_id", "a", "b", f"{col}_q", f"{col}_w"])


def main():
    df = load_runs(DB, surface=SURFACE)
    F = features.build(df, "2018-01")
    F = F[F["odds"].notna() & (F["field"] >= 5)].copy()
    F = add_pace(F)
    y = F["date"].dt.year
    train, valid, test = F[y <= 2022], F[y == 2023], F[y >= 2023]
    res = {}
    preds = test[["race_id", "date", "number", "odds", "finish", "field"]].copy()
    preds["p_mkt"] = evaluate.market_probs(test)
    for name, feats, rank in (("base", BASE, False), ("pace", BASE + PACE, False),
                              ("rank", BASE, True), ("rank_pace", BASE + PACE, True)):
        tr = stages(train) if rank else train
        m = GBDT(feats, rounds=1500, lr=0.05).fit(tr, valid)
        p = m.predict(test)
        preds[f"p_{name}"] = p
        T = test[test["date"].dt.year >= 2024]
        pt = p[(test["date"].dt.year >= 2024).to_numpy()]
        met = evaluate.metrics(T, pt)
        res[name] = {"trees": len(m.trees), "test_logloss": round(met["logloss"], 4),
                     "top_pick_win": round(met["win_hit"], 4), "top_pick_in3": round(met["top_pick_in3"], 4)}
        if name in ("pace", "rank_pace"):
            imp = m.importance()
            res[name]["pace_splits"] = {k: int(v) for k, v in imp.items() if k in PACE}
            res[name]["all_splits"] = int(sum(imp.values()))
        print(name, res[name], flush=True)
    res["market_test_logloss"] = round(evaluate.metrics(test[test["date"].dt.year >= 2024],
                                                         preds.loc[test["date"].dt.year >= 2024, "p_mkt"].to_numpy())["logloss"], 4)
    preds.to_pickle(ROOT / "data" / f"rpe_{KEY}.pkl")
    pays = payouts(preds["race_id"].unique())
    pays.to_pickle(ROOT / "data" / f"rpe_pay_{KEY}.pkl")
    (ROOT / "experiments" / f"rank_pace_exotic_{KEY}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("done", flush=True)


if __name__ == "__main__":
    main()
