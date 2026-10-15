"""Train / validate / test the win model on turf races.

    train: 2018-2022   valid: 2023   test: 2024-01 .. today

Prints accuracy against the betting market and writes the numbers to
data/backtest.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import evaluate, features  # noqa: E402
from model.data import load_runs  # noqa: E402
from model.logit import Logit  # noqa: E402

CACHE = ROOT / "data" / "features_turf.pkl"


def subsets(d):
    long_ = d["distance"] >= 2200
    graded = d["grade"].isin(["G1", "G2", "G3"])
    return {"all turf": d, "turf >=2200m": d[long_], "graded": d[graded],
            "菊花賞": d[d["race_name"].str.contains("菊花賞")]}


def main():
    if CACHE.exists() and "--rebuild" not in sys.argv:
        F = pd.read_pickle(CACHE)
    else:
        F = features.build(load_runs(), "2018-01")
        F.to_pickle(CACHE)
    F = F[F["odds"].notna() & (F["field"] >= 5)]
    year = F["date"].dt.year
    train, valid, test = (F[year <= 2022].copy(), F[year == 2023].copy(), F[year >= 2024].copy())

    model = Logit(features.FEATURES).fit(train)
    print("coefficients:", model.coefs())
    # Benter-style blend with the market: softmax(a * model score + b * log market prob).
    for part in (train, valid, test):
        part["m_score"] = model.score(part)
        part["mkt"] = np.log(np.clip(evaluate.market_probs(part), 1e-4, 1))
    blend = Logit(["m_score", "mkt"]).fit(train)
    print("blend:", blend.coefs())
    out = {"coefficients": model.coefs(), "periods": {}}
    for name, part in [("valid 2023", valid), ("test 2024-", test)]:
        res = {}
        for sub, d in subsets(part).items():
            p = model.predict(d)
            pb = blend.predict(d)
            res[sub] = {"model": evaluate.metrics(d, p), "market": evaluate.metrics(d, evaluate.market_probs(d)),
                        "blend": evaluate.metrics(d, pb),
                        "roi_top_pick": evaluate.roi_top_pick(d, p, 1.0),
                        "roi_blend_edge": {e: evaluate.roi_value(d, pb, e) for e in (1.0, 1.2, 1.5)}}
        out["periods"][name] = res
        print(f"\n== {name}")
        for sub, r in res.items():
            m, k = r["model"], r["market"]
            print(f"{sub:14s} races={m['races']:5d}  logloss model {m['logloss']:.3f} / market {k['logloss']:.3f}  "
                  f"win-hit {m['win_hit']:.3f} / {k['win_hit']:.3f}  top3 {m['top_pick_in3']:.3f} / {k['top_pick_in3']:.3f}  "
                  f"ROI(p*odds>=1) {r['roi_top_pick']['roi']:.2f} on {r['roi_top_pick']['bets']}")
            b = r["blend"]
            print(f"{'':14s} blend logloss {b['logloss']:.3f} win-hit {b['win_hit']:.3f}  value bets "
                  + "  ".join(f"edge>={e}: ROI {v['roi']:.2f} on {v['bets']}" for e, v in r["roi_blend_edge"].items()))
    (ROOT / "data" / "backtest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
