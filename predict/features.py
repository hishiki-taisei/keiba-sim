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


def class_level(grade: pd.Series, class_text: pd.Series) -> pd.Series:
    """0 = maiden/debut, 1-3 = 1/2/3-win class, 4 = open/listed, 5-7 = G3/G2/G1."""
    t = class_text.fillna("")
    lv = pd.Series(np.nan, index=t.index)
    for pat, v in [("新馬|未勝利", 0), ("1勝|500万", 1), ("2勝|1000万", 2), ("3勝|1600万", 3), ("オープン", 4)]:
        lv = lv.where(lv.notna() | ~t.str.contains(pat), v)
    g = grade.map({"G1": 7, "G2": 6, "G3": 5, "L": 4, "OP": 4})
    return g.fillna(lv).fillna(2.0)


def dist_cat(distance: pd.Series) -> pd.Series:
    return pd.cut(distance, [0, 1399, 1899, 2299, 9999], labels=False)


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
    df["cls"] = class_level(df.grade, df.class_text)
    df["dcat"] = dist_cat(df.distance)
    # raw speed figure: how many std faster than the standard time (higher is better)
    raw = (df.t_mean - df.time_sec) / df.t_std
    # track variant: how fast the course rode that day, from all runs there compared
    # with what their class usually runs
    resid = raw - raw.groupby(df.cls).transform("mean")
    variant = resid.groupby([df.date, df.venue, df.surface]).transform("mean")
    n_day = resid.groupby([df.date, df.venue, df.surface]).transform("count")
    df["fig"] = raw - variant.where(n_day >= 20, 0)
    # closing speed relative to the field (higher is better)
    df["l3_rel"] = df.groupby("race_id").last3f.transform("mean") - df.last3f
    # seconds behind the winner, capped so one blow-up does not dominate
    df["behind"] = (df.time_sec - df.groupby("race_id").time_sec.transform("min")).clip(upper=5)
    df["log_odds"] = np.log(df.odds)
    df["fin_ratio"] = (df.finish - 1) / (df.field - 1).clip(lower=1)
    first_corner = pd.to_numeric(df.passing.str.split("-").str[0], errors="coerce")
    df["early_pos"] = (first_corner - 1) / (df.field - 1).clip(lower=1)
    df["win"] = (df.finish == 1).astype(float)
    df["top3"] = (df.finish <= 3).astype(float)
    # class-weighted result: finishing top 3 at a higher class counts more
    df["cls_top3"] = df.cls.where(df.top3 == 1)
    return df.drop(columns=["gg", "t_mean", "t_std", "t_n"])


def _expanding_mean(df, keys, col):
    prev = df.groupby(keys, sort=False)[col].shift(1)
    grp = [df[k] for k in keys] if isinstance(keys, list) else df[keys]
    s = prev.fillna(0).groupby(grp, sort=False).cumsum()
    n = prev.notna().astype(float).groupby(grp, sort=False).cumsum()
    return s / n.where(n > 0)


def _expanding(df, keys, col, how):
    prev = df.groupby(keys, sort=False)[col].shift(1)
    grp = [df[k] for k in keys] if isinstance(keys, list) else df[keys]
    fill = -np.inf if how == "max" else np.inf
    out = getattr(prev.fillna(fill).groupby(grp, sort=False), "cum" + how)()
    return out.replace([np.inf, -np.inf], np.nan)


def _rolling_mean(df, key, col, window):
    prev = df.groupby(key, sort=False)[col].shift(1)
    return prev.groupby(df[key], sort=False).rolling(window, min_periods=1).mean().reset_index(level=0, drop=True)


def _horse_history(df: pd.DataFrame) -> pd.DataFrame:
    """Stats over each horse's previous starts."""
    g = df.groupby("horse_id", sort=False)
    out = pd.DataFrame(index=df.index)
    out["h_n"] = g.cumcount()
    wins = g.win.shift(1).fillna(0).groupby(df.horse_id, sort=False).cumsum()
    top3 = g.top3.shift(1).fillna(0).groupby(df.horse_id, sort=False).cumsum()
    out["h_win_rate"] = (wins + PRIOR_N * 0.07) / (out.h_n + PRIOR_N)
    out["h_top3_rate"] = (top3 + PRIOR_N * 0.21) / (out.h_n + PRIOR_N)
    out["h_fin_mean"] = _expanding_mean(df, "horse_id", "fin_ratio")
    out["h_fin_last3"] = _rolling_mean(df, "horse_id", "fin_ratio", 3)
    out["h_fin_last"] = g.fin_ratio.shift(1)
    out["h_fig_best"] = _expanding(df, "horse_id", "fig", "max")
    out["h_fig_last3"] = _rolling_mean(df, "horse_id", "fig", 3)
    out["h_fig_last"] = g.fig.shift(1)
    out["h_behind_last"] = g.behind.shift(1)
    out["h_behind_last3"] = _rolling_mean(df, "horse_id", "behind", 3)
    out["h_odds_last"] = g.log_odds.shift(1)
    out["h_fig_surface"] = _expanding(df, ["horse_id", "surface"], "fig", "max")
    out["h_fig_dcat"] = _expanding(df, ["horse_id", "surface", "dcat"], "fig", "max")
    out["h_l3_last3"] = _rolling_mean(df, "horse_id", "l3_rel", 3)
    out["h_early_pos"] = _rolling_mean(df, "horse_id", "early_pos", 5)
    out["h_pop_last3"] = _rolling_mean(df, "horse_id", "popularity", 3)
    out["h_prize_log"] = np.log1p(g.prize.shift(1).fillna(0).groupby(df.horse_id, sort=False).cumsum())
    out["h_max_dist"] = _expanding(df, "horse_id", "distance", "max")
    out["h_cls_last"] = g.cls.shift(1)
    out["h_cls_top3"] = _expanding(df, "horse_id", "cls_top3", "max")
    out["days_since"] = (df.date - g.date.shift(1)).dt.days
    out["dist_diff"] = df.distance - g.distance.shift(1)
    same = df.groupby(["horse_id", "surface"], sort=False)
    out["h_same_surface_n"] = same.cumcount()
    return out


def _connection_rate(df: pd.DataFrame, key: str, prefix: str) -> pd.DataFrame:
    """Win / top-3 rate of a jockey or trainer over all earlier race days, and the last year."""
    day = (df.groupby([key, "date"]).agg(n=("win", "size"), w=("win", "sum"), t=("top3", "sum"))
             .reset_index().sort_values([key, "date"]))
    for c in ["n", "w", "t"]:
        day[c + "_past"] = day.groupby(key)[c].cumsum() - day[c]
    # last 365 days, excluding the day itself
    rolled = (day.set_index("date").groupby(key)[["n", "t"]]
                 .rolling("365D", closed="left").sum().reset_index())
    day = day.merge(rolled.rename(columns={"n": "n_1y", "t": "t_1y"}), on=[key, "date"], how="left")
    day[f"{prefix}_win_rate"] = (day.w_past + PRIOR_N * 0.07) / (day.n_past + PRIOR_N)
    day[f"{prefix}_top3_rate"] = (day.t_past + PRIOR_N * 0.21) / (day.n_past + PRIOR_N)
    day[f"{prefix}_top3_1y"] = (day.t_1y.fillna(0) + 20 * 0.21) / (day.n_1y.fillna(0) + 20)
    day[f"{prefix}_n_log"] = np.log1p(day.n_past)
    cols = [f"{prefix}_win_rate", f"{prefix}_top3_rate", f"{prefix}_top3_1y", f"{prefix}_n_log"]
    return df[[key, "date"]].merge(day[[key, "date"] + cols], on=[key, "date"], how="left")[cols].set_axis(df.index)


FEATURES = [
    # horse form
    "h_n_log", "debut", "h_win_rate", "h_top3_rate", "h_fin_mean", "h_fin_last3", "h_fin_last",
    "h_fig_best", "h_fig_last3", "h_fig_last", "h_fig_surface", "h_fig_dcat", "h_l3_last3",
    "h_pop_last3", "h_prize_log", "h_early_pos", "fig_missing", "h_behind_last", "h_behind_last3",
    "h_odds_last",
    # class
    "cls_step", "cls_top3_gap",
    # fit for today
    "days_since_log", "long_rest", "dist_diff_rel", "dist_up_new", "same_surface_rate",
    # connections
    "j_win_rate", "j_top3_rate", "j_top3_1y", "j_n_log", "t_win_rate", "t_top3_rate", "t_top3_1y",
    # standing within today's field
    "fig_best_gap", "fig_last3_gap", "fig_dcat_gap", "pop_rank", "prize_rank", "jockey_rank",
    "front_runners",
    # today's conditions (relative to the field)
    "age_rel", "female", "gelding", "weight_rel", "body_weight_rel", "bw_diff_abs", "gate_rel",
]


def build(df: pd.DataFrame, standards: pd.DataFrame) -> pd.DataFrame:
    """Return df with FEATURES columns added. df must be sorted by date."""
    df = add_race_figures(df.reset_index(drop=True), standards)
    df = df.join(_horse_history(df))
    df = df.join(_connection_rate(df, "jockey_id", "j"))
    df = df.join(_connection_rate(df, "trainer_id", "t"))

    race = df.groupby("race_id")
    rel = lambda c: df[c] - race[c].transform("mean")  # noqa: E731

    df["h_n_log"] = np.log1p(df.h_n)
    df["debut"] = (df.h_n == 0).astype(float)
    df["fig_missing"] = df.h_fig_best.isna().astype(float)
    # moving up (+) or down (-) in class since the last race
    df["cls_step"] = (df.cls - df.h_cls_last).fillna(0)
    # best class where the horse placed, compared with today's class
    df["cls_top3_gap"] = (df.h_cls_top3 - df.cls).fillna(-3)
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
    df["h_fig_surface"] = df.h_fig_surface.fillna(df.h_fig_best - 0.5)
    df["h_fig_dcat"] = df.h_fig_dcat.fillna(df.h_fig_surface - 0.5)
    fill = {"h_fin_mean": 0.5, "h_fin_last3": 0.5, "h_fin_last": 0.5, "h_fig_best": -1.0,
            "h_fig_last3": -1.0, "h_fig_last": -1.0, "h_fig_surface": -1.5, "h_fig_dcat": -2.0,
            "h_l3_last3": 0.0, "h_behind_last": 2.0, "h_behind_last3": 2.0, "h_odds_last": 3.5, "h_pop_last3": 8.0, "h_early_pos": 0.5, "body_weight_rel": 0.0,
            "weight_rel": 0.0}
    df = df.fillna(fill)
    df["h_pop_last3"] = np.log(df.h_pop_last3)
    # gap to the best horse in the field and rank inside the field
    race = df.groupby("race_id")
    for src, dst in [("h_fig_best", "fig_best_gap"), ("h_fig_last3", "fig_last3_gap"), ("h_fig_dcat", "fig_dcat_gap")]:
        df[dst] = df[src] - race[src].transform("max")
    for src, dst, asc in [("h_pop_last3", "pop_rank", True), ("h_prize_log", "prize_rank", False),
                          ("j_top3_1y", "jockey_rank", False)]:
        df[dst] = race[src].rank(ascending=asc, pct=True)
    # how many other habitual front runners are in the field (pace pressure)
    front = (df.h_early_pos < 0.2) & (df.h_n > 0)
    df["front_runners"] = (front.groupby(df.race_id).transform("sum") - front) * front
    df[FEATURES] = df[FEATURES].fillna(0.0)
    return df
