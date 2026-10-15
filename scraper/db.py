from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS races (
  race_id TEXT PRIMARY KEY, date TEXT, venue TEXT, kai INT, day INT, race_no INT,
  name TEXT, grade TEXT, surface TEXT, distance INT, direction TEXT, course_note TEXT,
  weather TEXT, going TEXT, start_time TEXT, class_text TEXT, n_runners INT,
  laps TEXT, corners TEXT
);
CREATE TABLE IF NOT EXISTS results (
  race_id TEXT, number INT, finish INT, finish_raw TEXT, frame INT,
  horse_id TEXT, horse_name TEXT, sex TEXT, age INT, weight_carried REAL,
  jockey_id TEXT, jockey_name TEXT, time_sec REAL, margin TEXT, passing TEXT, last3f REAL,
  odds REAL, popularity INT, body_weight INT, body_weight_diff INT,
  trainer_id TEXT, trainer_name TEXT, stable TEXT, owner_id TEXT, prize REAL,
  PRIMARY KEY (race_id, number, horse_id)
);
CREATE INDEX IF NOT EXISTS results_horse ON results(horse_id);
CREATE TABLE IF NOT EXISTS payouts (
  race_id TEXT, bet_type TEXT, combo TEXT, payout INT, popularity INT,
  PRIMARY KEY (race_id, bet_type, combo)
);
CREATE TABLE IF NOT EXISTS horses (
  horse_id TEXT PRIMARY KEY, name TEXT, sire TEXT, sire_id TEXT, dam TEXT, dam_id TEXT,
  damsire TEXT, damsire_id TEXT, sire_sire TEXT, sire_sire_id TEXT
);
-- Bookkeeping so a run can be stopped and resumed.
CREATE TABLE IF NOT EXISTS race_days (date TEXT PRIMARY KEY, listed INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS race_queue (race_id TEXT PRIMARY KEY, date TEXT, status TEXT DEFAULT 'todo');
"""


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def upsert(con: sqlite3.Connection, table: str, rows: list[dict]):
    if not rows:
        return
    cols = list(rows[0])
    con.executemany(
        f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in rows],
    )
