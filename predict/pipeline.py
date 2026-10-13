"""Shared steps of the backtest and the race prediction."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from . import features
from .evaluate import market_prob
from .gbm import RaceGBM
from .model import race_softmax

# settled by the PDCA rounds in reports/pdca.md
GBM_PARAMS = dict(learning_rate=0.05, max_depth=4, colsample=0.5)
RESID_PARAMS = dict(learning_rate=0.02, max_depth=3, colsample=0.5)
SEEDS = (1, 2, 3)


def coverage_start(dates: pd.Series) -> pd.Timestamp:
    """First day after the last gap of more than 60 days (older stray races are skipped)."""
    d = np.sort(dates.unique())
    gaps = np.flatnonzero(np.diff(d) > np.timedelta64(60, "D"))
    return pd.Timestamp(d[gaps[-1] + 1] if len(gaps) else d[0])


def scorable(df: pd.DataFrame) -> pd.DataFrame:
    """Finished races with a winner and odds for every starter, plus market probability."""
    ok = df.groupby("race_id").agg(w=("finish", lambda s: (s == 1).any()), o=("odds", lambda s: s.notna().all()))
    df = df[df.race_id.isin(ok[ok.w & ok.o].index)].reset_index(drop=True)
    df["mkt"] = market_prob(df)
    return df


def training_rows(df: pd.DataFrame) -> pd.DataFrame:
    # the first months have almost no history to build features from
    return df[df.date >= coverage_start(df.date) + pd.DateOffset(months=6)]


def _won(d):
    return (d.finish == 1).to_numpy()


def _fit_one(args):
    train, valid, params, seed, n_trees, resid = args
    cols = features.FEATURES
    init = (lambda d: np.log(d.mkt.to_numpy())) if resid else (lambda d: None)
    v = None if valid is None else (valid[cols].to_numpy(), valid.race_id.to_numpy(), _won(valid), init(valid))
    return RaceGBM(cols, n_trees=n_trees, seed=seed, **params).fit(
        train[cols].to_numpy(), train.race_id.to_numpy(), _won(train), init=init(train), valid=v)


class Ensemble:
    """Average of RaceGBM scores over several seeds."""

    def __init__(self, models, resid=False):
        self.models, self.resid = models, resid

    @classmethod
    def fit(cls, train, valid=None, n_trees=2000, resid=False, seeds=SEEDS):
        params = RESID_PARAMS if resid else GBM_PARAMS
        jobs = [(train, valid, params, s, n_trees, resid) for s in seeds]
        with ProcessPoolExecutor(min(len(jobs), 4)) as ex:
            return cls(list(ex.map(_fit_one, jobs)), resid)

    @property
    def n_trees(self):
        return int(np.mean([len(m.trees) for m in self.models]))

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        X = d[features.FEATURES].to_numpy()
        init = np.log(d.mkt.to_numpy()) if self.resid else None
        s = np.mean([m.score(X, init) for m in self.models], 0)
        return race_softmax(s, d.race_id.to_numpy())

    def importance(self) -> dict[str, int]:
        tot = {}
        for m in self.models:
            for k, v in m.importance().items():
                tot[k] = tot.get(k, 0) + v
        return dict(sorted(tot.items(), key=lambda kv: -kv[1]))
