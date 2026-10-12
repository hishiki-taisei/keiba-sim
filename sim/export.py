"""Write simulation output as JSON for the web app."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .course import Course
from .horse import Horse
from .race import simulate, probabilities


def build(course: Course, horses: list[Horse], n: int = 2000, seed: int = 0,
          title: str = "", note: str = "") -> dict:
    p = probabilities(simulate(course, horses, n=n, seed=seed))
    replay = simulate(course, horses, n=1, seed=seed + 1, trace_every=0.5)
    rail_x, rail_y = course.outline(0.0)
    outer_x, outer_y = course.outline(16.0)
    fin_x, fin_y = course.xy(np.full(2, course.distance), np.array([0.0, 16.0]))
    return {
        "title": title,
        "note": note,
        "course": {
            "name": course.name,
            "distance": course.distance,
            "rail": [np.round(rail_x, 1).tolist(), np.round(rail_y, 1).tolist()],
            "outer": [np.round(outer_x, 1).tolist(), np.round(outer_y, 1).tolist()],
            "finish": [np.round(fin_x, 1).tolist(), np.round(fin_y, 1).tolist()],
        },
        "simulations": n,
        "horses": [
            {**h.to_dict(),
             "win": round(float(p["win"][i]), 4),
             "place": round(float(p["place"][i]), 4),
             "mean_rank": round(float(p["mean_rank"][i]), 2)}
            for i, h in enumerate(horses)
        ],
        "replay": {
            "order": replay.order[0].tolist(),
            "finish_time": np.round(replay.finish_time[0], 2).tolist(),
            **replay.trace,
        },
    }


def write(data: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
