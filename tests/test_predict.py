import unittest

import numpy as np
import pandas as pd

from predict import features
from predict.model import ConditionalLogit, race_softmax


class ConditionalLogitTest(unittest.TestCase):
    def test_softmax_sums_to_one_per_race(self):
        p = race_softmax(np.array([0.0, 1.0, 2.0, 5.0, -1.0]), np.array(["a", "a", "a", "b", "b"]))
        self.assertAlmostEqual(p[:3].sum(), 1.0)
        self.assertAlmostEqual(p[3:].sum(), 1.0)

    def test_recovers_true_weights(self):
        rng = np.random.default_rng(0)
        races, size, w_true = 3000, 10, np.array([1.0, -0.5])
        X = rng.normal(size=(races * size, 2))
        rid = np.repeat(np.arange(races), size)
        p = race_softmax(X @ w_true, rid)
        won = np.zeros(len(X))
        for r in range(races):
            won[r * size + rng.choice(size, p=p[r * size:(r + 1) * size])] = 1
        m = ConditionalLogit(["a", "b"], l2=0.0).fit(X, rid, won)
        np.testing.assert_allclose(m.coef / m.scale, w_true, atol=0.1)


class NoLeakTest(unittest.TestCase):
    def runners(self, last_winner):
        rows = []
        for k, date in enumerate(["2024-01-06", "2024-02-03", "2024-03-02"]):
            for n, horse in enumerate(["A", "B", "C"], 1):
                finish = n if k < 2 else (1 if horse == last_winner else n + 1)
                rows.append(dict(race_id=f"r{k}", date=pd.Timestamp(date), venue="京都", race_name="", grade=None,
                                 surface="芝", distance=2000, going="良", n_runners=3, field=3, number=n,
                                 finish=min(finish, 3), finish_raw=str(finish), frame=n, horse_id=horse,
                                 horse_name=horse, sex="牡", age=3, weight_carried=57.0, jockey_id=f"j{horse}",
                                 jockey_name=horse, time_sec=120.0 + finish, passing="1-1", last3f=34.0,
                                 odds=3.0, popularity=n, body_weight=480, body_weight_diff=0,
                                 trainer_id="t", prize=np.nan))
        return pd.DataFrame(rows)

    def test_features_ignore_same_and_later_races(self):
        std = pd.DataFrame({"venue": ["京都"], "surface": ["芝"], "distance": [2000], "gg": ["fast"],
                            "t_mean": [121.0], "t_std": [1.0], "t_n": [30]})
        a = features.build(self.runners("A"), std)
        b = features.build(self.runners("C"), std)
        pd.testing.assert_frame_equal(a[features.FEATURES], b[features.FEATURES])


if __name__ == "__main__":
    unittest.main()
