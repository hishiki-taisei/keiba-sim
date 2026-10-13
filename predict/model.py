"""Conditional logit (multinomial logit within each race).

P(horse i wins race r) = exp(w . x_i) / sum_{j in r} exp(w . x_j)

This is the classic model for race prediction (Bolton & Chapman, Benter): it
compares runners inside the same race, so anything shared by the whole field
cancels out. Fitted with Newton's method and an L2 penalty, numpy only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np


def _race_index(race_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rows must be grouped by race. Returns (start offset per race, race number per row)."""
    change = np.r_[True, race_ids[1:] != race_ids[:-1]]
    starts = np.flatnonzero(change)
    return starts, np.cumsum(change) - 1


def race_softmax(score: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    starts, rix = _race_index(race_ids)
    mx = np.maximum.reduceat(score, starts)
    e = np.exp(score - mx[rix])
    return e / np.add.reduceat(e, starts)[rix]


@dataclass
class ConditionalLogit:
    features: list[str]
    l2: float = 1.0
    mean: np.ndarray | None = None
    scale: np.ndarray | None = None
    coef: np.ndarray | None = None
    history: list[float] = field(default_factory=list)

    def _x(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / self.scale

    def fit(self, X: np.ndarray, race_ids: np.ndarray, won: np.ndarray, iters: int = 30):
        """won: 1 for the winner(s) of each race, else 0. Rows grouped by race."""
        X = np.asarray(X, float)
        self.mean = X.mean(0)
        self.scale = X.std(0) + 1e-9
        Z = self._x(X)
        starts, rix = _race_index(race_ids)
        n_races = len(starts)
        # target distribution per race (dead heats share the win)
        won = np.asarray(won, float)
        tot = np.add.reduceat(won, starts)
        if (tot == 0).any():
            raise ValueError("every race needs a winner")
        y = won / tot[rix]
        w = np.zeros(Z.shape[1])
        self.history = []
        for _ in range(iters):
            p = race_softmax(Z @ w, race_ids)
            ll = (y * np.log(p + 1e-300)).sum() - 0.5 * self.l2 * w @ w
            self.history.append(-ll / n_races)
            # gradient: sum over winners of x - E_p[x]
            m = np.add.reduceat(p[:, None] * Z, starts)  # E_p[x] per race
            grad = y @ Z - m.sum(0) - self.l2 * w
            H = Z.T @ (p[:, None] * Z) - m.T @ m + self.l2 * np.eye(len(w))
            step = np.linalg.solve(H, grad)
            w = w + step
            if np.abs(step).max() < 1e-7:
                break
        self.coef = w
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        return self._x(np.asarray(X, float)) @ self.coef

    def predict(self, X: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
        return race_softmax(self.score(X), race_ids)

    def coefficients(self) -> dict[str, float]:
        return {f: round(float(c), 4) for f, c in zip(self.features, self.coef)}

    def to_json(self) -> str:
        return json.dumps({"features": self.features, "l2": self.l2, "mean": self.mean.tolist(),
                           "scale": self.scale.tolist(), "coef": self.coef.tolist()},
                          ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "ConditionalLogit":
        d = json.loads(s)
        return cls(features=d["features"], l2=d["l2"], mean=np.array(d["mean"]),
                   scale=np.array(d["scale"]), coef=np.array(d["coef"]))
