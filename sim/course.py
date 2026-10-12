"""Course geometry.

The course is modelled as a stadium shape: two straights joined by two
semicircular bends. Distances along the rail use a "lap coordinate" u that
is 0 at the finish line and increases in the running direction.

Running order of segments from the finish line (right-handed / clockwise):
  0: bend 1-2 (left side)
  1: back straight (top, left -> right)
  2: bend 3-4 (right side, contains the hill)
  3: home straight (bottom, right -> left), ends at the finish line
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

LANE_WIDTH = 1.2  # metres of lateral offset per lane


@dataclass(frozen=True)
class Course:
    name: str
    lap: float          # rail length of one lap (m)
    straight: float     # home straight length (m); back straight is the same
    distance: float     # race distance (m)
    hill_height: float  # peak height of the hill on bend 3-4 (m)
    hill_start: float   # lap coordinate where the climb starts
    hill_peak: float    # lap coordinate of the summit
    hill_end: float     # lap coordinate where the descent ends

    @property
    def radius(self) -> float:
        return (self.lap - 2 * self.straight) / (2 * math.pi)

    @property
    def bend(self) -> float:
        return math.pi * self.radius

    @property
    def start_u(self) -> float:
        return (-self.distance) % self.lap

    def lap_u(self, s):
        """Lap coordinate for distance run s (scalar or array)."""
        return (self.start_u + np.asarray(s, dtype=float)) % self.lap

    def in_bend(self, s):
        u = self.lap_u(s)
        b, L = self.bend, self.straight
        return (u < b) | ((u >= b + L) & (u < 2 * b + L))

    def elevation(self, s):
        u = self.lap_u(s)
        up = (u - self.hill_start) / (self.hill_peak - self.hill_start)
        down = (self.hill_end - u) / (self.hill_end - self.hill_peak)
        h = np.where((u >= self.hill_start) & (u < self.hill_peak), up,
                     np.where((u >= self.hill_peak) & (u < self.hill_end), down, 0.0))
        return self.hill_height * h

    def grade(self, s, ds: float = 5.0):
        """Rise over run at s (positive = uphill)."""
        s = np.asarray(s, dtype=float)
        return (self.elevation(s + ds) - self.elevation(s - ds)) / (2 * ds)

    def xy(self, s, lane):
        """Plan-view coordinates (m) for distance run s at lateral lane."""
        u = np.atleast_1d(self.lap_u(s))
        lane = np.broadcast_to(np.asarray(lane, dtype=float), u.shape)
        R, L, b = self.radius, self.straight, self.bend
        r = R + lane * LANE_WIDTH
        x = np.empty_like(u)
        y = np.empty_like(u)

        m = u < b  # bend 1-2, centre (-L/2, 0), bottom -> left -> top
        th = -math.pi / 2 - (u[m] / b) * math.pi
        x[m] = -L / 2 + r[m] * np.cos(th)
        y[m] = r[m] * np.sin(th)

        m = (u >= b) & (u < b + L)  # back straight
        x[m] = -L / 2 + (u[m] - b)
        y[m] = r[m]

        m = (u >= b + L) & (u < 2 * b + L)  # bend 3-4, centre (L/2, 0), top -> right -> bottom
        th = math.pi / 2 - ((u[m] - b - L) / b) * math.pi
        x[m] = L / 2 + r[m] * np.cos(th)
        y[m] = r[m] * np.sin(th)

        m = u >= 2 * b + L  # home straight
        x[m] = L / 2 - (u[m] - 2 * b - L)
        y[m] = -r[m]
        return x, y

    def outline(self, lane: float, step: float = 10.0):
        u = np.arange(0.0, self.lap + step, step)
        # convert lap coordinate back to a distance-run value
        s = (u - self.start_u) % self.lap
        return self.xy(s, lane)


def kyoto_turf_3000() -> Course:
    """Kyoto turf outer course, 3000m (Kikuka Sho).

    Approximate public figures: outer lap ~1894m, home straight ~404m,
    hill of ~4.3m on the 3rd corner. Two full passes of the hill in 3000m.
    """
    lap, straight = 1894.3, 403.7
    b = (lap - 2 * straight) / 2
    bend34 = b + straight  # lap coordinate where bend 3-4 starts
    return Course(
        name="京都 芝3000m（外回り）",
        lap=lap,
        straight=straight,
        distance=3000.0,
        hill_height=4.3,
        hill_start=bend34 - 150.0,
        hill_peak=bend34 + 0.35 * b,
        hill_end=bend34 + b,
    )
