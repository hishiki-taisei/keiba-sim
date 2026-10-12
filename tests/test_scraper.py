import gzip
import unittest
from pathlib import Path

from scraper import parse

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return gzip.decompress((FIX / name).read_bytes()).decode("euc-jp", "replace")


class RaceParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = parse.race(load("race_202408050611.html.gz"), "202408050611")

    def test_race_info(self):
        r = self.d["race"]
        self.assertEqual(r["date"], "2024-10-20")
        self.assertEqual((r["venue"], r["surface"], r["distance"], r["direction"]), ("京都", "芝", 3000, "右"))
        self.assertEqual(r["grade"], "G1")
        self.assertEqual(r["going"], "良")
        self.assertEqual(r["n_runners"], 18)
        self.assertAlmostEqual(sum(float(x) for x in r["laps"].split(" - ")), 184.1, places=1)

    def test_winner(self):
        w = self.d["results"][0]
        self.assertEqual((w["finish"], w["number"], w["horse_name"]), (1, 13, "アーバンシック"))
        self.assertEqual(w["horse_id"], "2021105436")
        self.assertEqual(w["jockey_id"], "05339")
        self.assertEqual(w["time_sec"], 184.1)
        self.assertEqual((w["odds"], w["popularity"], w["last3f"]), (3.7, 2, 35.6))
        self.assertEqual((w["body_weight"], w["body_weight_diff"]), (510, 0))

    def test_payouts(self):
        p = {(x["bet_type"], x["combo"]): x["payout"] for x in self.d["payouts"]}
        self.assertEqual(p[("単勝", "13")], 370)
        self.assertEqual(p[("三連単", "13-16-17")], 19390)
        self.assertEqual(sum(1 for k in p if k[0] == "複勝"), 3)


class OtherPagesTest(unittest.TestCase):
    def test_pedigree(self):
        p = parse.pedigree(load("ped_2021105898.html.gz"), "2021105898")
        self.assertEqual((p["sire"], p["dam"], p["damsire"]), ("スワーヴリチャード", "ロカ", "ハービンジャー"))

    def test_race_list_keeps_jra_only(self):
        ids = parse.race_ids(load("list_20241020.html.gz"))
        self.assertEqual(len(ids), 36)
        self.assertTrue(all(i[4:6] in parse.VENUES for i in ids))

    def test_time(self):
        self.assertEqual(parse.time_to_sec("3:04.1"), 184.1)
        self.assertEqual(parse.time_to_sec("58.9"), 58.9)


if __name__ == "__main__":
    unittest.main()
