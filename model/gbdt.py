"""Gradient-boosted trees for the per-race win probability, in plain numpy.

Same objective as the linear model (softmax over the runners of each race),
but each round fits a small regression tree to the gradient, so the model can
pick up thresholds and interactions (e.g. "strong rating AND long distance").
Features are cut into quantile bins once, and split search uses per-node
histograms built with np.bincount.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .logit import softmax_by_race

N_BINS = 32


class GBDT:
    def __init__(self, feats, rounds=400, lr=0.05, depth=4, lam=1.0, min_hess=20.0, seed=0, base=None):
        """``base``: optional function df -> starting score (e.g. log market probability), so the
        trees learn only the correction on top of it."""
        self.feats, self.rounds, self.lr, self.depth = feats, rounds, lr, depth
        self.base = base
        self.lam, self.min_hess = lam, min_hess
        self.rng = np.random.default_rng(seed)

    # -- binning -----------------------------------------------------------
    def _fit_bins(self, X):
        self.edges = [np.unique(np.nanquantile(X[:, j], np.linspace(0, 1, N_BINS + 1)[1:-1]))
                      for j in range(X.shape[1])]

    def _bin(self, X):
        return np.stack([np.searchsorted(e, X[:, j], side="right") for j, e in enumerate(self.edges)], 1)

    # -- one tree ----------------------------------------------------------
    def _tree(self, B, g, h):
        n, F = B.shape
        node = np.zeros(n, dtype=np.int64)
        splits = []  # per level: arrays (feature, threshold bin) per node; -1 = leaf
        n_nodes = 1
        for _ in range(self.depth):
            G = np.bincount(node, g, n_nodes)
            H = np.bincount(node, h, n_nodes)
            best_gain = np.zeros(n_nodes)
            best_f = np.full(n_nodes, -1)
            best_t = np.zeros(n_nodes, dtype=np.int64)
            parent = G ** 2 / (H + self.lam)
            for f in range(F):
                key = node * N_BINS + B[:, f]
                gh = np.bincount(key, g, n_nodes * N_BINS).reshape(n_nodes, N_BINS)
                hh = np.bincount(key, h, n_nodes * N_BINS).reshape(n_nodes, N_BINS)
                GL, HL = np.cumsum(gh, 1)[:, :-1], np.cumsum(hh, 1)[:, :-1]
                GR, HR = G[:, None] - GL, H[:, None] - HL
                gain = GL ** 2 / (HL + self.lam) + GR ** 2 / (HR + self.lam) - parent[:, None]
                gain[(HL < self.min_hess) | (HR < self.min_hess)] = 0.0
                t = gain.argmax(1)
                gbest = gain[np.arange(n_nodes), t]
                better = gbest > best_gain
                best_gain[better], best_f[better], best_t[better] = gbest[better], f, t[better]
            splits.append((best_f.copy(), best_t.copy()))
            go_right = (best_f[node] >= 0) & (B[np.arange(n), np.maximum(best_f[node], 0)] > best_t[node])
            node = node * 2 + go_right
            n_nodes *= 2
        G = np.bincount(node, g, n_nodes)
        H = np.bincount(node, h, n_nodes)
        leaf = -G / (H + self.lam) * self.lr
        return splits, leaf

    @staticmethod
    def _apply(tree, B):
        splits, leaf = tree
        n = len(B)
        node = np.zeros(n, dtype=np.int64)
        for f, t in splits:
            go_right = (f[node] >= 0) & (B[np.arange(n), np.maximum(f[node], 0)] > t[node])
            node = node * 2 + go_right
        return leaf[node]

    # -- training ----------------------------------------------------------
    def fit(self, train: pd.DataFrame, valid: pd.DataFrame | None = None, patience=50, verbose=False):
        X = train[self.feats].to_numpy(float)
        self._fit_bins(X)
        B = self._bin(X)
        r = pd.factorize(train["race_id"])[0]
        y = (train["finish"].to_numpy() == 1).astype(float)
        score = self._base(train)
        if valid is not None:
            Bv = self._bin(valid[self.feats].to_numpy(float))
            rv = pd.factorize(valid["race_id"])[0]
            yv = valid["finish"].to_numpy() == 1
            sv = self._base(valid)
        self.trees, best, best_i = [], np.inf, 0
        self.history = []
        for i in range(self.rounds):
            p = softmax_by_race(score, r)
            g, h = p - y, np.maximum(p * (1 - p), 1e-6)
            tree = self._tree(B, g, h)
            self.trees.append(tree)
            score += self._apply(tree, B)
            if valid is not None:
                sv += self._apply(tree, Bv)
                ll = float(-np.log(np.clip(softmax_by_race(sv, rv)[yv], 1e-6, 1)).mean())
                self.history.append(ll)
                if verbose and i % 25 == 0:
                    print(f"round {i} valid logloss {ll:.4f}", flush=True)
                if ll < best - 1e-5:
                    best, best_i = ll, i
                elif i - best_i >= patience:
                    break
        if valid is not None:
            self.trees = self.trees[: best_i + 1]
        return self

    def _base(self, df):
        return np.asarray(self.base(df), dtype=float) if self.base is not None else np.zeros(len(df))

    def score(self, df):
        B = self._bin(df[self.feats].to_numpy(float))
        return self._base(df) + sum(self._apply(t, B) for t in self.trees)

    def predict(self, df):
        return softmax_by_race(self.score(df), pd.factorize(df["race_id"])[0])

    def importance(self):
        """How often each feature is used for a split."""
        cnt = np.zeros(len(self.feats))
        for splits, _ in self.trees:
            for f, _ in splits:
                for j in f[f >= 0]:
                    cnt[j] += 1
        return dict(sorted(zip(self.feats, cnt.astype(int)), key=lambda kv: -kv[1]))
