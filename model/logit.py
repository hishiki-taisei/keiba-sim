"""Conditional logit: P(horse i wins) = softmax over the field of w . x_i."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _design(df, feats, mu=None, sd=None):
    X = df[feats].to_numpy(float)
    if mu is None:
        mu, sd = X.mean(0), X.std(0) + 1e-9
    return (X - mu) / sd, mu, sd


def softmax_by_race(score, race_codes):
    R = race_codes.max() + 1
    mx = np.full(R, -np.inf)
    np.maximum.at(mx, race_codes, score)
    e = np.exp(score - mx[race_codes])
    return e / np.bincount(race_codes, e, R)[race_codes]


class Logit:
    def __init__(self, feats, l2=1e-3):
        self.feats, self.l2 = feats, l2

    def fit(self, df: pd.DataFrame, iters=500, lr=0.5):
        X, self.mu, self.sd = _design(df, self.feats)
        r = pd.factorize(df["race_id"])[0]
        win = (df["finish"].to_numpy() == 1).astype(float)
        n_races = r.max() + 1
        w = np.zeros(X.shape[1])
        # Plain gradient descent with Adam steps on the mean negative log-likelihood.
        m = v = np.zeros_like(w)
        for t in range(1, iters + 1):
            p = softmax_by_race(X @ w, r)
            grad = X.T @ (p - win) / n_races + self.l2 * w
            m = 0.9 * m + 0.1 * grad
            v = 0.999 * v + 0.001 * grad ** 2
            w -= lr * 0.1 * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
        self.w = w
        return self

    def score(self, df):
        X, _, _ = _design(df, self.feats, self.mu, self.sd)
        return X @ self.w

    def score_without(self, df, drop):
        """Score leaving out some features (ones the simulator models itself, such as style and gate)."""
        X, _, _ = _design(df, self.feats, self.mu, self.sd)
        keep = np.array([f not in drop for f in self.feats])
        return X[:, keep] @ self.w[keep]

    def predict(self, df):
        return softmax_by_race(self.score(df), pd.factorize(df["race_id"])[0])

    def coefs(self):
        return dict(zip(self.feats, np.round(self.w, 3)))
