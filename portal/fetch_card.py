"""Download a race's card and current odds for the portal.

    python3 portal/fetch_card.py 202608040911

Writes portal/cache/<race_id>/: shutuba.html (entries, gates, jockeys) and
odds.json (win and place odds with the time netkeiba published them) and
baba.json (JRA's going, moisture and the week's weather for Kyoto). Run it
again on race day to pick up newer odds. Nothing is written to the database.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CARD = "https://race.netkeiba.com/race/shutuba.html?race_id={}"
ODDS = "https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={}&type={}&action=update"
BABA = "https://www.jra.go.jp/keiba/baba/index2.html"  # 京都 (index.html is 東京)
HEADERS = {"User-Agent": "Mozilla/5.0 (keiba-sim portal)"}
RESULT = "https://race.netkeiba.com/race/result.html?race_id={}"


def baba(text):
    """JRA's track page -> going, moisture and the week's weather (one dict)."""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    out = {"source": BABA}
    m = re.search(r"(第\d+回京都競馬第\d+日) （(.+?)） 馬場状態 （(.+?)現在） .*?天候： (\S+) 芝 (\S+) ダート (\S+)", t)
    if m:
        out.update(meeting=m[1], day=m[2], as_of=m[3], weather=m[4], turf=m[5], dirt=m[6])
    m = re.search(r"ゴール前 4コーナー 芝 ([\d.]+) ([\d.]+) ダート ([\d.]+) ([\d.]+)", t)
    if m:
        out["moisture"] = {"turf": [float(m[1]), float(m[2])], "dirt": [float(m[3]), float(m[4])]}
    m = re.search(r"週間情報 .*?（(\S+)） (\d+時)現在 (.*?) 天候 (.*?) 雨量", t)
    if m:
        days = re.findall(r"(\d+)日 （(\S+?)）", m[3])
        weather = m[4].split()
        if len(days) == len(weather):
            out["week"] = [{"day": f"{d}日({w[0]})", "weather": x} for (d, w), x in zip(days, weather)]
    m = re.search(r"使用コース (\S+ コース（.*?）)", t)
    if m:
        out["course"] = m[1]
    m = re.search(r"芝の状態 (.*?) 芝コースの様子", t)
    if m:
        out["turf_note"] = m[1]
    return out


def day_before(race_id):
    """Weather and going of the races run the day before at the same meeting
    (JRA's own page can lag a day behind; netkeiba's results show what the
    track actually was)."""
    prefix = race_id[:8] + f"{int(race_id[8:10]) - 1:02d}"
    out = []
    for r in range(1, 13):
        res = requests.get(RESULT.format(f"{prefix}{r:02d}"), headers=HEADERS, timeout=30)
        m = re.search(r'RaceData01.*?</div>', res.content.decode("utf-8", "replace"), re.S)
        if not m:
            continue
        t = re.sub(r"<[^>]+>|&nbsp;|\s+", " ", m[0])
        g = re.search(r"(芝|ダ)(\d+)m.*?天候:(\S+).*?馬場:(\S+)", t)
        if g:
            out.append({"r": r, "surface": g[1], "distance": int(g[2]), "weather": g[3], "going": g[4]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("race_id")
    args = ap.parse_args()
    out = ROOT / "cache" / args.race_id
    out.mkdir(parents=True, exist_ok=True)

    r = requests.get(CARD.format(args.race_id), headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(rb'charset="?([\w-]+)', r.content[:2000])
    (out / "shutuba.html").write_text(r.content.decode(m[1].decode() if m else "euc-jp", "replace"))

    odds = {}
    for kind, typ in (("win", 1), ("place", 2)):
        r = requests.get(ODDS.format(args.race_id, typ), headers=HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json().get("data") or {}
        odds[kind] = (d.get("odds") or {}).get(str(typ), {})
        odds["time"] = d.get("official_datetime")
    (out / "odds.json").write_text(json.dumps(odds, ensure_ascii=False))

    r = requests.get(BABA, headers=HEADERS, timeout=30)
    if r.ok:
        b = baba(r.content.decode("shift_jis", "replace"))
        b["day_before"] = day_before(args.race_id)
        (out / "baba.json").write_text(json.dumps(b, ensure_ascii=False))
    print(out, "odds at", odds.get("time"), file=sys.stderr)


if __name__ == "__main__":
    main()
