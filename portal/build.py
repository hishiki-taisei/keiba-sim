"""Build the data files for the prediction portal (portal/www).

    python3 portal/build.py --db data/keiba.sqlite --featured theater/data/kikka2026.json

--featured is a race-replay file made by theater/tools/build_field.py and
calibrate.mjs from scripts/predict.py's output. The portal takes the win
probability, the top-3 rate (1000s of simulated races) and each horse's running
style from it, so the race page and the replay always show the same numbers.
The replay itself is copied to www/theater/ and shown in the 展開 tab.

Read-only: opens the database in read-only mode and never imports the model
code, so it can run next to the data-collection and model work. Every figure
shown for a race (past runs, jockey and sire records, course trends) uses only
races run before that race's date.

Writes portal/www/data/index.json and portal/www/data/race/<race_id>.json.
"""
import argparse
import itertools
import shutil
import sys
import json
import math
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "www" / "data"
THEATER = ROOT.parent / "theater"
sys.path.insert(0, str(THEATER / "tools"))
import build_field  # noqa: E402  (one definition of running style for the site and the replay)

# Upcoming race shown before its card is in the database.
KIKKA = {
    "race_id": "202608040911", "date": "2026-10-25", "venue": "京都", "race_no": 11,
    "name": "第87回菊花賞(GI)", "grade": "G1", "surface": "芝", "distance": 3000,
    "direction": "右", "course_note": "外", "class_text": "3歳オープン (国際)牡・牝(指)(馬齢)",
    "start_time": "15:40",
}

# Simplified sire lines, keyed by the sire's sire (or the sire itself).
LINES = {
    "サンデー系": "サンデーサイレンス ディープインパクト ステイゴールド ハーツクライ フジキセキ ブラックタイド "
                "ダイワメジャー ゴールドアリュール ネオユニヴァース マンハッタンカフェ スペシャルウィーク "
                "アグネスタキオン ゼンノロブロイ キズナ オルフェーヴル ドリームジャーニー ゴールドシップ "
                "ジャスタウェイ キタサンブラック ブラックタイド ディープブリランテ リアルスティール "
                "サトノダイヤモンド コントレイル エピカリス シルバーステート ミッキーアイル アドマイヤマーズ "
                "スワーヴリチャード シャフリヤール イクイノックス ハーツクライ",
    "ミスプロ系": "キングカメハメハ ロードカナロア Kingmambo キングズベスト ルーラーシップ ドゥラメンテ "
                "Forestry Street_Cry Unbridled's_Song Lemon_Drop_Kid Dubawi Raven's_Pass Speightstown "
                "エンドスウィープ スウェプトオーヴァーボード アドマイヤムーン Pioneerof_the_Nile "
                "アメリカンファラオ First_Defence Smart_Strike Distorted_Humor Gone_West "
                "サートゥルナーリア レイデオロ リオンディーズ ホッコータルマエ",
    "ロベルト系": "シンボリクリスエス スクリーンヒーロー エピファネイア ブライアンズタイム グラスワンダー "
                "モーリス Blame Kris_S. タニノギムレット",
    "ノーザンダンサー系": "War_Front Giant's_Causeway Dansili Galileo Frankel Scat_Daddy Harlan's_Holiday Marju "
                      "ヘニーヒューズ ヘネシー Kitten's_Joy Medaglia_d'Oro Into_Mischief Helmet Posse Gio_Ponti "
                      "Nashwan Monsun ホワイトマズル Storm_Cat Danehill Sadler's_Wells "
                      "Poseidon's_Warrior Dawn_Approach ハービンジャー",
    "ナスルーラ系": "A.P._Indy Old_Trieste Pulpit Lucky_Pulpit Tapit マジェスティックウォリアー サクラバクシンオー "
                 "Leroidesanimaux タイキシャトル",
}
LINE_OF = {name.replace("_", " "): line for line, names in LINES.items() for name in names.split()}


def clean(name):
    """'A.P. Indy\xa0(米)' -> 'A.P. Indy'"""
    if not isinstance(name, str):
        return None
    return re.sub(r"\s*[(（].*$", "", name.replace("\xa0", " ")).strip() or None


def line_of(sire, sire_sire):
    for n in (clean(sire_sire), clean(sire)):
        if n in LINE_OF:
            return LINE_OF[n]
    return "その他"


def dist_band(d):
    for lim, label in ((1400, "〜1400m"), (1800, "1401〜1800m"), (2200, "1801〜2200m"), (2600, "2201〜2600m")):
        if d <= lim:
            return label
    return "2601m〜"


def style_of(passing, field):
    """Running style of one run, from the first-corner position (0 = led, 1 = last)."""
    p = build_field.positions(passing) if isinstance(passing, str) else []
    if not p or not field or field < 2:
        return None
    return build_field.style_word((p[0] - 1) / (field - 1))


def horse_style(hist):
    """A horse's running style, computed exactly as the race replay does
    (recent flat runs, newer ones weighted more)."""
    h = hist[(hist["surface"] != "障") & hist["finish"].notna() & (hist["finish"] > 0)]
    runs = [{"field": int(r.n_runners or 0), "passing": r.passing, "finish": r.finish, "surface": r.surface,
             "last3f": None, "med3f": None, "distance": r.distance, "going": r.going}
            for r in h.tail(build_field.RECENT).iloc[::-1].itertuples()]
    if not runs:
        return None
    return build_field.style_word(build_field.features(runs)["style"])


def num(x, nd=None):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        if nd is not None:
            return round(float(x), nd)
        return int(x) if float(x).is_integer() else float(x)
    return x


def load(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    races = pd.read_sql("select * from races", con)
    res = pd.read_sql("select * from results", con)
    horses = pd.read_sql("select * from horses", con)
    payouts = pd.read_sql("select * from payouts", con)
    con.close()
    races["date"] = pd.to_datetime(races["date"])
    df = res.merge(races[["race_id", "date", "venue", "name", "grade", "surface", "distance", "going",
                          "n_runners", "course_note"]], on="race_id")
    df = df.merge(horses[["horse_id", "sire", "sire_id", "damsire", "sire_sire"]], on="horse_id", how="left")
    df["line"] = [line_of(s, ss) for s, ss in zip(df["sire"], df["sire_sire"])]
    df["band"] = df["distance"].map(dist_band)
    df["style"] = [style_of(p, n) for p, n in zip(df["passing"], df["n_runners"])]
    ok = df["finish"].notna() & (df["finish"] > 0)
    df["win"] = (ok & (df["finish"] == 1)).astype(int)
    df["top3"] = (ok & (df["finish"] <= 3)).astype(int)
    df["ret"] = np.where(df["win"] == 1, df["odds"].fillna(0) * 100, 0)
    df["l3rank"] = df.groupby("race_id")["last3f"].rank(method="min")
    win_time = df[df["finish"] == 1].groupby("race_id")["time_sec"].min()
    df["behind"] = df["time_sec"] - df["race_id"].map(win_time)
    df = df.sort_values(["date", "race_id", "finish"])
    return races, df, horses, payouts


HEAVY = ["稍重", "重", "不良"]
SCRATCHED = ["取", "除"]  # did not start

# Situations a horse can be in before a race. Each is worked out the same way for
# every past run and for today's entries, so "how did horses in this situation do"
# is a plain count over the database.
SITUATIONS = [
    # (key, label shown on the site)
    ("s_prev", "前走着順"),
    ("s_l3", "前走の上がり"),
    ("s_gap", "間隔"),
    ("s_dist", "距離の変化"),
    ("s_maxd", "距離経験"),
    ("s_course", "コース経験"),
    ("s_heavy", "道悪の経験"),
    ("s_jockey", "騎手"),
    ("s_carried", "斤量の変化"),
    ("s_bw", "馬体重の増減"),
]


def _band(x, edges, labels, missing=None):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return missing
    for lim, lab in zip(edges, labels):
        if x <= lim:
            return lab
    return labels[-1]


def add_situations(df):
    """Label every run with the situation the horse was in before it (from earlier runs only)."""
    scratched = df[df["finish_raw"].isin(SCRATCHED)]
    df = df[~df["finish_raw"].isin(SCRATCHED)].sort_values(["horse_id", "date", "race_id"]).copy()
    g = df.groupby("horse_id", sort=False)
    prev = {c: g[c].shift() for c in ("date", "finish", "distance", "weight_carried", "jockey_id",
                                       "jockey_name", "l3rank", "race_id")}
    first = prev["race_id"].isna()
    days = (df["date"] - prev["date"]).dt.days
    wk = days // 7 - 1

    df["s_prev"] = [None if f else ("競走中止など" if math.isnan(x) else _band(x, (1, 3, 5, 9), ("1着", "2〜3着", "4〜5着", "6〜9着", "10着以下")))
                    for f, x in zip(first, prev["finish"])]
    df["s_l3"] = [None if f or math.isnan(x) else _band(x, (1, 3), ("1位", "2〜3位", "4位以下"))
                  for f, x in zip(first, prev["l3rank"])]
    df["s_gap"] = [None if math.isnan(w) else _band(w, (1, 2, 4, 8, 24), ("連闘・中1週", "中2週", "中3〜4週", "中5〜8週", "中9〜24週", "中25週以上"))
                   for w in wk]
    dd = df["distance"] - prev["distance"]
    df["s_dist"] = [None if math.isnan(x) else _band(x, (-400, -1, 0, 399), ("400m以上短縮", "短縮（300m以内）", "同じ距離", "延長（300m以内）", "400m以上延長"))
                    for x in dd]
    maxd = g["distance"].transform(lambda s: s.shift().cummax())
    df["s_maxd"] = np.where(first, None, np.where(df["distance"] > maxd, "初めての長さ", "経験のある長さ"))

    # earlier top-3 finishes at the same course / on a wet track, same surface
    def tally(mask, keys):
        m = mask.astype(int)
        t3 = (df["top3"] * m)
        runs = m.groupby(keys).cumsum() - m
        hits = t3.groupby(keys).cumsum() - t3
        return runs, hits
    course_keys = [df["horse_id"], df["venue"], df["surface"], df["distance"]]
    runs = df.groupby(course_keys).cumcount()
    hits = df.groupby(course_keys)["top3"].cumsum() - df["top3"]
    df["s_course"] = np.where(runs == 0, "初めて", np.where(hits > 0, "3着内あり", "走ったが3着内なし"))
    wet = df["going"].isin(HEAVY)
    hruns, hhits = tally(wet, [df["horse_id"], df["surface"]])
    df["s_heavy"] = np.where(~wet, None, np.where(hruns == 0, "初めて", np.where(hhits > 0, "3着内あり", "走ったが3着内なし")))

    def same_jockey(j, pj, n, pn):
        if isinstance(j, str) and isinstance(pj, str):
            return j == pj
        if isinstance(n, str) and isinstance(pn, str):
            return n.startswith(pn) or pn.startswith(n)
        return None
    sj = [same_jockey(*a) for a in zip(df["jockey_id"], prev["jockey_id"], df["jockey_name"], prev["jockey_name"])]
    df["s_jockey"] = [None if f or x is None else ("前走と同じ騎手" if x else "乗り替わり") for f, x in zip(first, sj)]
    dc = df["weight_carried"] - prev["weight_carried"]
    df["s_carried"] = [None if math.isnan(x) else _band(x, (-2, -0.5, 0, 1.5), ("2kg以上減", "1kg減", "同じ", "1kg増", "2kg以上増"))
                       for x in dc]
    df["s_bw"] = [_band(x, (-10, -4, 3, 9), ("-10kg以下", "-4〜-8kg", "±2kg以内", "+4〜+8kg", "+10kg以上"))
                  for x in df["body_weight_diff"]]
    df.loc[first, ["s_gap", "s_dist", "s_carried"]] = None
    return pd.concat([df, scratched]).sort_values(["date", "race_id", "finish"])


def mark(rate_, base, n, min_n):
    """+ / - when the rate is clearly above / below the average and the sample is big enough."""
    if rate_ is None or not base or n < min_n:
        return ""
    if rate_ >= base * 1.2:
        return "+"
    if rate_ <= base * 0.8:
        return "-"
    return ""


def rate(g):
    n = len(g)
    return {"n": n, "win": num(g["win"].mean(), 3), "top3": num(g["top3"].mean(), 3),
            "roi": num(g["ret"].sum() / n, 0) if n else None}


def course_trends(df, race, date):
    past = df[(df["date"] < date) & (df["date"] >= date - pd.DateOffset(years=5))]
    same = past[(past["venue"] == race["venue"]) & (past["surface"] == race["surface"])
                & (past["distance"] == race["distance"])]
    if race.get("course_note") and "外" in str(race["course_note"]):
        same = same[same["course_note"].fillna("").str.contains("外")]
    out = {"races": int(same["race_id"].nunique()), "runs": int(len(same))}
    if not len(same):
        return out
    out["base"] = num(same["top3"].mean(), 3)
    out["frame"] = [{"key": int(k), **rate(g)} for k, g in same.groupby("frame") if k > 0]
    out["style"] = [{"key": k, **rate(same[same["style"] == k])} for k in ("逃げ", "先行", "差し", "追込")]
    pop = same["popularity"].clip(upper=10)
    out["popularity"] = [{"key": ("10〜" if k == 10 else str(int(k))), **rate(g)}
                         for k, g in same.groupby(pop) if k > 0]
    out["line"] = sorted(({"key": k, **rate(g)} for k, g in same.groupby("line")), key=lambda r: -r["n"])
    sires = [{"key": clean(k), **rate(g)} for k, g in same.groupby("sire") if len(g) >= 8]
    out["sire"] = sorted(sires, key=lambda r: -r["top3"])[:10]
    winners = same[same["finish"] == 1]
    out["winner_l3"] = num(winners["last3f"].mean(), 1)
    out["winner_pop"] = num(winners["popularity"].mean(), 1)
    return out


class Cutoff:
    """Jockey and sire records as of one race day."""

    def __init__(self, df, date):
        self.date = date
        year = df[(df["date"] < date) & (df["date"] >= date - pd.DateOffset(years=1))]
        agg = dict(n=("top3", "size"), top3=("top3", "mean"), win=("win", "mean"), ret=("ret", "mean"))
        self.jockey = year.groupby("jockey_id").agg(**agg)
        self.jockey_by_name = year.groupby("jockey_name").agg(**agg)
        self.jockey_base = year["top3"].mean()
        five = df[(df["date"] < date) & (df["date"] >= date - pd.DateOffset(years=5))]
        self.sire = five.groupby(["sire_id", "surface", "band"]).agg(
            n=("top3", "size"), top3=("top3", "mean"), win=("win", "mean"), ret=("ret", "mean"))
        self.base = five.groupby(["surface", "band"]).agg(top3=("top3", "mean"))
        five = five[~five["finish_raw"].isin(SCRATCHED)]
        self.sit = {k: five.groupby(["surface", k]).agg(**agg) for k, _ in SITUATIONS}
        self.sit_base = five.groupby("surface")["top3"].mean()
        wet = five[five["going"].isin(HEAVY)]
        self.sit["s_heavy"] = wet.groupby(["surface", "s_heavy"]).agg(**agg)
        self.wet_base = wet.groupby("surface")["top3"].mean()

    def situation(self, key, value, surface):
        """How horses in the same situation did over the last five years, same surface."""
        t = self.sit[key]
        if value is None or (surface, value) not in t.index:
            return None
        r = t.loc[(surface, value)]
        base = (self.wet_base if key == "s_heavy" else self.sit_base).get(surface)
        n, top3 = int(r["n"]), num(r["top3"], 3)
        return {"n": n, "top3": top3, "win": num(r["win"], 3), "roi": num(r["ret"], 0), "base": num(base, 3),
                "s": mark(top3, base, n, 300)}

    def jockey_rec(self, jid, name):
        t = self.jockey
        if jid in t.index:
            r = t.loc[jid]
        else:
            t = self.jockey_by_name
            hit = [n for n in t.index if isinstance(n, str) and name and (n.startswith(name) or name.startswith(n))]
            if not hit:
                return None
            r = t.loc[max(hit, key=lambda n: t.loc[n, "n"])]
        return {"n": int(r["n"]), "top3": num(r["top3"], 3), "win": num(r["win"], 3), "roi": num(r["ret"], 0)}

    def sire_rec(self, sid, surface, band):
        k = (sid, surface, band)
        if k not in self.sire.index:
            return None
        r = self.sire.loc[k]
        base = self.base.loc[(surface, band), "top3"] if (surface, band) in self.base.index else None
        return {"n": int(r["n"]), "top3": num(r["top3"], 3), "win": num(r["win"], 3), "roi": num(r["ret"], 0),
                "base": num(base, 3)}


def past_runs(hist, k=10):
    rows = []
    for r in hist.tail(k).iloc[::-1].itertuples():
        rows.append({
            "date": r.date.strftime("%Y-%m-%d"), "race_id": r.race_id, "venue": r.venue, "name": r.name,
            "grade": r.grade, "surface": r.surface, "distance": int(r.distance), "going": r.going,
            "field": num(r.n_runners), "finish": num(r.finish), "finish_raw": r.finish_raw,
            "pop": num(r.popularity), "odds": num(r.odds, 1), "l3": num(r.last3f, 1), "l3rank": num(r.l3rank),
            "passing": r.passing, "behind": num(r.behind, 1), "jockey": r.jockey_name,
            "carried": num(r.weight_carried, 1), "bw": num(r.body_weight), "style": r.style,
        })
    return rows


def record(hist, mask):
    g = hist[mask]
    if not len(g):
        return [0, 0, 0, 0]
    f = g["finish"]
    return [int((f == 1).sum()), int((f == 2).sum()), int((f == 3).sum()), int(((f > 3) | f.isna()).sum())]


def _detail(key, h, race, e):
    """The horse's own numbers behind a situation label."""
    p = h["past"][0] if h["past"] else None
    if not p:
        return None
    if key == "s_prev":
        return f"{p['name']} {p['finish'] or p['finish_raw']}着（{p['pop']}番人気）" if p["pop"] else f"{p['name']}"
    if key == "s_l3":
        return f"前走の上がり{p['l3']}秒（メンバー{p['l3rank']}位）" if p["l3"] else None
    if key == "s_gap":
        return f"前走 {p['date']}"
    if key == "s_dist":
        return f"前走{p['surface']}{p['distance']}m → 今回{race['surface']}{race['distance']}m"
    if key == "s_maxd":
        return f"これまでの最長{max(r['distance'] for r in h['past'])}m"
    if key == "s_course":
        rec = h["records"]["course_exact"]
        return f"{race['venue']}{race['surface']}{race['distance']}mで{'-'.join(map(str, rec))}"
    if key == "s_heavy":
        return f"{race['surface']}の稍重〜不良で{'-'.join(map(str, h['records']['heavy']))}"
    if key == "s_jockey":
        return f"前走{p['jockey']} → 今回{h['jockey']}"
    if key == "s_carried":
        return f"{p['carried']}kg → {h['carried']}kg" if p["carried"] and h["carried"] else None
    if key == "s_bw":
        return f"{h['bw']}kg（{h['bw_diff']:+d}）" if h["bw"] is not None and h["bw_diff"] is not None else None
    return None


def checks(h, race, e, cut, trends):
    """Each point a handicapper looks at, with how horses in the same spot did in the past."""
    out = []
    surface, band = race["surface"], dist_band(race["distance"])
    for key, label in SITUATIONS:
        v = e.get(key)
        if not isinstance(v, str):
            continue
        st = cut.situation(key, v, surface)
        if st:
            out.append({"k": label, "v": v, "d": _detail(key, h, race, e),
                        "scope": f"{surface}の全レース・過去5年" if key != "s_heavy" else f"{surface}の稍重〜不良・過去5年", **st})
    tb = trends.get("base")
    st = next((x for x in trends.get("style", []) if x["key"] == h.get("style")), None)
    if st:
        out.append({"k": "脚質", "v": h["style"], "d": "近5走で最も多い位置取り", "scope": "このコース・過去5年",
                     "n": st["n"], "top3": st["top3"], "win": st["win"], "roi": st["roi"], "base": tb,
                     "s": mark(st["top3"], tb, st["n"], 30)})
    if h.get("frame") and trends.get("frame"):
        st = next((x for x in trends["frame"] if x["key"] == h["frame"]), None)
        if st:
            out.append({"k": "枠", "v": f"{h['frame']}枠", "d": None, "scope": "このコース・過去5年",
                         "n": st["n"], "top3": st["top3"], "win": st["win"], "roi": st["roi"], "base": tb,
                         "s": mark(st["top3"], tb, st["n"], 30)})
    j = h.get("jockey_rec")
    if j:
        base = num(cut.jockey_base, 3)
        out.append({"k": "騎手の成績", "v": h["jockey"], "d": None, "scope": "この騎手の全レース・直近1年",
                     **j, "base": base, "s": mark(j["top3"], base, j["n"], 50)})
    sr = h.get("sire_rec")
    if sr:
        out.append({"k": "血統", "v": f"父{h['sire']}", "d": None, "scope": f"父の産駒・{surface}{band}・過去5年",
                     "n": sr["n"], "top3": sr["top3"], "win": sr["win"], "roi": sr["roi"], "base": sr["base"],
                     "s": mark(sr["top3"], sr["base"], sr["n"], 30)})
    return out


def race_payload(race, entrants, df, cut, payouts, preds=None):
    date = pd.Timestamp(race["date"])
    trends = course_trends(df, race, date)
    hist_all = df[df["date"] < date]
    by_horse = {k: g for k, g in hist_all[hist_all["horse_id"].isin(entrants["horse_id"])].groupby("horse_id")}
    band = dist_band(race["distance"])
    entrants = entrants.reindex(columns=entrants.columns.union(["odds", "number", "frame"]))
    inv = 1 / entrants["odds"].where(entrants["odds"] > 0)
    market = (inv / inv.sum()) if inv.notna().any() else pd.Series(np.nan, index=entrants.index)
    horses = []
    for i, e in entrants.iterrows():
        hist = by_horse.get(e["horse_id"], df.iloc[0:0])
        h = {
            "number": num(e.get("number")), "frame": num(e.get("frame")), "horse_id": e["horse_id"],
            "name": e["horse_name"], "sex": e.get("sex"), "age": num(e.get("age")),
            "carried": num(e.get("weight_carried"), 1), "jockey": e.get("jockey_name"),
            "trainer": e.get("trainer_name"), "stable": e.get("stable"),
            "bw": num(e.get("body_weight")), "bw_diff": num(e.get("body_weight_diff")),
            "odds": num(e.get("odds"), 1), "pop": num(e.get("popularity")),
            "finish": num(e.get("finish")), "finish_raw": e.get("finish_raw"), "time": num(e.get("time_sec"), 1),
            "l3": num(e.get("last3f"), 1), "passing": e.get("passing"),
            "sire": clean(e.get("sire")), "damsire": clean(e.get("damsire")),
            "line": line_of(e.get("sire"), e.get("sire_sire")),
            "p_market": num(market.get(i), 4),
            "past": past_runs(hist),
            "records": {
                "all": record(hist, pd.Series(True, index=hist.index)),
                "band": record(hist, (hist["band"] == band) & (hist["surface"] == race["surface"])),
                "course": record(hist, (hist["venue"] == race["venue"]) & (hist["surface"] == race["surface"])),
                "course_exact": record(hist, (hist["venue"] == race["venue"]) & (hist["surface"] == race["surface"])
                                       & (hist["distance"] == race["distance"])),
                "heavy": record(hist, hist["going"].isin(["稍重", "重", "不良"]) & (hist["surface"] == race["surface"])),
            },
            "prize": num(hist["prize"].sum(), 0),
            "jockey_rec": cut.jockey_rec(e.get("jockey_id"), e.get("jockey_name")),
            "sire_rec": cut.sire_rec(e.get("sire_id"), race["surface"], band),
        }
        h["style"] = horse_style(hist)
        if preds is not None:
            p = preds.get(h["name"])
            if p:
                h.update(p)
        h["checks"] = checks(h, race, e, cut, trends)
        horses.append(h)
    out = {k: (num(v) if not isinstance(v, str) else v) for k, v in race.items()}
    out["date"] = date.strftime("%Y-%m-%d")
    out["horses"] = horses
    out["trends"] = trends
    pay = payouts[payouts["race_id"] == race["race_id"]]
    out["payouts"] = [{"type": r.bet_type, "combo": r.combo, "payout": int(r.payout), "pop": num(r.popularity)}
                      for r in pay.itertuples()]
    out["has_ai"] = preds is not None
    out["seg"] = seg_of(race, entrants["odds"].min())
    return out


# --- betting by situation -------------------------------------------------
SEG_DIMS = {
    "surface": ["芝", "ダ"],
    "field": ["〜10頭", "11〜14頭", "15頭〜"],
    "cls": ["新馬・未勝利", "1〜3勝クラス", "オープン・重賞"],
    "hande": ["ハンデ戦", "ハンデ戦以外"],
    "fav": ["1番人気が1倍台", "2倍台", "3倍台", "4倍以上"],
}
# (key, label, tickets per race); horses are picked by popularity rank only
STRATEGIES = [
    ("win1", "1番人気の単勝", 1),
    ("place1", "1番人気の複勝", 1),
    ("q12", "1-2番人気の馬連", 1),
    ("w12", "1-2番人気のワイド", 1),
    ("t123", "1・2・3番人気の3連複", 1),
    ("q1x", "1番人気から2〜5番人気へ馬連流し", 4),
    ("t1x", "1番人気軸で2〜6番人気へ3連複流し", 10),
    ("tf1x", "1番人気1着固定、2〜4番人気へ3連単", 6),
    ("win456", "4・5・6番人気の単勝", 3),
    ("win789", "7・8・9番人気の単勝", 3),
]


def seg_of(race, fav_odds):
    ct = str(race.get("class_text") or "")
    grade = race.get("grade")
    if "新馬" in ct or "未勝利" in ct:
        cls = "新馬・未勝利"
    elif isinstance(grade, str) or "オープン" in ct:
        cls = "オープン・重賞"
    else:
        cls = "1〜3勝クラス"
    n = race.get("n_runners") or 0
    fav = None
    if fav_odds is not None and not (isinstance(fav_odds, float) and math.isnan(fav_odds)):
        fav = _band(fav_odds, (1.99, 2.99, 3.99), SEG_DIMS["fav"])
    return {"surface": race.get("surface"), "field": _band(n, (10, 14), SEG_DIMS["field"]), "cls": cls,
            "hande": "ハンデ戦" if "ハンデ" in ct else "ハンデ戦以外", "fav": fav}


def strategy_table(races, df, payouts):
    """Historical hit rate and return of simple, popularity-based bets, by race situation."""
    pay = {(r.race_id, r.bet_type, r.combo): r.payout for r in payouts.itertuples()}
    paid = set(payouts["race_id"])
    runs = df[df["popularity"].notna() & ~df["finish_raw"].isin(SCRATCHED)]
    rows, horse_rows = [], []
    meta = races.set_index("race_id")
    for rid, g in runs.groupby("race_id"):
        race = meta.loc[rid]
        g = g.sort_values("popularity")
        nums = [int(x) for x in g["number"]]
        if len(nums) < 6 or race["surface"] not in ("芝", "ダ") or rid not in paid:
            continue
        p = {i + 1: nums[i] for i in range(min(9, len(nums)))}
        get = lambda t, c: pay.get((rid, t, c), 0)  # noqa: E731
        pair = lambda a, b: "-".join(map(str, sorted((a, b))))  # noqa: E731
        trio = lambda a, b, c: "-".join(map(str, sorted((a, b, c))))  # noqa: E731
        ret = {
            "win1": get("単勝", str(p[1])),
            "place1": get("複勝", str(p[1])),
            "q12": get("馬連", pair(p[1], p[2])),
            "w12": get("ワイド", pair(p[1], p[2])),
            "t123": get("三連複", trio(p[1], p[2], p[3])),
            "q1x": sum(get("馬連", pair(p[1], p[k])) for k in range(2, 6)),
            "t1x": sum(get("三連複", trio(p[1], p[a], p[b])) for a in range(2, 7) for b in range(a + 1, 7)),
            "tf1x": sum(get("三連単", f"{p[1]}-{p[a]}-{p[b]}") for a in range(2, 5) for b in range(2, 5) if a != b),
            "win456": sum(get("単勝", str(p[k])) for k in (4, 5, 6)),
            "win789": sum(get("単勝", str(p[k])) for k in (7, 8, 9) if k in p),
        }
        fav = g["odds"].iloc[0]
        row = {"race_id": rid, "year": race["date"].year, **seg_of(race.to_dict(), fav), **ret}
        top3 = g[g["finish"] <= 3]
        row["fav_top3"] = int(g["finish"].iloc[0] <= 3) if not math.isnan(g["finish"].iloc[0]) else 0
        row["top_pop_max"] = int(top3["popularity"].max()) if len(top3) else 99
        rows.append(row)
        for x in g.itertuples():
            horse_rows.append((rid, int(x.popularity), x.win, x.top3, x.ret, get("複勝", str(int(x.number)))))
    R = pd.DataFrame(rows)
    H = pd.DataFrame(horse_rows, columns=["race_id", "pop", "win", "top3", "ret", "pret"])
    trio_pay = payouts[payouts["bet_type"] == "三連複"].groupby("race_id")["payout"].max()
    tri_pay = payouts[payouts["bet_type"] == "三連単"].groupby("race_id")["payout"].max()
    R["trio"] = R["race_id"].map(trio_pay)
    R["trifecta"] = R["race_id"].map(tri_pay)
    H = H.merge(R[["race_id"] + list(SEG_DIMS)], on="race_id")
    H["pband"] = H["pop"].map(lambda k: str(k) if k <= 5 else ("6〜9" if k <= 9 else "10〜"))
    split = (R["year"] <= 2020)

    out = {}
    keys = list(SEG_DIMS)
    for combo in itertools.product(*[[None] + SEG_DIMS[k] for k in keys]):
        m = pd.Series(True, index=R.index)
        hm = pd.Series(True, index=H.index)
        for k, v in zip(keys, combo):
            if v is not None:
                m &= R[k] == v
                hm &= H[k] == v
        sub = R[m]
        if len(sub) < 30:
            continue
        strat = []
        for k, label, n in STRATEGIES:
            a, b = sub[split[m]], sub[~split[m]]
            strat.append({"key": k, "label": label, "tickets": n,
                          "hit": num((sub[k] > 0).mean(), 3), "roi": num(sub[k].sum() / (len(sub) * n), 0),
                          "roi_a": num(a[k].sum() / (len(a) * n), 0) if len(a) else None,
                          "roi_b": num(b[k].sum() / (len(b) * n), 0) if len(b) else None,
                          "avg": num(sub.loc[sub[k] > 0, k].mean(), 0) if (sub[k] > 0).any() else None})
        hs = H[hm]
        pops = [{"key": pb, "win": num(gg["win"].mean(), 3), "top3": num(gg["top3"].mean(), 3),
                 "roi": num(gg["ret"].mean(), 0), "proi": num(gg["pret"].mean(), 0)}
                for pb, gg in hs.groupby("pband", sort=False)]
        order = ["1", "2", "3", "4", "5", "6〜9", "10〜"]
        pops.sort(key=lambda x: order.index(x["key"]))
        out["|".join(v or "" for v in combo)] = {
            "races": int(len(sub)),
            "fav_top3": num(sub["fav_top3"].mean(), 3),
            "calm": num((sub["top_pop_max"] <= 5).mean(), 3),
            "trio_med": num(sub["trio"].median(), 0), "trifecta_med": num(sub["trifecta"].median(), 0),
            "big": num((sub["trifecta"] >= 100000).mean(), 3),
            "strategies": strat, "pops": pops,
        }
    years = f"{int(R['year'].min())}〜{int(R['year'].max())}年"
    return {"dims": SEG_DIMS, "keys": keys, "years": years, "split": ["2015〜2020年", "2021年〜"], "table": out}


def dump(obj):
    """JSON without NaN (browsers reject it)."""
    def fix(o):
        if isinstance(o, float) and math.isnan(o):
            return None
        if isinstance(o, dict):
            return {k: fix(v) for k, v in o.items()}
        if isinstance(o, list):
            return [fix(v) for v in o]
        return o
    return json.dumps(fix(obj), ensure_ascii=False, separators=(",", ":"))


def summary(race):
    keys = ["race_id", "date", "venue", "race_no", "name", "grade", "surface", "distance", "direction",
            "course_note", "start_time", "n_runners", "going", "weather"]
    out = {k: num(race.get(k)) if not isinstance(race.get(k), str) else race.get(k) for k in keys}
    out["date"] = pd.Timestamp(race["date"]).strftime("%Y-%m-%d")
    return out


def read_featured(path):
    """Win probability, top-3 rate and running style per horse from a calibrated race-replay file."""
    f = json.loads(Path(path).read_text(encoding="utf-8"))
    place = f.get("calibration", {}).get("place") or [None] * len(f["horses"])
    out = {}
    for h, pl in zip(f["horses"], place):
        out[h["name"]] = {
            "p_ai": num(h["p_model"], 4), "p_place": num(pl, 4),
            "style": build_field.style_word(h["style"]) if h.get("style") is not None else None,
            "jockey_plan": h.get("jockey") or None,
            "number": h.get("gate"), "frame": frame_of(h.get("gate"), len(f["horses"])),
            "odds": h.get("odds"),
        }
    return f, out


def frame_of(number, n):
    """JRA post position (枠) of horse ``number`` in a field of ``n``: eight frames,
    the extra horses going to the outside frames."""
    if not number:
        return None
    base, extra = divmod(n, 8)
    sizes = [base + (1 if f >= 8 - extra else 0) for f in range(8)]
    for f, size in enumerate(sizes, 1):
        number -= size
        if number <= 0:
            return f
    return 8


def copy_theater(field_path):
    """The replay's scripts plus this race's file, served next to the site."""
    dst = ROOT / "www" / "theater"
    (dst / "data").mkdir(parents=True, exist_ok=True)
    for name in ("player.js", "engine.js", "course.js", "tally-worker.js"):
        shutil.copy(THEATER / name, dst / name)
    shutil.copy(field_path, dst / "data" / Path(field_path).name)
    return f"theater/data/{Path(field_path).name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/mnt/project-files/keiba-sim/data/keiba.sqlite")
    ap.add_argument("--featured", default=str(THEATER / "data" / "kikka2026.json"),
                    help="calibrated race-replay file of the upcoming race (theater/data/<name>.json)")
    ap.add_argument("--days", type=int, default=2, help="how many recent race days to include")
    args = ap.parse_args()

    races, df, horses, payouts = load(args.db)
    (OUT / "race").mkdir(parents=True, exist_ok=True)
    index = {"built": pd.Timestamp.now().strftime("%Y-%m-%d"), "days": [], "featured": [], "history": []}

    # Upcoming: Kikka-sho, from the race-replay file (same numbers as the replay)
    field, preds = read_featured(args.featured)
    names = list(preds)
    latest = horses[horses["name"].isin(names)].drop_duplicates("name", keep="last")
    last_run = df[df["horse_name"].isin(names)].groupby("horse_name").tail(1).set_index("horse_name")
    ent = pd.DataFrame({"horse_name": names})
    ent = ent.merge(latest.rename(columns={"name": "horse_name"}), on="horse_name", how="left")
    ent["sex"] = ent["horse_name"].map(last_run["sex"])
    ent["age"] = 3
    ent["weight_carried"] = ent["sex"].map(lambda s: 55.0 if s == "牝" else 57.0)
    ent["jockey_name"] = [preds[n]["jockey_plan"] or last_run["jockey_name"].get(n) for n in names]
    ent["jockey_id"] = [None if preds[n]["jockey_plan"] else last_run["jockey_id"].get(n) for n in names]
    ent["number"] = [preds[n]["number"] for n in names]
    ent["frame"] = [preds[n]["frame"] for n in names]
    ent["odds"] = [preds[n]["odds"] for n in names]
    ent["trainer_name"] = ent["horse_name"].map(last_run["trainer_name"])
    ent["stable"] = ent["horse_name"].map(last_run["stable"])
    date = pd.Timestamp(KIKKA["date"])
    # today's entries go through the same situation labelling as every past run
    for k in ("race_id", "venue", "name", "grade", "surface", "distance", "course_note"):
        ent[k] = KIKKA[k]
    ent["date"], ent["n_runners"], ent["going"] = date, len(ent), None
    ent["finish"], ent["finish_raw"], ent["top3"], ent["win"], ent["ret"] = np.nan, None, 0, 0, 0.0
    df = add_situations(pd.concat([df, ent], ignore_index=True))
    ent = df[df["race_id"] == KIKKA["race_id"]].set_index("horse_name").loc[names].reset_index()
    df = df[df["race_id"] != KIKKA["race_id"]]
    kikka = race_payload({**KIKKA, "n_runners": len(ent)}, ent, df, Cutoff(df, date), payouts, preds)
    kikka["note"] = "出走予定馬での予想です。枠順とオッズは未確定、騎手は予定または前走の騎手です。"
    kikka["theater"] = copy_theater(args.featured)
    kikka["model"] = field.get("model")
    (OUT / "race" / f"{KIKKA['race_id']}.json").write_text(dump(kikka))
    index["featured"].append({**summary({**KIKKA, "n_runners": len(ent)}), "upcoming": True})
    print("kikka", len(ent), "horses")

    # Recent race days with full results
    days = sorted(races["date"].unique())[-args.days:]
    for d in days:
        cut = Cutoff(df, pd.Timestamp(d))
        day = races[races["date"] == d].sort_values(["venue", "race_no"])
        index["days"].append({"date": pd.Timestamp(d).strftime("%Y-%m-%d"),
                              "races": [summary(r) for r in day.to_dict("records")]})
        for r in day.to_dict("records"):
            ent = df[df["race_id"] == r["race_id"]].sort_values("number")
            (OUT / "race" / f"{r['race_id']}.json").write_text(
                dump(race_payload(r, ent, df, cut, payouts)))
        print(pd.Timestamp(d).date(), len(day), "races")

    # Past Kikka-sho editions, for the history tab
    for r in races[races["name"].str.contains("菊花賞", na=False)].sort_values("date").to_dict("records"):
        ent = df[df["race_id"] == r["race_id"]].sort_values("number")
        cut = Cutoff(df, r["date"])
        (OUT / "race" / f"{r['race_id']}.json").write_text(
            dump(race_payload(r, ent, df, cut, payouts)))
        index["history"].append(summary(r))
    (OUT / "strategy.json").write_text(dump(strategy_table(races, df, payouts)))
    (OUT / "index.json").write_text(dump(index))
    print("done")


if __name__ == "__main__":
    main()
