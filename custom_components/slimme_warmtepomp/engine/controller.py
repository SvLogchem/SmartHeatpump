"""The brain: turns sensor readings + settings into a heat pump decision.

``SmartController.step`` is pure Python (no Home Assistant objects), so the
whole control loop can be simulated in tests against a synthetic house.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .dhw import DhwController
from .model import HouseModel
from .modulation import ModulationLearner
from .planner import PlanInput, PlanResult, plan as run_plan
from .prices import PriceCurve, PriceStats, weight_for
from .settings import DEFAULTS
from .solar import sun_gain

S_MIN = 20.0            # lowest water setpoint we ever ask for
KP, KI = 1.2, 0.25
KP_PLANNED = 0.5       # the planner already anticipates; keep the reactive part gentle      # feedback on top of the model (K per K, K per K*h)
SAMPLE_MIN = 5
LEARN_MIN = 15
WINDOW = 18             # samples (~90 minutes)
PROGRAM_DAY, PROGRAM_NIGHT, PROGRAM_MANUAL = "Dag", "Nacht", "Handmatig"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass
class Inputs:
    now: datetime
    room: float | None
    outside: float | None
    flow: float | None = None
    ret: float | None = None
    floor: float | None = None
    freq: float | None = None
    power_w: float | None = None
    flow_lh: float | None = None
    tank: float | None = None
    price_now: float | None = None
    price_forecast: list = field(default_factory=list)   # [(datetime, price)]
    pv_w: float | None = None
    weather: list = field(default_factory=list)          # [(datetime, temp, cloud%|None)]
    cloud_now: float | None = None
    lat: float = 52.0
    lon: float = 5.0
    control_mode: str = "retour"
    hvac_on: bool = True
    regeling_actief: bool = True
    learning_enabled: bool = True
    preheat_enabled: bool = True
    price_enabled: bool = True
    modulation_enabled: bool = True
    dhw_enabled: bool = False
    windows_open: bool = False            # any configured window/door sensor reports open
    away: bool = False                    # nobody home (raw; the controller debounces it)
    return_at: datetime | None = None     # announced time of return, if known
    grid_import_w: float | None = None    # power drawn from the grid (positive = import)
    preset: str = PROGRAM_DAY
    manual_temp: float = 21.0
    switch_state: str | None = None   # "on" / "off" / None (no switch configured)
    target_current: float | None = None
    setpoint_step: float = 1.0
    settings: dict = field(default_factory=dict)


@dataclass
class Decision:
    setpoint: float | None = None      # quantised value to write, None = leave alone
    setpoint_raw: float | None = None
    switch: str | None = None          # "on" / "off" / None
    dhw_request: bool | None = None
    dhw_setpoint: float | None = None
    program: str = PROGRAM_DAY
    room_setpoint: float = 21.0
    revert_manual: bool = False
    reason: str = ""
    sensor_problem: bool = False
    defrost: bool = False
    summer: bool = False
    expensive: bool = False
    preheating: bool = False
    coasting: bool = False
    bivalent: bool = False
    dhw_active: bool = False
    heating: bool = False
    window_open: bool = False
    away: bool = False
    grid_limited: bool = False
    freq_limited: bool = False         # setpoint limited by the maximum frequency setting
    soft: bool = False                 # setpoint held just above the return temperature (low frequency)
    cop_today: float | None = None
    cop_yesterday: float | None = None
    starts_today: int = 0
    starts_yesterday: int | None = None
    shadow: bool = False               # computed, but nothing is sent to the heat pump
    switch_state: str | None = None    # observed state of the heat pump switch
    thermal_kw: float = 0.0
    cop: float = 0.0
    electric_w: float = 0.0
    energy_thermal_kwh: float = 0.0
    energy_electric_kwh: float = 0.0
    diag: dict = field(default_factory=dict)


class EveningTracker:
    """Learns from the evening result: if the room was too cold an hour after
    bedtime, charge the floor a bit more tomorrow (and vice versa)."""

    def __init__(self) -> None:
        self.bias = 0.0
        self.last_date: str | None = None
        self.last_error: float | None = None

    def update(self, now: datetime, tr: float, sp: float, bedtime_h: float) -> None:
        h = (bedtime_h + 1.0) % 24.0
        check = now.replace(hour=int(h), minute=int((h % 1) * 60), second=0, microsecond=0)
        if check <= now < check + timedelta(minutes=30) and self.last_date != now.date().isoformat():
            err = tr - sp
            if err < -0.15:
                self.bias += min(0.5, -err)
            elif err > 0.4:
                self.bias -= min(0.5, err - 0.4)
            self.bias = _clamp(self.bias, -1.5, 3.0)
            self.last_error = err
            self.last_date = now.date().isoformat()

    def to_dict(self):
        return {"bias": self.bias, "last_date": self.last_date, "last_error": self.last_error}

    def from_dict(self, d):
        try:
            self.bias = float(d.get("bias", 0.0))
            self.last_date = d.get("last_date")
            self.last_error = d.get("last_error")
        except (TypeError, ValueError):
            self.bias = 0.0


def _slope(ts, ys):
    n = len(ts)
    tm, ym = sum(ts) / n, sum(ys) / n
    den = sum((t - tm) ** 2 for t in ts)
    return 0.0 if den == 0 else sum((t - tm) * (y - ym) for t, y in zip(ts, ys)) / den


def _interp(points, t, default):
    """points: sorted [(datetime, value)]; linear interpolation, clamped at the ends."""
    if not points:
        return default
    keys = [p[0] for p in points]
    i = bisect.bisect_right(keys, t)
    if i == 0:
        return points[0][1]
    if i >= len(points):
        return points[-1][1]
    (t0, v0), (t1, v1) = points[i - 1], points[i]
    span = (t1 - t0).total_seconds()
    return v0 if span <= 0 else v0 + (v1 - v0) * (t - t0).total_seconds() / span


class SmartController:
    def __init__(self) -> None:
        self.model = HouseModel()
        self.tracker = EveningTracker()
        self.prices = PriceStats()
        self.dhw = DhwController()
        self.mod = ModulationLearner()
        # persistent scalars
        self.pi_i = 0.0
        self.summer_mean: float | None = None
        self.summer = False
        self.f_est: float | None = None
        self.dT_sup = 3.5
        self.energy_th = 0.0
        self.energy_el = 0.0
        self.day_key: str | None = None
        self.today = {"th": 0.0, "el": 0.0, "starts": 0}
        self.yesterday: dict | None = None
        self._reset_runtime()

    def _reset_runtime(self) -> None:
        self._win: list = []
        self._last_sample: datetime | None = None
        self._last_learn: datetime | None = None
        self._last_step: datetime | None = None
        self._plan_key = None
        self._plan: PlanResult | None = None
        self._prev_s: float | None = None
        self._heat_state: str | None = None
        self._heat_since: datetime | None = None
        self._last_on: datetime | None = None
        self._last_off: datetime | None = None
        self._last_switch: str | None = None
        self._manual_prog: str | None = None
        self._last: Decision | None = None
        self._q_acc = 0.0
        self._q_last: datetime | None = None
        self._open_since: datetime | None = None
        self._away_since: datetime | None = None
        self._grid_hi_since: datetime | None = None
        self._grid_block_since: datetime | None = None
        self._grid_lock_until: datetime | None = None
        self._was_heating: bool | None = None
        self._stopped_at: datetime | None = None
        self._tgt_value: float | None = None
        self._tgt_since: datetime | None = None
        self._probe_until: datetime | None = None
        self._probe_next: datetime | None = None

    def reset_model(self) -> None:
        self.model.reset()
        self.tracker = EveningTracker()
        self.pi_i = 0.0
        self._win = []

    # ----------------------------------------------------------- persistence
    def export_state(self) -> dict:
        return {
            "model": self.model.to_dict(), "tracker": self.tracker.to_dict(),
            "prices": self.prices.to_dict(), "mod": self.mod.to_dict(), "dhw": self.dhw.to_dict(),
            "pi_i": self.pi_i, "summer_mean": self.summer_mean, "summer": self.summer,
            "dT_sup": self.dT_sup, "energy_th": self.energy_th, "energy_el": self.energy_el,
            "day_key": self.day_key, "today": self.today, "yesterday": self.yesterday,
        }

    def import_state(self, d: dict) -> None:
        if not d:
            return
        try:
            self.model.from_dict(d.get("model", {}))
            self.tracker.from_dict(d.get("tracker", {}))
            self.prices.from_dict(d.get("prices", {}))
            self.dhw.from_dict(d.get("dhw", {}))
            self.mod.from_dict(d.get("mod", {}))
            self.pi_i = float(d.get("pi_i", 0.0))
            self.summer_mean = d.get("summer_mean")
            self.summer = bool(d.get("summer", False))
            self.dT_sup = float(d.get("dT_sup", 3.5))
            self.energy_th = float(d.get("energy_th", 0.0))
            self.energy_el = float(d.get("energy_el", 0.0))
            self.day_key = d.get("day_key")
            t = d.get("today") or {}
            self.today = {"th": float(t.get("th", 0.0)), "el": float(t.get("el", 0.0)), "starts": int(t.get("starts", 0))}
            y = d.get("yesterday")
            self.yesterday = None if not y else {"th": float(y["th"]), "el": float(y["el"]), "starts": int(y["starts"])}
        except (TypeError, ValueError, AttributeError, KeyError):
            # corrupted storage must never stop the integration from starting
            self.model.reset()

    # ----------------------------------------------------------- helpers
    @staticmethod
    def _program(t: datetime, s: dict) -> str:
        h = t.hour + t.minute / 60.0
        ns, ne = s["nacht_start"], s["nacht_eind"]
        night = (h >= ns or h < ne) if ns > ne else (ns <= h < ne)
        return PROGRAM_NIGHT if night else PROGRAM_DAY

    @staticmethod
    def _heating(inp: Inputs, thr: float) -> bool:
        if inp.freq is not None:
            return inp.freq >= thr
        if inp.power_w is not None:
            return inp.power_w >= 250.0
        if inp.flow is not None and inp.ret is not None:
            return inp.flow - inp.ret > 1.5
        return False

    def _quantize(self, raw: float, step: float, current: float | None, dt_h: float, now: datetime) -> float:
        """Round to the device resolution with error diffusion.

        A whole-degree setpoint would otherwise leave a permanent +-0.5 K error
        on the floor temperature. Instead the output steps up or down once the
        accumulated error is large enough, so the *average* equals ``raw``.
        """
        if current is None or abs(raw - current) >= 1.5 * step:
            self._q_acc = 0.0
            self._q_last = now
            return round(raw / step) * step
        self._q_acc += (raw - current) * dt_h
        quiet_for = (now - self._q_last) if self._q_last else timedelta(hours=1)
        if quiet_for >= timedelta(minutes=20):
            thr = 0.25 * step
            if self._q_acc >= thr and raw > current:
                self._q_acc, self._q_last = 0.0, now
                return current + step
            if self._q_acc <= -thr and raw < current:
                self._q_acc, self._q_last = 0.0, now
                return current - step
        return current

    def _learn(self, inp: Inputs, valid: bool, heating: bool, f_meas, sun_now: float) -> None:
        now = inp.now
        if self._last_sample and (now - self._last_sample) < timedelta(minutes=SAMPLE_MIN):
            return
        self._last_sample = now
        if not valid:
            self._win.append(None)
            self._win = self._win[-2 * WINDOW:]
            return
        self._win.append((now.timestamp() / 3600.0, inp.room, inp.outside, f_meas, inp.flow,
                          1.0 if heating else 0.0, sun_now))
        self._win = self._win[-2 * WINDOW:]
        if len(self._win) < WINDOW or (self._last_learn and now - self._last_learn < timedelta(minutes=LEARN_MIN)):
            return
        w = self._win[-WINDOW:]
        if any(x is None for x in w):
            return
        ts = [x[0] for x in w]
        if not 1.0 <= ts[-1] - ts[0] <= 2.3:
            return
        mean = lambda i: sum(x[i] for x in w) / WINDOW  # noqa: E731
        tr, to, f, sun = mean(1), mean(2), mean(3), mean(6)
        self.model.learn_room(_slope(ts, [x[1] for x in w]), f - tr, tr - to, sun)
        if all(x[4] is not None for x in w):
            drive = sum(x[5] * max(0.0, x[4] - x[3]) for x in w) / WINDOW
            self.model.learn_floor(_slope(ts, [x[3] for x in w]), drive, f - tr)
            # supply-vs-return offset while heating (used to translate return setpoints)
            hot = [x[4] - x[3] for x in w if x[5] > 0 and x[4] is not None]
            if len(hot) > WINDOW // 2:
                self.dT_sup = _clamp(0.98 * self.dT_sup + 0.02 * (sum(hot) / len(hot)), 0.5, 10.0)
        self._last_learn = now

    # ----------------------------------------------------------- main step
    def step(self, inp: Inputs) -> Decision:
        now = inp.now
        s = {**DEFAULTS, **inp.settings}
        dt_h = 0.0
        if self._last_step is not None:
            dt_h = _clamp((now - self._last_step).total_seconds() / 3600.0, 0.0, 0.5)
        self._last_step = now
        d = Decision()

        program_now = self._program(now, s)
        d.program = program_now
        if inp.room is None or inp.outside is None:
            d.sensor_problem = True
            d.reason = "sensor_ontbreekt"
            d.room_setpoint = self._last.room_setpoint if self._last else s["setpoint_dag"]
            return d

        # ---- manual preset reverts at the next day/night switch
        if inp.preset == PROGRAM_MANUAL:
            if self._manual_prog is None:
                self._manual_prog = program_now
            elif program_now != self._manual_prog:
                d.revert_manual = True
                self._manual_prog = None
        else:
            self._manual_prog = None
        manual_active = inp.preset == PROGRAM_MANUAL and not d.revert_manual

        # ---- away (debounced) and open windows
        if inp.away:
            self._away_since = self._away_since or now
        else:
            self._away_since = None
        away_active = bool(self._away_since and now - self._away_since >= timedelta(minutes=s["afwezig_vertraging"]))
        if inp.windows_open:
            self._open_since = self._open_since or now
        else:
            self._open_since = None
        window_active = bool(self._open_since and now - self._open_since >= timedelta(minutes=s["raam_vertraging"]))
        d.away, d.window_open = away_active, window_active

        def sp_at(t: datetime) -> float:
            prog = self._program(t, s)
            if manual_active and prog == self._manual_prog:
                return inp.manual_temp
            if away_active and not manual_active and (inp.return_at is None or t < inp.return_at):
                return s["afwezig_setpoint"]
            return s["setpoint_nacht"] if prog == PROGRAM_NIGHT else s["setpoint_dag"]

        sp_now = sp_at(now)
        d.room_setpoint = sp_now
        d.program = PROGRAM_MANUAL if manual_active else program_now
        tr, to_now = inp.room, inp.outside

        # ---- bookkeeping: heating state, defrost, energy
        heating = self._heating(inp, s["min_freq"])
        d.defrost = bool(heating and inp.flow is not None and inp.ret is not None
                         and inp.flow - inp.ret < -0.5)
        sun_now = sun_gain(now, inp.lat, inp.lon, inp.cloud_now)
        d.bivalent = to_now < s["bivalent_temp"]
        d.heating = heating and not d.defrost
        d.switch_state = inp.switch_state
        d.shadow = not inp.regeling_actief

        power_w = inp.power_w or 0.0
        if d.defrost or not heating or not inp.flow_lh or inp.flow is None or inp.ret is None:
            d.thermal_kw = 0.0
        else:
            dtw = inp.flow - inp.ret
            d.thermal_kw = round(max(0.0, inp.flow_lh * 4.186 * dtw / 3600.0), 2) if dtw > 0 else 0.0
        d.electric_w = round(power_w, 1)
        if d.thermal_kw > 0 and power_w > 10.0:
            cop = d.thermal_kw / (power_w / 1000.0)
            d.cop = round(cop, 2) if 0.5 <= cop <= 12.0 else 0.0
        e_dt = min(dt_h, 0.1)
        self.energy_th += d.thermal_kw * e_dt
        self.energy_el += power_w / 1000.0 * e_dt
        d.energy_thermal_kwh, d.energy_electric_kwh = round(self.energy_th, 3), round(self.energy_el, 3)

        # ---- learn how the heat pump reacts to the gap between setpoint and return temperature
        if inp.target_current != self._tgt_value:
            self._tgt_value, self._tgt_since = inp.target_current, now
        if (inp.target_current is not None and inp.ret is not None and inp.hvac_on and not d.defrost
                and not self.dhw.active and not window_active and inp.switch_state != "off"
                and self._tgt_since is not None and now - self._tgt_since >= timedelta(minutes=15)
                and inp.learning_enabled):
            self.mod.observe(inp.target_current - inp.ret, d.heating, inp.freq, d.thermal_kw or None)

        # ---- daily statistics: COP and compressor starts per day
        key = now.date().isoformat()
        if key != self.day_key:
            if self.day_key is not None:
                self.yesterday = self.today
            self.day_key, self.today = key, {"th": 0.0, "el": 0.0, "starts": 0}
        self.today["th"] += d.thermal_kw * e_dt
        self.today["el"] += power_w / 1000.0 * e_dt
        if self._was_heating and not heating:
            self._stopped_at = now
        if heating and self._was_heating is False and (
                self._stopped_at is None or now - self._stopped_at >= timedelta(minutes=2)):
            self.today["starts"] += 1
        self._was_heating = heating
        d.starts_today = self.today["starts"]
        d.cop_today = _day_cop(self.today)
        if self.yesterday:
            d.cop_yesterday, d.starts_yesterday = _day_cop(self.yesterday), self.yesterday["starts"]

        # ---- prices
        price_enabled = inp.price_enabled and s["prijs_gevoeligheid"] > 0
        if inp.price_now is not None:
            self.prices.add(now.timestamp(), inp.price_now)
        ref = self.prices.reference()
        curve = PriceCurve(inp.price_forecast, ref, s["prijs_gevoeligheid"]) if inp.price_forecast else None
        if ref is None and curve is not None:
            ref = curve.ref
        weight_now = weight_for(inp.price_now, ref, s["prijs_gevoeligheid"]) if price_enabled else 1.0
        pv_surplus = inp.pv_w is not None and inp.pv_w >= s["pv_drempel"]
        d.expensive = bool(price_enabled and inp.price_now is not None
                           and inp.price_now > s["max_stroomprijs"])

        def price_fn(t: datetime) -> float:
            w = 1.0
            if price_enabled:
                if curve is not None and curve.covers(t):
                    w = curve.weight(t)
                elif (t - now) < timedelta(hours=1):
                    w = weight_now
            if pv_surplus and (t - now) < timedelta(hours=2):
                w *= 0.4
            return w

        # ---- floor state: measured proxy or decayed estimate
        f_meas = inp.floor if inp.floor is not None else inp.ret
        dhw_busy = self.dhw.active
        proxy_ok = f_meas is not None and inp.switch_state != "off" and not dhw_busy
        beta = self.model.params.beta
        if proxy_ok:
            self.f_est = f_meas if self.f_est is None else 0.5 * self.f_est + 0.5 * f_meas
        elif self.f_est is not None:
            self.f_est += -beta * (self.f_est - tr) * dt_h
        f_known = self.f_est is not None

        # ---- learning
        if inp.learning_enabled:
            valid = proxy_ok and inp.hvac_on and not d.defrost and not dhw_busy and not inp.windows_open
            self._learn(inp, valid, heating, f_meas, sun_now)

        # ---- summer mode (24h mean with hysteresis)
        a = 1.0 - math.exp(-dt_h / 24.0)
        self.summer_mean = to_now if self.summer_mean is None else self.summer_mean + a * (to_now - self.summer_mean)
        if self.summer:
            self.summer = self.summer_mean > s["stookgrens"] - 1.0
        else:
            self.summer = self.summer_mean >= s["stookgrens"]
        d.summer = self.summer

        # ---- domestic hot water
        dhw = self.dhw.step(now, inp.tank, s, weight_now, pv_surplus, inp.dhw_enabled and inp.regeling_actief)
        d.dhw_request, d.dhw_setpoint, d.dhw_active = dhw.request, dhw.setpoint, dhw.active

        # ---- evening learning (bias for the floor target at bedtime)
        if not away_active:
            self.tracker.update(now, tr, sp_now, s["bedtijd"])

        d.diag = self._diag(s, f_known, sun_now)
        mode = inp.control_mode
        x_meas = inp.flow if mode == "aanvoer" else inp.ret

        # ---- states in which we do not touch space heating
        if not inp.hvac_on:
            d.reason = "uit"
            if inp.regeling_actief and inp.switch_state == "on":
                d.switch = "off"
            self._finish(d, now)
            return d
        if dhw.active:
            d.reason = "tapwater"
            self._finish(d, now)
            return d
        if d.defrost:
            d.reason = "ontdooien"
            self._finish(d, now)
            return d

        # ---- heating curve: blend learned model with the manual curve
        conf = self.model.confidence()
        use_learned = inp.learning_enabled and f_known and self.model.plausible()
        wl = _clamp((conf - 0.35) / 0.45, 0.0, 1.0) if use_learned else 0.0
        w_off = self.dT_sup if mode == "retour" else 0.0
        s_max = max(s["max_flow_temp"], s["min_setpoint"] + 1.0)

        def s_manual(to, sun, sp):
            return (s["basis_temperatuur"] + s["setpoint_offset"] + s["stooklijn"] * (20.0 - to)
                    + 1.5 * (sp - 21.0) - s["zon_factor"] * sun)

        def s_base(t, to, sun, sp):
            man = s_manual(to, sun, sp)
            if wl <= 0.0:
                return _clamp(man, s["min_setpoint"], s_max)
            # retour mode: the setpoint *is* the floor/return temperature; aanvoer: supply water
            eq = (self.model.floor_equilibrium(sp, to, sun) if mode == "retour"
                  else self.model.water_equilibrium(sp, to, sun))
            lrn = _clamp(eq, man - 6.0, man + 6.0)
            return _clamp(wl * lrn + (1.0 - wl) * man, s["min_setpoint"], s_max)

        # ---- weather forecast helpers
        fc_t = sorted([(t, v) for t, v, _ in inp.weather], key=lambda x: x[0])
        fc_c = sorted([(t, c) for t, _, c in inp.weather if c is not None], key=lambda x: x[0])
        if fc_t and fc_t[0][0] > now:
            fc_t.insert(0, (now, to_now))

        def to_fn(t):
            return _interp(fc_t, t, to_now)

        d.diag["verwacht_buiten"] = round(to_fn(now + timedelta(hours=s["horizon"])), 1)

        def sun_fn(t):
            return sun_gain(t, inp.lat, inp.lon, _interp(fc_c, t, inp.cloud_now))

        # ---- quiet hours + bedtime
        bed_h = s["bedtijd"] % 24.0
        ne = s["nacht_eind"]

        def quiet_fn(t):
            h = t.hour + t.minute / 60.0
            return (h >= bed_h or h < ne) if bed_h > ne else (bed_h <= h < ne)

        bedtime = now.replace(hour=int(bed_h), minute=int((bed_h % 1) * 60), second=0, microsecond=0)
        if bedtime <= now:
            bedtime += timedelta(days=1)

        # ---- frequency limit: translate max Hz (day / quiet hours) into a max gap above the return temp
        def gap_cap_fn(t):
            if not inp.modulation_enabled:
                return None
            fmax = s["max_freq_stil"] if quiet_fn(t) else s["max_freq_dag"]
            return self.mod.gap_cap(fmax) if fmax > 0 else None

        # ---- plan
        plan_ok = inp.preheat_enabled and wl >= 0.3 and f_known
        pl = PlanResult()
        if plan_ok:
            key = (now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0), sp_now,
                   round(tr, 1), manual_active, round(self.tracker.bias, 2))
            if key != self._plan_key or self._plan is None:
                self._plan = run_plan(PlanInput(
                    now=now, tr=tr, f=self.f_est, model=self.model, to_fn=to_fn, sun_fn=sun_fn,
                    sp_fn=sp_at, price_fn=price_fn, s_base_fn=s_base, w_offset=w_off,
                    s_min=s["min_setpoint"], s_max=s_max, bedtime=bedtime, quiet_fn=quiet_fn,
                    quiet_boost=s["stille_boost_max"], tol_low=s["tolerantie_laag"],
                    tol_high=s["tolerantie_hoog"], d_max=s["voorverwarm_max"],
                    bias=self.tracker.bias, hard_min_room=s["min_kamertemp"],
                    allow_coast=True, mode=mode, gap_cap_fn=gap_cap_fn,
                    quiet_energy_mult=1.0 + 2.0 * s["stille_voorkeur"]))
                self._plan_key = key
            pl = self._plan
        d.diag.update({
            "plan": pl.kind, "plan_reden": pl.reason or "-", "voorspeld_kamer_na_bedtijd": _r(pl.tr_check),
            "voorspeld_vloer_bedtijd": _r(pl.f_bed), "vloer_doel_bedtijd": _r(pl.f_target),
            "voorspeld_kamer_min": _r(pl.tr_min), "voorspeld_kamer_max": _r(pl.tr_max),
            "start_voorverwarmen": pl.start.isoformat() if pl.start else None,
        })

        # ---- decide run / coast (with minimum run and standstill times)
        in_quiet = quiet_fn(now)
        emergency = tr < s["min_kamertemp"] or tr < sp_now - s["tolerantie_laag"] - 0.3
        over = tr > sp_now + s["tolerantie_hoog"]
        grid_block = self._grid_limiter(inp, s, now)
        d.grid_limited = grid_block
        cap_coast = d.expensive and not emergency and tr >= sp_now - s["tolerantie_laag"]
        want_coast = (self.summer or over or cap_coast or pl.coast_now or window_active or grid_block) and not emergency
        want = "coast" if want_coast else "run"
        if self._heat_state is None:
            self._heat_state, self._heat_since = want, now
        elif want != self._heat_state:
            need = s["minimum_runtime"] if self._heat_state == "run" else s["minimum_stilstand"]
            if emergency or now - self._heat_since >= timedelta(minutes=need):
                self._heat_state, self._heat_since = want, now
        d.coasting = self._heat_state == "coast"

        # ---- setpoint
        if d.coasting:
            raw = _clamp((x_meas - 1.0) if x_meas is not None else s["min_setpoint"], s["min_setpoint"], s_max)
            d.reason = ("zomermodus" if self.summer else "raam_open" if window_active
                        else "netlimiet" if grid_block else "dure_stroom" if cap_coast
                        else "te_warm" if over else "uitlopen" if pl.coast_now else "wacht_draaitijd")
        else:
            e = sp_now - tr
            self.pi_i = _clamp(self.pi_i + KI * e * dt_h, -2.0, 2.0)
            if abs(e) < 0.1:
                self.pi_i *= 1.0 - min(1.0, 0.2 * dt_h)
            delta = min(pl.delta_now, s["stille_boost_max"]) if in_quiet else pl.delta_now
            kp = KP_PLANNED if plan_ok else KP
            kick = _clamp(kp * e, -2.5, 2.5) + delta
            kick = min(kick, s["stille_boost_max"] if in_quiet else 5.0)
            pv = s["pv_boost"] if (pv_surplus and tr < sp_now + s["tolerantie_hoog"]) else 0.0
            raw = s_base(now, to_now, sun_fn(now), sp_now) + self.pi_i + kick + pv
            raw, soft = self._soft_running(raw, inp, s, now, e, pl.delta_now, tr, sp_now, in_quiet)
            d.soft = soft
            cap = gap_cap_fn(now)
            if cap is not None and not soft and inp.ret is not None and not emergency:
                base_now = s_base(now, to_now, sun_fn(now), sp_now) + self.pi_i
                limited = max(base_now, inp.ret + cap)
                if raw > limited:
                    raw, d.freq_limited = limited, True
            raw = _clamp(raw, s["min_setpoint"], s_max)
            if self._prev_s is not None and dt_h > 0:
                lim = max(0.5, 12.0 * dt_h)
                raw = _clamp(raw, self._prev_s - lim, self._prev_s + lim)
            self._prev_s = raw
            d.preheating = pl.delta_now > 0
            d.reason = f"voorverwarmen ({pl.reason})" if d.preheating else (
                "regelen_geleerd" if wl >= 0.99 else "regelen_stooklijn" if wl <= 0 else "regelen_gemengd")
        d.setpoint_raw = round(raw, 2)
        d.setpoint = self._quantize(raw, max(inp.setpoint_step, 0.1), inp.target_current, dt_h, now)

        # ---- hard on/off with compressor protection
        sw = inp.switch_state
        if sw is not None:
            if sw != self._last_switch:
                (setattr(self, "_last_on", now) if sw == "on" else setattr(self, "_last_off", now))
                self._last_switch = sw
            off_wanted = self.summer or (d.coasting and tr >= sp_now + s["waakhond_marge"])
            if off_wanted and sw == "on":
                if self._last_on is None or now - self._last_on >= timedelta(minutes=s["minimum_runtime"]):
                    d.switch = "off"
            elif not off_wanted and sw == "off":
                if self._last_off is None or now - self._last_off >= timedelta(minutes=s["minimum_stilstand"]):
                    d.switch = "on"
        self._finish(d, now)
        return d

    def _diag(self, s: dict, f_known: bool, sun_now: float = 0.0) -> dict:
        p = self.model.params
        return {
            "model_vertrouwen": round(self.model.confidence(), 2),
            "model_geloofwaardig": self.model.plausible(),
            "huis_tijdconstante_u": round(1.0 / p.k, 1),
            "vloer_tijdconstante_u": round(1.0 / p.beta, 1),
            "vloer_opwarmtijd_u": round(1.0 / p.alpha, 2),
            "stooklijn_helling_geleerd": round(p.k / p.gamma, 3),
            "leervensters": self.model.windows_room,
            "model_bias_k_per_u": round(self.model.c_adapt, 3),
            "zon_reductie_k": round(p.sigma * sun_now / p.gamma, 2),
            "avond_bias_k": round(self.tracker.bias, 2),
            "avond_laatste_afwijking": _r(self.tracker.last_error),
            "vloer_geschat": _r(self.f_est),
            "gemiddelde_buiten_24u": _r(self.summer_mean),
            "tapwater_modus": self.dhw.mode,
            "geleerde_stooklijn": self._learned_curve(s),
            "modulatie_minimaal_verschil": self.mod.floor(),
            "modulatie_frequentie_op_minimum": self.mod.freq_at_floor(),
            "frequentie_tabel": self.mod.table() or None,
        }

    def _learned_curve(self, s: dict):
        """Setpoint the model would use at a few outdoor temperatures (sp=day, no sun)."""
        if self.model.confidence() < 0.5 or not self.model.plausible():
            return None
        out = {}
        for to in (-5, 0, 5, 10, 15):
            out[str(to)] = round(self.model.floor_equilibrium(s["setpoint_dag"], to, 0.0), 1)
        return out

    def _soft_running(self, raw: float, inp: Inputs, s: dict, now: datetime, e: float,
                      delta_now: float, tr: float, sp_now: float, in_quiet: bool):
        """When little heat is needed, hold the setpoint just above the return temperature.

        The learned floor is the smallest gap that still kept the compressor running; the heat
        pump then modulates down instead of running hard and stopping. A small, occasional probe
        one step below the floor keeps the knowledge up to date.
        """
        if not (inp.modulation_enabled and inp.ret is not None):
            return raw, False
        floor = self.mod.floor()
        low_demand = e <= 0.15 and delta_now <= 0.0 and tr >= sp_now - 0.15
        if floor is None or not low_demand:
            self._probe_until = None
            return raw, False
        gap = floor + s["modulatie_marge"]
        if self._probe_until and now < self._probe_until:
            gap = floor - 0.5
        elif self._probe_until:
            self._probe_until, self._probe_next = None, now + timedelta(hours=2)
        elif (self.mod.needs_probe() and tr >= sp_now + 0.1
              and (self._probe_next is None or now >= self._probe_next)):
            self._probe_until = now + timedelta(minutes=30)
            gap = floor - 0.5
        target = inp.ret + gap
        if target < raw:
            return target, True
        return raw, False

    def _grid_limiter(self, inp: Inputs, s: dict, now: datetime) -> bool:
        """Back off when the house draws too much from the grid (capacity tariff, battery saver).

        Needs the limit to be exceeded for 5 minutes (ignores cooking spikes), blocks for at
        most 45 minutes and then stays released for 15 minutes so comfort cannot suffer.
        """
        limit, imp = s["netimport_limiet"], inp.grid_import_w
        if limit <= 0 or imp is None:
            self._grid_hi_since = self._grid_block_since = None
            return False
        if self._grid_block_since is not None:
            if imp < 0.8 * limit:
                self._grid_block_since = None
            elif now - self._grid_block_since >= timedelta(minutes=45):
                self._grid_block_since = None
                self._grid_lock_until = now + timedelta(minutes=15)
            return self._grid_block_since is not None
        if imp > limit:
            self._grid_hi_since = self._grid_hi_since or now
            if now - self._grid_hi_since >= timedelta(minutes=5) and (
                    self._grid_lock_until is None or now >= self._grid_lock_until):
                self._grid_block_since = now
                return True
        else:
            self._grid_hi_since = None
        return False

    def _finish(self, d: Decision, now: datetime) -> None:
        if d.shadow:  # "schaduwmodus": everything is calculated and visible, nothing is sent
            d.switch = None
            d.dhw_request = None
        self._last = d


def _day_cop(day: dict):
    return round(day["th"] / day["el"], 2) if day["el"] > 0.5 else None


def _r(v, n=2):
    return None if v is None else round(v, n)
