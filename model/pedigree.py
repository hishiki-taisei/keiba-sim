"""Distance aptitude inherited from the sire and the dam's sire.

The speed rating gives every horse a distance slope (how its rating moves per
doubling of distance). A stallion's aptitude is the average slope of his
offspring, from a rating fit on races before ``cutoff``. A horse's own slope is
left out of its sire's average, so the feature never contains the result it is
used to predict.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from . import rating
from .data import DB

SHRINK = 10.0  # pseudo-offspring pulling a stallion with few runners toward zero


def features(df: pd.DataFrame, cutoff: str = "2023-01-01", db=DB) -> pd.DataFrame:
    """horse_id -> sire_apt, damsire_apt (0 when unknown)."""
    con = sqlite3.connect(db)
    peds = pd.read_sql("SELECT horse_id, sire_id, damsire_id FROM horses", con)
    con.close()
    R = rating.fit(df, pd.Timestamp(cutoff))
    slope = pd.Series(R.b, index=list(R.horse_index))
    # only horses with a few runs carry a meaningful slope
    slope = slope[pd.Series(R.n_runs, index=slope.index) >= 3]
    peds["b"] = peds["horse_id"].map(slope)
    out = peds[["horse_id"]].copy()
    for key, name in (("sire_id", "sire_apt"), ("damsire_id", "damsire_apt")):
        g = peds.dropna(subset=["b"]).groupby(key)["b"]
        s, n = peds[key].map(g.sum()).fillna(0), peds[key].map(g.count()).fillna(0)
        own = peds["b"].fillna(0)
        own_n = peds["b"].notna().astype(float)
        out[name] = ((s - own) / (n - own_n + SHRINK)).fillna(0.0).values
    return out
