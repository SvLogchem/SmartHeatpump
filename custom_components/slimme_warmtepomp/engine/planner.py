"""Receding-horizon planner: pre-charge the floor, coast through expensive hours.

Every planning round the controller simulates a small family of candidate
plans on the learned house model and applies the first step of the cheapest
one:

* *pre-charge*: raise the water setpoint by ``delta`` K from ``t_start`` until
  a deadline (bedtime or the next rise of the comfort setpoint), so the floor
  is full of heat before the quiet hours and nothing has to be recovered
  hard afterwards;
* *coast*: do not heat for the first ``c`` hours (price peaks, overshoot).

Cost = comfort violations + price-weighted electricity + a "floor charged at
bedtime" term. Everything is expressed in K and K^2 so the weights are
comparable across houses.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .model import HouseModel

DT = 0.25  # hours per planning step
STEP_H = int(1 / DT)

W_LOW = 40.0       # comfort below setpoint-tolerance
W_HIGH = 8.0       # comfort above setpoint+tolerance (stored floor heat cannot be removed)
W_FLOOR = 8.0      # floor not charged at bedtime
W_ENERGY = 1.0
EVENING_MULT = 3.0  # too-cold is worse during the quiet hours
W_HARD = 300.0     # below minimum room temperature


@dataclass
class PlanInput:
    now: datetime
    tr: float
    f: float
    model: HouseModel
    to_fn: Callable[[datetime], float]
    sun_fn: Callable[[datetime], float]
    sp_fn: Callable[[datetime], float]
    price_fn: Callable[[datetime], float]
    s_base_fn: Callable[[datetime, float, float, float], float]
    w_offset: float
    s_min: float
    s_max: float
    bedtime: datetime | None
    quiet_fn: Callable[[datetime], bool]
    quiet_boost: float
    tol_low: float
    tol_high: float
    d_max: float
    bias: float
    hard_min_room: float
    quiet_energy_mult: float = 1.0  # extra "noise cost" of running during the quiet hours
    mode: str = "retour"          # which water temperature the setpoint refers to
    eta: float = 0.4
    horizon_h: float = 14.0
    allow_precharge: bool = True
    allow_coast: bool = True
    gap_cap_fn: Callable[[datetime], float | None] | None = None  # max (setpoint - floor) in K, from the frequency limit


@dataclass
class PlanResult:
    kind: str = "normaal"            # normaal | voorverwarmen | uitlopen
    coast_now: bool = False
    delta_now: float = 0.0
    delta: float = 0.0
    start: datetime | None = None
    coast_hours: float = 0.0
    cost: float = 0.0
    tr_min: float = 0.0
    tr_max: float = 0.0
    tr_check: float | None = None    # predicted room temp one hour after bedtime
    f_bed: float | None = None
    f_target: float | None = None
    reason: str = ""
    trajectory: list = field(default_factory=list)


def plan(inp: PlanInput) -> PlanResult:
    n = int(inp.horizon_h / DT)
    now, m = inp.now, inp.model
    p = m.params
    times = [now + timedelta(hours=DT * i) for i in range(n)]
    to = [inp.to_fn(t) for t in times]
    sun = [inp.sun_fn(t) for t in times]
    sp = [inp.sp_fn(t) for t in times]
    price = [inp.price_fn(t) for t in times]
    quiet = [inp.quiet_fn(t) for t in times]
    gcap = [inp.gap_cap_fn(t) if inp.gap_cap_fn else None for t in times]
    base = [min(max(inp.s_base_fn(times[i], to[i], sun[i], sp[i]), inp.s_min), inp.s_max) for i in range(n)]

    # --- deadline for pre-charging: bedtime or next rise of the comfort setpoint
    bed_idx = None
    if inp.bedtime is not None:
        bi = round((inp.bedtime - now).total_seconds() / 3600.0 / DT)
        if 1 <= bi < n:
            bed_idx = bi
    up_idx = next((i for i in range(1, n) if sp[i] > sp[i - 1] + 0.05), None)
    deadline = min((x for x in (bed_idx, up_idx) if x is not None), default=None)

    # --- floor charge target at bedtime (hold the room through the first 3 quiet hours)
    f_target = None
    if bed_idx is not None:
        idxs = range(bed_idx, min(n, bed_idx + 12))
        f_target = sum(m.floor_equilibrium(sp[i], to[i], 0.0) for i in idxs) / len(idxs) + inp.bias
    check_idx = None if bed_idx is None else min(n - 1, bed_idx + STEP_H)

    ea = math.exp(-p.alpha * DT)
    w_off, s_min, s_max = inp.w_offset, inp.s_min, inp.s_max
    hard = inp.hard_min_room
    retour = inp.mode == "retour"
    avg_price = sum(price) / n
    f_eq_end = m.floor_equilibrium(sp[-1], to[-1], 0.0)

    def simulate(c_steps: int, ts: int, te: int, delta: float, record: bool = False):
        tr, f = inp.tr, inp.f
        cost = 0.0
        tr_min, tr_max = tr, tr
        traj = []
        f_bed = tr_check = None
        for i in range(n):
            q = 0.0
            if i >= c_steps:
                s = base[i]
                if ts <= i < te:
                    s += min(delta, inp.quiet_boost) if quiet[i] else delta
                s = min(max(s, s_min), s_max)
                if gcap[i] is not None:      # frequency limit: never push harder than the pump may run
                    s = min(s, max(base[i], f + gcap[i]))
                if retour:
                    # unit supplies (setpoint + dT) water until the *return* reaches the setpoint
                    if s > f:
                        q_max = min((s + w_off - f) * (1.0 - ea) / DT, m.MAX_CHARGE)
                        q = max(0.0, min(q_max, (s - f) / DT + p.beta * (f - tr)))
                elif s > f:
                    q = min((s - f) * (1.0 - ea) / DT, m.MAX_CHARGE)
            dtr = p.gamma * (f - tr) - p.k * (tr - to[i]) + p.sigma * sun[i] + p.c
            tr_n = tr + dtr * DT
            f_n = f + (q - p.beta * (f - tr)) * DT
            lo, hi = sp[i] - inp.tol_low, sp[i] + inp.tol_high
            if tr_n < lo:
                cost += W_LOW * (EVENING_MULT if quiet[i] else 1.0) * (lo - tr_n) ** 2 * DT
            elif tr_n > hi:
                cost += W_HIGH * (tr_n - hi) ** 2 * DT
            if tr_n < hard:
                cost += W_HARD * (hard - tr_n) ** 2 * DT
            if q > 0.0:
                wv = s + w_off if retour else s
                cop = min(6.0, max(1.5, inp.eta * (wv + 273.15) / max(wv - to[i], 5.0)))
                cost += W_ENERGY * price[i] * (inp.quiet_energy_mult if quiet[i] else 1.0) * q * DT / cop
            if i == bed_idx:
                f_bed = f_n
                cost += W_FLOOR * max(0.0, f_target - f_n) ** 2
            if i == check_idx:
                tr_check = tr_n
            tr, f = tr_n, f_n
            tr_min, tr_max = min(tr_min, tr), max(tr_max, tr)
            if record:
                traj.append((times[i], tr, f, q))
        cost += W_ENERGY * avg_price * max(0.0, f_eq_end - f) / 3.0
        return cost, tr_min, tr_max, f_bed, tr_check, traj

    coasts = [0, 4, 8, 12] if inp.allow_coast else [0]
    options: list[tuple[int, int, int, float]] = []  # (c_steps, ts, te, delta)
    deltas = []
    d = 1.0
    while inp.allow_precharge and d <= inp.d_max + 1e-9:
        deltas.append(d)
        d += 1.0
    for c in coasts:
        options.append((c, 0, 0, 0.0))
        if deadline is not None:
            for ts in range(0, deadline, STEP_H):
                if c > ts:
                    continue
                for dl in deltas:
                    options.append((c, ts, deadline, dl))

    best = None
    for opt in options:
        res = simulate(*opt)
        if best is None or res[0] < best[1][0] - 1e-9:
            best = (opt, res)
    (c, ts, te, delta), (cost, tr_min, tr_max, f_bed, tr_check, _) = best
    _, _, _, _, _, traj = simulate(c, ts, te, delta, record=True)

    out = PlanResult(cost=cost, tr_min=tr_min, tr_max=tr_max, tr_check=tr_check, f_bed=f_bed,
                     f_target=f_target, trajectory=traj)
    out.coast_now = c > 0
    out.coast_hours = c * DT
    if delta > 0:
        out.kind = "voorverwarmen"
        out.delta = delta
        out.start = times[ts]
        out.delta_now = delta if (c == 0 and ts == 0) else 0.0
        out.reason = f"+{delta:.0f} K vanaf {times[ts]:%H:%M}"
    elif c > 0:
        out.kind = "uitlopen"
        out.reason = f"uitlopen {out.coast_hours:.0f} u"
    return out
