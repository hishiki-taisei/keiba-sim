"""Generate the demo race shown on the web app.

The runners here are fictional and their abilities are random. This only
shows the simulator working; it is not a prediction.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.course import kyoto_turf_3000  # noqa: E402
from sim.export import build, write  # noqa: E402
from sim.horse import Horse  # noqa: E402

NAMES = ["アカツキ", "ブルーライン", "サクラフブキ", "ゴールドタイド", "ミナモ", "クロガネ",
         "ハヤテ", "シラユキ", "ヨドノサカ", "ミカヅキ", "ツバメ", "コハク",
         "アオアラシ", "ヒノデ", "ナギサ", "イナズマ", "モミジ", "ホシアカリ"]


def main():
    rng = np.random.default_rng(2026)
    horses = [
        Horse(name=f"（架空）{name}",
              speed=round(float(17.2 + rng.normal(0, 0.12)), 2),
              stamina=round(float(1.0 + rng.normal(0, 0.025)), 3),
              kick=round(float(rng.uniform()), 2),
              style=round(float(rng.uniform()), 2),
              gate=i + 1)
        for i, name in enumerate(NAMES)
    ]
    data = build(kyoto_turf_3000(), horses, n=2000, seed=1,
                 title="デモレース（架空の馬）",
                 note="架空の馬にランダムな能力値を与えたデモです。実際の予想ではありません。")
    out = Path(__file__).resolve().parents[1] / "web" / "data" / "demo.json"
    write(data, out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
