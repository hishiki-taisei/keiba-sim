"""Per-runner features built only from races before the race date.

Every feature for a runner in a race on day D uses races strictly before D, so
the same table can be split by date into train and test without leakage. Rows
for an upcoming race (no result yet) can be appended and get features too.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# smoothing for rates: (hits + PRIOR_N * prior) / (n + PRIOR_N)
PRIOR_N = 5


def _going_group(going: pd.Series) -> pd.Series:
    return np.where(going.isin(["良", "稍重"]), "fast", "slow")


def speed_standards(df: pd.DataFrame, before=None) -> pd.DataFrame:
    """Mean and std of finishing time per (venue, surface, distance, going group).

    Only races before `before` are used so test races do not shape the scale.
    """
    d = df if before is None else df[df.date < pd.Timestamp(before)]
    d = d[d.time_sec.notna()]
    d = d.assign(gg=_going_group(d.going))
    g = d.groupby(["venue", "surface", "distance", "gg"]).time_sec
    st = pd.DataFrame({"t_mean": g.mean(), "t_std": g.std(), "t_n": g.size()}).reset_index()
    return st[st.t_n >= 30]


def add_race_figures(df: pd.DataFrame, standards: pd.DataFrame) -> pd.DataFrame:
    """Per-run performance numbers (used later as history)."""
    df = df.assign(gg=_going_group(df.going))
    df = df.merge(standards, on=["venue", "surface", "distance", "gg"], how="left")
    # speed figure: how many std faster than the standard time (higher is better)
    df["fig"] = (df.t_mean - df.time_sec) / df.t_std
    # closing speed relative to the field (higher is better)
    df["l3_rel"] = df.groupby("race_id").last3f.transform("mean") - df.last3f
    df["fin_ratio"] = (df.finish - 1) / (df.field - 1).clip(lower=1)
    first_corner = pd.to_numeric(df.passing.str.split("-").str[0], errors="coerce")
    df["early_pos"] = (first_corner - 1) / (df.field - 1).clip(lower=1)
    df["win"] = (df.finish == 1).astype(float)
    df["top3"] = (df.finish <= 3).astype(float)
    return df.drop(columns=["gg", "t_mean", "t_std", "t_n"])


def _horse_history(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling stats over each horse's previous starts."""
    g = df.groupby("horse_id", sort=False)
    out = pd.DataFrame(index=df.index)
    out["h_n"] = g.cumcount()

    def past(col, fn, **kw):
        return g[col].transform(lambda s: getattr(s.shift(1).rolling(**kw), fn)())

    big = dict(window=10_000, min_periods=1)
    out["h_win_rate"] = (g.win.transform(lambda s: s.shift(1).cumsum()).fillna(0) + PRIOR_N * 0.07) / (out.h_n + PRIOR_N)
    out["h_top3_rate"] = (g.top3.transform(lambda s: s.shift(1).cumsum()).fillna(0) + PRIOR_N * 0.21) / (out.h_n + PRIOR_N)
    out["h_fin_mean"] = past("fin_ratio", "mean", **big)
    out["h_fin_last3"] = past("fin_ratio", "mean", window=3, min_periods=1)
    out["h_fin_last"] = g.fin_ratio.shift(1)
    out["h_fig_best"] = past("fig", "max", **big)
    out["h_fig_last3"] = past("fig", "mean", window=3, min_periods=1)
    out["h_fig_last"] = g.fig.shift(1)
    out["h_l3_last3"] = past("l3_rel", "mean", window=3, min_periods=1)
    out["h_early_pos"] = past("early_pos", "mean", window=5, min_periods=1)
    out["h_pop_last3"] = past("popularity", "mean", window=3, min_periods=1)
    out["h_prize_log"] = np.log1p(g.prize.transform(lambda s: s.fillna(0).shift(1).cumsum()).fillna(0))
    out["h_max_dist"] = past("distance", "max", **big)
    out["days_since"] = (df.date - g.date.shift(1)).dt.days
    out["dist_diff"] = df.distance - g.distance.shift(1)
    same = df.groupby(["horse_id", "surface"], sort=False)
    out["h_same_surface_n"] = same.cumcount()
    return out


def _connection_rate(df: pd.DataFrame, key: str, prefix: str) -> pd.DataFrame:
    """Win / top-3 rate of a jockey or trainer over all earlier race days."""
    day = (df.groupby([key, "date"]).agg(n=("win", "size"), w=("win", "sum"), t=("top3", "sum"))
             .reset_index().sort_values([key, "date"]))
    for c in ["n", "w", "t"]:
        day[c + "_past"] = day.groupby(key)[c].cumsum() - day[c]
    day[f"{prefix}_win_rate"] = (day.w_past + PRIOR_N * 0.07) / (day.n_past + PRIOR_N)
    day[f"{prefix}_top3_rate"] = (day.t_past + PRIOR_N * 0.21) / (day.n_past + PRIOR_N)
    day[f"{prefix}_n_log"] = np.log1p(day.n_past)
    cols = [f"{prefix}_win_rate", f"{prefix}_top3_rate", f"{prefix}_n_log"]
    return df[[key, "date"]].merge(day[[key, "date"] + cols], on=[key, "date"], how="left")[cols].set_axis(df.index)


FEATURES = [
    # horse form
    "h_n_log", "debut", "h_win_rate", "h_top3_rate", "h_fin_mean", "h_fin_last3", "h_fin_last",
    "h_fig_best", "h_fig_last3", "h_fig_last", "h_l3_last3", "h_pop_last3", "h_prize_log",
    "h_early_pos", "fig_missing",
    # fit for today
    "days_since_log", "long_rest", "dist_diff_rel", "dist_up_new", "same_surface_rate",
    # connections
    "j_win_rate", "j_top3_rate", "j_n_log", "t_win_rate", "t_top3_rate",
    # today's conditions (relative to the field)
    "age_rel", "female", "gelding", "weight_rel", "body_weight_rel", "bw_diff_abs", "gate_rel",
]


def build(df: pd.DataFrame, standards: pd.DataFrame) -> pd.DataFrame:
    """Return df with FEATURES columns added. df must be sorted by date."""
    df = add_race_figures(df, standards)
    df = df.join(_horse_history(df))
    df = df.join(_connection_rate(df, "jockey_id", "j"))
    df = df.join(_connection_rate(df, "trainer_id", "t"))

    race = df.groupby("race_id")
    rel = lambda c: df[c] - race[c].transform("mean")  # noqa: E731

    df["h_n_log"] = np.log1p(df.h_n)
    df["debut"] = (df.h_n == 0).astype(float)
    df["fig_missing"] = df.h_fig_best.isna().astype(float)
    df["days_since_log"] = np.log1p(df.days_since.fillna(0))
    df["long_rest"] = (df.days_since > 180).astype(float)
    df["dist_diff_rel"] = (df.dist_diff / df.distance).fillna(0)
    df["dist_up_new"] = ((df.distance > df.h_max_dist.fillna(0) + 100) & (df.h_n > 0)).astype(float)
    df["same_surface_rate"] = (df.h_same_surface_n / df.h_n.clip(lower=1)).where(df.h_n > 0, 0)
    df["age_rel"] = rel("age")
    df["female"] = (df.sex == "牝").astype(float)
    df["gelding"] = (df.sex == "セ").astype(float)
    df["weight_rel"] = rel("weight_carried")
    df["body_weight_rel"] = rel("body_weight") / 20
    df["bw_diff_abs"] = df.body_weight_diff.abs().fillna(0) / 10
    df["gate_rel"] = (df.number - 1) / (df.field - 1).clip(lower=1)
    # missing history -> neutral values (debut / fig_missing flags carry the signal)
    fill = {"h_fin_mean": 0.5, "h_fin_last3": 0.5, "h_fin_last": 0.5, "h_fig_best": -1.0,
            "h_fig_last3": -1.0, "h_fig_last": -1.0, "h_l3_last3": 0.0, "h_pop_last3": 8.0,
            "h_early_pos": 0.5, "body_weight_rel": 0.0, "weight_rel": 0.0}
    df = df.fillna(fill)
    df["h_pop_last3"] = np.log(df.h_pop_last3)
    df[FEATURES] = df[FEATURES].fillna(0.0)
    return df
