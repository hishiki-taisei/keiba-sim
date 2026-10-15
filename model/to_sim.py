"""Turn a race's feature rows into simulator horses.

The win model's score sets each horse's top speed. Running style, finishing
kick and stamina come straight from the horse's own history, so the simulator
can play out pace, position and the long-distance grind on top of that:

    speed   = 17.2 + k_speed * (score - field mean score)      [m/s]
    stamina = 1.0  + k_stamina * (distance slope, in rating % per doubling) + k_energy * score
    kick    = logistic(kick5)       (last-600m edge over the field, seconds)
    style   = early_pos5            (0 = leads at the first corner, 1 = last)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sim.course import Course, kyoto_turf_3000
from sim.horse import Horse
from sim.race import probabilities, simulate


@dataclass
class SimParams:
    k_speed: float = 0.12      # m/s per unit of win-model score
    k_stamina: float = 0.0     # stamina per unit of distance slope
    k_energy: float = 0.0      # stamina per unit of win-model score


def horses(rows: pd.DataFrame, score: np.ndarray, prm: SimParams) -> list[Horse]:
    sc = score - score.mean()
    out = []
    for (_, r), s in zip(rows.iterrows(), sc):
        out.append(Horse(
            name=r["horse_name"],
            speed=round(float(17.2 + prm.k_speed * s), 3),
            stamina=round(float(np.clip(1.0 + prm.k_stamina * r["slope"] + prm.k_energy * s, 0.85, 1.15)), 3),
            kick=round(float(1 / (1 + np.exp(-2.0 * r["kick5"]))), 3),
            style=round(float(np.clip(r["early_pos5"], 0, 1)), 3),
            gate=int(r["number"]),
        ))
    return out


def course_for(distance: float) -> Course:
    """A Kyoto-like oval for any distance.

    Kyoto's own layout is used for 3000m. For other distances the lap length is
    adjusted (keeping Kyoto's proportions and hill) so the start sits early on a
    straight, as it does on real JRA turf courses; starting in a bend would hand
    the inside gates an unrealistic edge.
    """
    k = kyoto_turf_3000()
    if distance == k.distance:
        return k
    best = None
    for lap in np.arange(1600.0, 2300.0, 5.0):
        straight = k.straight / k.lap * lap
        b = (lap - 2 * straight) / 2
        u = (-distance) % lap
        for s0 in (b, 2 * b + straight):  # start of the back or home straight
            off = u - s0
            if 0.15 * straight <= off <= 0.6 * straight:
                score = abs(lap - k.lap)
                if best is None or score < best[0]:
                    best = (score, lap, straight, b)
    _, lap, straight, b = best
    bend34 = b + straight
    return Course(name=f"芝{int(distance)}m（京都型）", lap=lap, straight=straight, distance=float(distance),
                  hill_height=k.hill_height, hill_start=bend34 - 150.0, hill_peak=bend34 + 0.35 * b,
                  hill_end=bend34 + b)


def race_probs(rows: pd.DataFrame, score: np.ndarray, prm: SimParams, n: int = 300, seed: int = 0) -> dict:
    hs = horses(rows, score, prm)
    res = simulate(course_for(rows["distance"].iloc[0]), hs, n=n, seed=seed)
    return probabilities(res)
