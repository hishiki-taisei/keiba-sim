"""Build the data files for the prediction portal (portal/www).

    python3 portal/build.py --db /mnt/project-files/keiba-sim/data/keiba.sqlite \
        --predictions /mnt/project-files/keiba-sim/predictions/kikka2026_preliminary.csv

Read-only: opens the database in read-only mode and never imports the model
code, so it can run next to the data-collection and model work. Every figure
shown for a race (past runs, jockey and sire records, course trends) uses only
races run before that race's date.

Writes portal/www/data/index.json and portal/www/data/race/<race_id>.json.
"""
import argparse
import json
import math
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "www" / "data"

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
    """Running style from the first corner position."""
    if not isinstance(passing, str) or not field:
        return None
    try:
        first = int(passing.split("-")[0])
    except ValueError:
        return None
    r = first / field
    if first == 1:
        return "逃げ"
    if r <= 0.35:
        return "先行"
    if r <= 0.7:
        return "差し"
    return "追込"


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
        self.jockey = year.groupby("jockey_id").agg(n=("top3", "size"), top3=("top3", "mean"), win=("win", "mean"))
        self.jockey_by_name = year.groupby("jockey_name").agg(n=("top3", "size"), top3=("top3", "mean"),
                                                              win=("win", "mean"))
        five = df[(df["date"] < date) & (df["date"] >= date - pd.DateOffset(years=5))]
        self.sire = five.groupby(["sire_id", "surface", "band"]).agg(
            n=("top3", "size"), top3=("top3", "mean"), win=("win", "mean"), ret=("ret", "mean"))
        self.base = five.groupby(["surface", "band"]).agg(top3=("top3", "mean"))

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
        return {"n": int(r["n"]), "top3": num(r["top3"], 3), "win": num(r["win"], 3)}

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


def reasons(h, race):
    """Plain-language points for beginners: (good, caution)."""
    good, warn = [], []
    runs = h["past"]
    if not runs:
        return ["データがまだ少ない馬です"], []
    last = runs[0]
    if last["finish"] == 1:
        good.append(f"前走「{last['name']}」で1着")
    elif last["finish"] and last["finish"] <= 3:
        good.append(f"前走「{last['name']}」で{last['finish']}着と好走")
    if any(r["l3rank"] == 1 for r in runs[:3]):
        good.append("最近の3走で、ゴール前の末脚（上がり3F）がメンバー最速だったことがある")
    rec = h["records"]["band"]
    if rec[0] + rec[1] + rec[2] > 0:
        good.append(f"同じくらいの距離（{dist_band(race['distance'])}）で3着以内に入ったことがある")
    rec = h["records"]["course"]
    if rec[0] + rec[1] + rec[2] > 0:
        good.append(f"{race['venue']}の{race['surface']}コースで3着以内の経験あり")
    j = h.get("jockey_rec")
    if j and j["n"] >= 50 and j["top3"] >= 0.33:
        good.append(f"騎手の{h['jockey']}は最近1年で3回に1回以上3着以内（{j['top3'] * 100:.0f}%）")
    s = h.get("sire_rec")
    if s and s["n"] >= 30 and s["base"] and s["top3"] >= s["base"] * 1.25:
        good.append(f"父{h['sire']}の子はこの距離で平均より好成績（3着内率{s['top3'] * 100:.0f}%）")
    if s and s["n"] >= 30 and s["base"] and s["top3"] <= s["base"] * 0.7:
        warn.append(f"父{h['sire']}の子はこの距離で平均より成績が落ちる")
    gap = (pd.Timestamp(race["date"]) - pd.Timestamp(last["date"])).days
    if gap >= 90:
        warn.append(f"前走から{gap // 7}週間あいた休み明け")
    longest = max(r["distance"] for r in runs)
    if race["distance"] - longest >= 400:
        warn.append(f"今回が初めての長い距離（これまでの最長は{longest}m）")
    if h.get("bw_diff") is not None and abs(h["bw_diff"]) >= 12:
        warn.append(f"馬体重が前走から{h['bw_diff']:+d}kgと大きく変わった")
    return good[:3], warn[:2]


def race_payload(race, entrants, df, cut, payouts, preds=None):
    date = pd.Timestamp(race["date"])
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
                "heavy": record(hist, hist["going"].isin(["稍重", "重", "不良"]) & (hist["surface"] == race["surface"])),
            },
            "prize": num(hist["prize"].sum(), 0),
            "jockey_rec": cut.jockey_rec(e.get("jockey_id"), e.get("jockey_name")),
            "sire_rec": cut.sire_rec(e.get("sire_id"), race["surface"], band),
        }
        styles = [r["style"] for r in h["past"][:5] if r["style"]]
        h["style"] = max(set(styles), key=styles.count) if styles else None
        if preds is not None:
            p = preds.get(h["name"])
            if p:
                h.update(p)
        h["good"], h["warn"] = reasons(h, race)
        horses.append(h)
    out = {k: (num(v) if not isinstance(v, str) else v) for k, v in race.items()}
    out["date"] = date.strftime("%Y-%m-%d")
    out["horses"] = horses
    out["trends"] = course_trends(df, race, date)
    pay = payouts[payouts["race_id"] == race["race_id"]]
    out["payouts"] = [{"type": r.bet_type, "combo": r.combo, "payout": int(r.payout), "pop": num(r.popularity)}
                      for r in pay.itertuples()]
    out["has_ai"] = preds is not None
    return out


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


def read_preds(path):
    p = pd.read_csv(path)
    out = {}
    for r in p.to_dict("records"):
        out[r["馬"]] = {
            "p_ai": num(r.get("勝率(モデル)"), 4), "p_sim": num(r.get("勝率(シミュ)"), 4),
            "p_sim_place": num(r.get("複勝率(シミュ)"), 4),
            "jockey_plan": r.get("騎手") if isinstance(r.get("騎手"), str) else None,
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/mnt/project-files/keiba-sim/data/keiba.sqlite")
    ap.add_argument("--predictions", default="/mnt/project-files/keiba-sim/predictions/kikka2026_preliminary.csv")
    ap.add_argument("--days", type=int, default=2, help="how many recent race days to include")
    args = ap.parse_args()

    races, df, horses, payouts = load(args.db)
    (OUT / "race").mkdir(parents=True, exist_ok=True)
    index = {"built": pd.Timestamp.now().strftime("%Y-%m-%d"), "days": [], "featured": [], "history": []}

    # Upcoming: Kikka-sho, from the prediction file
    preds = read_preds(args.predictions)
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
    ent["trainer_name"] = ent["horse_name"].map(last_run["trainer_name"])
    ent["stable"] = ent["horse_name"].map(last_run["stable"])
    date = pd.Timestamp(KIKKA["date"])
    kikka = race_payload({**KIKKA, "n_runners": len(ent)}, ent, df, Cutoff(df, date), payouts, preds)
    kikka["note"] = ("出走予定馬の段階の予想です。枠順・オッズ・騎手は未確定で、騎手は予定または前走の騎手です。"
                     "AI勝率は「過去レースのデータ収集」スレッドの勝率モデル、シミュレーションはレースを"
                     "何千回も走らせた結果です。")
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
    (OUT / "index.json").write_text(dump(index))
    print("done")


if __name__ == "__main__":
    main()
