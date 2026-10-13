"""Win probabilities for an upcoming race from a list of entries.

    python3 scripts/predict_race.py races/kikka2026.csv --date 2026-10-25 \
        --venue 京都 --surface 芝 --distance 3000 --out reports/kikka2026.md

The entries CSV needs horse_name; jockey_name, number, weight_carried and odds
are optional. Missing values come from each horse's latest race. The models are
refitted on every finished race in the database, so rerun it as data grows.
With an odds column for every horse it also shows the market-corrected win rate.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from predict import data, features  # noqa: E402
from predict.evaluate import market_prob  # noqa: E402
from predict.pipeline import Ensemble, scorable, training_rows  # noqa: E402

UPCOMING = "UPCOMING"


def entry_rows(entries: pd.DataFrame, runners: pd.DataFrame, args) -> tuple[pd.DataFrame, list[str]]:
    last = runners.sort_values("date").groupby("horse_name").tail(1).set_index("horse_name")
    jockeys = runners.sort_values("date").groupby("jockey_name").jockey_id.last()
    rows, notes = [], []
    n = len(entries)
    for i, e in enumerate(entries.itertuples(index=False)):
        if e.horse_name not in last.index:
            notes.append(f"{e.horse_name}: データベースに過去走がないため除外")
            continue
        h = last.loc[e.horse_name]
        jname = getattr(e, "jockey_name", None)
        jid = jockeys.get(jname) if isinstance(jname, str) and jname else None
        if jid is None:
            reason = f"騎手「{jname}」が見つからない" if isinstance(jname, str) and jname else "騎手未定の"
            notes.append(f"{e.horse_name}: {reason}ため前走の{h.jockey_name}騎手で計算")
            jid, jname = h.jockey_id, h.jockey_name
        number = getattr(e, "number", np.nan)
        wc = getattr(e, "weight_carried", np.nan)
        rows.append({
            "race_id": UPCOMING, "date": pd.Timestamp(args.date), "venue": args.venue,
            "race_name": args.name, "grade": args.grade, "class_text": "", "surface": args.surface, "distance": args.distance,
            "going": args.going, "n_runners": n, "field": n,
            "number": number if pd.notna(number) else (n + 1) / 2,
            "finish": np.nan, "finish_raw": None, "frame": np.nan,
            "horse_id": h.horse_id, "horse_name": e.horse_name, "sex": h.sex,
            "age": h.age + (pd.Timestamp(args.date).year - h.date.year),
            "weight_carried": wc if pd.notna(wc) else (55.0 if h.sex == "牝" else 57.0),
            "jockey_id": jid, "jockey_name": jname, "time_sec": np.nan, "passing": None,
            "last3f": np.nan, "odds": getattr(e, "odds", np.nan), "popularity": np.nan,
            "body_weight": h.body_weight, "body_weight_diff": 0, "trainer_id": h.trainer_id,
            "prize": np.nan, "last_race": f"{h.date.date()} {h.race_name} {int(h.finish)}着",
        })
    return pd.DataFrame(rows), notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entries")
    ap.add_argument("--db")
    ap.add_argument("--date", required=True)
    ap.add_argument("--venue", default="京都")
    ap.add_argument("--surface", default="芝")
    ap.add_argument("--distance", type=int, default=3000)
    ap.add_argument("--going", default="良")
    ap.add_argument("--name", default="")
    ap.add_argument("--grade", default="G1")
    ap.add_argument("--trees", type=int, default=550, help="trees per model (backtest picks ~550)")
    ap.add_argument("--out")
    args = ap.parse_args()

    runners = data.load_runners(args.db)
    runners = runners[runners.date < args.date]
    entries = pd.read_csv(args.entries, dtype={"jockey_name": str})
    up, notes = entry_rows(entries, runners, args)

    df = features.build(pd.concat([runners, up], ignore_index=True), features.speed_standards(runners))
    hist = training_rows(scorable(df[df.race_id != UPCOMING]))
    model = Ensemble.fit(hist, n_trees=args.trees)

    race = df[df.race_id == UPCOMING].copy()
    race["p_win"] = model.predict(race)
    with_odds = race.odds.notna().all()
    if with_odds:
        # odds given: also correct the market with the model trained to do that
        race["mkt"] = market_prob(race)
        race["p_mkt"] = race.mkt
        race["p_adj"] = Ensemble.fit(hist, n_trees=args.trees, resid=True).predict(race)
    race = race.sort_values("p_win", ascending=False)

    lines = [f"# {args.name or 'レース'} 予想（{args.date} {args.venue}{args.surface}{args.distance}m）", "",
             f"学習データ: {hist.date.min().date()}〜{hist.date.max().date()}の{hist.race_id.nunique()}レース。"
             "勝率はオッズを使わない能力モデル（ブースティング木3本の平均）の値です。"
             + ("市場はオッズから出した勝率、補正後は市場の勝率をモデルで直した値です。" if with_odds else ""), "",
             "| 順位 | 馬 | 騎手 | 勝率 | " + ("市場 | 補正後 | " if with_odds else "") + "前走 | 過去走数 | 最高指数 |",
             "|---|---|---|---|" + ("---|---|" if with_odds else "") + "---|---|---|"]
    for i, r in enumerate(race.itertuples(), 1):
        odds_cols = f"{r.p_mkt:.1%} | {r.p_adj:.1%} | " if with_odds else ""
        lines.append(f"| {i} | {r.horse_name} | {r.jockey_name} | {r.p_win:.1%} | {odds_cols}{r.last_race} | "
                     f"{int(r.h_n)} | {r.h_fig_best:+.2f} |")
    if notes:
        lines += ["", "注記:", ""] + [f"- {s}" for s in notes]
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
