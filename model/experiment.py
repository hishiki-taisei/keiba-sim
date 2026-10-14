"""Record every model we try in one table so progress can be followed over time.

Each run appends a row to experiments/log.csv and rewrites experiments/README.md.
Periods: train 2018-2022, valid 2023, test 2024-. The 菊花賞-like subset is
3-year-olds in turf races of 2400m+ from September to November.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from . import evaluate

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "experiments" / "log.csv"
SIM_LOG = ROOT / "experiments" / "sim_log.csv"
README = ROOT / "experiments" / "README.md"


def subsets(d: pd.DataFrame) -> dict:
    long_ = d["distance"] >= 2200
    kikka_like = (d["distance"] >= 2400) & (d["age"] == 3) & d["date"].dt.month.between(9, 11)
    return {"all": d, "long": d[long_], "kikka_like": d[kikka_like]}


def score(predict, valid: pd.DataFrame, test: pd.DataFrame) -> dict:
    row = {}
    for period, part in (("valid", valid), ("test", test)):
        for sub, d in subsets(part).items():
            if d.empty:
                continue
            m = evaluate.metrics(d, predict(d))
            row[f"{period}_{sub}_logloss"] = round(m["logloss"], 4)
            row[f"{period}_{sub}_win"] = round(m["win_hit"], 4)
            row[f"{period}_{sub}_top3"] = round(m["top_pick_in3"], 4)
            row[f"{period}_{sub}_races"] = m["races"]
    return row


def record(name: str, description: str, predict, valid, test, surface: str = "芝") -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    row = {"date": dt.date.today().isoformat(), "surface": surface, "name": name, "description": description,
           "commit": commit,
           **score(predict, valid, test)}
    LOG.parent.mkdir(exist_ok=True)
    log = pd.read_csv(LOG) if LOG.exists() else pd.DataFrame()
    if "surface" in log:
        log["surface"] = log["surface"].fillna("芝")
        log = log[~((log["name"] == name) & (log["surface"] == surface))]  # re-running replaces the row
    log = pd.concat([log, pd.DataFrame([row])], ignore_index=True)
    log.to_csv(LOG, index=False)
    write_readme(log)
    return row


def record_sim(name: str, description: str, sim: dict, base: dict):
    """One row for a simulator test on turf 2400m+ (2024-)."""
    row = {"date": dt.date.today().isoformat(), "name": name, "description": description,
           "races": sim["races"], "logloss": round(sim["logloss"], 4), "win": round(sim["win_hit"], 4),
           "top3": round(sim["top_pick_in3"], 4), "strength_logloss": round(base["logloss"], 4),
           "strength_win": round(base["win_hit"], 4)}
    log = pd.read_csv(SIM_LOG) if SIM_LOG.exists() else pd.DataFrame()
    log = log[log["name"] != name] if "name" in log else log
    pd.concat([log, pd.DataFrame([row])], ignore_index=True).to_csv(SIM_LOG, index=False)
    write_readme(pd.read_csv(LOG))


def write_readme(log: pd.DataFrame):
    pct = lambda x: "" if pd.isna(x) else f"{100 * x:.1f}%"
    lines = [
        "# モデルの記録",
        "",
        "試したモデルを1行ずつ記録しています（`python3 scripts/experiment.py` が自動で更新）。",
        "学習 2018〜2022年、調整 2023年、テスト 2024年1月〜。対数損失は低いほど良く、",
        "「本命」はモデルがいちばん勝率が高いと出した馬です。菊花賞型は「3歳・芝2400m以上・9〜11月」。",
        "勾配ブースティング（gbdt）は調整期間で学習の止めどころを決めているので、比べるときはテストの列を見てください。",
        "",
    ]
    log = log.assign(surface=log["surface"].fillna("芝") if "surface" in log else "芝")
    for surface, part in log.groupby("surface", sort=False):
        lines += ["", f"## {surface}", "",
                  "| 日付 | モデル | 内容 | 調整 対数損失 | テスト 対数損失 | テスト 本命勝率 | テスト 本命3着内 "
                  "| 長距離 対数損失 | 長距離 本命勝率 | 菊花賞型 本命勝率 | 菊花賞型 本命3着内 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in part.iterrows():
            lines.append(
                f"| {r['date']} | {r['name']} | {r['description']} | {r['valid_all_logloss']:.4f} "
                f"| {r['test_all_logloss']:.4f} | {pct(r['test_all_win'])} | {pct(r['test_all_top3'])} "
                f"| {r['test_long_logloss']:.4f} | {pct(r['test_long_win'])} "
                + (f"| {pct(r.get('test_kikka_like_win'))} | {pct(r.get('test_kikka_like_top3'))} |"
                   if surface == "芝" else "| — | — |"))
        n = part.iloc[-1]
        kl = n.get("test_kikka_like_races")
        lines += ["", f"テストのレース数：全体 {int(n['test_all_races'])}、長距離（2200m以上） {int(n['test_long_races'])}"
                  + (f"、菊花賞型 {int(kl)}" if pd.notna(kl) and surface == "芝" else "") + "。"]
    if SIM_LOG.exists():
        sim = pd.read_csv(SIM_LOG)
        lines += ["", "## シミュレーター", "",
                  "芝2400m以上のテスト期間（2024年〜）のレースを実際に走らせた成績です。"
                  "「元のモデル」はシミュレーターの最高速度の元になっている勝率モデル単体の成績です。", "",
                  "| 日付 | 版 | 内容 | レース数 | 対数損失 | 本命勝率 | 本命3着内 | 元のモデル 対数損失 | 元のモデル 本命勝率 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for _, r in sim.iterrows():
            lines.append(f"| {r['date']} | {r['name']} | {r['description']} | {r['races']} | {r['logloss']:.4f} "
                         f"| {pct(r['win'])} | {pct(r['top3'])} | {r['strength_logloss']:.4f} | {pct(r['strength_win'])} |")
    README.write_text("\n".join(lines) + "\n", encoding="utf-8")
