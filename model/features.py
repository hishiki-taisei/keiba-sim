"""Per-runner features known before the race (no look-ahead).

Ratings are refit at the start of every month using only earlier races, and
form features use only the horse's previous runs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import pedigree
from . import rating as rating_mod

GOING = {"良": 0.0, "稍重": 1.0, "重": 2.0, "不良": 3.0}
GOING_FEATURES = ["going_num", "heavy_apt", "heavy_x", "heavy_runs"]
# Field-relative copies help tree models, which see one runner at a time.
REL_FEATURES = ["pop5_rel", "jockey_rel", "y5_rel", "best_y3_rel", "fin5_rel", "early_pos5_rel"]
# v2: race-day body weight, trainer form, pace the horse ran against, same-day track bias.
V2_FEATURES = ["bw_diff", "bw_rel", "bw_vs_best", "trainer", "trainer_rel",
               "pace_favor5", "pace5", "bias_front_x", "bias_inner_x", "bias_front", "bias_inner", "bias_n"]
FEATURES = ["rating", "slope", "unrated", "log_runs", "early_pos5", "kick5",
            "days_off", "last_fin", "fin5", "pop5", "earnings", "dist_change",
            "weight_rel", "gate_rel", "jockey", "female", "age", "last_y", "best_y3", "y5", "ped_long"]


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
    # Going: how the horse has run on rain-affected ground versus good ground.
    wet = df["going"].map(GOING).fillna(0.0) >= 1.0
    yy = y.fillna(0.0)
    hid = df["horse_id"]
    cum = lambda v: v.groupby(hid).cumsum() - v  # sum over previous runs only
    sy_w, n_w = cum(yy.where(wet, 0.0)), cum(wet.astype(float))
    sy_d, n_d = cum(yy.where(~wet, 0.0)), cum((~wet).astype(float))
    out["heavy_apt"] = sy_w / (n_w + 3.0) - sy_d / (n_d + 3.0)
    out["heavy_runs"] = np.log1p(n_w)
    out["runs_before"] = g.cumcount()
    # Pace: how hard the early fractions were, and whether that suited the horse's position.
    pace = race_pace(df)
    favor = (df["early_pos"].fillna(0.5) - 0.5) * pace  # >0: ran behind in a fast race / led a slow one
    out["pace_favor5"] = favor.groupby(hid).transform(lambda s: s.shift().rolling(5, min_periods=1).mean())
    out["pace5"] = pace.groupby(hid).transform(lambda s: s.shift().rolling(5, min_periods=1).mean())
    # Body weight relative to the weight at the horse's best previous run.
    bw = df["body_weight"] if "body_weight" in df else pd.Series(np.nan, index=df.index)
    best_bw = pd.Series(np.nan, index=df.index)
    for _, idx in g.groups.items():
        yy_h, bw_h = y.loc[idx].to_numpy(), bw.loc[idx].to_numpy()
        best, arg = -np.inf, np.nan
        res = np.full(len(idx), np.nan)
        for i in range(len(idx)):
            res[i] = arg
            if not np.isnan(yy_h[i]) and yy_h[i] > best and not np.isnan(bw_h[i]):
                best, arg = yy_h[i], bw_h[i]
        best_bw.loc[idx] = res
    out["bw_vs_best"] = bw - best_bw
    return out


def _laps(s):
    try:
        return [float(x) for x in str(s).split(" - ")]
    except ValueError:
        return None


def race_pace(df: pd.DataFrame) -> pd.Series:
    """Early-minus-late speed per race (positive = fast early pace), centred on the
    typical value for the distance in races before 2023 (the training years)."""
    races = df.drop_duplicates("race_id").set_index("race_id")
    vals = {}
    for rid, laps in races["laps"].items() if "laps" in races else []:
        L = _laps(laps)
        if not L or len(L) < 6:
            continue
        L = L[1:]  # the first furlong includes the standing start
        early = np.mean(L[: len(L) // 2])
        late = np.mean(L[-3:])
        vals[rid] = late - early
    p = pd.Series(vals, dtype=float)
    d = races["distance"].reindex(p.index)
    train = races["date"].reindex(p.index) < "2023-01-01"
    norm = p[train].groupby(d[train]).mean()
    p = p - d.map(norm).fillna(p[train].mean() if train.any() else 0.0)
    return df["race_id"].map(p).fillna(0.0)


def day_bias(df: pd.DataFrame) -> pd.DataFrame:
    """Track bias from earlier races on the same day, venue and surface:
    were the top three further forward / nearer the rail than the field?"""
    top = df["finish"] <= 3
    per = pd.DataFrame({
        "race_id": df["race_id"],
        "front": df["early_pos"].where(top) - df.groupby("race_id")["early_pos"].transform("mean"),
        "inner": ((df["number"] - 1) / (df["field"] - 1).clip(lower=1)).where(top) - 0.5,
    }).groupby("race_id")[["front", "inner"]].mean().fillna(0.0)
    meta = df.drop_duplicates("race_id").set_index("race_id")
    rid = per.index.to_series()
    per["day"] = rid.str[:10] + meta["surface"].reindex(per.index)
    per["no"] = rid.str[10:].astype(int)
    per = per.sort_values(["day", "no"])
    g = per.groupby("day")
    cnt = g.cumcount()
    res = pd.DataFrame(index=per.index)
    for c in ["front", "inner"]:
        prev_sum = g[c].cumsum() - per[c]
        res["bias_" + c] = prev_sum / (cnt + 2.0)  # shrink toward no bias
    res["bias_n"] = cnt
    return df[["race_id"]].join(res, on="race_id").drop(columns="race_id")


def jockey_strength(df: pd.DataFrame, key: str = "jockey_id") -> pd.Series:
    """Jockey (or trainer) top-3 rate over the previous 365 days (shrunk toward the mean)."""
    top3 = (df["finish"] <= 3).astype(float)
    j = pd.DataFrame({"date": df["date"], "jockey_id": df[key], "top3": top3})
    daily = j.groupby(["jockey_id", "date"])["top3"].agg(["sum", "count"]).reset_index()
    out = []
    for jid, grp in daily.groupby("jockey_id"):
        grp = grp.set_index("date").sort_index()
        s = grp["sum"].rolling("365D", closed="left").sum().fillna(0)
        c = grp["count"].rolling("365D", closed="left").sum().fillna(0)
        out.append(pd.DataFrame({"jockey_id": jid, "date": grp.index, "jk": ((s + 0.25 * 30) / (c + 30)).values}))
    m = pd.concat(out)
    return j[["jockey_id", "date"]].merge(m, on=["jockey_id", "date"], how="left")["jk"].fillna(0.25).values


def build(df: pd.DataFrame, start: str = "2018-01", asof: pd.Timestamp | None = None,
          **rating_kw) -> pd.DataFrame:
    """Feature table for every run from ``start`` on.

    Ratings are fit at the start of each month, or at ``asof`` when given (used for
    a single upcoming race, so runs earlier in the same month count).
    """
    f = form(df)
    df = df.join(f)
    df["jockey"] = jockey_strength(df)
    df["trainer"] = jockey_strength(df, "trainer_id")
    df = df.join(day_bias(df))
    months = pd.date_range(start, df["date"].max() + pd.offsets.MonthBegin(1), freq="MS")
    parts = []
    for m0, m1 in zip(months[:-1], months[1:]):
        sel = df[(df["date"] >= m0) & (df["date"] < m1)].copy()
        if sel.empty:
            continue
        R = rating_mod.fit(df, asof if asof is not None and m0 <= asof < m1 else m0, **rating_kw)
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
    ped = pedigree.features(df)
    out = out.merge(ped, on="horse_id", how="left").set_index(out.index)
    x = np.log2(out["distance"] / 2000.0)
    out["ped_long"] = (out["sire_apt"].fillna(0) + 0.5 * out["damsire_apt"].fillna(0)) * x
    out["unrated"] = (out["n_rated"] == 0).astype(float)
    out["log_runs"] = np.log1p(out["runs_before"])
    out["weight_rel"] = out["weight_carried"] - out.groupby("race_id")["weight_carried"].transform("mean")
    out["gate_rel"] = (out["number"] - 1) / (out["field"] - 1).clip(lower=1)
    # Missing form for debut runners: field averages.
    for c in ["early_pos5", "kick5", "last_fin", "fin5", "pop5", "last_y", "best_y3", "y5", "ped_long"]:
        out[c] = out[c].fillna(out.groupby("race_id")[c].transform("mean")).fillna(0.5 if c in ("early_pos5", "last_fin", "fin5") else 0.0)
    out["pop5"] = out["pop5"].fillna(3.0)
    out["dist_change"] = out["dist_change"].fillna(0.0)
    out["female"] = (out["sex"] == "牝").astype(float)
    out["going_num"] = out["going"].map(GOING).fillna(0.0)
    out["heavy_x"] = out["heavy_apt"].fillna(0.0) * out["going_num"]
    bw = out["body_weight"] if "body_weight" in out else pd.Series(np.nan, index=out.index)
    out["bw_rel"] = (bw - out.groupby("race_id")["body_weight"].transform("mean")).fillna(0.0) if "body_weight" in out else 0.0
    out["bw_diff"] = out["body_weight_diff"].fillna(0.0).clip(-30, 30) if "body_weight_diff" in out else 0.0
    out["bw_vs_best"] = out["bw_vs_best"].fillna(0.0).clip(-40, 40)
    for c in ["pace_favor5", "pace5"]:
        out[c] = out[c].fillna(0.0)
    for c in ["bias_front", "bias_inner", "bias_n"]:
        out[c] = out[c].fillna(0.0)
    out["trainer_rel"] = out["trainer"] - out.groupby("race_id")["trainer"].transform("mean")
    out["bias_front_x"] = out["bias_front"] * (out["early_pos5"] - 0.5)
    out["bias_inner_x"] = out["bias_inner"] * (out["gate_rel"] - 0.5)
    for c in ["pop5", "jockey", "y5", "best_y3", "fin5", "early_pos5"]:
        out[c + "_rel"] = out[c] - out.groupby("race_id")[c].transform("mean")
    out["age"] = out["age"].clip(upper=7).astype(float)
    out["earnings"] = out["earnings"] - out.groupby("race_id")["earnings"].transform("mean")
    out["days_off"] = np.log1p(out["days_off"].fillna(180).clip(upper=720))
    # Ratings are relative to the field.
    out["rating"] = out["rating"] - out.groupby("race_id")["rating"].transform("mean")
    return out


def for_entries(df: pd.DataFrame, race: dict, going: str = "良") -> pd.DataFrame:
    """Features for an upcoming race. ``race`` is scraper.parse.entries() output;
    ``going`` is the expected ground (not known until race day)."""
    date = pd.Timestamp(race["date"])
    rows = pd.DataFrame(race["horses"])
    n = len(rows)
    if rows["number"].isna().any():  # before the draw: spread them evenly
        rows["number"] = np.arange(1, n + 1)
    rows = rows.assign(race_id=race["race_id"], date=date, surface=race["surface"],
                       distance=race["distance"], field=n, finish=np.nan, time_sec=np.nan,
                       odds=np.nan, prize=np.nan, speed=np.nan, early_pos=np.nan, kick_rel=np.nan,
                       last3f=np.nan, passing=None, race_name=race["title"], going=going)
    rows["number"] = rows["number"].astype(int)
    hist = df[df["date"] < date]
    all_ = pd.concat([hist, rows], ignore_index=True)
    out = build(all_, start=date.strftime("%Y-%m"), asof=date)
    return out[out["race_id"] == race["race_id"]]
