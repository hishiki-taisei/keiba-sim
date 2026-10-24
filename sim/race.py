"""Vectorised race simulation.

Every runner is an agent with a speed, an energy reserve and a lane. The
race is stepped in fixed time increments for many races at once
(arrays of shape [n_races, n_horses]) so that thousands of Monte Carlo
runs are cheap. Mechanics:

* pace:     each race draws a pace; runners hold a speed around it that
            depends on running style, then spurt near the end
* energy:   drains with (speed / reference)^3, faster uphill; an empty
            tank caps speed well below the top speed
* hill:     slows runners on the climb and helps on the descent
* bends:    running wide costs ground (radius grows with lane)
* traffic:  a runner closing on a slower horse in its lane is held up and
            tries to switch out; otherwise it drifts toward the rail
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .course import Course, LANE_WIDTH
from .horse import Horse

V_REF = 16.4         # reference pace speed for the energy model (m/s)
ACCEL = 1.0          # m/s^2
DECEL = 0.6          # m/s^2
GAP = 2.5            # metres: closer than this to a horse ahead means held up
FORM_SD = 0.03       # day-to-day variation of speed and stamina
PACE_SD = 0.015      # race-to-race variation of the pace
DRAFT_SAVING = 0.02  # energy saved per step while tucked in behind a runner
EARLY_STYLE = 0.015  # early-pace difference between a front runner and a closer
EARLY_DRIFT = 0.6    # lanes per second runners move toward the rail after the start


@dataclass
class RaceResult:
    order: np.ndarray        # [n_races, n_horses] horse indices, winner first
    finish_time: np.ndarray  # [n_races, n_horses]
    trace: dict | None = None


def _params(horses: list[Horse]):
    f = lambda k: np.array([getattr(h, k) for h in horses], dtype=float)
    return f("speed"), f("stamina"), f("kick"), f("style"), f("gate")


def simulate(course: Course, horses: list[Horse], n: int = 1000, dt: float = 0.25,
             seed: int | None = None, trace_every: float | None = None) -> RaceResult:
    rng = np.random.default_rng(seed)
    H = len(horses)
    D = course.distance
    speed, stamina, kick, style, gate = _params(horses)

    form = rng.normal(1.0, FORM_SD, (n, H))
    v_top = speed * form
    pace = V_REF * rng.normal(1.0, PACE_SD, (n, 1))
    energy0 = (D / V_REF) * stamina * rng.normal(1.0, FORM_SD, (n, H))
    energy = energy0.copy()
    # spurt starts earlier for horses with stamina in hand, and for closers
    spurt_at = 450 + 250 * (stamina - 1.0) / 0.1 + 150 * style
    spurt_at = np.clip(spurt_at + rng.normal(0, 80, (n, H)), 300, 900)

    s = np.zeros((n, H))
    v = np.full((n, H), 2.0)
    lane = np.broadcast_to((gate - 1) * 0.5, (n, H)).copy()
    finished = np.zeros((n, H), dtype=bool)
    t_fin = np.full((n, H), np.inf)

    rec = [] if trace_every else None
    next_rec = 0.0
    t = 0.0
    while not finished.all() and t < 400:
        remaining = D - s
        grade = course.grade(s)
        bend = course.in_bend(s)

        # target speed by phase
        early = s < 500
        cruise = pace * (1 + 0.004 * (0.5 - style))
        target = np.where(early, pace * (1 + EARLY_STYLE * (0.5 - style)), cruise)
        spurt = remaining < spurt_at
        target = np.where(spurt, v_top * (1 + 0.04 * kick), target)
        target = np.minimum(target, v_top * (1 + 0.04 * kick))
        target = target - 25.0 * grade              # ~ -0.3 m/s on a 1.2% climb
        tired = energy <= 0
        target = np.where(tired, np.minimum(target, 0.90 * v_top), target)

        # traffic: nearest horse ahead in the same lane
        ds = s[:, None, :] - s[:, :, None]                     # [n, i, j] = s_j - s_i
        same = np.abs(lane[:, None, :] - lane[:, :, None]) < 0.8
        ahead = (ds > 0) & (ds < GAP) & same & ~finished[:, None, :]
        v_ahead = np.where(ahead, v[:, None, :], np.inf).min(axis=2)
        blocked = (v_ahead < target) & ~finished
        target = np.where(blocked, np.minimum(target, v_ahead), target)

        # lanes: switch out when blocked, otherwise ease toward the rail
        # (never in the home straight spurt, where horses fan out instead)
        lane = np.where(blocked, lane + 1.0 * dt, lane)
        drift = ~blocked & ~spurt
        lane = np.where(drift, np.maximum(lane - (EARLY_DRIFT if t < 25 else 0.2) * dt, 0.0), lane)
        lane = np.where(spurt & ~blocked, lane + 0.05 * dt, lane)

        accel = ACCEL * (3.0 if t < 8 else 1.0)
        dv = np.clip(target - v, -DECEL * dt, accel * dt)
        v = np.where(finished, v, v + dv)

        # energy drain
        cost = (v / V_REF) ** 3 * (1 + 40.0 * np.maximum(grade, 0)) * dt
        # sitting in behind other runners saves energy (drafting)
        near = np.abs(lane[:, None, :] - lane[:, :, None]) < 1.5
        drafting = ((ds > 0.5) & (ds < 6.0) & near).any(axis=2)
        cost = np.where(drafting & ~spurt, cost * (1 - DRAFT_SAVING), cost)
        energy = np.where(finished, energy, energy - cost)

        # ground covered: running wide in a bend loses distance
        progress = v * dt
        progress = np.where(bend, progress * course.radius / (course.radius + lane * LANE_WIDTH), progress)
        new_s = s + np.where(finished, 0.0, progress)

        crossing = (new_s >= D) & ~finished
        frac = np.where(crossing, (D - s) / np.maximum(new_s - s, 1e-9), 0.0)
        t_fin = np.where(crossing, t + frac * dt, t_fin)
        finished |= crossing
        s = np.minimum(new_s, D)
        t += dt

        if rec is not None and t >= next_rec:
            rec.append((t, s[0].copy(), lane[0].copy(), v[0].copy(), energy[0] / energy0[0]))
            next_rec += trace_every

    order = np.argsort(t_fin, axis=1)
    trace = _build_trace(course, rec) if rec is not None else None
    return RaceResult(order=order, finish_time=t_fin, trace=trace)


def _build_trace(course: Course, rec) -> dict:
    frames = []
    for t, s, lane, v, e in rec:
        x, y = course.xy(s, lane)
        frames.append({
            "t": round(float(t), 2),
            "x": np.round(x, 1).tolist(),
            "y": np.round(y, 1).tolist(),
            "s": np.round(s, 1).tolist(),
            "v": np.round(v, 2).tolist(),
            "e": np.round(np.clip(e, 0, 1), 3).tolist(),
        })
    return {"frames": frames}


def probabilities(result: RaceResult, places: int = 3) -> dict:
    n, H = result.order.shape
    win = np.bincount(result.order[:, 0], minlength=H) / n
    top = np.zeros(H)
    for k in range(min(places, H)):
        top += np.bincount(result.order[:, k], minlength=H)
    rank = np.empty_like(result.order)
    rank[np.arange(n)[:, None], result.order] = np.arange(H)
    return {
        "win": win,
        "place": top / n,
        "mean_rank": rank.mean(axis=0) + 1,
        "mean_time": np.where(np.isfinite(result.finish_time), result.finish_time, np.nan).mean(axis=0),
    }
