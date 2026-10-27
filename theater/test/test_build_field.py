import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_field  # noqa: E402


def run(finish, field, passing, distance=2400, going="良", last3f=35.0, med3f=35.5, surface="芝"):
    return {"finish": finish, "field": field, "passing": passing, "distance": distance, "going": going,
            "last3f": last3f, "med3f": med3f, "surface": surface}


class Features(unittest.TestCase):
    def test_front_runner_who_quickens(self):
        runs = [run(1, 16, "1-1-1-1", last3f=34.5) for _ in range(5)]
        f = build_field.features(runs)
        self.assertLess(f["style"], 0.15)
        self.assertGreater(f["kick"], 0.7)

    def test_closer_who_makes_ground(self):
        runs = [run(3, 16, "15-15-10-6") for _ in range(5)]
        f = build_field.features(runs)
        self.assertGreater(f["style"], 0.75)
        self.assertGreater(f["move"], 0.5)

    def test_stays_better_than_it_sprints(self):
        runs = [run(1, 12, "5-5", distance=2600) for _ in range(3)] + [run(10, 12, "5-5", distance=1600) for _ in range(3)]
        self.assertGreater(build_field.features(runs)["stamina"], 0.3)

    def test_kick_uses_the_race_surface(self):
        runs = [run(1, 12, "5-5", surface="ダ", last3f=36.0, med3f=37.0)]
        self.assertEqual(build_field.features(runs, "芝")["kick"], 0.0)
        self.assertGreater(build_field.features(runs, "ダ")["kick"], 0.0)

    def test_sections_match_engine(self):
        self.assertEqual(build_field.sections(3000), (1000, 2000, 2400))
        self.assertEqual(build_field.sections(1200), (420.0, 420.0, 600))


class Predictions(unittest.TestCase):
    def test_reads_predict_output_and_old_csv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            new = Path(d) / "new.csv"
            new.write_text("race_id,horse_id,horse_name,jockey_name,number,p_ability,odds,p_market,p_win,model\n"
                           "1,9,アルファ,武豊,3,0.2,,,0.25,gbdt\n1,8,ベータ,,,0.8,,,0.75,gbdt\n", encoding="utf-8")
            e = build_field.entries_from_csv(str(new), "ignored")
            self.assertEqual([(x["name"], x["jockey"], x["gate"], x["p"]) for x in e],
                             [("アルファ", "武豊", 3, 0.25), ("ベータ", "", None, 0.75)])
            old = Path(d) / "old.csv"
            old.write_text("馬,騎手,勝率(モデル)\nアルファ,武豊,0.3\n", encoding="utf-8")
            self.assertEqual(build_field.entries_from_csv(str(old), "勝率(モデル)")[0]["p"], 0.3)


if __name__ == "__main__":
    unittest.main()
