"""Train and record models in experiments/log.csv.

    python3 scripts/experiment.py market linear_v1 linear_going gbdt gbdt_going
    python3 scripts/experiment.py --rebuild ...   # rebuild the feature table first
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import evaluate, experiment, features  # noqa: E402
from model.data import load_runs  # noqa: E402
from model.gbdt import GBDT  # noqa: E402
from model.logit import Logit  # noqa: E402

CACHE = ROOT / "data" / "features_turf.pkl"
BASE = [f for f in features.FEATURES if f != "ped_long"]

EXPERIMENTS = {
    "market": ("単勝オッズ（比較用の基準）", None),
    "linear_v1": ("線形モデル（ロジット）：スピード指数・近走・騎手など20項目", ("logit", BASE)),
    "linear_ped": ("linear_v1 ＋ 父・母父の距離適性", ("logit", features.FEATURES)),
    "linear_going": ("linear_ped ＋ 馬場状態（当日の馬場×重馬場の得意不得意）",
                     ("logit", features.FEATURES + features.GOING_FEATURES)),
    "gbdt": ("勾配ブースティング（深さ4の決定木）：linear_ped と同じ項目", ("gbdt", features.FEATURES)),
    "gbdt_going": ("gbdt ＋ 馬場状態", ("gbdt", features.FEATURES + features.GOING_FEATURES)),
    "gbdt_going_rel": ("gbdt_going ＋ 出走馬の平均との差（人気・騎手・指数など6項目）",
                       ("gbdt", features.FEATURES + features.GOING_FEATURES + features.REL_FEATURES)),
}


def main(names):
    if CACHE.exists() and "--rebuild" not in sys.argv:
        F = pd.read_pickle(CACHE)
    else:
        F = features.build(load_runs(), "2018-01")
        F.to_pickle(CACHE)
    F = F[F["odds"].notna() & (F["field"] >= 5)]
    year = F["date"].dt.year
    train, valid, test = F[year <= 2022], F[year == 2023], F[year >= 2024]
    for name in names:
        desc, spec = EXPERIMENTS[name]
        if spec is None:
            predict = evaluate.market_probs
        elif spec[0] == "logit":
            predict = Logit(spec[1]).fit(train).predict
        else:
            m = GBDT(spec[1], rounds=800, lr=0.05, depth=4).fit(train, valid)
            print(name, "trees", len(m.trees), "importance", m.importance())
            predict = m.predict
        row = experiment.record(name, desc, predict, valid, test)
        print(name, {k: v for k, v in row.items() if k.endswith(("logloss", "_win"))}, flush=True)


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("--")])
