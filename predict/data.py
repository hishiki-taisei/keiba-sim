"""Load race results from the collected SQLite database.

The database is written by the data-collection job and may be updated while we
read it, so it is opened read-only.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "keiba.sqlite"

# finish_raw values meaning the horse never started (scratched / excluded)
NON_STARTERS = {"取", "除"}


def db_path(path: str | os.PathLike | None = None) -> Path:
    return Path(path or os.environ.get("KEIBA_DB") or DEFAULT_DB)


def connect(path=None) -> sqlite3.Connection:
    p = db_path(path)
    if not p.exists():
        raise FileNotFoundError(f"database not found: {p} (set KEIBA_DB or pass --db)")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def load_runners(path=None) -> pd.DataFrame:
    """One row per starter in flat (non-jump) races, joined with race info."""
    con = connect(path)
    df = pd.read_sql(
        """
        SELECT r.race_id, r.date, r.venue, r.name AS race_name, r.grade, r.surface,
               r.distance, r.going, r.n_runners, r.class_text,
               x.number, x.finish, x.finish_raw, x.frame, x.horse_id, x.horse_name,
               x.sex, x.age, x.weight_carried, x.jockey_id, x.jockey_name, x.time_sec,
               x.passing, x.last3f, x.odds, x.popularity, x.body_weight,
               x.body_weight_diff, x.trainer_id, x.prize
        FROM races r JOIN results x USING (race_id)
        WHERE r.surface IN ('芝', 'ダ')
        """,
        con,
    )
    con.close()
    df = df[~df.finish_raw.isin(NON_STARTERS)].copy()
    df["date"] = pd.to_datetime(df.date)
    # actual number of starters (n_runners on the card counts scratched horses)
    df["field"] = df.groupby("race_id").number.transform("size")
    # 中止 (did not finish) counts as last
    df["finish"] = df.finish.fillna(df.field).astype(int)
    return df.sort_values(["date", "race_id", "number"]).reset_index(drop=True)


def load_payouts(path=None) -> pd.DataFrame:
    con = connect(path)
    df = pd.read_sql("SELECT race_id, bet_type, combo, payout FROM payouts", con)
    con.close()
    return df
