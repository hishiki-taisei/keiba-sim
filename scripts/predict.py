"""Win probabilities for an upcoming race, in the one format every screen reads.

    python3 scripts/predict.py 202608040911                    # entries from race.netkeiba.com
    python3 scripts/predict.py 202608040911 --odds odds.csv    # also correct the odds (horse_name,odds)
    python3 scripts/predict.py 202608040911 --going 稍重

Fetches the entries, builds each horse's features as of race day and scores
them with the win model (gradient boosting, trained on every turf race up to
the week before; see experiments/model-log.md, gbdt_going_rel). When odds are
given, a second model starts from the odds and learns only where the market is
off (offset_pace2); that becomes the main probability.

Writes data/preds/<race_id>.csv with these columns:

    race_id, horse_id, horse_name, jockey_name, number,
    p_ability  win probability from past form only (no odds)
    odds       the odds that were given, if any
    p_market   probability implied by those odds
    p_win      the probability the site and the race replay use:
               the odds-corrected model when odds were given, else p_ability
    model      which model produced p_win
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import evaluate, features  # noqa: E402
from model.data import load_runs  # noqa: E402
from model.gbdt import GBDT  # noqa: E402
from scraper import parse  # noqa: E402
from scraper.fetch import Fetcher  # noqa: E402

ABILITY = features.FEATURES + features.GOING_FEATURES + features.REL_FEATURES
OFFSET = ABILITY + features.PACE_FEATURES
OUT = ROOT / "data" / "preds"


def log_market(df):
    return np.log(np.clip(evaluate.market_probs(df), 1e-6, 1.0))


def fetch_entries(race_id: str) -> dict:
    f = Fetcher(ROOT / "data" / "raw", interval=1.2)
    html = f.get(f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}",
                 f"entries/{race_id}", encoding="utf-8", refresh=True)
    race = parse.entries(html, race_id)
    if race is None:
        raise SystemExit(f"no entries on the netkeiba page for {race_id}")
    return race


def read_odds(path: str) -> dict:
    o = pd.read_csv(path)
    return dict(zip(o["horse_name"], o["odds"].astype(float)))


def predict(race: dict, going: str = "良", odds: dict | None = None) -> pd.DataFrame:
    df = load_runs()
    F = pd.read_pickle(ROOT / "data" / "features_turf.pkl")
    F = F[F["odds"].notna() & (F["field"] >= 5) & (F["date"] < pd.Timestamp(race["date"]))]
    # stopped on the most recent year of races
    last = F["date"] >= pd.Timestamp(race["date"]) - pd.Timedelta(days=365)
    rows = features.for_entries(df, race, going=going).reset_index(drop=True)
    ability = GBDT(ABILITY, rounds=800).fit(F[~last], F[last])
    out = pd.DataFrame({"race_id": race["race_id"], "horse_id": rows["horse_id"], "horse_name": rows["horse_name"],
                        "jockey_name": rows["jockey_name"],
                        "number": [h["number"] for h in race["horses"]],
                        "p_ability": ability.predict(rows).round(4)})
    out["odds"], out["p_market"] = np.nan, np.nan
    out["p_win"], out["model"] = out["p_ability"], "gbdt_going_rel"
    if odds:
        missing = [n for n in out["horse_name"] if n not in odds]
        if missing:
            raise SystemExit(f"no odds for: {', '.join(missing)}")
        rows["odds"] = rows["horse_name"].map(odds)
        out["odds"] = rows["odds"]
        out["p_market"] = evaluate.market_probs(rows).round(4)
        offset = GBDT(OFFSET, base=log_market, rounds=800).fit(F[~last], F[last])
        out["p_win"], out["model"] = offset.predict(rows).round(4), "offset_pace2"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("race_id")
    ap.add_argument("--going", default="良", help="expected ground: 良・稍重・重・不良")
    ap.add_argument("--odds", help="CSV with horse_name,odds (win odds)")
    a = ap.parse_args()
    race = fetch_entries(a.race_id)
    print(f"{race['title']} {race['date']} {race['distance']}m  {len(race['horses'])} horses")
    out = predict(race, a.going, read_odds(a.odds) if a.odds else None)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{a.race_id}.csv"
    out.to_csv(path, index=False)
    print(out.sort_values("p_win", ascending=False).to_string(index=False))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
