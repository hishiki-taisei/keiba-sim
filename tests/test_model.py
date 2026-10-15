import unittest

import numpy as np
import pandas as pd

from model.gbdt import GBDT
from model.logit import Logit


def races(n_races=400, field=8, seed=0):
    """Synthetic races where the winner is driven by a threshold on x."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        x = rng.normal(size=field)
        strength = np.where(x > 0.5, 2.0, 0.0) + rng.gumbel(size=field)
        winner = strength.argmax()
        for i in range(field):
            rows.append({"race_id": f"r{r}", "x": x[i], "finish": 1 if i == winner else 2})
    return pd.DataFrame(rows)


class ModelTest(unittest.TestCase):
    def test_gbdt_beats_linear_on_threshold(self):
        tr, te = races(seed=0), races(seed=1)
        ll = lambda p, d: -np.log(p[d["finish"].to_numpy() == 1]).mean()
        gb = GBDT(["x"], rounds=150, lr=0.1, depth=2, min_hess=1.0).fit(tr)
        lin = Logit(["x"]).fit(tr)
        self.assertLess(ll(gb.predict(te), te), ll(lin.predict(te), te))
        self.assertLess(ll(gb.predict(te), te), np.log(8))


if __name__ == "__main__":
    unittest.main()
