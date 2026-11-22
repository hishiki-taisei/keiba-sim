"""Parsers for netkeiba pages. Each returns plain dicts ready for the database."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

VENUES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
          "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}

RACE_ID_RE = re.compile(r"/race/(\d{12})/")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html.replace("\xa0", " "), "lxml")


def calendar_dates(html: str) -> list[str]:
    """race.netkeiba.com/top/calendar.html -> race days as YYYYMMDD."""
    return sorted(set(re.findall(r"kaisai_date=(\d{8})", html)))


def race_ids(html: str) -> list[str]:
    """db.netkeiba.com/race/list/YYYYMMDD/ -> JRA race ids (local/overseas races dropped)."""
    ids = set(RACE_ID_RE.findall(html))
    return sorted(i for i in ids if i[4:6] in VENUES)


def _num(s: str | None, typ=float):
    if s is None:
        return None
    s = s.replace(",", "").strip()
    try:
        return typ(s)
    except ValueError:
        return None


def time_to_sec(s: str) -> float | None:
    m = re.fullmatch(r"(?:(\d+):)?(\d+(?:\.\d+)?)", s.strip())
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def _id(a, kind: str) -> str | None:
    if a is None:
        return None
    m = re.search(rf"/{kind}/(?:result/recent/)?(\w+)/?", a.get("href", ""))
    return m.group(1) if m else None


def race(html: str, race_id: str) -> dict | None:
    """db.netkeiba.com/race/<id>/ -> {'race': {...}, 'results': [...], 'laps': [...], 'payouts': [...]}."""
    b = soup(html)
    table = b.select_one("table.race_table_01")
    intro = b.select_one(".data_intro")
    if table is None or intro is None:
        return None

    name = intro.select_one("h1").get_text(strip=True)
    cond = intro.select_one("dd p span").get_text(" ", strip=True)
    small = intro.select_one("p.smalltxt").get_text(" ", strip=True)

    surface = "障" if "障" in cond[:3] else ("芝" if cond.startswith("芝") else "ダ")
    dist = re.search(r"(\d+)m", cond)
    direction = next((d for d in ("右", "左", "直線") if d in cond.split("/")[0]), None)
    weather = re.search(r"天候\s*:\s*(\S+)", cond)
    going = re.search(r"(?:芝|ダート)\s*:\s*(\S+)", cond)
    start = re.search(r"発走\s*:\s*(\d+:\d+)", cond)
    date = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", small)
    grade = re.search(r"\((G[1-3]|GI{1,3}|J\.G[1-3]|L|OP)\)", name)
    grade_s = grade.group(1).replace("GIII", "G3").replace("GII", "G2").replace("GI", "G1") if grade else None

    info = {
        "race_id": race_id,
        "date": f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}" if date else None,
        "venue": VENUES.get(race_id[4:6]),
        "kai": int(race_id[6:8]),
        "day": int(race_id[8:10]),
        "race_no": int(race_id[10:12]),
        "name": name,
        "grade": grade_s,
        "surface": surface,
        "distance": int(dist.group(1)) if dist else None,
        "direction": direction,
        "course_note": "外" if "外" in cond.split("/")[0] else ("内" if "内" in cond.split("/")[0] else None),
        "weather": weather.group(1) if weather else None,
        "going": going.group(1) if going else None,
        "start_time": start.group(1) if start else None,
        "class_text": re.sub(r"\s+", " ", small.split("日目", 1)[-1] if "日目" in small else small).strip(),
    }

    rows = table.find_all("tr")
    header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    col = {h: i for i, h in enumerate(header)}

    def cell(cells, key):
        i = col.get(key)
        return cells[i] if i is not None and i < len(cells) else None

    def text(cells, key):
        c = cell(cells, key)
        return c.get_text(strip=True) if c is not None else None

    results = []
    for r in rows[1:]:
        cells = r.find_all("td")
        if len(cells) < 10:
            continue
        sexage = text(cells, "性齢") or ""
        bw = re.fullmatch(r"(\d+)\(([+-]?\d+)\)", text(cells, "馬体重") or "")
        trainer_cell = cell(cells, "調教師")
        trainer_txt = trainer_cell.get_text(strip=True) if trainer_cell else ""
        stable = re.match(r"\[(.)\]", trainer_txt)
        horse_a = cell(cells, "馬名").find("a")
        results.append({
            "race_id": race_id,
            "finish": _num(text(cells, "着順"), int),
            "finish_raw": text(cells, "着順"),
            "frame": _num(text(cells, "枠番"), int),
            "number": _num(text(cells, "馬番"), int),
            "horse_id": _id(horse_a, "horse"),
            "horse_name": horse_a.get_text(strip=True) if horse_a else text(cells, "馬名"),
            "sex": sexage[:1] or None,
            "age": _num(sexage[1:], int),
            "weight_carried": _num(text(cells, "斤量")),
            "jockey_id": _id(cell(cells, "騎手").find("a"), "jockey"),
            "jockey_name": text(cells, "騎手"),
            "time_sec": time_to_sec(text(cells, "タイム") or ""),
            "margin": text(cells, "着差") or None,
            "passing": text(cells, "通過") or None,
            "last3f": _num(text(cells, "上り")),
            "odds": _num(text(cells, "単勝")),
            "popularity": _num(text(cells, "人気"), int),
            "body_weight": int(bw.group(1)) if bw else None,
            "body_weight_diff": int(bw.group(2)) if bw else None,
            "trainer_id": _id(trainer_cell.find("a") if trainer_cell else None, "trainer"),
            "trainer_name": trainer_txt[3:] if stable else trainer_txt,
            "stable": stable.group(1) if stable else None,
            "owner_id": _id(cell(cells, "馬主").find("a") if cell(cells, "馬主") else None, "owner"),
            "prize": _num(text(cells, "賞金(万円)")),
        })

    laps, corners, payouts = None, {}, []
    for t in b.select("table.result_table_02"):
        summary = t.get("summary", "")
        for tr in t.find_all("tr"):
            th, td = tr.find("th"), tr.find("td")
            if th is None or td is None:
                continue
            k, v = th.get_text(strip=True), td.get_text(strip=True)
            if summary == "ラップタイム" and k == "ラップ":
                laps = v
            elif summary == "コーナー通過順位":
                corners[k] = v
    info["laps"] = laps
    info["corners"] = " / ".join(f"{k}:{v}" for k, v in corners.items()) or None
    info["n_runners"] = len(results)

    for t in b.select("table.pay_table_01"):
        for tr in t.find_all("tr"):
            th = tr.find("th")
            tds = tr.find_all("td")
            if th is None or len(tds) < 2:
                continue
            kinds = [x for x in tds[0].stripped_strings]
            pays = [x for x in tds[1].stripped_strings]
            pops = [x for x in tds[2].stripped_strings] if len(tds) > 2 else []
            for i, combo in enumerate(kinds):
                payouts.append({
                    "race_id": race_id,
                    "bet_type": th.get_text(strip=True),
                    "combo": combo.replace(" ", ""),
                    "payout": _num(pays[i] if i < len(pays) else None, int),
                    "popularity": _num(pops[i] if i < len(pops) else None, int),
                })

    return {"race": info, "results": results, "payouts": payouts}


def pedigree(html: str, horse_id: str) -> dict | None:
    """db.netkeiba.com/horse/ped/<id>/ -> sire / dam / damsire with ids."""
    b = soup(html)
    t = b.select_one("table.blood_table")
    if t is None:
        return None
    # Generation-1 cells span 16 rows: first is sire, the one in the 17th row is dam.
    gen1 = [td for td in t.find_all("td") if td.get("rowspan") == "16"]
    gen2 = [td for td in t.find_all("td") if td.get("rowspan") == "8"]

    def nm(td):
        if td is None:
            return None, None
        a = td.find("a", href=re.compile(r"/horse/"))
        if a is None:
            return td.get_text(strip=True) or None, None
        return a.get_text(strip=True), _id(a, "horse")

    sire, sire_id = nm(gen1[0] if gen1 else None)
    dam, dam_id = nm(gen1[1] if len(gen1) > 1 else None)
    damsire, damsire_id = nm(gen2[2] if len(gen2) > 2 else None)
    siresire, siresire_id = nm(gen2[0] if gen2 else None)
    title = b.title.get_text() if b.title else ""
    return {"horse_id": horse_id, "name": title.split("(")[0].split("の血統")[0].strip() or None,
            "sire": sire, "sire_id": sire_id, "dam": dam, "dam_id": dam_id,
            "damsire": damsire, "damsire_id": damsire_id,
            "sire_sire": siresire, "sire_sire_id": siresire_id}


def _grade(title: str) -> str | None:
    m = re.search(r"\((G[1-3]|GI{1,3}|L|OP)\)", title)
    if not m:
        return None
    return {"GI": "G1", "GII": "G2", "GIII": "G3"}.get(m.group(1), m.group(1))


def entries(html: str, race_id: str) -> dict | None:
    """race.netkeiba.com/race/shutuba.html -> race conditions and the entered horses.

    Before the draw, gate and number are None; before betting opens, odds are None.
    """
    b = soup(html)
    rows = b.select("tr.HorseList")
    if not rows:
        return None
    data01 = b.select_one(".RaceData01")
    cond = data01.get_text(" ", strip=True) if data01 else ""
    dist = re.search(r"(\d+)m", cond)
    course = re.search(r"(障|芝|ダ)\S*\d+m", cond)
    surface = {"障": "障", "芝": "芝"}.get(course.group(1) if course else "", "ダ")
    going = re.search(r"馬場\s*:\s*(良|稍重|稍|重|不良|不)", cond)
    post = re.search(r"(\d{1,2}:\d{2})発走", cond)
    data02 = b.select_one(".RaceData02")
    cls = data02.get_text(" ", strip=True) if data02 else ""
    m_cls = re.search(r"\S*(新馬|未勝利|勝クラス|オープン|万下)\S*(?:\s+\S+)*?\s+(定量|別定|ハンデ|馬齢)", cls)
    title = b.title.get_text() if b.title else ""
    date = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
    out, seen = [], set()
    for r in rows:
        horse_a = r.find("a", href=re.compile(r"/horse/\d+"))
        if horse_a is None:
            continue
        hid = re.search(r"/horse/(\d+)", horse_a["href"]).group(1)
        # The page repeats some horses in other tables further down; keep the entry row only.
        if hid in seen or r.select_one("td[class^=Umaban]") is None:
            continue
        seen.add(hid)
        cells = r.find_all("td")
        txt = [c.get_text(" ", strip=True) for c in cells]
        sexage = next((t for t in txt if re.fullmatch(r"[牡牝セ]\d+", t)), "")
        weight = next((t for t in txt if re.fullmatch(r"\d{2}(\.\d)?", t)), None)
        frame = r.select_one("td[class^=Waku]")
        num = r.select_one("td[class^=Umaban]")
        odds = r.select_one("td.Popular span, span[id^=odds-]")
        jockey_a = r.find("a", href=re.compile(r"/jockey/"))
        out.append({
            "horse_id": re.search(r"/horse/(\d+)", horse_a["href"]).group(1),
            "horse_name": horse_a.get_text(strip=True),
            "sex": sexage[:1] or None, "age": _num(sexage[1:], int),
            "weight_carried": _num(weight),
            "frame": _num(frame.get_text(strip=True), int) if frame else None,
            "number": _num(num.get_text(strip=True), int) if num else None,
            "jockey_id": _id(jockey_a, "jockey"),
            "jockey_name": jockey_a.get_text(strip=True) if jockey_a else None,
            "odds": _num(odds.get_text(strip=True)) if odds else None,
            "scratched": "Cancel" in " ".join(r.get("class", [])) or "取消" in " ".join(txt) or "除外" in " ".join(txt),
        })
    return {"race_id": race_id, "title": title.split("|")[0].strip(),
            "date": f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}" if date else None,
            "surface": surface, "distance": int(dist.group(1)) if dist else None,
            "going": going.group(1) if going else None, "post_time": post.group(1) if post else None,
            "class_text": m_cls.group(0) if m_cls else cls, "grade": _grade(title),
            "horses": out}


def result_page(html: str, race_id: str) -> dict | None:
    """race.netkeiba.com/race/result.html -> finishing order, win odds and win/place payouts.

    Up the same evening, while the db.netkeiba.com race page can lag by days; used to settle bets.
    """
    b = soup(html)
    table = b.select_one("table#All_Result_Table") or b.select_one("table.RaceTable01")
    if table is None:
        return None
    results = []
    for r in table.select("tr.HorseList"):
        txt = [c.get_text(" ", strip=True) for c in r.find_all("td")]
        if len(txt) < 11:
            continue
        num = _num(txt[2], int)
        if num is None:
            continue
        fr = txt[0][:1] if txt[0][:1] in ("取", "除", "中", "失") else txt[0]  # 取消 -> 取, as in the DB
        results.append({"race_id": race_id, "number": num, "finish_raw": fr, "finish": _num(txt[0], int),
                        "odds": _num(txt[10])})
    payouts = []
    for tr in b.select("table.Payout_Detail_Table tr"):
        th = tr.find("th")
        kind = th.get_text(strip=True) if th else ""
        if kind not in ("単勝", "複勝"):
            continue
        res, pay = tr.select_one("td.Result"), tr.select_one("td.Payout")
        nums = [s.get_text(strip=True) for s in res.find_all("span") if s.get_text(strip=True)] if res else []
        yen = re.findall(r"([\d,]+)円", pay.get_text(" ")) if pay else []
        for n, y in zip(nums, yen):
            payouts.append({"race_id": race_id, "bet_type": kind, "combo": n, "payout": int(y.replace(",", ""))})
    return {"results": results, "payouts": payouts} if results else None
