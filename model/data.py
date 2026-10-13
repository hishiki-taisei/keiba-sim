"""Load race results from the scraper database into a tidy DataFrame."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB = Path(__file__).resolve().parent.parent / "data" / "keiba.sqlite"


def first_corner(passing: str | None) -> float:
    if not passing:
        return np.nan
    try:
        return float(passing.split("-")[0])
    except ValueError:
        return np.nan


def load_runs(db: Path = DB, surface: str | None = "芝") -> pd.DataFrame:
    """One row per runner that finished, with race conditions attached."""
    con = sqlite3.connect(db)
    q = """
    SELECT r.race_id, ra.date, ra.venue, ra.surface, ra.distance, ra.course_note, ra.going,
           ra.grade, ra.name AS race_name, ra.class_text, ra.n_runners,
           r.number, r.frame, r.finish, r.horse_id, r.horse_name, r.sex, r.age,
           r.weight_carried, r.jockey_id, r.trainer_id, r.time_sec, r.passing, r.last3f,
           r.odds, r.popularity, r.body_weight, r.prize
    FROM results r JOIN races ra USING(race_id)
    WHERE r.finish IS NOT NULL AND r.time_sec IS NOT NULL
    """
    if surface:
        q += " AND ra.surface = ?"
    df = pd.read_sql(q, con, params=(surface,) if surface else None)
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df["field"] = df.groupby("race_id")["number"].transform("size")
    df["speed"] = df["distance"] / df["time_sec"]
    df["early_pos"] = (df["passing"].map(first_corner) - 1) / (df["field"] - 1).clip(lower=1)
    # Finishing burst relative to the field: positive = quicker last 600m than the race average.
    df["kick_rel"] = df.groupby("race_id")["last3f"].transform("mean") - df["last3f"]
    return df.sort_values(["date", "race_id", "finish"]).reset_index(drop=True)
