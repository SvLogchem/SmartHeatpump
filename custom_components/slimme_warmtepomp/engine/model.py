"""Self-learning two-node house model: floor (screed) + room.

    dTr/dt = gamma*(F - Tr) - k*(Tr - To) + sigma*sun + c        (room)
    dF/dt  = alpha*max(0, W - F)*heating - beta*(F - Tr)         (floor)

F is the floor temperature, measured by a floor sensor or, by default, by
the return-water temperature. W is the supply water temperature while the
compressor heats. Both equations are linear in their parameters, so they are
learned online with a regularised, forgetting least-squares fit (see
``RidgeEW``) from 90-minute windows of measurements.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .regression import RidgeEW

N0 = 30.0  # strength of the prior, in "windows" of typical excitation

ROOM_PRIOR = [0.30, 0.05, 0.40, 0.0]  # gamma, k, sigma, c
ROOM_LO = [0.03, 0.004, 0.0, -0.3]
ROOM_HI = [1.20, 0.30, 3.0, 0.6]
ROOM_TYP2 = [9.0, 225.0, 0.1, 1.0]  # typical x^2 per feature -> prior strength

FLOOR_PRIOR = [0.9, 0.12]  # alpha, beta
FLOOR_LO = [0.08, 0.02]
FLOOR_HI = [6.0, 0.9]
FLOOR_TYP2 = [9.0, 9.0]


@dataclass
class Params:
    gamma: float
    k: float
    sigma: float
    c: float
    alpha: float
    beta: float


class HouseModel:
    MAX_CHARGE = 3.0  # K/h, upper limit on how fast the compressor can charge the floor

    def __init__(self) -> None:
        self.room = RidgeEW(ROOM_PRIOR, [N0 * t for t in ROOM_TYP2], ROOM_LO, ROOM_HI)
        self.floor = RidgeEW(FLOOR_PRIOR, [N0 * t for t in FLOOR_TYP2], FLOOR_LO, FLOOR_HI)
        self._cache: Params | None = None
        self.windows_room = 0
        self.windows_floor = 0
        # fast disturbance observer: absorbs what the slow regression cannot
        # (model-structure error, unmodelled gains) so predictions stay unbiased
        self.c_adapt = 0.0

    # ------------------------------------------------------------ learning
    def reset(self) -> None:
        self.room.reset()
        self.floor.reset()
        self._cache = None
        self.windows_room = self.windows_floor = 0
        self.c_adapt = 0.0

    def learn_room(self, dtr_dt: float, f_minus_tr: float, tr_minus_to: float, sun: float) -> None:
        self.room.update([f_minus_tr, -tr_minus_to, sun, 1.0], dtr_dt - self.c_adapt)
        self.windows_room += 1
        self._cache = None
        p = self.params
        pred = p.gamma * f_minus_tr - p.k * tr_minus_to + p.sigma * sun + p.c
        resid = dtr_dt - pred
        self.c_adapt = min(0.4, max(-0.4, self.c_adapt + 0.04 * resid))
        self._cache = None

    def learn_floor(self, df_dt: float, heat_drive: float, f_minus_tr: float) -> None:
        self.floor.update([heat_drive, -f_minus_tr], df_dt)
        self.windows_floor += 1
        self._cache = None

    @property
    def params(self) -> Params:
        if self._cache is None:
            g, k, s, c = self.room.solve()
            a, b = self.floor.solve()
            self._cache = Params(g, k, s, c + self.c_adapt, a, b)
        return self._cache

    def confidence(self) -> float:
        """Trust in the parameters that matter for planning (gamma, k, alpha, beta).

        sigma (sun gain) and c (internal gains) are excitation-poor by nature and
        stay regularised towards their priors, so they do not gate the model.
        """
        return min(self.room.confidence([0, 1]), self.floor.confidence([0, 1]))

    def plausible(self) -> bool:
        """Guard against a degenerate fit (parameters stuck on a bound, absurd ratios)."""
        p = self.params
        ratio = p.k / p.gamma
        if not 0.03 <= ratio <= 1.5:
            return False
        at_bound = (
            p.gamma >= ROOM_HI[0] * 0.98 or p.gamma <= ROOM_LO[0] * 1.02
            or p.k >= ROOM_HI[1] * 0.98 or p.k <= ROOM_LO[1] * 1.02
        )
        return not at_bound

    # ------------------------------------------------------------ physics
    def step(self, tr: float, f: float, to: float, sun: float, w: float | None, dt: float):
        """Advance (room, floor) by dt hours. ``w`` is supply water temp or None (not heating)."""
        p = self.params
        q = 0.0
        if w is not None and w > f:
            # exact exponential approach avoids instability for large alpha*dt
            q = (w - f) * (1.0 - math.exp(-p.alpha * dt)) / dt
            q = min(q, self.MAX_CHARGE)
        dtr = p.gamma * (f - tr) - p.k * (tr - to) + p.sigma * sun + p.c
        df = q - p.beta * (f - tr)
        return tr + dtr * dt, f + df * dt, q

    def floor_equilibrium(self, sp: float, to: float, sun: float) -> float:
        """Floor temperature that holds the room at ``sp`` in steady state."""
        p = self.params
        return ((p.gamma + p.k) * sp - p.k * to - p.sigma * sun - p.c) / p.gamma

    def water_equilibrium(self, sp: float, to: float, sun: float) -> float:
        """Supply water temperature that holds the room at ``sp`` in steady state."""
        p = self.params
        f = self.floor_equilibrium(sp, to, sun)
        return f + (p.beta / p.alpha) * (f - sp)

    # ------------------------------------------------------------ storage
    def to_dict(self) -> dict:
        return {
            "room": self.room.to_dict(),
            "floor": self.floor.to_dict(),
            "windows_room": self.windows_room,
            "windows_floor": self.windows_floor,
            "c_adapt": self.c_adapt,
        }

    def from_dict(self, d: dict) -> None:
        self.room.from_dict(d.get("room", {}))
        self.floor.from_dict(d.get("floor", {}))
        self.windows_room = int(d.get("windows_room", 0))
        self.windows_floor = int(d.get("windows_floor", 0))
        self.c_adapt = float(d.get("c_adapt", 0.0))
        self._cache = None
