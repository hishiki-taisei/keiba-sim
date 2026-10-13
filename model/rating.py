"""Within-race speed rating.

For every run we take the runner's average speed relative to the race median
(in percent), so the course, going and pace of that day cancel out. Each horse
gets an ability ``a`` and a distance slope ``b`` (better or worse per doubling
of distance), and the model explains each run as

    y = a_h + b_h * log2(dist / 2000) + c * (weight carried - field mean)
        - (the same quantity averaged over the field)

Horses are linked through the opponents they have met, so a horse that keeps
finishing close to G1 winners is rated near them. Recent runs weigh more
(``half_life`` days). Solved with conjugate gradients in plain numpy.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CLIP = (-5.0, 3.0)


@dataclass
class Rating:
    horse_index: dict
    a: np.ndarray
    b: np.ndarray
    c: float
    n_runs: np.ndarray

    def predict(self, horse_ids, distance: float) -> tuple[np.ndarray, np.ndarray]:
        """Ability at ``distance`` for each horse (0 for unknown horses) and its run count."""
        x = np.log2(distance / 2000.0)
        idx = np.array([self.horse_index.get(h, -1) for h in horse_ids])
        known = idx >= 0
        val = np.zeros(len(idx))
        n = np.zeros(len(idx), dtype=int)
        val[known] = self.a[idx[known]] + self.b[idx[known]] * x
        n[known] = self.n_runs[idx[known]]
        return val, n


def relative_speed(df: pd.DataFrame) -> np.ndarray:
    med = df.groupby("race_id")["speed"].transform("median")
    return np.clip(100.0 * (df["speed"] / med - 1.0), *CLIP).to_numpy()


def fit(df: pd.DataFrame, asof: pd.Timestamp, half_life: float = 180.0,
        lam_a: float = 1.0, lam_b: float = 4.0, iters: int = 200) -> Rating:
    """Fit on runs strictly before ``asof``."""
    d = df[df["date"] < asof]
    d = d[d.groupby("race_id")["number"].transform("size") >= 3]
    horses, h = np.unique(d["horse_id"].to_numpy(), return_inverse=True)
    _, r = np.unique(d["race_id"].to_numpy(), return_inverse=True)
    H, R = len(horses), r.max() + 1
    x = np.log2(d["distance"].to_numpy() / 2000.0)
    w_kg = d["weight_carried"].to_numpy() - d.groupby("race_id")["weight_carried"].transform("mean").to_numpy()
    y = relative_speed(d)
    age_days = (asof - d["date"]).dt.days.to_numpy()
    wt = 0.5 ** (age_days / half_life)
    cnt = np.bincount(r, minlength=R)

    def demean(v):
        return v - (np.bincount(r, v, R) / cnt)[r]

    def X(theta):
        a, b, c = theta[:H], theta[H:2 * H], theta[-1]
        return a[h] + b[h] * x + c * w_kg

    def XT(u):
        return np.concatenate([np.bincount(h, u, H), np.bincount(h, u * x, H), [np.dot(u, w_kg)]])

    lam = np.concatenate([np.full(H, lam_a), np.full(H, lam_b), [0.0]])

    def A(theta):  # normal-equation operator, demean is a symmetric projection
        return XT(demean(wt * demean(X(theta)))) + lam * theta

    rhs = XT(demean(wt * demean(y)))
    theta = np.zeros(2 * H + 1)
    res = rhs - A(theta)
    p = res.copy()
    rs = res @ res
    for _ in range(iters):
        Ap = A(p)
        alpha = rs / (p @ Ap)
        theta += alpha * p
        res -= alpha * Ap
        rs_new = res @ res
        if np.sqrt(rs_new) < 1e-6 * np.sqrt(rhs @ rhs):
            break
        p = res + (rs_new / rs) * p
        rs = rs_new

    return Rating(horse_index={k: i for i, k in enumerate(horses)},
                  a=theta[:H], b=theta[H:2 * H], c=float(theta[-1]),
                  n_runs=np.bincount(h, minlength=H))
