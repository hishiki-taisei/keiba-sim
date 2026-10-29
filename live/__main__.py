"""Paper betting on upcoming JRA races, settled against the real results. No real money is used.

    python3 -m live morning [--date YYYY-MM-DD]   # races today? fetch entries + odds, place paper bets
    python3 -m live night                         # add new results to the DB, settle bets, retrain, report
    python3 -m live bet|settle|train|report|update  # the single steps

Three groups of 100-yen bets run side by side (STRATEGIES):

    オッズ準拠モデル  the market-offset model: win and place on its top pick, win on p x odds >= 1.2
    独自モデル        the odds-free model (the horse's own record only): win and place on its top pick
    Claudeの買い方    rules chosen on 2018-2023 and checked on 2024- (scripts/strategy_search.py,
                      scripts/rule_search.py): win on horses the odds-free model rates at 3x the market
                      (under 20/1), and dirt favourites backed by several of the facts that held up
Records live in the project's shared folder (keiba-sim/betting/):

    bets.csv               one row per paper bet, settled the night after the race
    predictions/DATE.csv   every runner's model and market probability at bet time
    daily/DATE.md          the day's bets and results
    summary.md             running totals per strategy and how the model compares with the market
    models/                the win models, retrained every night with the newest results
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pickle
import shutil
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from model import evaluate, features  # noqa: E402
from model.data import load_runs  # noqa: E402
from model.gbdt import GBDT  # noqa: E402
from scraper import __main__ as scraper_cli  # noqa: E402
from scraper import parse  # noqa: E402
from scraper.fetch import Fetcher  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
SHARED = Path(os.environ.get("KEIBA_SHARED", "/mnt/project-files/keiba-sim"))
SHARED_DB = SHARED / "data" / "keiba.sqlite"
LOCAL_DB = ROOT / "data" / "keiba.sqlite"
OUT = SHARED / "betting"
BETS = OUT / "bets.csv"
WEB_RESULTS = OUT / "results_web.csv"  # results read from race.netkeiba.com before the DB has them
MODELS = OUT / "models"

# Same items as the offset_pace2 experiment: the market's odds are the starting point and the
# trees learn how far to move away from them.
WIN_FEATURES = features.FEATURES + features.GOING_FEATURES + features.REL_FEATURES + features.PACE_FEATURES
STAKE = 100
EV_MIN, EV_MAX_ODDS = 1.2, 100.0
STRATEGIES = {  # key: (group, label)
    "fav_win": ("オッズ準拠モデル", "本命の単勝"), "fav_place": ("オッズ準拠モデル", "本命の複勝"),
    "value_win": ("オッズ準拠モデル", "期待値買い（単勝）"),
    "indep_win": ("独自モデル", "本命の単勝"), "indep_place": ("独自モデル", "本命の複勝"),
    "claude_gap_win": ("Claudeの買い方", "独自モデルが市場の3倍評価（単勝）"),
    "claude_dirt_place": ("Claudeの買い方", "ダート1番人気＋好材料2つ以上（複勝）"),
    "claude_dirt_win": ("Claudeの買い方", "ダート1番人気＋好材料3つ以上（単勝）"),
}
GAP_RATIO, GAP_MAX_ODDS = 3.0, 20.0
# Dirt facts that held up on 2018-2023 and on 2024- for the favourite (experiments/rules.md):
# strong field last time, wide draw, dropping in distance, ran against the pace, high speed figure.
DIRT_FACTS = {"last_field_y5": (0.8, ">="), "gate_rel": (0.8, ">="), "dist_change": (0.2, "<="),
              "pace_favor5": (0.2, "<="), "rating": (0.8, ">=")}
BET_COLS = ["date", "race_id", "venue", "race_no", "post_time", "race_name", "surface", "distance",
            "strategy", "bet_type", "number", "horse_name", "stake", "p_model", "p_market", "odds_at_bet", "odds_source",
            "placed_at", "model", "settled", "finish", "final_odds", "payout"]
ODDS_SOURCE = {"yoso": "予想オッズ", "middle": "発売中オッズ", "result": "確定オッズ"}
GOING_NORM = {"稍": "稍重", "不": "不良"}


def log_market(df):
    return np.log(np.clip(evaluate.market_probs(df), 1e-6, 1.0))


def now_jst() -> dt.datetime:
    return dt.datetime.now(JST)


# -- database -----------------------------------------------------------------

def sync_in():
    """Work on a local copy of the shared database (the shared folder is a network mount)."""
    if SHARED_DB.exists() and (not LOCAL_DB.exists() or SHARED_DB.stat().st_mtime > LOCAL_DB.stat().st_mtime + 1):
        LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SHARED_DB, LOCAL_DB)
        print(f"copied {SHARED_DB} -> {LOCAL_DB}")


def sync_out():
    tmp = SHARED_DB.with_suffix(".tmp")
    src = sqlite3.connect(LOCAL_DB)
    with sqlite3.connect(tmp) as dst:
        src.backup(dst)
    src.close()
    tmp.replace(SHARED_DB)
    print(f"saved {LOCAL_DB} -> {SHARED_DB}")


def update():
    """Fetch results of race days up to today (run after the last race), and pedigrees of new horses."""
    today = now_jst().date()
    start = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    db = ["--db", str(LOCAL_DB)]
    scraper_cli.main(db + ["days", "--from", start, "--to", today.strftime("%Y-%m"), "--include-today"])
    scraper_cli.main(db + ["races"])
    scraper_cli.main(db + ["peds", "--limit", "400"])


# -- models -------------------------------------------------------------------

def train():
    """Refit the win models on every race in the DB. The newest year picks the number of trees,
    then the model is refit on all races including that year."""
    MODELS.mkdir(parents=True, exist_ok=True)
    for surface, key in (("芝", "turf"), ("ダ", "dirt")):
        F = features.build(load_runs(LOCAL_DB, surface=surface), "2018-01")
        F = F[F["odds"].notna() & (F["field"] >= 5)]
        last = F["date"] >= F["date"].max() - pd.Timedelta(days=365)
        probe = GBDT(WIN_FEATURES, base=log_market, rounds=800).fit(F[~last], F[last])
        n = max(len(probe.trees), 20)
        model = GBDT(WIN_FEATURES, base=log_market, rounds=n).fit(F)
        v = F[last]
        info = {"surface": surface, "trained_at": now_jst().isoformat(timespec="seconds"),
                "data_until": F["date"].max().strftime("%Y-%m-%d"), "runs": int(len(F)), "trees": n,
                "valid_logloss": round(evaluate.metrics(v, probe.predict(v))["logloss"], 4),
                "valid_market_logloss": round(evaluate.metrics(v, evaluate.market_probs(v))["logloss"], 4)}
        model.base = None  # a function; set again on load so the pickle does not depend on where it ran
        with open(MODELS / f"{key}.pkl", "wb") as fh:
            pickle.dump({"model": model, "info": info}, fh)
        # The odds-free model.
        probe = GBDT(features.INDEP_FEATURES, rounds=1500).fit(F[~last], F[last])
        n = max(len(probe.trees), 20)
        indep = GBDT(features.INDEP_FEATURES, rounds=n).fit(F)
        info_i = dict(info, surface=surface + "（独自）", trees=n,
                      valid_logloss=round(evaluate.metrics(v, probe.predict(v))["logloss"], 4))
        with open(MODELS / f"indep_{key}.pkl", "wb") as fh:
            pickle.dump({"model": indep, "info": info_i}, fh)
        if surface == "ダ":  # thresholds for the dirt facts, from the years the rules were chosen on
            tr = F[F["date"].dt.year <= 2022]
            th = {c: [float(tr[c].quantile(q)), op] for c, (q, op) in DIRT_FACTS.items()}
            (MODELS / "dirt_facts.json").write_text(json.dumps(th, indent=1))
        log = OUT / "train_log.csv"
        pd.DataFrame([info, info_i]).to_csv(log, mode="a", header=not log.exists(), index=False)
        print("trained", info, info_i, flush=True)


def load_model(surface: str, indep: bool = False):
    path = MODELS / f"{'indep_' if indep else ''}{'turf' if surface == '芝' else 'dirt'}.pkl"
    if not path.exists():
        return None, None
    with open(path, "rb") as fh:
        d = pickle.load(fh)
    d["model"].base = None if indep else log_market
    return d["model"], d["info"]


def dirt_facts(rows: pd.DataFrame) -> pd.Series:
    path = MODELS / "dirt_facts.json"
    if not path.exists():
        return pd.Series(0, index=rows.index)
    th = json.loads(path.read_text())
    n = pd.Series(0, index=rows.index)
    for c, (v, op) in th.items():
        n += (rows[c] >= v) if op == ">=" else (rows[c] <= v)
    return n


# -- entries and odds ---------------------------------------------------------

def race_ids_on(day: dt.date, f: Fetcher) -> list[str]:
    # The race list answers 400 on days without racing, which the fetcher backs off on for minutes;
    # the month calendar says up front whether there is racing that day.
    cal = f.get(f"https://race.netkeiba.com/top/calendar.html?year={day:%Y}&month={day.month}",
                f"live/calendar/{day:%Y%m}", encoding="utf-8", refresh=True) or ""
    dates = parse.calendar_dates(cal)
    if dates and f"{day:%Y%m%d}" not in dates:
        return []
    html = f.get(f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={day:%Y%m%d}",
                 f"live/list/{day:%Y%m%d}", encoding="utf-8", refresh=True) or ""
    import re
    ids = sorted(set(re.findall(r"race_id=(\d{12})", html)))
    return [i for i in ids if i[4:6] in parse.VENUES and i[:4] == f"{day:%Y}"]


def win_odds(race_id: str, f: Fetcher) -> tuple[dict, str]:
    """Win odds by horse number, and where they come from (netkeiba's forecast before sales open)."""
    txt = f.get(f"https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=init",
                f"live/odds/{race_id}", encoding="utf-8", refresh=True) or "{}"
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        return {}, ""
    odds = {}
    for num, v in ((d.get("data") or {}).get("odds") or {}).get("1", {}).items():
        try:
            o = float(v[0])
        except (ValueError, TypeError, IndexError):
            continue
        if o > 0:
            odds[int(num)] = o
    return odds, d.get("status", "")


def entry_rows(df: pd.DataFrame, races: list[dict]) -> pd.DataFrame:
    """Features for the runners of several upcoming races on one surface (one feature build)."""
    date = pd.Timestamp(races[0]["date"])
    parts = []
    for race in races:
        rows = pd.DataFrame(race["horses"])
        n = len(rows)
        if rows["number"].isna().any():
            rows["number"] = np.arange(1, n + 1)
        going = GOING_NORM.get(race.get("going") or "良", race.get("going") or "良")
        parts.append(rows.assign(race_id=race["race_id"], date=date, surface=race["surface"],
                                 distance=race["distance"], field=n, finish=np.nan, time_sec=np.nan,
                                 odds=np.nan, prize=np.nan, speed=np.nan, early_pos=np.nan,
                                 kick_rel=np.nan, last3f=np.nan, passing=None, race_name=race["title"],
                                 going=going, venue=parse.VENUES[race["race_id"][4:6]],
                                 class_text=race.get("class_text"), grade=race.get("grade")))
    rows = pd.concat(parts, ignore_index=True)
    rows["number"] = rows["number"].astype(int)
    keep = [c for c in rows.columns if c in df.columns or c in ("jockey_name",)]
    all_ = pd.concat([df[df["date"] < date], rows[keep]], ignore_index=True)
    out = features.build(all_, start=date.strftime("%Y-%m"), asof=date)
    out = out[out["race_id"].isin([r["race_id"] for r in races])].copy()
    # build() reorders rows; put the odds back by race and number.
    odds = {(r["race_id"], h["number"]): h["odds"] for r in races for h in r["horses"]}
    out["odds"] = [odds.get((rid, n)) for rid, n in zip(out["race_id"], out["number"])]
    return out


# -- betting ------------------------------------------------------------------

def read_bets() -> pd.DataFrame:
    b = pd.read_csv(BETS, dtype={"race_id": str, "date": str}) if BETS.exists() else pd.DataFrame(columns=BET_COLS)
    b["settled"] = b["settled"].astype(str).str.lower().eq("true")
    b["finish"] = b["finish"].astype(object)
    for c in ("payout", "final_odds", "stake", "p_model", "p_market", "odds_at_bet"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    return b


def write_bets(b: pd.DataFrame):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = BETS.with_suffix(".tmp")
    b[BET_COLS].to_csv(tmp, index=False)
    tmp.replace(BETS)


def bet(day: dt.date):
    f = Fetcher(ROOT / "data" / "raw", interval=1.2)
    ids = race_ids_on(day, f)
    if not ids:
        print(f"{day}: JRAの開催なし")
        return []
    existing = read_bets()
    done = set(existing.loc[existing["date"] == day.isoformat(), "race_id"])
    ids = [i for i in ids if i not in done]
    print(f"{day}: {len(ids)} races to bet ({len(done)} already bet)", flush=True)
    races = []
    for rid in ids:
        html = f.get(f"https://race.netkeiba.com/race/shutuba.html?race_id={rid}", f"live/entries/{rid}",
                     encoding="utf-8", refresh=True)
        race = parse.entries(html or "", rid)
        if not race:
            print(rid, "no entries page", flush=True)
            continue
        odds, status = win_odds(rid, f)
        horses = [h for h in race["horses"] if not h["scratched"] and (not odds or h["number"] in odds)]
        for h in horses:
            h["odds"] = odds.get(h["number"])
        race.update(horses=horses, odds_source=ODDS_SOURCE.get(status, status), date=day.isoformat())
        races.append(race)

    df_cache = {}
    preds, new = [], []
    stamp = now_jst()
    for surface in ("芝", "ダ", "障"):
        group = [r for r in races if r["surface"] == surface and r["horses"]]
        if not group:
            continue
        model, info = load_model(surface) if surface != "障" else (None, None)
        indep = load_model(surface, indep=True)[0] if surface != "障" else None
        if model is not None:
            if surface not in df_cache:
                df_cache[surface] = load_runs(LOCAL_DB, surface=surface)
            rows = entry_rows(df_cache[surface], group)
        else:  # jump races (no model yet): the market's own probabilities
            rows = pd.DataFrame([dict(h, race_id=r["race_id"]) for r in group for h in r["horses"]])
        rows = rows[rows["odds"].notna()].copy()
        if rows.empty:
            continue
        rows["p_market"] = evaluate.market_probs(rows)
        rows["p_model"] = model.predict(rows) if model is not None else rows["p_market"]
        rows["p_indep"] = indep.predict(rows) if indep is not None else np.nan
        rows["pop_rank"] = rows.groupby("race_id")["odds"].rank(method="first")
        rows["facts"] = dirt_facts(rows) if surface == "ダ" else 0
        name = "offset_pace2" if model is not None else "market"
        for race in group:
            d = rows[rows["race_id"] == race["race_id"]]
            if d.empty:
                continue
            for _, h in d.iterrows():
                preds.append({"race_id": race["race_id"], "number": int(h["number"]), "horse_name": h["horse_name"],
                              "odds_at_bet": h["odds"], "p_market": round(h["p_market"], 5),
                              "p_model": round(h["p_model"], 5), "p_indep": round(float(h["p_indep"]), 5),
                              "pop_rank": int(h["pop_rank"]), "facts": int(h["facts"]), "model": name})
            post = race.get("post_time")
            if post:
                start = dt.datetime.combine(day, dt.time.fromisoformat(post.zfill(5)), JST)
                if start <= stamp + dt.timedelta(minutes=1):
                    print(race["race_id"], "already off, not bet", flush=True)
                    continue
            top = d.loc[d["p_model"].idxmax()]
            picks = [("fav_win", "単勝", top), ("fav_place", "複勝", top)]
            picks += [("value_win", "単勝", h) for _, h in d.iterrows()
                      if h["p_model"] * h["odds"] >= EV_MIN and h["odds"] < EV_MAX_ODDS and name != "market"]
            if indep is not None:
                itop = d.loc[d["p_indep"].idxmax()]
                picks += [("indep_win", "単勝", itop), ("indep_place", "複勝", itop)]
                picks += [("claude_gap_win", "単勝", h) for _, h in d.iterrows()
                          if h["p_indep"] >= GAP_RATIO * h["p_market"] and h["odds"] < GAP_MAX_ODDS]
                fav = d.loc[d["pop_rank"].idxmin()]
                if surface == "ダ" and fav["facts"] >= 2:
                    picks.append(("claude_dirt_place", "複勝", fav))
                if surface == "ダ" and fav["facts"] >= 3:
                    picks.append(("claude_dirt_win", "単勝", fav))
            for strat, kind, h in picks:
                pm = h["p_indep"] if strat.startswith(("indep", "claude_gap")) else h["p_model"]
                new.append({"date": day.isoformat(), "race_id": race["race_id"],
                            "venue": parse.VENUES[race["race_id"][4:6]], "race_no": int(race["race_id"][-2:]),
                            "post_time": post, "race_name": race["title"].replace(" 出馬表", ""),
                            "surface": surface, "distance": race["distance"], "strategy": strat,
                            "bet_type": kind, "number": int(h["number"]), "horse_name": h["horse_name"],
                            "stake": STAKE, "p_model": round(float(pm), 4), "p_market": round(float(h["p_market"]), 4),
                            "odds_at_bet": h["odds"],
                            "odds_source": race["odds_source"], "placed_at": stamp.isoformat(timespec="seconds"),
                            "model": name, "settled": False, "finish": None, "final_odds": None, "payout": None})
    if preds:
        pdir = OUT / "predictions"
        pdir.mkdir(parents=True, exist_ok=True)
        path = pdir / f"{day.isoformat()}.csv"
        p = pd.DataFrame(preds)
        if path.exists():
            p = pd.concat([pd.read_csv(path, dtype={"race_id": str}), p]).drop_duplicates(["race_id", "number"], keep="last")
        p.to_csv(path, index=False)
    if new:
        write_bets(pd.concat([existing, pd.DataFrame(new)], ignore_index=True))
    n_races = len({b["race_id"] for b in new})
    print(f"placed {len(new)} paper bets on {n_races} races ({sum(b['stake'] for b in new)} yen)")
    return new


def results_for(ids: list[str], fetch: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Results and win/place payouts for these races: from the DB, else from race.netkeiba.com's
    result page (up the same evening; db.netkeiba.com can lag by days). Web results are kept
    in WEB_RESULTS so reports can use them too."""
    con = sqlite3.connect(LOCAL_DB)
    q = ",".join("?" * len(ids))
    res = pd.read_sql(f"SELECT race_id, number, finish, finish_raw, odds FROM results WHERE race_id IN ({q})", con, params=ids)
    pay = pd.read_sql(f"SELECT race_id, bet_type, combo, payout FROM payouts WHERE race_id IN ({q}) "
                      "AND bet_type IN ('単勝','複勝')", con, params=ids)
    con.close()
    web = pd.read_csv(WEB_RESULTS, dtype={"race_id": str, "combo": str}) if WEB_RESULTS.exists() else pd.DataFrame(
        columns=["kind", "race_id", "number", "finish", "finish_raw", "odds", "bet_type", "combo", "payout"])
    todo = [i for i in ids if i not in set(res["race_id"]) and i not in set(web["race_id"])]
    if fetch and todo:
        f = Fetcher(ROOT / "data" / "raw", interval=1.2)
        new = []
        for rid in todo:
            html = f.get(f"https://race.netkeiba.com/race/result.html?race_id={rid}", f"live/result/{rid}",
                         encoding="utf-8", refresh=True)
            d = parse.result_page(html or "", rid)
            if d and d["payouts"]:
                new += [dict(r, kind="result") for r in d["results"]] + [dict(p, kind="payout") for p in d["payouts"]]
        if new:
            web = pd.concat([web, pd.DataFrame(new)], ignore_index=True)
            web.to_csv(WEB_RESULTS, index=False)
        print(f"read {len({r['race_id'] for r in new})} results from race.netkeiba.com", flush=True)
    web = web[web["race_id"].isin(ids) & ~web["race_id"].isin(set(res["race_id"]))]
    w_res = web[web["kind"] == "result"][res.columns]
    w_pay = web[web["kind"] == "payout"][pay.columns]
    res = pd.concat([res, w_res.astype({"number": int})], ignore_index=True)
    pay = pd.concat([pay, w_pay], ignore_index=True)
    for c in ("finish", "odds"):
        res[c] = pd.to_numeric(res[c], errors="coerce")
    pay["payout"] = pd.to_numeric(pay["payout"], errors="coerce").fillna(0)
    return res, pay


def settle():
    """Settle every open bet whose race result is known."""
    b = read_bets()
    open_ = b[~b["settled"]]
    if open_.empty:
        print("no open bets")
        return b
    ids = sorted(open_["race_id"].unique())
    res, pay = results_for(ids)
    pay["combo"] = pay["combo"].astype(str)
    con = sqlite3.connect(LOCAL_DB)
    q = ",".join("?" * len(ids))
    missing = {r for r, s in con.execute(f"SELECT race_id, status FROM race_queue WHERE race_id IN ({q})", ids)
               if s == "missing"}
    con.close()
    today = now_jst().date()
    n = 0
    for i, r in open_.iterrows():
        rr = res[(res["race_id"] == r["race_id"]) & (res["number"] == r["number"])]
        if rr.empty:
            old = (today - dt.date.fromisoformat(r["date"])).days >= 4
            if r["race_id"] in missing or (old and r["race_id"] not in set(res["race_id"])):
                b.loc[i, ["settled", "finish", "payout"]] = [True, "中止", r["stake"]]  # race not run: refund
                n += 1
            continue
        rr = rr.iloc[0]
        b.loc[i, "final_odds"] = rr["odds"]
        if rr["finish_raw"] in ("取", "除"):  # scratched after the bet: refund
            b.loc[i, ["settled", "finish", "payout"]] = [True, rr["finish_raw"], r["stake"]]
            n += 1
            continue
        hit = pay[(pay["race_id"] == r["race_id"]) & (pay["bet_type"] == r["bet_type"])
                  & (pay["combo"] == str(int(r["number"])))]
        payout = int(hit["payout"].sum() * r["stake"] / 100) if not hit.empty else 0
        b.loc[i, ["settled", "finish", "payout"]] = [True, rr["finish_raw"], payout]
        n += 1
    write_bets(b)
    print(f"settled {n} bets, {int((~b['settled'].astype(bool)).sum())} still open")
    return b


# -- reports ------------------------------------------------------------------

def _yen(x) -> str:
    return f"{int(round(x)):,}円"


def _strategy_table(s: pd.DataFrame, by: str | None = None) -> list[str]:
    keys = [by, "strategy"] if by else ["strategy"]
    g = s.groupby(keys, sort=False)
    t = pd.DataFrame({"bets": g.size(), "hits": g["payout"].apply(lambda x: (x > 0).sum()),
                      "stake": g["stake"].sum(), "ret": g["payout"].sum()}).reset_index()
    order = {k: i for i, k in enumerate(STRATEGIES)}
    t = t.sort_values(([by] if by else []) + ["strategy"], key=lambda c: c.map(order) if c.name == "strategy" else c)
    head = ([{"surface": "芝ダ障", "venue": "競馬場"}.get(by, by)] if by else []) + ["グループ", "買い方", "点数", "的中", "的中率", "投資", "払戻", "回収率"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for _, r in t.iterrows():
        grp, label = STRATEGIES.get(r["strategy"], ("", r["strategy"]))
        cells = ([str(r[by])] if by else []) + [grp, label, str(r["bets"]), str(r["hits"]),
                                                f"{r['hits'] / max(r['bets'], 1):.1%}", _yen(r["stake"]), _yen(r["ret"]),
                                                f"{r['ret'] / max(r['stake'], 1):.1%}"]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def model_feedback(settled_dates: list[str]) -> list[str]:
    """How the model's probabilities did against the market on the races already run."""
    frames = []
    for d in settled_dates:
        path = OUT / "predictions" / f"{d}.csv"
        if path.exists():
            frames.append(pd.read_csv(path, dtype={"race_id": str}))
    if not frames:
        return []
    p = pd.concat(frames)
    res = results_for(sorted(p["race_id"].unique()), fetch=False)[0]
    res = res[["race_id", "number", "finish", "odds"]].rename(columns={"odds": "final_odds"})
    p = p.merge(res, on=["race_id", "number"], how="inner")
    p = p[p.groupby("race_id")["finish"].transform(lambda s: (s == 1).any())]
    m = p[p["model"] != "market"]
    if m.empty:
        return []
    m = m.astype({c: float for c in ("p_model", "p_market", "odds_at_bet", "final_odds") if c in m})
    m = m.assign(p_final=evaluate.market_probs(m.rename(columns={"odds": "_o", "final_odds": "odds"})))
    w = m[m["finish"] == 1]
    ll = lambda col: -np.log(np.clip(w[col], 1e-6, 1))
    d = ll("p_model") - ll("p_market")
    lines = [f"対象：モデルで予想した決着済み {w['race_id'].nunique()} レース（障害は除く）", "",
             "| 予想 | 対数損失（低いほど良い） | 本命の勝率 |", "|---|---|---|"]
    cols = [("オッズ準拠モデル", "p_model")] + ([("独自モデル（オッズ不使用）", "p_indep")] if "p_indep" in m and m["p_indep"].notna().all() else [])
    for label, col in cols + [("賭けた時点のオッズ", "p_market"), ("確定オッズ", "p_final")]:
        top = m.loc[m.groupby("race_id")[col].idxmax()]
        lines.append(f"| {label} | {ll(col).mean():.4f} | {(top['finish'] == 1).mean():.1%} |")
    se = d.std() / np.sqrt(len(d)) if len(d) > 1 else float("nan")
    lines += ["", f"オッズ準拠モデル − 賭けた時点のオッズ：{d.mean():+.4f}（±{se:.4f}）。"
              + ("マイナスならモデルがオッズより当たっています。" if len(d) >= 30 else "まだレース数が少なく、差は偶然の範囲です。")]
    # Value threshold sweep on the races so far (win payouts approximated by final odds).
    lines += ["", "期待値のしきい値を変えた場合（確定オッズで計算した単勝の回収率）：", "",
              "| しきい値 | 点数 | 回収率 |", "|---|---|---|"]
    for t in (1.0, 1.1, 1.2, 1.3, 1.5):
        sel = m[(m["p_model"] * m["odds_at_bet"] >= t) & (m["odds_at_bet"] < EV_MAX_ODDS)]
        roi = ((sel["finish"] == 1) * sel["final_odds"]).sum() / max(len(sel), 1)
        lines.append(f"| {t:.1f} | {len(sel)} | {roi:.1%} |")
    # Calibration: predicted vs actual win rate by probability band.
    bands = pd.cut(m["p_model"], [0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0])
    cal = m.groupby(bands, observed=True).agg(n=("p_model", "size"), pred=("p_model", "mean"),
                                              act=("finish", lambda s: (s == 1).mean()))
    lines += ["", "予想勝率の帯ごとの実際の勝率：", "", "| 予想勝率 | 頭数 | 予想の平均 | 実際 |", "|---|---|---|---|"]
    for band, r in cal.iterrows():
        lines.append(f"| {band.left:.0%}〜{band.right:.0%} | {int(r['n'])} | {r['pred']:.1%} | {r['act']:.1%} |")
    return lines


def report():
    b = read_bets()
    s = b[b["settled"].astype(bool)].copy()
    lines = ["# 仮想ベットの成績", "",
             f"更新：{now_jst():%Y-%m-%d %H:%M} JST。実際の馬券は買っていません。1点100円。",
             "", "3つのグループを並べて賭けています。",
             f"- **オッズ準拠モデル**：オッズを出発点に補正するモデル。本命の単勝・複勝を全レース、勝率×オッズが{EV_MIN}以上の馬の単勝。"
             "障害レースはモデルがないので1番人気を本命にしています。",
             "- **独自モデル**：オッズも過去の人気も使わず、馬の走りの記録（スピード指数、近走、ペース、コース・距離の得意、昇級降級、騎手の格上げ、前走の相手の強さなど）だけで勝率を出すモデル。本命の単勝・複勝を芝・ダートの全レース。",
             f"- **Claudeの買い方**：過去データ（2018〜2023年で選び、2024年以降で確認）から決めたルール。独自モデルの勝率が市場の{GAP_RATIO:.0f}倍以上で{GAP_MAX_ODDS:.0f}倍未満の馬の単勝。"
             "ダートの1番人気のうち、好材料（前走の相手が強い・外枠・距離短縮・前走でペースが不利・スピード指数上位）が2つ以上なら複勝、3つ以上なら単勝も。"
             "検証は[experiments/strategies.md](https://github.com/hishiki-taisei/keiba-sim/blob/main/experiments/strategies.md)と[rules.md](https://github.com/hishiki-taisei/keiba-sim/blob/main/experiments/rules.md)。", ""]
    if s.empty:
        lines += ["まだ決着したベットはありません。"]
    else:
        s["payout"] = s["payout"].astype(float)
        dates = sorted(s["date"].unique())
        lines += [f"## 通算（{dates[0]}〜{dates[-1]}、{s['race_id'].nunique()}レース）", ""]
        lines += _strategy_table(s) + ["", "## 芝・ダート・障害別", ""] + _strategy_table(s, "surface")
        lines += ["", "## 日ごと", "", "| 日付 | レース | " + " | ".join(f"{g[:2]}：{v}" for g, v in STRATEGIES.values()) + " |",
                  "|---|---|" + "---|" * len(STRATEGIES)]
        for d in dates[::-1]:
            x = s[s["date"] == d]
            cells = []
            for k in STRATEGIES:
                y = x[x["strategy"] == k]
                cells.append(f"{y['payout'].sum() / y['stake'].sum():.0%}（{len(y)}点）" if len(y) else "—")
            lines.append(f"| [{d}](daily/{d}.md) | {x['race_id'].nunique()} | " + " | ".join(cells) + " |")
        fb = model_feedback(dates)
        if fb:
            lines += ["", "## モデルへのフィードバック", ""] + fb
        for d in dates:
            write_daily(d, b[b["date"] == d])
    trained = OUT / "train_log.csv"
    if trained.exists():
        t = pd.read_csv(trained).tail(4)
        lines += ["", "## いまのモデル", "", "毎晩、その日までの結果を足して学び直しています。", "",
                  "| 芝ダ | 学習した日時 | データの最終日 | 木の数 | 直近1年 対数損失 | 同 オッズ |", "|---|---|---|---|---|---|"]
        for _, r in t.iterrows():
            lines.append(f"| {r['surface']} | {r['trained_at'][:16]} | {r['data_until']} | {r['trees']} | "
                         f"{r['valid_logloss']} | {r['valid_market_logloss']} |")
    open_ = b[~b["settled"].astype(bool)]
    if not open_.empty:
        lines += ["", f"未決着：{open_['race_id'].nunique()}レース {len(open_)}点（{', '.join(sorted(open_['date'].unique()))}）"]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print((OUT / "summary.md").read_text())


def write_daily(day: str, b: pd.DataFrame):
    (OUT / "daily").mkdir(parents=True, exist_ok=True)
    b = b.sort_values(["venue", "race_no"])
    s = b[b["settled"].astype(bool)]
    lines = [f"# {day} の仮想ベット", ""]
    if not s.empty:
        lines += _strategy_table(s.assign(payout=s["payout"].astype(float))) + [""]
    lines += ["| レース | 発走 | 買い方 | 馬番 | 馬 | 勝率(その買い方のモデル) | 賭けた時のオッズ | 着順 | 確定オッズ | 払戻 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in b.iterrows():
        pay = "" if not r["settled"] else _yen(float(r["payout"]))
        fo = "" if pd.isna(r["final_odds"]) else f"{float(r['final_odds']):.1f}"
        lines.append(f"| {r['venue']}{int(r['race_no'])}R {r['race_name']} | {r['post_time']} | "
                     f"{'：'.join(STRATEGIES[r['strategy']])} | {int(r['number'])} | {r['horse_name']} | {float(r['p_model']):.1%} | "
                     f"{float(r['odds_at_bet']):.1f}（{r['odds_source']}） | {'' if pd.isna(r['finish']) else r['finish']} | {fo} | {pay} |")
    (OUT / "daily" / f"{day}.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m live")
    ap.add_argument("cmd", choices=["morning", "night", "bet", "settle", "train", "report", "update"])
    ap.add_argument("--date", type=dt.date.fromisoformat, default=None)
    ap.add_argument("--no-train", action="store_true")
    a = ap.parse_args(argv)
    day = a.date or now_jst().date()
    OUT.mkdir(parents=True, exist_ok=True)
    sync_in()
    if a.cmd in ("morning", "bet"):
        if load_model("芝")[0] is None:
            train()
        bet(day)
        report()
    elif a.cmd == "night":
        update()
        settle()
        sync_out()
        if not a.no_train:
            train()
        report()
    elif a.cmd == "update":
        update()
        sync_out()
    else:
        {"settle": settle, "train": train, "report": report}[a.cmd]()


if __name__ == "__main__":
    main()
