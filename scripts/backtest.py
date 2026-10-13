"""Train on past years, test on later ones, and write a report.

    python3 scripts/backtest.py --db data/keiba.sqlite

Split by date (no shuffling): train < --valid-start <= valid < --test-start <= test.
1. Fundamentals model (no odds): conditional logit on FEATURES, L2 picked on valid.
2. Blend with the market: a second conditional logit on [model score, log market
   probability], fitted on valid (Benter's two-stage method).
Both are scored on test with accuracy and win/place returns from the payouts
table. Rerun as the database grows; the split dates are arguments.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from predict import data, features  # noqa: E402
from predict.evaluate import market_prob, metrics, payout_lookup  # noqa: E402
from predict.model import ConditionalLogit  # noqa: E402

L2_GRID = [0.1, 1, 10, 100, 1000]


def subsets(df):
    yield "全レース", np.ones(len(df), bool)
    yield "芝", (df.surface == "芝").to_numpy()
    yield "芝2200m以上", ((df.surface == "芝") & (df.distance >= 2200)).to_numpy()
    yield "重賞", df.grade.isin(["G1", "G2", "G3"]).to_numpy()


def fmt_table(rows):
    cols = ["model", "subset", "races", "logloss", "top1_win", "top1_in3", "winner_in_top3",
            "roi_win_top1", "roi_place_top1", "value_bets", "roi_win_value"]
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = ""
    for r in rows:
        body += "| " + " | ".join(f"{r[c]:.3f}" if isinstance(r[c], float) else str(r[c]) for c in cols) + " |\n"
    return head + body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--valid-start", default="2025-01-01")
    ap.add_argument("--test-start", default="2026-01-01")
    ap.add_argument("--out", default=str(ROOT / "reports"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    runners = data.load_runners(args.db)
    pay = payout_lookup(data.load_payouts(args.db))
    std = features.speed_standards(runners, before=args.valid_start)
    df = features.build(runners, std)
    # races need a winner and odds for every starter to be scored
    ok = df.groupby("race_id").agg(w=("finish", lambda s: (s == 1).any()), o=("odds", lambda s: s.notna().all()))
    df = df[df.race_id.isin(ok[ok.w & ok.o].index)].reset_index(drop=True)
    df["mkt"] = market_prob(df)

    tr = df[df.date < args.valid_start]
    va = df[(df.date >= args.valid_start) & (df.date < args.test_start)]
    te = df[df.date >= args.test_start]
    # the first months have almost no history; skip them for training
    tr = tr[tr.date >= tr.date.min() + pd.DateOffset(months=6)]
    print(f"train {tr.race_id.nunique()} races, valid {va.race_id.nunique()}, test {te.race_id.nunique()}")

    def fit(d, l2, cols=features.FEATURES):
        return ConditionalLogit(list(cols), l2=l2).fit(d[cols].to_numpy(), d.race_id.to_numpy(), (d.finish == 1).to_numpy())

    best = None
    for l2 in L2_GRID:
        m = fit(tr, l2)
        ll = metrics(va, m.predict(va[features.FEATURES].to_numpy(), va.race_id.to_numpy()), pay)["logloss"]
        print(f"l2={l2}: valid logloss {ll:.4f}")
        if best is None or ll < best[0]:
            best = (ll, l2, m)
    _, l2, model = best

    def stage2_inputs(d):
        return np.c_[model.score(d[features.FEATURES].to_numpy()), np.log(d.mkt.to_numpy())]

    stage2 = ConditionalLogit(["model_score", "log_market"], l2=0.01).fit(
        stage2_inputs(va), va.race_id.to_numpy(), (va.finish == 1).to_numpy())

    preds = {
        "市場オッズ": lambda d: d.mkt.to_numpy(),
        "能力モデル": lambda d: model.predict(d[features.FEATURES].to_numpy(), d.race_id.to_numpy()),
        "能力+市場": lambda d: stage2.predict(stage2_inputs(d), d.race_id.to_numpy()),
    }
    rows = []
    for split_name, d in [("valid", va), ("test", te)]:
        for name, f in preds.items():
            p = f(d)
            for sub, mask in subsets(d):
                if mask.sum() == 0:
                    continue
                r = metrics(d[mask], p[mask], pay)
                rows.append({"split": split_name, "model": name, "subset": sub, **r})

    # past Kikka-sho: how would the fundamentals model have ranked the field?
    kikka = []
    for rid, g in df[df.race_name.str.contains("菊花賞", na=False)].groupby("race_id"):
        g = g.assign(p=model.predict(g[features.FEATURES].to_numpy(), g.race_id.to_numpy())).sort_values("p", ascending=False)
        kikka.append((g.date.iloc[0].date(), g.head(5)[["horse_name", "p", "popularity", "finish"]],
                      g[g.finish == 1].horse_name.iloc[0], int(g[g.finish == 1].p.rank().iloc[0]),
                      int((g.p.rank(ascending=False)[g.finish == 1]).iloc[0])))

    lines = [
        "# バックテスト結果", "",
        f"- 学習: {tr.date.min().date()} 〜 {tr.date.max().date()}（{tr.race_id.nunique()}レース）",
        f"- 検証: {va.date.min().date()} 〜 {va.date.max().date()}（{va.race_id.nunique()}レース）, L2={l2}",
        f"- テスト: {te.date.min().date()} 〜 {te.date.max().date()}（{te.race_id.nunique()}レース）",
        "- logloss は勝ち馬に付けた確率の負の対数の平均（小さいほど良い）。回収率は100円ずつ買ったときの払戻/購入額。",
        "- 「能力+市場」と value 買いは確定オッズを使うので、実際に買える前日オッズより少し有利な見積もりです。",
        "",
    ]
    for split_name in ["test", "valid"]:
        lines += [f"## {split_name}", "", fmt_table([r for r in rows if r["split"] == split_name]), ""]
    lines += ["## 能力モデルの係数（標準化後）", "", "| 特徴量 | 係数 |", "|---|---|"]
    lines += [f"| {k} | {v:+.3f} |" for k, v in sorted(model.coefficients().items(), key=lambda kv: -abs(kv[1]))]
    lines += ["", f"市場ブレンド: {stage2.coefficients()}", "", "## 過去の菊花賞（能力モデルの上位5頭）", "",
              f"{va.date.min().year}年より前の菊花賞は学習期間に入っているので参考値です。", ""]
    for date, top5, winner, _, wrank in kikka:
        lines.append(f"**{date}** 勝ち馬 {winner}（モデル{wrank}位）")
        lines.append("")
        lines.append("| 馬 | 予想勝率 | 人気 | 着順 |\n|---|---|---|---|")
        lines += [f"| {r.horse_name} | {r.p:.1%} | {r.popularity:.0f} | {r.finish} |" for r in top5.itertuples()]
        lines.append("")

    (out / "backtest.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "backtest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "model.json").write_text(model.to_json(), encoding="utf-8")
    print("\n".join(lines[:8]))
    print(fmt_table([r for r in rows if r["split"] == "test"]))


if __name__ == "__main__":
    main()
