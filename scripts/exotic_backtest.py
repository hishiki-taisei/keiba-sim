"""Quinella (馬連) and wide (ワイド) bets from the odds-free models, after scripts/rank_pace_exotic.py.

Pair probabilities come from Harville on each model's win probabilities, and the market's from
Harville on the win odds (the pair odds of the day are not in the DB). A pair is bought when the
model's probability is at least k times the market's; real payouts settle it. Thresholds are
chosen on 2023 and reported on 2024-.

    python3 scripts/exotic_backtest.py [turf|dirt]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KEY = sys.argv[1] if len(sys.argv) > 1 else "turf"
MODELS = ["mkt", "base", "pace", "rank", "rank_pace"]


def pair_matrices(p: np.ndarray):
    p = p / p.sum()
    n = len(p)
    a = p[:, None, None]
    b = p[None, :, None]
    c = p[None, None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        T = a * b / (1 - a) * c / (1 - a - b)  # P(order a, b, c)
    i = np.arange(n)
    T[i, i, :] = 0
    T[i, :, i] = 0
    T[:, i, i] = 0
    T = np.nan_to_num(T)
    first_two = T.sum(2)  # a first, b second
    q = first_two + first_two.T
    w = T.sum(2) + T.sum(1) + T.sum(0)  # a,b in the top three with a before b (any slots)
    w = w + w.T
    return q, w


def build(P: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rid, d in P.groupby("race_id", sort=False):
        nums = d["number"].to_numpy(int)
        mats = {m: pair_matrices(d[f"p_{m}"].to_numpy(float)) for m in MODELS}
        iu = np.triu_indices(len(nums), 1)
        block = {"race_id": rid, "date": d["date"].iloc[0],
                 "a": np.minimum(nums[iu[0]], nums[iu[1]]), "b": np.maximum(nums[iu[0]], nums[iu[1]])}
        for m, (q, w) in mats.items():
            block[f"q_{m}"] = q[iu]
            block[f"w_{m}"] = w[iu]
        rows.append(pd.DataFrame(block))
    return pd.concat(rows, ignore_index=True)


def settle(X: pd.DataFrame, pay: pd.DataFrame) -> pd.DataFrame:
    for bt, col in (("馬連", "pay_q"), ("ワイド", "pay_w")):
        p = pay[pay["bet_type"] == bt].copy()
        ab = p["combo"].str.split("-", expand=True)
        p["a"] = pd.to_numeric(ab[0], errors="coerce")
        p["b"] = pd.to_numeric(ab[1], errors="coerce")
        p = p.dropna(subset=["a", "b"])
        p[["a", "b"]] = np.sort(p[["a", "b"]].to_numpy(int), axis=1)
        p = p.groupby(["race_id", "a", "b"])["payout"].sum().rename(col).reset_index()
        X = X.merge(p, on=["race_id", "a", "b"], how="left")
        X[col] = X[col].fillna(0)
    return X


def roi(sel, col):
    r = sel[col].to_numpy()
    n = len(r)
    return {"n": int(n), "hits": int((r > 0).sum()), "roi": round(float(r.mean()), 1) if n else None,
            "se": round(float(r.std(ddof=1) / np.sqrt(n)), 1) if n > 1 else None}


def main():
    P = pd.read_pickle(ROOT / "data" / f"rpe_{KEY}.pkl")
    P = P.rename(columns={"p_mkt": "p_mkt"})
    pay = pd.read_pickle(ROOT / "data" / f"rpe_pay_{KEY}.pkl")
    X = settle(build(P), pay)
    X["year"] = pd.to_datetime(X["date"]).dt.year
    out = {}
    # how well each model prices pairs: log loss of the pair that came in (quinella)
    for m in MODELS:
        win_pairs = X[(X["year"] >= 2024) & (X["pay_q"] > 0)]
        out[f"pair_logloss_{m}"] = round(float(-np.log(np.clip(win_pairs[f"q_{m}"], 1e-6, 1)).mean()), 4)
    grid = []
    for m in MODELS[1:]:
        for kind, prob, col in (("馬連", "q", "pay_q"), ("ワイド", "w", "pay_w")):
            ratio = X[f"{prob}_{m}"] / X[f"{prob}_mkt"]
            for k in (1.5, 2, 3, 4):
                for lo, hi in ((0.01, 0.05), (0.02, 0.1), (0.05, 0.3)) if kind == "ワイド" else ((0.003, 0.02), (0.005, 0.05), (0.01, 0.1)):
                    sel = (ratio >= k) & (X[f"{prob}_mkt"] >= lo) & (X[f"{prob}_mkt"] < hi)
                    v = roi(X[sel & (X["year"] == 2023)], col)
                    t = roi(X[sel & (X["year"] >= 2024)], col)
                    grid.append({"model": m, "bet": kind, "k": k, "mkt_range": [lo, hi], "valid": v, "test": t})
    out["grid"] = grid
    # the best rule per model and bet on 2023 (at least 100 bets), reported on 2024-
    best = {}
    for m in MODELS[1:]:
        for kind in ("馬連", "ワイド"):
            cand = [g for g in grid if g["model"] == m and g["bet"] == kind and g["valid"]["n"] >= 100]
            if cand:
                g = max(cand, key=lambda g: g["valid"]["roi"])
                best[f"{m}/{kind}"] = g
    out["best_on_2023"] = best
    (ROOT / "experiments" / f"exotic_{KEY}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "grid"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
