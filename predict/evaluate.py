"""Accuracy and betting return of win probabilities."""
from __future__ import annotations

import numpy as np
import pandas as pd


def market_prob(df: pd.DataFrame) -> np.ndarray:
    """Win probability implied by final odds, normalised inside each race."""
    inv = 1.0 / df.odds.fillna(df.odds.max()).to_numpy()
    s = pd.Series(inv).groupby(df.race_id.to_numpy()).transform("sum").to_numpy()
    return inv / s


def payout_lookup(payouts: pd.DataFrame) -> dict:
    return {(r, b, c): p for r, b, c, p in payouts[["race_id", "bet_type", "combo", "payout"]].itertuples(index=False)}


def metrics(df: pd.DataFrame, p: np.ndarray, pay: dict, value_edge: float = 1.2) -> dict:
    """df: runners of the evaluated races (grouped by race), p: predicted win prob."""
    d = df[["race_id", "number", "finish", "odds"]].copy()
    d["p"] = p
    d["rank"] = d.groupby("race_id").p.rank(ascending=False, method="first")
    races = d.race_id.nunique()
    winners = d[d.finish == 1]
    top = d[d["rank"] == 1]

    def ret(rows, bet_type):
        got = sum(pay.get((r, bet_type, str(n)), 0) for r, n in zip(rows.race_id, rows.number))
        return got / (100 * len(rows)) if len(rows) else float("nan")

    value = d[d.p * d.odds >= value_edge]
    return {
        "races": races,
        # mean negative log-likelihood of the actual winner (lower is better)
        "logloss": float(-np.log(winners.groupby("race_id").p.sum()).mean()),
        "top1_win": float((top.finish == 1).mean()),
        "top1_in3": float((top.finish <= 3).mean()),
        "winner_in_top3": float((winners.groupby("race_id")["rank"].min() <= 3).mean()),
        "roi_win_top1": ret(top, "単勝"),
        "roi_place_top1": ret(top, "複勝"),
        "value_bets": int(len(value)),
        "roi_win_value": ret(value, "単勝"),
    }

