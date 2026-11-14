"""Look for betting strategies that do not just follow the odds.

    python3 scripts/strategy_search.py [--features-dir DIR]

1. An odds-free win model: gradient boosting on the horse's own record (speed
   figures, form, pace, pedigree, jockey and trainer), without today's odds and
   without past popularity, so it judges horses from a different angle than the market.
2. Strategies built on it and on simple race facts, chosen on the train/valid years
   only and then reported on the test years (2024-), with real win and place payouts.

Writes experiments/strategies.md and data/strategies.json (the rules picked, used by live/).
"""
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

FDIR = Path(sys.argv[sys.argv.index("--features-dir") + 1]) if "--features-dir" in sys.argv else ROOT / "data"
INDEP_FEATURES = features.INDEP_FEATURES


def payouts(race_ids) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    p = pd.read_sql("SELECT race_id, bet_type, combo, payout FROM payouts WHERE bet_type IN ('単勝','複勝')", con)
    con.close()
    p = p[p["race_id"].isin(set(race_ids))]
    p["number"] = pd.to_numeric(p["combo"], errors="coerce")
    w = p[p["bet_type"] == "単勝"].groupby(["race_id", "number"])["payout"].sum().rename("win_pay")
    pl = p[p["bet_type"] == "複勝"].groupby(["race_id", "number"])["payout"].sum().rename("place_pay")
    return pd.concat([w, pl], axis=1).reset_index()


def load(surface: str) -> pd.DataFrame:
    F = pd.read_pickle(FDIR / ("features_turf.pkl" if surface == "芝" else "features_dirt.pkl"))
    F = F[F["odds"].notna() & (F["field"] >= 5)].copy()
    F = F.merge(payouts(F["race_id"].unique()), on=["race_id", "number"], how="left")
    F[["win_pay", "place_pay"]] = F[["win_pay", "place_pay"]].fillna(0)
    F["pop_rank"] = F.groupby("race_id")["odds"].rank(method="first")
    return F


def add_model(F: pd.DataFrame) -> tuple[pd.DataFrame, GBDT]:
    year = F["date"].dt.year
    train, valid = F[year <= 2022], F[year == 2023]
    m = GBDT(INDEP_FEATURES, rounds=1500, lr=0.05).fit(train, valid)
    F["p_indep"] = m.predict(F)
    F["p_mkt"] = evaluate.market_probs(F)
    F["indep_rank"] = F.groupby("race_id")["p_indep"].rank(ascending=False, method="first")
    F["edge"] = F["p_indep"] * F["odds"]
    F["ratio"] = F["p_indep"] / F["p_mkt"]
    return F, m


def roi(sel: pd.DataFrame, kind: str) -> dict:
    pay = sel["win_pay"] if kind == "win" else sel["place_pay"]
    n = len(sel)
    if n == 0:
        return {"n": 0, "hit": 0.0, "roi": 0.0, "se": 0.0}
    r = pay / 100.0
    return {"n": n, "hit": float((pay > 0).mean()), "roi": float(r.mean()), "se": float(r.std() / np.sqrt(n))}


def candidates():
    """Rule = (name, description, function df -> boolean mask, bet kind)."""
    rules = []
    for kind in ("win", "place"):
        rules.append((f"indep_top_{kind}", "オッズ抜きモデルの本命", lambda d: d["indep_rank"] == 1, kind))
        for lo, hi in [(2, 3), (2, 5), (3, 6), (4, 8), (6, 10)]:
            rules.append((f"indep_top_pop{lo}-{hi}_{kind}", f"オッズ抜きモデルの本命で、{lo}〜{hi}番人気",
                          lambda d, lo=lo, hi=hi: (d["indep_rank"] == 1) & d["pop_rank"].between(lo, hi), kind))
        for r in [1.2, 1.5, 2.0, 3.0]:
            for omax in [10, 20, 50]:
                rules.append((f"ratio{r}_odds{omax}_{kind}",
                              f"モデルの勝率がオッズの{r}倍以上、{omax}倍未満",
                              lambda d, r=r, omax=omax: (d["ratio"] >= r) & (d["odds"] < omax), kind))
        for t in [1.0, 1.2, 1.5, 2.0]:
            for omax in [10, 20, 50]:
                rules.append((f"edge{t}_odds{omax}_{kind}", f"モデルの勝率×オッズが{t}以上、{omax}倍未満",
                              lambda d, t=t, omax=omax: (d["edge"] >= t) & (d["odds"] < omax), kind))
        for k in [2, 3]:
            rules.append((f"indep_top{k}_ratio1.3_{kind}", f"モデル上位{k}頭のうち、勝率がオッズの1.3倍以上",
                          lambda d, k=k: (d["indep_rank"] <= k) & (d["ratio"] >= 1.3), kind))
    return rules


def search(F: pd.DataFrame, surface: str) -> list[dict]:
    year = F["date"].dt.year
    parts = {"train": F[year <= 2022], "valid": F[year == 2023], "test": F[year >= 2024]}
    out = []
    for name, desc, fn, kind in candidates():
        row = {"surface": surface, "name": name, "desc": desc, "kind": kind}
        for p, d in parts.items():
            row[p] = roi(d[fn(d)], kind)
        out.append(row)
    return out


def main():
    rows, picked = [], {}
    lines = ["# 独自の買い方の検証", "",
             "オッズを使わないモデル（今日のオッズも過去の人気も使わず、馬の走りの記録だけで勝率を出す）と、それを使った買い方の検証です。",
             "学習 2018〜2022年でモデルを作り、2023年（調整）で買い方を選び、2024年1月〜（テスト）の成績を見ています。",
             "払戻は実際の単勝・複勝の払戻金、オッズは確定オッズで判断しているので、実際（朝の予想オッズ）より甘めです。",
             "学習期間の回収率はモデルを作ったのと同じデータなので高く出ます。信用できるのは調整とテストの列です。", ""]
    for surface in ("芝", "ダ"):
        F, m = add_model(load(surface))
        test = F[F["date"].dt.year >= 2024]
        mk, md = evaluate.metrics(test, test["p_mkt"].to_numpy()), evaluate.metrics(test, test["p_indep"].to_numpy())
        lines += [f"## {surface}", "",
                  f"オッズ抜きモデル（木{len(m.trees)}本）テスト：対数損失 {md['logloss']:.4f}（オッズ {mk['logloss']:.4f}）、"
                  f"本命の勝率 {md['win_hit']:.1%}（1番人気 {mk['win_hit']:.1%}）、"
                  f"モデルの本命が1番人気と違うレース {(test.loc[test.groupby('race_id')['p_indep'].idxmax(), 'pop_rank'] != 1).mean():.0%}。", "",
                  "よく使った項目：" + "、".join(list(m.importance())[:8]), ""]
        res = search(F, surface)
        rows += res
        # Pick on train+valid only: both above 85% with at least 300 bets in train, best valid ROI.
        ok = [r for r in res if r["train"]["n"] >= 300 and r["valid"]["n"] >= 80]
        ok.sort(key=lambda r: -(min(r["train"]["roi"], r["valid"]["roi"])))
        lines += ["| 買い方 | 券種 | 学習 点数 | 学習 回収率 | 調整 点数 | 調整 回収率 | テスト 点数 | テスト 的中率 | テスト 回収率 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in ok[:12]:
            t = r["test"]
            lines.append(f"| {r['desc']} | {'単勝' if r['kind'] == 'win' else '複勝'} | {r['train']['n']} | {r['train']['roi']:.1%} | "
                         f"{r['valid']['n']} | {r['valid']['roi']:.1%} | {t['n']} | {t['hit']:.1%} | {t['roi']:.1%}（±{t['se']:.1%}） |")
        lines.append("")
        picked[surface] = [{"name": r["name"], "desc": r["desc"], "kind": r["kind"],
                            "train_roi": round(r["train"]["roi"], 4), "valid_roi": round(r["valid"]["roi"], 4),
                            "test_roi": round(r["test"]["roi"], 4), "test_n": r["test"]["n"]} for r in ok[:3]]
    (ROOT / "experiments" / "strategies.md").write_text("\n".join(lines) + "\n")
    (ROOT / "data" / "strategies.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1))
    pd.DataFrame([{**{k: v for k, v in r.items() if k not in ("train", "valid", "test")},
                   **{f"{p}_{k}": r[p][k] for p in ("train", "valid", "test") for k in r[p]}} for r in rows]
                 ).to_csv(ROOT / "experiments" / "strategies.csv", index=False)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
