"""Calibrate and test the race simulator on long turf races (>= 2400m).

The strength model's score drives top speed; the simulator adds pace, position and
stamina. k_speed / k_stamina are picked on 2023 races and then scored on
2024- races against the strength model alone and the betting market.

    python3 scripts/sim_backtest.py [--n 300] [--record NAME "description"]
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import evaluate, experiment, features  # noqa: E402
from model.gbdt import GBDT  # noqa: E402
from model.to_sim import SimParams, race_probs  # noqa: E402

GRID = [(ks, 0.0, ke) for ks in (0.05, 0.1, 0.2) for ke in (0.0, 0.005, 0.01)] + \
       [(0.1, kst, 0.005) for kst in (0.005, 0.01)]
SIMULATED = ["early_pos5", "gate_rel", "kick5", "early_pos5_rel"]  # the simulator plays these out itself
SIM_FEATURES = [f for f in features.FEATURES + features.GOING_FEATURES + features.REL_FEATURES if f not in SIMULATED]


def sim_score(model, d):
    return model.score(d)


N = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 300


def _one(args):
    rows, score, prm = args
    return race_probs(rows, score, prm, n=N, seed=1)["win"]


def sim_predict(d: pd.DataFrame, score: np.ndarray, prm: SimParams, pool) -> np.ndarray:
    d = d.assign(_s=score)
    groups = [(g, g["_s"].to_numpy(), prm) for _, g in d.groupby("race_id", sort=False)]
    wins = pool.map(_one, groups)
    p = pd.Series(np.concatenate(wins), index=np.concatenate([g.index for g, _, _ in groups]))
    # Floor so a horse that never won in N runs is not scored as impossible.
    p = p.reindex(d.index).clip(lower=0.5 / N)
    return (p / p.groupby(d["race_id"]).transform("sum")).to_numpy()


def main():
    F = pd.read_pickle(ROOT / "data" / "features_turf.pkl")
    F = F[F["odds"].notna() & (F["field"] >= 5)]
    year = F["date"].dt.year
    # Strength model for top speed: gradient boosting without the features the simulator plays out.
    model = GBDT(SIM_FEATURES, rounds=800).fit(F[year <= 2022], F[year == 2023])
    long_ = F["distance"] >= 2400
    valid, test = F[(year == 2023) & long_], F[(year >= 2024) & long_]

    with Pool(4) as pool:
        best = None
        grid = {}
        for ks, kst, ke in GRID:
            prm = SimParams(ks, kst, ke)
            m = evaluate.metrics(valid, sim_predict(valid, sim_score(model, valid), prm, pool))
            grid[f"{ks},{kst},{ke}"] = m["logloss"]
            print(f"k_speed={ks} k_stamina={kst} k_energy={ke}  valid logloss {m['logloss']:.3f} "
                  f"win-hit {m['win_hit']:.3f}", flush=True)
            if best is None or m["logloss"] < best[0]:
                best = (m["logloss"], prm)
        prm = best[1]
        p_sim = sim_predict(test, sim_score(model, test), prm, pool)

    out = {"params": prm.__dict__, "grid": grid, "test": {
        "simulator": evaluate.metrics(test, p_sim),
        "strength model": evaluate.metrics(test, model.predict(test)),
        "market": evaluate.metrics(test, evaluate.market_probs(test)),
        "simulator roi": evaluate.roi_top_pick(test, p_sim, 1.0),
    }}
    for k, v in out["test"].items():
        print(f"test 2024- {k:12s} {v}")
    (ROOT / "data" / "sim_backtest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    if "--record" in sys.argv:
        name, desc = sys.argv[sys.argv.index("--record") + 1:sys.argv.index("--record") + 3]
        experiment.record_sim(name, desc, out["test"]["simulator"], out["test"]["strength model"])


if __name__ == "__main__":
    main()
