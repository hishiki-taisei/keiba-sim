"""Build a race theater field from the database and a win-model prediction.

Any JRA course and distance works. An upcoming race, from a predictions CSV:

    python3 theater/tools/build_field.py --predictions preds.csv \
        --date 2026-10-25 --venue 京都 --surface 芝 --distance 3000 --outer \
        --title "菊花賞 2026" --out theater/data/kikka2026.field.json

A race already in the database (post positions and the real result come
along; the final odds stand in for the model unless --predictions is given):

    python3 theater/tools/build_field.py --race-id 202506050811 --out theater/data/arima2025.field.json

With no arguments it builds the Kikuka Sho 2026 field.

The predictions CSV needs a horse-name column (馬) and a win-probability
column (勝率(モデル)); a jockey column (騎手) and a post-position column (馬番)
are used when present. Everything else comes from each horse's own past runs
before --date, read from the database without changing it:

  style    average position at the first corner (0 = leads, 1 = last)
  move     places made up between the first and the last corner, per field
  kick     last-600m time against the field's median, in seconds (+ = faster)
  stamina  results at 2200m+ against results at shorter trips
  going    results on soft ground against results on good ground
  form_sd  how much its results swing from race to race (1 = average)

Run tools/calibrate.mjs on the output to set each horse's ability so that the
simulated win rates match the model's.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from pathlib import Path

RECENT = 8          # past runs used per horse
DECAY = 0.8         # weight of each older run relative to the next newer one


def wmean(vals, weights, default, prior=1.0):
    """Weighted mean shrunk toward `default` by `prior` runs' worth of weight."""
    num = sum(v * w for v, w in zip(vals, weights))
    den = sum(weights)
    return (num + default * prior) / (den + prior)


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def positions(passing):
    try:
        return [int(p) for p in passing.split("-") if p]
    except (AttributeError, ValueError):
        return []


def runs_of(con, name, date):
    """The horse's latest flat runs before `date`, newest first."""
    row = con.execute(
        "SELECT r.horse_id FROM results r JOIN races ra USING(race_id) "
        "WHERE r.horse_name = ? AND ra.date < ? ORDER BY ra.date DESC LIMIT 1", (name, date)).fetchone()
    if not row:
        return None, []
    q = """
      SELECT r.race_id, ra.date, ra.name, ra.surface, ra.distance, ra.going, r.finish, r.passing, r.last3f
      FROM results r JOIN races ra USING(race_id)
      WHERE r.horse_id = ? AND ra.date < ? AND ra.surface != '障' AND r.finish IS NOT NULL
      ORDER BY ra.date DESC LIMIT ?"""
    cols = ["race_id", "date", "race", "surface", "distance", "going", "finish", "passing", "last3f"]
    runs = [dict(zip(cols, r)) for r in con.execute(q, (row[0], date, RECENT))]
    for r in runs:
        others = con.execute("SELECT finish, last3f FROM results WHERE race_id = ?", (r["race_id"],)).fetchall()
        r["field"] = sum(1 for f, _ in others if f is not None)
        l3 = sorted(x for _, x in others if x)
        r["med3f"] = l3[len(l3) // 2] if l3 else None
    return row[0], runs


def features(runs):
    w = [DECAY ** k for k in range(len(runs))]
    style_v, style_w, move_v, move_w, kick_v, kick_w = [], [], [], [], [], []
    perf = []
    for r, wk in zip(runs, w):
        n = r["field"] or 0
        p = positions(r["passing"])
        if n >= 2:
            perf.append(1 - (r["finish"] - 1) / (n - 1))
        else:
            perf.append(0.5)
        if p and n >= 2:
            style_v.append((p[0] - 1) / (n - 1)); style_w.append(wk)
            if len(p) >= 2:
                move_v.append((p[0] - p[-1]) / (n - 1)); move_w.append(wk)
        if r["surface"] == "芝" and r["last3f"] and r["med3f"]:
            kick_v.append(r["med3f"] - r["last3f"]); kick_w.append(wk)

    def split(cond):
        a = [(pf, wk) for r, pf, wk in zip(runs, perf, w) if cond(r)]
        b = [(pf, wk) for r, pf, wk in zip(runs, perf, w) if not cond(r)]
        if not a or not b:
            return 0.0, len(a)
        ma = sum(x * y for x, y in a) / sum(y for _, y in a)
        mb = sum(x * y for x, y in b) / sum(y for _, y in b)
        return (ma - mb) * len(a) / (len(a) + 2), len(a)

    stamina, n_long = split(lambda r: r["distance"] >= 2200)
    going, n_soft = split(lambda r: r["going"] in ("稍重", "重", "不良"))
    mean_perf = sum(perf) / len(perf) if perf else 0.5
    sd = math.sqrt(sum((x - mean_perf) ** 2 for x in perf) / len(perf)) if len(perf) >= 3 else 0.28
    return {
        "style": round(clip(wmean(style_v, style_w, 0.5), 0, 1), 3),
        "move": round(clip(wmean(move_v, move_w, 0.0) / 0.25, -1, 1), 3),
        "kick": round(clip(wmean(kick_v, kick_w, 0.0), -1.2, 1.5), 3),
        "stamina": round(clip(2 * stamina, -1, 1), 3),
        "going": round(clip(2 * going, -1, 1), 3),
        "form_sd": round(clip(sd / 0.28, 0.6, 1.5), 3),
        "n_long": n_long, "n_soft": n_soft,
    }


def sections(distance):
    """Same split as engine.js sections(): early / mid / pre / last 600m."""
    early = min(1000, max(distance - 1000, 0.35 * distance))
    return early, max(early, distance - 1000), distance - 600


def course_pace(con, venue, surface, distance, outer, before, graded=False):
    """Median leader speed (m/s) per section on this course and distance, good ground.

    For a graded race, graded races only when there are enough of them (they
    are run faster than the course's average race)."""
    note = "AND course_note LIKE '%外%'" if outer else "AND (course_note IS NULL OR course_note NOT LIKE '%外%')"
    q = (f"SELECT laps FROM races WHERE venue = ? AND surface = ? AND distance = ? AND going = '良' "
         f"AND laps IS NOT NULL AND date < ? {note} {{}} ORDER BY date DESC LIMIT 300")
    rows = []
    if graded:
        rows = con.execute(q.format("AND grade IN ('G1', 'G2', 'G3')"), (venue, surface, distance, before)).fetchall()
    if len(rows) < 5:
        rows = con.execute(q.format(""), (venue, surface, distance, before)).fetchall()
    early, pre, last = sections(distance)
    marks = [0, early, pre, last, distance]
    speeds = [[] for _ in range(4)]
    for (laps,) in rows:
        try:
            lap = [float(x) for x in laps.split(" - ")]
        except ValueError:
            continue
        if abs(sum(lap)) < 1 or len(lap) < 3:
            continue
        # cumulative distance at the end of each lap: the first lap is short
        first = distance - 200 * (len(lap) - 1)
        ends = [first + 200 * k for k in range(len(lap))]
        t = 0.0
        cum = {0: 0.0}
        for d, x in zip(ends, lap):
            t += x
            cum[d] = t

        def at(d):  # time at distance d, interpolated between lap ends
            ks = sorted(cum)
            for k0, k1 in zip(ks, ks[1:]):
                if k0 <= d <= k1:
                    return cum[k0] + (cum[k1] - cum[k0]) * (d - k0) / (k1 - k0)
            return cum[ks[-1]]

        for k in range(4):
            if marks[k + 1] > marks[k]:
                speeds[k].append((marks[k + 1] - marks[k]) / (at(marks[k + 1]) - at(marks[k])))
    if len(rows) < 5:
        return None, len(rows)
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
    early_v, mid_v, pre_v, last_v = (med(x) for x in speeds)
    mid_v = mid_v or (early_v + pre_v) / 2
    return {"early": round(early_v, 3), "mid": round(mid_v, 3), "pre": round(pre_v, 3),
            "last600": round(last_v, 3)}, len(rows)


def past_runnings(con, race_name, venue):
    out = []
    for rid, date, laps, going in con.execute(
            "SELECT race_id, date, laps, going FROM races WHERE name LIKE ? AND venue = ? ORDER BY date",
            (f"%{race_name}%", venue)):
        if not laps:
            continue
        lap = [float(x) for x in laps.split(" - ")]
        win = con.execute("SELECT horse_name, time_sec, last3f, passing FROM results WHERE race_id = ? AND finish = 1",
                          (rid,)).fetchone()
        if not win:
            continue
        out.append({"date": date, "going": going, "time": round(sum(lap), 1),
                    "first1000": round(sum(lap[:5]), 1), "last600": round(sum(lap[-3:]), 1),
                    "winner": win[0], "winner_last3f": win[2], "winner_passing": win[3]})
    return out


def entries_from_csv(path, column):
    with open(path, encoding="utf-8-sig") as f:
        preds = list(csv.DictReader(f))
    return [{"name": p["馬"], "jockey": p.get("騎手") or "",
             "gate": int(p["馬番"]) if p.get("馬番") else None,
             "p": float(p[column])} for p in preds]


def entries_from_race(con, race_id):
    """A finished race's runners; win probabilities from the final odds."""
    rows = con.execute("SELECT horse_name, jockey_name, number, odds, finish FROM results "
                       "WHERE race_id = ? ORDER BY number", (race_id,)).fetchall()
    return [{"name": n, "jockey": j or "", "gate": g, "p": 0.8 / o if o else 0.001, "actual": f}
            for n, j, g, o, f in rows if f is not None]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="/mnt/project-files/keiba-sim/data/keiba.sqlite")
    ap.add_argument("--predictions", help="CSV with 馬 and a win-probability column (default: Kikuka Sho 2026)")
    ap.add_argument("--prob-column", default="勝率(モデル)")
    ap.add_argument("--race-id", help="build from a race in the database instead (odds as the probabilities "
                                      "unless --predictions is given)")
    ap.add_argument("--date", default="2026-10-25")
    ap.add_argument("--title", default="菊花賞 2026")
    ap.add_argument("--venue", default="京都")
    ap.add_argument("--surface", default="芝", choices=["芝", "ダ"])
    ap.add_argument("--distance", type=int, default=3000)
    ap.add_argument("--outer", action="store_true", default=None, help="outer course (外回り)")
    ap.add_argument("--straight", action="store_true", help="Niigata's straight course")
    ap.add_argument("--going", default="良")
    ap.add_argument("--grade", default="G1", help="G1/G2/G3 for a graded race, anything else otherwise")
    ap.add_argument("--past", default=None, help="race name whose past runnings to list (e.g. 菊花賞)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "kikka2026.field.json"))
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    if a.race_id:
        r = con.execute("SELECT date, name, venue, surface, distance, course_note, direction, going, grade "
                        "FROM races WHERE race_id = ?", (a.race_id,)).fetchone()
        if not r:
            raise SystemExit(f"race {a.race_id} not in the database")
        a.date, title, a.venue, a.surface, a.distance, note, direction, a.going, a.grade = r
        a.title = f"{title}（{a.date}）"
        a.outer = bool(note and "外" in note)
        a.straight = direction == "直線"
        entries = entries_from_race(con, a.race_id)
        source = "単勝オッズ"
        if a.predictions:
            probs = {e["name"]: e["p"] for e in entries_from_csv(a.predictions, a.prob_column)}
            for e in entries:
                e["p"] = probs.get(e["name"], 0.001)
            source = Path(a.predictions).name
    else:
        if a.outer is None:  # Kikuka Sho default
            a.outer = a.venue == "京都" and a.distance == 3000
        entries = entries_from_csv(a.predictions or "/mnt/project-files/keiba-sim/predictions/kikka2026_preliminary.csv",
                                   a.prob_column)
        source = Path(a.predictions or "kikka2026_preliminary.csv").name
        if a.past is None and a.title.startswith("菊花賞"):
            a.past = "菊花賞"

    total = sum(e["p"] for e in entries)
    horses = []
    for e in entries:
        hid, runs = runs_of(con, e["name"], a.date)
        h = {"name": e["name"], "jockey": e["jockey"], "gate": e["gate"], "p_model": round(e["p"] / total, 4),
             "horse_id": hid, **(features(runs) if runs else {})}
        if "actual" in e:
            h["actual"] = e["actual"]
        h["recent"] = [{"date": r["date"], "race": r["race"], "distance": r["distance"], "going": r["going"],
                        "finish": r["finish"], "field": r["field"], "passing": r["passing"], "last3f": r["last3f"]}
                       for r in runs[:5]]
        horses.append(h)
        print(f"{e['name']:12s} runs={len(runs)} " + " ".join(f"{k}={h.get(k)}" for k in
              ("p_model", "style", "move", "kick", "stamina", "going", "form_sd")))

    pace, n_pace = course_pace(con, a.venue, a.surface, a.distance, a.outer, a.date,
                               graded=a.grade in ("G1", "G2", "G3"))
    print(f"pace from {n_pace} past races on this course: {pace}")
    course = {"venue": a.venue, "surface": a.surface, "distance": a.distance,
              "note": "外" if a.outer else "", "direction": "直線" if a.straight else ""}
    field = {"title": a.title, "date": a.date, "course": course, "going": a.going,
             "pace": pace, "pace_races": n_pace,
             "model": {"source": source, "column": a.prob_column if source != "単勝オッズ" else None},
             "past": past_runnings(con, a.past, a.venue) if a.past else [], "horses": horses}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(field, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
