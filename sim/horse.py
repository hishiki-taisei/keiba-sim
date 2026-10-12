from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Horse:
    """Ability parameters of one runner.

    speed:   top cruising speed in m/s (typical G1 stayer ~17.0-17.6)
    stamina: energy budget multiplier (1.0 = just enough to run 3000m at pace)
    kick:    finishing burst, 0..1
    style:   running style, 0 = front runner (逃げ) ... 1 = closer (追込)
    gate:    post position (1 = inside)
    """
    name: str
    speed: float
    stamina: float
    kick: float
    style: float
    gate: int
    odds: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)
