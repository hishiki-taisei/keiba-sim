"""Gradient-boosted trees with a per-race softmax loss, numpy only.

Same objective as the conditional logit (the winner's share of exp(score)
inside its race), but the score is a sum of small regression trees, so it can
pick up thresholds and interactions the linear model cannot. Histogram-based:
features are bucketed into at most `n_bins` quantile bins once up front.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field

import numpy as np

from .model import _race_index, race_softmax


def _bin_edges(X: np.ndarray, n_bins: int) -> list[np.ndarray]:
    qs = np.linspace(0, 1, n_bins + 1)[1:-1]
    return [np.unique(np.quantile(X[:, j], qs)) for j in range(X.shape[1])]


def _apply_bins(X: np.ndarray, edges: list[np.ndarray]) -> np.ndarray:
    return np.stack([np.searchsorted(e, X[:, j], side="right") for j, e in enumerate(edges)], 1).astype(np.uint8)


@dataclass
class _Tree:
    feature: np.ndarray  # -1 for a leaf
    threshold: np.ndarray  # go left when bin <= threshold
    left: np.ndarray
    right: np.ndarray
    value: np.ndarray

    def predict(self, B: np.ndarray) -> np.ndarray:
        node = np.zeros(len(B), dtype=np.int32)
        while True:
            f = self.feature[node]
            inner = f >= 0
            if not inner.any():
                return self.value[node]
            idx = np.flatnonzero(inner)
            go_left = B[idx, f[idx]] <= self.threshold[node[idx]]
            node[idx] = np.where(go_left, self.left[node[idx]], self.right[node[idx]])


@dataclass
class RaceGBM:
    features: list[str]
    n_trees: int = 500
    learning_rate: float = 0.05
    max_depth: int = 4
    min_hess: float = 20.0
    l2: float = 10.0
    subsample: float = 0.7
    colsample: float = 0.8
    n_bins: int = 48
    seed: int = 0
    edges: list = field(default_factory=list)
    trees: list = field(default_factory=list)
    best_iter: int | None = None
    history: list = field(default_factory=list)

    def _build_tree(self, B, g, h, rng) -> _Tree:
        n, F = B.shape
        nb = self.n_bins
        cols = np.sort(rng.choice(F, max(1, int(F * self.colsample)), replace=False))
        feat, thr, left, right, val = [], [], [], [], []

        def new_node():
            for a in (feat, thr, left, right, val):
                a.append(0)
            feat[-1] = -1
            return len(feat) - 1

        root = new_node()
        frontier = [(root, np.arange(n))]
        for depth in range(self.max_depth + 1):
            nxt = []
            for node, idx in frontier:
                G, H = g[idx].sum(), h[idx].sum()
                val[node] = -G / (H + self.l2)
                if depth == self.max_depth or H < 2 * self.min_hess:
                    continue
                sub = B[idx][:, cols].astype(np.int64) + np.arange(len(cols)) * nb
                hg = np.bincount(sub.ravel(), np.broadcast_to(g[idx][:, None], sub.shape).ravel(),
                                 minlength=len(cols) * nb).reshape(len(cols), nb)
                hh = np.bincount(sub.ravel(), np.broadcast_to(h[idx][:, None], sub.shape).ravel(),
                                 minlength=len(cols) * nb).reshape(len(cols), nb)
                GL, HL = np.cumsum(hg, 1)[:, :-1], np.cumsum(hh, 1)[:, :-1]
                GR, HR = G - GL, H - HL
                gain = GL ** 2 / (HL + self.l2) + GR ** 2 / (HR + self.l2) - G ** 2 / (H + self.l2)
                gain[(HL < self.min_hess) | (HR < self.min_hess)] = -np.inf
                j, t = np.unravel_index(np.argmax(gain), gain.shape)
                if not np.isfinite(gain[j, t]) or gain[j, t] <= 1e-6:
                    continue
                f = cols[j]
                go_left = B[idx, f] <= t
                feat[node], thr[node] = f, t
                left[node], right[node] = new_node(), new_node()
                nxt += [(left[node], idx[go_left]), (right[node], idx[~go_left])]
            frontier = nxt
        return _Tree(np.array(feat), np.array(thr), np.array(left), np.array(right),
                     np.array(val) * self.learning_rate)

    def fit(self, X, race_ids, won, init=None, valid=None, early_stop: int = 50, verbose: int = 0):
        """valid: optional (X, race_ids, won, init) used for early stopping on log-loss."""
        rng = np.random.default_rng(self.seed)
        X = np.asarray(X, float)
        self.edges = _bin_edges(X, self.n_bins)
        B = _apply_bins(X, self.edges)
        starts, rix = _race_index(race_ids)
        won = np.asarray(won, float)
        y = won / np.add.reduceat(won, starts)[rix]
        F = np.zeros(len(X)) if init is None else np.asarray(init, float).copy()
        if valid is not None:
            vX, vr, vw, vinit = valid
            vB = _apply_bins(np.asarray(vX, float), self.edges)
            vF = np.zeros(len(vB)) if vinit is None else np.asarray(vinit, float).copy()
            vw = np.asarray(vw) == 1
            vrace = np.unique(vr, return_inverse=True)[1][vw]
        n_races = len(starts)
        self.trees, self.history = [], []
        best = (np.inf, 0)
        for it in range(self.n_trees):
            p = race_softmax(F, race_ids)
            g, h = p - y, np.maximum(p * (1 - p), 1e-6)
            # row subsampling by race keeps each race's softmax intact
            keep = rng.random(n_races) < self.subsample
            idx = np.flatnonzero(keep[rix])
            tree = self._build_tree(B[idx], g[idx], h[idx], rng)
            self.trees.append(tree)
            F += tree.predict(B)
            if valid is not None:
                vF += tree.predict(vB)
                vp = race_softmax(vF, vr)
                vll = -np.log(np.bincount(vrace, vp[vw])).mean()
                self.history.append(vll)
                if verbose and it % verbose == 0:
                    print(it, round(vll, 4))
                if vll < best[0]:
                    best = (vll, it + 1)
                elif it + 1 - best[1] >= early_stop:
                    break
        if valid is not None:
            self.best_iter = best[1]
            self.trees = self.trees[: best[1]]
        return self

    def score(self, X, init=None) -> np.ndarray:
        B = _apply_bins(np.asarray(X, float), self.edges)
        s = np.zeros(len(B)) if init is None else np.asarray(init, float).copy()
        for t in self.trees:
            s += t.predict(B)
        return s

    def predict(self, X, race_ids, init=None) -> np.ndarray:
        return race_softmax(self.score(X, init), race_ids)

    def importance(self) -> dict[str, int]:
        c = np.zeros(len(self.features), int)
        for t in self.trees:
            for f in t.feature[t.feature >= 0]:
                c[f] += 1
        return dict(sorted(zip(self.features, c.tolist()), key=lambda kv: -kv[1]))

    def save(self, path):
        with open(path, "wb") as f:
            pickle.dump(self, f)
