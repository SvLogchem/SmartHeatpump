"""Synthetic floor-heating house + heat pump used to test the control loop.

The "real" house deliberately has a *three*-node floor (pipe layer, screed,
room) while the controller learns a *two*-node model, so the tests are not
circular. Sensors are quantised to 0.1 K and noisy; setpoints are integers
(like a Tuya heat pump).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.controller import Inputs, SmartController
from engine.solar import sun_gain

TZ = ZoneInfo("Europe/Amsterdam")
LAT, LON = 52.37, 4.9


@dataclass
class HouseParams:
    a1: float = 0.8    # pipe layer <- water
    a2: float = 0.8    # pipe -> screed
    a3: float = 0.4    # screed <- pipe
    a4: float = 0.12   # screed -> room
    g1: float = 0.12   # room <- screed
    g2: float = 0.04   # room <- pipe layer
    k: float = 0.06    # loss to outside
    sigma: float = 0.5
    c: float = 0.02


class Weather:
    def __init__(self, seed: int, start: datetime, mean=6.0, amp=2.5):
        self.r = random.Random(seed)
        self.ph = [self.r.uniform(0, 6.28) for _ in range(3)]
        self.mean = mean
        self.amp = amp
        self.start = start
        self.cloud_ph = self.r.uniform(0, 6.28)
        self.err = 0.0

    def temp(self, t: datetime) -> float:
        h = (t - self.start).total_seconds() / 3600.0
        daily = self.amp * math.sin(2 * math.pi * (t.hour + t.minute / 60 - 9) / 24)
        syn = 3.0 * math.sin(2 * math.pi * h / (24 * 5.3) + self.ph[0]) + 1.5 * math.sin(2 * math.pi * h / (24 * 2.1) + self.ph[1])
        return self.mean + daily + syn

    def cloud(self, t: datetime) -> float:
        h = (t - self.start).total_seconds() / 3600.0
        return 50 + 45 * math.sin(2 * math.pi * h / (24 * 1.7) + self.cloud_ph)

    def forecast(self, now: datetime, hours=30):
        out = []
        for i in range(1, hours + 1):
            t = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=i)
            out.append((t, self.temp(t) + self.err, self.cloud(t)))
        return out


def price_pattern(t: datetime) -> float:
    """Synthetic day-ahead style price in EUR/kWh: cheap night, morning and evening peaks."""
    h = t.hour
    base = 0.22
    if 1 <= h < 6:
        return 0.09
    if 6 <= h < 9:
        return 0.30
    if 9 <= h < 16:
        return 0.15
    if 16 <= h < 21:
        return 0.38
    return base


class Sim:
    def __init__(self, controller, seed=1, start=None, mode="retour", prices=False,
                 params: HouseParams | None = None, settings=None, tr0=21.0, amp=2.5, mean=6.0):
        self.p = params or HouseParams()
        self.start = start or datetime(2026, 11, 12, 0, 0, tzinfo=TZ)
        self.t = self.start
        self.w = Weather(seed, self.start, mean=mean, amp=amp)
        self.rng = random.Random(seed + 100)
        self.ctrl = controller
        self.mode = mode
        self.prices = prices
        self.settings = settings or {}
        self.tr, self.P, self.Sc = tr0, tr0 + 5.0, tr0 + 3.0
        self.on = False
        self.hp_target = 28.0
        self.switch = "on"
        self.W = self.P
        self.log: list[dict] = []
        self.last_ret = self.P
        self.preset = "Dag"

    # ---- sensors
    def _q(self, v, step=0.1, noise=0.03):
        return round((v + self.rng.gauss(0, noise)) / step) * step

    def inputs(self) -> Inputs:
        t = self.t
        fc = self.w.forecast(t)
        slots = []
        if self.prices:
            d0 = t.replace(hour=0, minute=0, second=0, microsecond=0)
            for i in range(0, 48):  # today and tomorrow, as day-ahead markets publish
                ts = d0 + timedelta(hours=i)
                slots.append((ts, price_pattern(ts)))
        flow_lh = 900.0 if self.on else 0.0
        freq = (20 + 30 * min(1.0, (self.W - self.P) / 6.0)) if self.on else 0.0
        return Inputs(
            now=t, room=self._q(self.tr), outside=self._q(self.w.temp(t)),
            flow=self._q(self.W if self.on else self.P + 0.3, 0.1), ret=self._q(self.P, 0.1),
            freq=freq, power_w=self._elec_w() if self.on else 0.0, flow_lh=flow_lh,
            price_now=price_pattern(t) if self.prices else None, price_forecast=slots,
            weather=fc, cloud_now=self.w.cloud(t), lat=LAT, lon=LON, control_mode=self.mode,
            preset=self.preset, manual_temp=21.0, switch_state=self.switch,
            target_current=self.hp_target, settings=self.settings,
        )

    def _elec_w(self) -> float:
        cop = max(1.5, 0.4 * (self.W + 273.15) / max(self.W - self.w.temp(self.t), 5.0))
        return self.thermal_kw() * 1000.0 / cop

    def thermal_kw(self) -> float:
        return 900.0 * 4.186 * max(0.0, self.W - self.P) / 3600.0 if self.on else 0.0

    # ---- physics
    def _unit(self):
        ret = self.P
        s = self.hp_target
        x = ret if self.mode == "retour" else self.W
        if self.switch == "off":
            self.on = False
        elif not self.on and s > x + 0.3:
            self.on = True
        elif self.on and s < x - 0.0:
            self.on = False
        if self.on:
            self.W = min(s + (3.5 if self.mode == "retour" else 0.0), self.P + 6.0)
            if self.mode == "aanvoer":
                self.W = min(max(s, self.P + 0.5), self.P + 6.0)
        else:
            self.W = self.P

    def advance(self, minutes=1):
        p, dt = self.p, 1 / 60
        for _ in range(minutes):
            self._unit()
            to = self.w.temp(self.t)
            sun = sun_gain(self.t, LAT, LON, self.w.cloud(self.t))
            h = 1.0 if self.on else 0.0
            dP = p.a1 * (self.W - self.P) * h - p.a2 * (self.P - self.Sc)
            dSc = p.a3 * (self.P - self.Sc) - p.a4 * (self.Sc - self.tr)
            dTr = p.g1 * (self.Sc - self.tr) + p.g2 * (self.P - self.tr) - p.k * (self.tr - to) + p.sigma * sun + p.c
            self.P += dP * dt
            self.Sc += dSc * dt
            self.tr += dTr * dt
            self.t += timedelta(minutes=1)

    def run(self, days: float, tick_min=2, apply=None):
        steps = int(days * 24 * 60 / tick_min)
        for _ in range(steps):
            if self.t.hour * 60 + self.t.minute in (0,) or not self.w.err:
                self.w.err = self.rng.gauss(0, 0.7)
            inp = self.inputs()
            d = apply(inp) if apply else self.ctrl.step(inp)
            if d.setpoint is not None:
                self.hp_target = d.setpoint
            if d.switch:
                self.switch = d.switch
            if d.revert_manual:
                self.preset = d.program
            e = self._elec_w() if self.on else 0.0
            self.log.append(dict(t=self.t, tr=self.tr, P=self.P, Sc=self.Sc, to=self.w.temp(self.t),
                                 s=self.hp_target, on=self.on, W=self.W, el=e, th=self.thermal_kw(),
                                 price=price_pattern(self.t), reason=d.reason, prog=d.program))
            self.advance(tick_min)
        return self.log


# --------------------------------------------------------------- baseline (v1 logic)
class V1Baseline:
    """Re-implementation of the v1 control law (with the UTC-hour bug fixed, to be fair)."""

    def __init__(self, mode="retour", sp_day=21.0, sp_night=20.4):
        self.mode, self.sp_day, self.sp_night = mode, sp_day, sp_night
        self.last = None

    def step(self, inp: Inputs):
        from engine.controller import Decision
        d = Decision()
        h = inp.now.hour
        in_night = h >= 23 or h < 7
        sp = self.sp_night if in_night else self.sp_day
        tr, to = inp.room, inp.outside
        fc = [x for x in inp.weather if x[0] > inp.now + timedelta(hours=4)]
        vb = fc[0][1] if fc else to
        cloud = fc[0][2] if fc else 100.0
        comb = 0.7 * to + 0.3 * vb
        weather_part = 0.4 * (20 - comb)
        el = max(0.0, math.degrees(math.asin(max(0.0, min(1.0, 0.0)))))
        sun = sun_gain(inp.now, inp.lat, inp.lon, cloud)
        ded = 2.0 * sun
        ideal = 22.0 + weather_part + (sp - tr) * 2.0 - ded
        if 9 <= h < 21:
            ideal += 1.0
        if in_night:
            ideal -= 1.0
        if self.last is not None:
            ideal = max(self.last - 0.5, min(self.last + 0.5, ideal))
        self.last = ideal
        x = inp.flow if self.mode == "aanvoer" else inp.ret
        if tr > sp:
            ideal = x - 1.0
        elif 9 <= h < 21:
            ideal = max(ideal, 22.0)
        ideal = min(ideal, 40.0)
        d.setpoint = float(round(ideal))
        if tr >= sp + 0.2 and inp.switch_state == "on":
            d.switch = "off"
        elif tr <= sp and inp.switch_state == "off":
            d.switch = "on"
        return d


# --------------------------------------------------------------- KPIs
def kpis(log, first_day=0, sp_day=21.0, sp_night=20.4):
    import statistics
    days = {}
    for r in log:
        days.setdefault(r["t"].date(), []).append(r)
    dates = sorted(days)[first_day:]
    out = dict(room_2200=[], night_min=[], evening_dip=[], night_peak_kw=[], el_kwh=[], cost=[], cold_h=[], warm_h=[],
               night_th=[], night_peak_1h=[], pre_th=[], floor_21=[])
    dt = (log[1]["t"] - log[0]["t"]).total_seconds() / 3600.0
    for dd in dates:
        rows = days[dd]
        if len(rows) < 0.9 * 24 * 60 / (dt * 60):
            continue
        r22 = next((r for r in rows if r["t"].hour == 22 and r["t"].minute < 2), None)
        if r22:
            out["room_2200"].append(r22["tr"] - sp_day)
        eve = [r for r in rows if r["t"].hour >= 21]
        out["night_min"].append(min(r["tr"] - (sp_night if r["t"].hour >= 23 else sp_day) for r in eve))
        out["evening_dip"].append(min(r["tr"] - sp_day for r in rows if 21 <= r["t"].hour < 23))
        out["night_peak_kw"].append(max([r["th"] for r in eve] or [0]))
        night = [r for r in rows if r["t"].hour >= 22 or r["t"].hour < 7]
        out["night_th"].append(sum(r["th"] for r in night) * dt)
        w = max(1, int(1.0 / dt))
        ths = [r["th"] for r in night]
        out["night_peak_1h"].append(max((sum(ths[i:i + w]) / w for i in range(0, max(1, len(ths) - w))), default=0.0))
        out["pre_th"].append(sum(r["th"] for r in rows if 17 <= r["t"].hour < 21) * dt)
        r21 = next((r for r in rows if r["t"].hour == 21 and r["t"].minute < 2), None)
        if r21:
            out["floor_21"].append(r21["Sc"])
        out["el_kwh"].append(sum(r["el"] for r in rows) / 1000.0 * dt)
        out["cost"].append(sum(r["el"] / 1000.0 * dt * r["price"] for r in rows))
        out["cold_h"].append(sum(dt for r in rows if r["tr"] < (sp_night if (r["t"].hour >= 23 or r["t"].hour < 7) else sp_day) - 0.3))
        out["warm_h"].append(sum(dt for r in rows if r["tr"] > (sp_night if (r["t"].hour >= 23 or r["t"].hour < 7) else sp_day) + 0.6))
    return {k: (statistics.mean(v) if v else float("nan")) for k, v in out.items()}
