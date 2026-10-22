import gzip
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scraper import db, parse

FIX = Path(__file__).parent / "fixtures"


class EntriesTest(unittest.TestCase):
    def test_entries_page(self):
        html = gzip.decompress((FIX / "shutuba_202605040711.html.gz").read_bytes()).decode("utf-8", "replace")
        r = parse.entries(html, "202605040711")
        self.assertEqual((r["surface"], r["distance"], r["post_time"], r["date"]), ("ダ", 2100, "15:20", "2026-10-18"))
        # 13 runners: the horse repeated in a table further down the page is not counted twice.
        self.assertEqual(len(r["horses"]), 13)
        self.assertEqual([h["number"] for h in r["horses"]], list(range(1, 14)))


class ResultPageTest(unittest.TestCase):
    def test_result_page(self):
        html = (FIX / "result_202605040711.html").read_text(encoding="utf-8")  # trimmed to the tables
        d = parse.result_page(html, "202605040711")
        self.assertEqual(len(d["results"]), 3)  # fixture keeps the first three rows
        self.assertEqual((d["results"][0]["number"], d["results"][0]["finish"], d["results"][0]["odds"]), (9, 1, 4.6))
        self.assertIn({"race_id": "202605040711", "bet_type": "単勝", "combo": "9", "payout": 460}, d["payouts"])
        self.assertEqual(sum(p["bet_type"] == "複勝" for p in d["payouts"]), 3)


class SettleTest(unittest.TestCase):
    def test_win_place_and_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["KEIBA_SHARED"] = tmp
            import importlib
            import live.__main__ as live
            live = importlib.reload(live)
            live.LOCAL_DB = Path(tmp) / "k.sqlite"
            # No network in tests: the result page "has not been posted" for races missing from the DB.
            live.Fetcher = lambda *a, **k: type("F", (), {"get": lambda self, *a, **k: None})()
            con = db.connect(live.LOCAL_DB)
            db.upsert(con, "results", [
                {"race_id": "R1", "number": 1, "finish": 1, "finish_raw": "1", "odds": 3.0},
                {"race_id": "R1", "number": 2, "finish": 4, "finish_raw": "4", "odds": 5.0},
                {"race_id": "R1", "number": 3, "finish": None, "finish_raw": "取", "odds": None}])
            db.upsert(con, "payouts", [
                {"race_id": "R1", "bet_type": "単勝", "combo": "1", "payout": 300},
                {"race_id": "R1", "bet_type": "複勝", "combo": "1", "payout": 130}])
            con.commit()
            con.close()
            base = {c: None for c in live.BET_COLS}
            rows = [dict(base, date="2026-10-18", race_id="R1", strategy=s, bet_type=k, number=n, stake=100, settled=False)
                    for s, k, n in [("fav_win", "単勝", 1), ("fav_place", "複勝", 1), ("value_win", "単勝", 2),
                                    ("value_win", "単勝", 3)]]
            rows.append(dict(base, date=live.now_jst().date().isoformat(), race_id="R2", strategy="fav_win", bet_type="単勝", number=1,
                             stake=100, settled=False))
            live.write_bets(pd.DataFrame(rows))
            b = live.settle()
            self.assertEqual(b["payout"].tolist()[:4], [300, 130, 0, 100])  # scratched horse is refunded
            self.assertFalse(bool(b["settled"].iloc[4]))  # result not in yet
            os.environ.pop("KEIBA_SHARED")


if __name__ == "__main__":
    unittest.main()
