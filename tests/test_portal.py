import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "portal"))
import build  # noqa: E402
import build_field  # noqa: E402  (put on the path by portal/build.py)


class Frames(unittest.TestCase):
    def test_jra_frames(self):
        self.assertEqual([build.frame_of(n, 18) for n in range(1, 19)],
                         [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7, 8, 8, 8])
        self.assertEqual([build.frame_of(n, 12) for n in range(1, 13)],
                         [1, 2, 3, 4, 5, 5, 6, 6, 7, 7, 8, 8])
        self.assertEqual([build.frame_of(n, 8) for n in range(1, 9)], list(range(1, 9)))
        self.assertIsNone(build.frame_of(None, 18))


class Style(unittest.TestCase):
    def test_site_and_replay_use_the_same_cut_offs(self):
        # (first corner position, field) -> label, for both the per-run label and the replay's word
        for passing, field, word in [("1-1-1-1", 16, "逃げ"), ("4-4-3-2", 16, "先行"),
                                     ("9-9-8-6", 16, "差し"), ("15-15-12-8", 16, "追込")]:
            self.assertEqual(build.style_of(passing, field), word)
            self.assertEqual(build_field.style_word((int(passing.split("-")[0]) - 1) / (field - 1)), word)


if __name__ == "__main__":
    unittest.main()
