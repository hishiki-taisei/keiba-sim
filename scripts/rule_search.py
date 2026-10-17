"""Search simple, readable betting rules: one race fact x popularity band.

    python3 scripts/rule_search.py --features-dir DIR

Each fact is cut into quintiles on the training years. A rule is "fact in bin b AND
popularity in band k", bet to win or to place. Rules are kept only when they return
well on the training years (2018-2022) AND on 2023; the test years (2024-) are only
reported. Writes experiments/rules.md and data/rules.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.strategy_search import load, roi  # noqa: E402

FACTS = {
    "jockey_up": "前走からの騎手の格上げ", "class_change": "クラスの上げ下げ", "days_off": "休養明けの間隔",
    "dist_change": "距離の延長・短縮", "venue_apt": "この競馬場の得意不得意", "dist_apt": "この距離帯の得意不得意",
    "last_fin": "前走の着順（割合）", "early_pos5": "近5走の位置取り", "gate_rel": "馬番（内外）",
    "weight_rel": "斤量（出走馬平均との差）", "age": "年齢", "last_field_y5": "前走の相手の強さ",
    "pace_favor5": "近走のペースの有利不利", "kick5": "近5走の上がり", "rating": "スピード指数（出走馬平均との差）",
    "trainer_rel": "調教師の成績（出走馬平均との差）", "field": "頭数", "heavy_x": "道悪の得意×当日の馬場",
}
BANDS = {"1番人気": (1, 1), "2〜3番人気": (2, 3), "4〜6番人気": (4, 6), "7〜10番人気": (7, 10)}
FLAGS = {"second_up": "休み明け2戦目", "jockey_change": "騎手の乗り替わり", "handicap": "ハンデ戦"}


def rules_for(F: pd.DataFrame):
    train = F[F["date"].dt.year <= 2022]
    for fact, label in FACTS.items():
        edges = np.unique(np.nanquantile(train[fact], [0.2, 0.4, 0.6, 0.8]))
        b = np.searchsorted(edges, F[fact].to_numpy(), side="right")
        for k in range(len(edges) + 1):
            lo = "最小" if k == 0 else f"{edges[k - 1]:.3g}"
            hi = "最大" if k == len(edges) else f"{edges[k]:.3g}"
            yield fact, (k, edges.tolist()), f"{label}が{lo}〜{hi}", b == k
    for fact, label in FLAGS.items():
        yield fact, (1, None), label, F[fact].to_numpy() == 1


def search(F: pd.DataFrame, surface: str) -> list[dict]:
    year = F["date"].dt.year.to_numpy()
    parts = {"train": year <= 2022, "valid": year == 2023, "test": year >= 2024}
    out = []
    for fact, spec, desc, mask in rules_for(F):
        for band, (lo, hi) in BANDS.items():
            m = mask & F["pop_rank"].between(lo, hi).to_numpy()
            for kind in ("win", "place"):
                row = {"surface": surface, "fact": fact, "bin": spec[0], "edges": spec[1], "band": [lo, hi],
                       "kind": kind, "desc": f"{desc}、{band}"}
                for p, sel in parts.items():
                    row[p] = roi(F[m & sel], kind)
                out.append(row)
    return out


def main():
    fdir = Path(sys.argv[sys.argv.index("--features-dir") + 1])
    lines = ["# 読める買い方のルール探し", "",
             "「ひとつの事実（休み明け、騎手の格上げ、距離短縮など）× 人気の帯」で買い方を作り、"
             "学習（2018〜2022年）と調整（2023年）の両方で回収率が高かったものだけを残して、テスト（2024年〜）の成績を見ています。"
             "払戻は実際の払戻金、人気は確定オッズの順位です。", ""]
    picked = {}
    for surface in ("芝", "ダ"):
        F = load(surface) if fdir is None else _load(fdir, surface)
        res = search(F, surface)
        ok = [r for r in res if r["train"]["n"] >= 400 and r["valid"]["n"] >= 80]
        ok.sort(key=lambda r: -min(r["train"]["roi"], r["valid"]["roi"]))
        lines += [f"## {surface}", "", "| ルール | 券種 | 学習 点数 | 学習 回収率 | 調整 点数 | 調整 回収率 | テスト 点数 | テスト 的中率 | テスト 回収率 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in ok[:15]:
            t = r["test"]
            lines.append(f"| {r['desc']} | {'単勝' if r['kind'] == 'win' else '複勝'} | {r['train']['n']} | {r['train']['roi']:.1%} | "
                         f"{r['valid']['n']} | {r['valid']['roi']:.1%} | {t['n']} | {t['hit']:.1%} | {t['roi']:.1%}（±{t['se']:.1%}） |")
        lines.append("")
        picked[surface] = [{k: r[k] for k in ("fact", "bin", "edges", "band", "kind", "desc")}
                           | {"train_roi": round(r["train"]["roi"], 4), "valid_roi": round(r["valid"]["roi"], 4),
                              "test_roi": round(r["test"]["roi"], 4), "test_n": r["test"]["n"]} for r in ok[:15]]
    (ROOT / "experiments" / "rules.md").write_text("\n".join(lines) + "\n")
    (ROOT / "data" / "rules_all.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1))
    print("\n".join(lines))


def _load(fdir, surface):
    import scripts.strategy_search as ss
    ss.FDIR = fdir
    return ss.load(surface)


if __name__ == "__main__":
    main()
