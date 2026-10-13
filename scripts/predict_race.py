"""Win probabilities for an upcoming race from a list of entries.

    python3 scripts/predict_race.py races/kikka2026.csv --date 2026-10-25 \
        --venue 京都 --surface 芝 --distance 3000 --out reports/kikka2026.md

The entries CSV needs horse_name; jockey_name, number, weight_carried and odds
are optional. Missing values come from each horse's latest race. The model is
refitted on every finished race in the database, so rerun it as data grows.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from predict import data, features  # noqa: E402
from predict.model import ConditionalLogit  # noqa: E402

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
            "race_name": args.name, "grade": None, "surface": args.surface, "distance": args.distance,
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
    ap.add_argument("--l2", type=float, default=1.0)
    ap.add_argument("--out")
    args = ap.parse_args()

    runners = data.load_runners(args.db)
    runners = runners[runners.date < args.date]
    entries = pd.read_csv(args.entries, dtype={"jockey_name": str})
    up, notes = entry_rows(entries, runners, args)

    df = features.build(pd.concat([runners, up], ignore_index=True), features.speed_standards(runners))
    hist = df[df.race_id != UPCOMING]
    hist = hist[(hist.date >= hist.date.min() + pd.DateOffset(months=6)) & hist.odds.notna()]
    hist = hist[hist.groupby("race_id").finish.transform(lambda s: (s == 1).any())]
    cols = features.FEATURES
    model = ConditionalLogit(cols, l2=args.l2).fit(hist[cols].to_numpy(), hist.race_id.to_numpy(),
                                                   (hist.finish == 1).to_numpy())

    race = df[df.race_id == UPCOMING].copy()
    race["p_win"] = model.predict(race[cols].to_numpy(), race.race_id.to_numpy())
    race = race.sort_values("p_win", ascending=False)

    lines = [f"# {args.name or 'レース'} 予想（{args.date} {args.venue}{args.surface}{args.distance}m）", "",
             f"学習データ: {hist.date.min().date()}〜{hist.date.max().date()}の{hist.race_id.nunique()}レース。"
             "オッズを使わない能力モデルの勝率です。", "",
             "| 順位 | 馬 | 騎手 | 勝率 | 前走 | 過去走数 | 最高指数 |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(race.itertuples(), 1):
        lines.append(f"| {i} | {r.horse_name} | {r.jockey_name} | {r.p_win:.1%} | {r.last_race} | "
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
