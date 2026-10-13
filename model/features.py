"""Per-runner features known before the race (no look-ahead).

Ratings are refit at the start of every month using only earlier races, and
form features use only the horse's previous runs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import rating as rating_mod

FEATURES = ["rating", "slope", "unrated", "log_runs", "early_pos5", "kick5",
            "days_off", "last_fin", "fin5", "pop5", "earnings", "dist_change",
            "weight_rel", "gate_rel", "jockey", "female", "age", "last_y", "best_y3", "y5"]


def form(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling per-horse form from previous runs only."""
    g = df.groupby("horse_id", sort=False)
    out = pd.DataFrame(index=df.index)
    prev = lambda col: g[col].transform(lambda s: s.shift().rolling(5, min_periods=1).mean())
    out["early_pos5"] = prev("early_pos")
    out["kick5"] = prev("kick_rel")
    out["days_off"] = g["date"].diff().dt.days
    fin_pct = (df["finish"] - 1) / (df["field"] - 1).clip(lower=1)
    out["last_fin"] = fin_pct.groupby(df["horse_id"]).shift()
    out["fin5"] = fin_pct.groupby(df["horse_id"]).transform(lambda s: s.shift().rolling(5, min_periods=1).mean())
    out["pop5"] = np.log(df["odds"].clip(lower=1)).groupby(df["horse_id"]).transform(
        lambda s: s.shift().rolling(3, min_periods=1).mean())
    prize = df["prize"].fillna(0) if "prize" in df else pd.Series(0.0, index=df.index)
    out["earnings"] = np.log1p(prize.groupby(df["horse_id"]).cumsum() - prize)
    out["dist_change"] = np.log2(df["distance"] / g["distance"].shift())
    y = pd.Series(rating_mod.relative_speed(df), index=df.index)
    gy = y.groupby(df["horse_id"])
    out["last_y"] = gy.shift()
    out["best_y3"] = gy.transform(lambda s: s.shift().rolling(3, min_periods=1).max())
    out["y5"] = gy.transform(lambda s: s.shift().rolling(5, min_periods=1).mean())
    out["runs_before"] = g.cumcount()
    return out


def jockey_strength(df: pd.DataFrame) -> pd.Series:
    """Jockey top-3 rate over the previous 365 days (shrunk toward the mean)."""
    top3 = (df["finish"] <= 3).astype(float)
    j = pd.DataFrame({"date": df["date"], "jockey_id": df["jockey_id"], "top3": top3})
    daily = j.groupby(["jockey_id", "date"])["top3"].agg(["sum", "count"]).reset_index()
    out = []
    for jid, grp in daily.groupby("jockey_id"):
        grp = grp.set_index("date").sort_index()
        s = grp["sum"].rolling("365D", closed="left").sum().fillna(0)
        c = grp["count"].rolling("365D", closed="left").sum().fillna(0)
        out.append(pd.DataFrame({"jockey_id": jid, "date": grp.index, "jk": ((s + 0.25 * 30) / (c + 30)).values}))
    m = pd.concat(out)
    return df[["jockey_id", "date"]].merge(m, on=["jockey_id", "date"], how="left")["jk"].fillna(0.25).values


def build(df: pd.DataFrame, start: str = "2018-01", **rating_kw) -> pd.DataFrame:
    """Feature table for every run from ``start`` on."""
    f = form(df)
    df = df.join(f)
    df["jockey"] = jockey_strength(df)
    months = pd.date_range(start, df["date"].max() + pd.offsets.MonthBegin(1), freq="MS")
    parts = []
    for m0, m1 in zip(months[:-1], months[1:]):
        sel = df[(df["date"] >= m0) & (df["date"] < m1)].copy()
        if sel.empty:
            continue
        R = rating_mod.fit(df, m0, **rating_kw)
        val = np.zeros(len(sel))
        slope = np.zeros(len(sel))
        n = np.zeros(len(sel))
        for dist, idx in sel.groupby("distance").groups.items():
            v, k = R.predict(sel.loc[idx, "horse_id"], dist)
            pos = sel.index.get_indexer(idx)
            val[pos], n[pos] = v, k
            slope[pos] = [R.b[R.horse_index[h]] if h in R.horse_index else 0.0 for h in sel.loc[idx, "horse_id"]]
        sel["rating"], sel["slope"], sel["n_rated"] = val, slope, n
        parts.append(sel)
    out = pd.concat(parts)
    out["unrated"] = (out["n_rated"] == 0).astype(float)
    out["log_runs"] = np.log1p(out["runs_before"])
    out["weight_rel"] = out["weight_carried"] - out.groupby("race_id")["weight_carried"].transform("mean")
    out["gate_rel"] = (out["number"] - 1) / (out["field"] - 1).clip(lower=1)
    # Missing form for debut runners: field averages.
    for c in ["early_pos5", "kick5", "last_fin", "fin5", "pop5", "last_y", "best_y3", "y5"]:
        out[c] = out[c].fillna(out.groupby("race_id")[c].transform("mean")).fillna(0.5 if c in ("early_pos5", "last_fin", "fin5") else 0.0)
    out["pop5"] = out["pop5"].fillna(3.0)
    out["dist_change"] = out["dist_change"].fillna(0.0)
    out["female"] = (out["sex"] == "牝").astype(float)
    out["age"] = out["age"].clip(upper=7).astype(float)
    out["earnings"] = out["earnings"] - out.groupby("race_id")["earnings"].transform("mean")
    out["days_off"] = np.log1p(out["days_off"].fillna(180).clip(upper=720))
    # Ratings are relative to the field.
    out["rating"] = out["rating"] - out.groupby("race_id")["rating"].transform("mean")
    return out
