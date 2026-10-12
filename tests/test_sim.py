import unittest

import numpy as np

from sim.course import kyoto_turf_3000
from sim.horse import Horse
from sim.race import simulate, probabilities


def field(n=10, **over):
    return [Horse(name=f"H{i}", speed=17.2, stamina=1.0, kick=0.5, style=0.4, gate=i + 1, **over)
            for i in range(n)]


class CourseTest(unittest.TestCase):
    def test_finish_is_at_lap_zero(self):
        c = kyoto_turf_3000()
        self.assertAlmostEqual(float(c.lap_u(c.distance)), 0.0, places=6)

    def test_hill_is_climbed_twice(self):
        c = kyoto_turf_3000()
        s = np.arange(0, c.distance, 1.0)
        h = c.elevation(s)
        peaks = np.sum((h[1:-1] > h[:-2]) & (h[1:-1] >= h[2:]) & (h[1:-1] > 4.0))
        self.assertEqual(peaks, 2)

    def test_outline_is_closed_loop(self):
        x, y = kyoto_turf_3000().outline(0.0, step=1.0)
        self.assertLess(np.hypot(np.diff(x), np.diff(y)).max(), 1.5)


class RaceTest(unittest.TestCase):
    def test_everyone_finishes_in_realistic_time(self):
        r = simulate(kyoto_turf_3000(), field(), n=50, seed=0)
        self.assertTrue(np.isfinite(r.finish_time).all())
        self.assertTrue(175 < r.finish_time.min() < 195)

    def test_probabilities_sum(self):
        p = probabilities(simulate(kyoto_turf_3000(), field(), n=100, seed=0))
        self.assertAlmostEqual(p["win"].sum(), 1.0)
        self.assertAlmostEqual(p["place"].sum(), 3.0)

    def test_better_horse_wins_more(self):
        horses = field(8)
        horses[3].speed = 17.6
        horses[3].stamina = 1.04
        p = probabilities(simulate(kyoto_turf_3000(), horses, n=300, seed=1))
        self.assertEqual(int(np.argmax(p["win"])), 3)

    def test_seed_is_reproducible(self):
        a = simulate(kyoto_turf_3000(), field(), n=20, seed=5)
        b = simulate(kyoto_turf_3000(), field(), n=20, seed=5)
        np.testing.assert_array_equal(a.order, b.order)


if __name__ == "__main__":
    unittest.main()
