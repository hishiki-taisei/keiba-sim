"""Collect past JRA races from netkeiba into SQLite.

    python3 -m scraper days   --from 2015-01 --to 2026-10   # list race days from the calendar
    python3 -m scraper races  [--limit N]                   # fetch race pages, newest first
    python3 -m scraper peds   [--limit N]                   # fetch pedigrees of horses seen in results
    python3 -m scraper status
    python3 -m scraper snapshot --out PATH                  # consistent copy of the DB

Requests are spaced by --interval seconds (default 1.2s + jitter) and every page is cached
gzipped under data/raw/, so re-runs never hit the site twice for the same page.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import db, parse
from .fetch import Fetcher

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "keiba.sqlite"
RAW = ROOT / "data" / "raw"


def months(start: str, end: str):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def cmd_days(args, con, f: Fetcher):
    today = dt.date.today()
    today = (today + dt.timedelta(days=1) if args.include_today else today).strftime("%Y%m%d")
    for y, m in months(args.start, args.end):
        html = f.get(f"https://race.netkeiba.com/top/calendar.html?year={y}&month={m}",
                     f"calendar/{y}{m:02d}", encoding="euc-jp",
                     refresh=(y, m) == (dt.date.today().year, dt.date.today().month))
        dates = [d for d in parse.calendar_dates(html or "") if d < today]
        con.executemany("INSERT OR IGNORE INTO race_days(date) VALUES (?)", [(d,) for d in dates])
        con.commit()
        print(f"{y}-{m:02d}: {len(dates)} days", flush=True)
    # Race ids per day.
    todo = [r[0] for r in con.execute("SELECT date FROM race_days WHERE listed=0 ORDER BY date DESC")]
    for i, d in enumerate(todo):
        html = f.get(f"https://db.netkeiba.com/race/list/{d}/", f"list/{d}", refresh=True)
        ids = parse.race_ids(html or "")
        con.executemany("INSERT OR IGNORE INTO race_queue(race_id, date) VALUES (?, ?)", [(r, d) for r in ids])
        if ids:  # an empty list means the results are not up yet: look again next run
            con.execute("UPDATE race_days SET listed=1 WHERE date=?", (d,))
        con.commit()
        print(f"[{i + 1}/{len(todo)}] {d}: {len(ids)} races", flush=True)


def cmd_races(args, con, f: Fetcher):
    q = "SELECT race_id FROM race_queue WHERE status='todo' ORDER BY date DESC, race_id"
    todo = [r[0] for r in con.execute(q)][: args.limit or None]
    for i, rid in enumerate(todo):
        try:
            html = f.get(f"https://db.netkeiba.com/race/{rid}/", f"race/{rid[:4]}/{rid}")
        except RuntimeError as e:
            # Leave it for a later run instead of stopping the whole collection.
            print(e, flush=True)
            con.execute("UPDATE race_queue SET status='error' WHERE race_id=?", (rid,))
            con.commit()
            continue
        d = parse.race(html, rid) if html else None
        if d is None:
            con.execute("UPDATE race_queue SET status='missing' WHERE race_id=?", (rid,))
        else:
            db.upsert(con, "races", [d["race"]])
            con.execute("DELETE FROM results WHERE race_id=?", (rid,))
            db.upsert(con, "results", d["results"])
            db.upsert(con, "payouts", d["payouts"])
            con.execute("UPDATE race_queue SET status='done' WHERE race_id=?", (rid,))
        con.commit()
        if (i + 1) % 25 == 0 or i + 1 == len(todo):
            print(f"[{i + 1}/{len(todo)}] {rid} {d['race']['name'] if d else 'missing'}", flush=True)


def cmd_peds(args, con, f: Fetcher):
    q = """SELECT DISTINCT r.horse_id FROM results r JOIN races ra USING(race_id)
           WHERE r.horse_id IS NOT NULL AND r.horse_id NOT IN (SELECT horse_id FROM horses)
           ORDER BY ra.date DESC"""
    todo = [r[0] for r in con.execute(q)][: args.limit or None]
    for i, hid in enumerate(todo):
        try:
            html = f.get(f"https://db.netkeiba.com/horse/ped/{hid}/", f"ped/{hid[:4]}/{hid}")
        except RuntimeError as e:
            print(e, flush=True)  # not stored, so the next run tries it again
            continue
        p = parse.pedigree(html, hid) if html else None
        db.upsert(con, "horses", [p or {"horse_id": hid}])
        con.commit()
        if (i + 1) % 50 == 0 or i + 1 == len(todo):
            print(f"[{i + 1}/{len(todo)}] {hid} {p and p['name']}", flush=True)


def cmd_reparse(args, con, f: Fetcher):
    """Re-run the race parser over cached pages (after a parser fix), without network."""
    for path in sorted((RAW / "race").glob("*/*.html.gz")):
        rid = path.name.split(".")[0]
        d = parse.race(f.get("", f"race/{rid[:4]}/{rid}"), rid)
        if d:
            db.upsert(con, "races", [d["race"]])
            con.execute("DELETE FROM results WHERE race_id=?", (rid,))
            db.upsert(con, "results", d["results"])
            db.upsert(con, "payouts", d["payouts"])
    con.commit()


def cmd_retry(args, con, f):
    n = con.execute("UPDATE race_queue SET status='todo' WHERE status='error'").rowcount
    con.commit()
    print(f"{n} failed races queued again")


def cmd_snapshot(args, con, f):
    """Copy the database to --out with SQLite's online backup (safe while a collector runs)."""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    with db.sqlite3.connect(tmp) as dst:
        con.backup(dst)
    tmp.replace(args.out)
    print(f"snapshot -> {args.out}")


def cmd_status(args, con, f):
    for sql in ["SELECT status, COUNT(*) FROM race_queue GROUP BY status",
                "SELECT substr(date,1,4) y, COUNT(*) FROM races GROUP BY y ORDER BY y",
                "SELECT COUNT(*) FROM results", "SELECT COUNT(*) FROM horses",
                "SELECT MIN(date), MAX(date) FROM race_days"]:
        print(sql.split("FROM")[0].replace("SELECT", "").strip(), "->", con.execute(sql).fetchall())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m scraper")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--interval", type=float, default=1.2)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("days")
    p.add_argument("--from", dest="start", default="2015-01")
    p.add_argument("--to", dest="end", default=dt.date.today().strftime("%Y-%m"))
    p.add_argument("--include-today", action="store_true", help="also list today (run after the last race)")
    for name in ("races", "peds"):
        sub.add_parser(name).add_argument("--limit", type=int, default=0)
    sub.add_parser("reparse")
    sub.add_parser("retry")
    sub.add_parser("status")
    sub.add_parser("snapshot").add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    con = db.connect(args.db)
    f = Fetcher(RAW, interval=args.interval)
    {"days": cmd_days, "races": cmd_races, "peds": cmd_peds,
     "reparse": cmd_reparse, "status": cmd_status, "retry": cmd_retry, "snapshot": cmd_snapshot}[args.cmd](args, con, f)
    print(f"requests made: {f.hits}", file=sys.stderr)


if __name__ == "__main__":
    main()
