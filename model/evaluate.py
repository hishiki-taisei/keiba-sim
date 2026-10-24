"""Metrics for win probabilities, compared against the betting market."""
from __future__ import annotations

import numpy as np
import pandas as pd


def market_probs(df: pd.DataFrame) -> np.ndarray:
    inv = 1.0 / df["odds"].where(df["odds"] > 0)
    return (inv / inv.groupby(df["race_id"]).transform("sum")).fillna(0).to_numpy()


def metrics(df: pd.DataFrame, p: np.ndarray) -> dict:
    d = df.assign(p=p)
    win = d[d["finish"] == 1]
    top_pick = d.loc[d.groupby("race_id")["p"].idxmax()]
    rank = d.groupby("race_id")["p"].rank(ascending=False, method="first")
    d["pick3"] = rank <= 3
    return {
        "races": int(d["race_id"].nunique()),
        "logloss": float(-np.log(np.clip(win["p"], 1e-6, 1)).mean()),
        "win_hit": float((top_pick["finish"] == 1).mean()),          # top pick wins
        "top_pick_in3": float((top_pick["finish"] <= 3).mean()),     # top pick finishes top 3
        "winner_in_pick3": float(d[(d["finish"] == 1)]["pick3"].mean()),
    }


def roi_top_pick(df: pd.DataFrame, p: np.ndarray, min_edge: float = 1.0) -> dict:
    """Bet 100 yen to win on the top pick when p * odds >= min_edge."""
    d = df.assign(p=p)
    top = d.loc[d.groupby("race_id")["p"].idxmax()]
    bets = top[top["p"] * top["odds"] >= min_edge]
    ret = (bets["finish"] == 1) * bets["odds"]
    return {"bets": int(len(bets)), "hit": float((bets["finish"] == 1).mean()) if len(bets) else 0.0,
            "roi": float(ret.sum() / len(bets)) if len(bets) else 0.0}


def roi_value(df: pd.DataFrame, p: np.ndarray, min_edge: float = 1.2) -> dict:
    """Bet 100 yen to win on every horse with p * odds >= min_edge (final odds, so optimistic)."""
    d = df.assign(p=p)
    bets = d[d["p"] * d["odds"] >= min_edge]
    ret = (bets["finish"] == 1) * bets["odds"]
    return {"bets": int(len(bets)), "hit": float((bets["finish"] == 1).mean()) if len(bets) else 0.0,
            "roi": float(ret.sum() / len(bets)) if len(bets) else 0.0}
