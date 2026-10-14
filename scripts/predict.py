"""Predict an upcoming race and write it for the web app.

    python3 scripts/predict.py 202608040911 kikka2026

Fetches the entries from race.netkeiba.com, builds each horse's features as of
race day, scores them with the win model (trained on every race up to the
week before) and runs the simulator. Before the draw the gates are unknown,
so the race is run with several random draws and the results averaged.
Writes web/data/<name>.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import features  # noqa: E402
from model.data import load_runs  # noqa: E402
from model.logit import Logit  # noqa: E402
from model.to_sim import SimParams, course_for, horses  # noqa: E402
from scraper import parse  # noqa: E402
from scraper.fetch import Fetcher  # noqa: E402
from sim.export import build, write  # noqa: E402
from sim.race import probabilities, simulate  # noqa: E402

SIMULATED = ["early_pos5", "gate_rel", "kick5"]
N_SIM = 4000


def main(race_id: str, name: str):
    f = Fetcher(ROOT / "data" / "raw", interval=1.2)
    html = f.get(f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}",
                 f"entries/{race_id}", encoding="utf-8", refresh=True)
    race = parse.entries(html, race_id)
    drawn = all(h["number"] for h in race["horses"])
    print(f"{race['title']} {race['date']} {race['distance']}m  {len(race['horses'])} horses, drawn={drawn}")

    df = load_runs()
    F = pd.read_pickle(ROOT / "data" / "features_turf.pkl")
    F = F[F["odds"].notna() & (F["field"] >= 5) & (F["date"] < pd.Timestamp(race["date"]))]
    model = Logit(features.FEATURES).fit(F)
    prm = SimParams(**json.loads((ROOT / "data" / "sim_backtest.json").read_text())["params"])

    rows = features.for_entries(df, race).reset_index(drop=True)
    p_model = model.predict(rows)
    score = model.score_without(rows, SIMULATED)
    hs = horses(rows, score, prm)
    course = course_for(race["distance"])

    if drawn:
        p = probabilities(simulate(course, hs, n=N_SIM, seed=0))
        win, place = p["win"], p["place"]
    else:
        rng = np.random.default_rng(0)
        win, place = np.zeros(len(hs)), np.zeros(len(hs))
        draws = 10
        for k in range(draws):
            gates = rng.permutation(len(hs)) + 1
            for h, g in zip(hs, gates):
                h.gate = int(g)
            p = probabilities(simulate(course, hs, n=N_SIM // draws, seed=k))
            win += p["win"] / draws
            place += p["place"] / draws
        for i, h in enumerate(hs):
            h.gate = i + 1

    table = pd.DataFrame({"馬": rows["horse_name"], "騎手": rows["jockey_name"],
                          "勝率(シミュ)": win.round(3), "複勝率(シミュ)": place.round(3),
                          "勝率(モデル)": p_model.round(3),
                          "speed": [h.speed for h in hs], "stamina": [h.stamina for h in hs],
                          "kick": [h.kick for h in hs], "style": [h.style for h in hs]})
    print(table.sort_values("勝率(シミュ)", ascending=False).to_string(index=False))

    note = ("過去の全レースから推定した能力値で走らせた予想です。"
            + ("" if drawn else "枠順が未確定のため、枠をランダムに10通り変えて平均しています。リプレイの枠は仮です。"))
    data = build(course, hs, n=N_SIM, seed=1, title=race["title"].replace(" 出馬表", ""), note=note)
    for h, w, pl, pm in zip(data["horses"], win, place, p_model):
        h["win"], h["place"], h["model_win"] = round(float(w), 4), round(float(pl), 4), round(float(pm), 4)
    write(data, ROOT / "web" / "data" / f"{name}.json")
    table.to_csv(ROOT / "data" / f"{name}.csv", index=False)
    print(f"wrote web/data/{name}.json")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
