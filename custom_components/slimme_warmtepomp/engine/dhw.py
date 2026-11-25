"""Optional domestic hot water (DHW) control: comfort minimum, price/PV-aware
top-up and a periodic legionella cycle.

The integration only *requests* a DHW run (switch and optional target
temperature); the heat pump hardware must handle valve switching itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# After a run that hit the maximum run time (the boiler does not reach its target: a legionella target above what
# the pump can deliver without element, a defective valve, ...) the same run must not start again straight away:
# it would keep the pump on hot water around the clock and the house would not be heated at all.
COOLDOWN_LEGIONELLA = timedelta(hours=24)
COOLDOWN_NORMAL = timedelta(hours=6)
# Without a (cheap) price signal the legionella cycle waits for the afternoon instead of starting in the night.
LEGIONELLA_WINDOW = (12, 17)


@dataclass
class DhwDecision:
    request: bool | None  # True: start/keep running, False: stop, None: no change
    setpoint: float | None
    active: bool
    mode: str  # idle | normal | topup | legionella
    reason: str


class DhwController:
    def __init__(self) -> None:
        self.active = False
        self.mode = "idle"
        self.started: datetime | None = None
        self.last_legionella: datetime | None = None
        self.timeouts = 0
        self.retry_after: datetime | None = None     # no new run before this moment (after a time-out)
        self.last_timeout: dict | None = None        # {"mode", "at", "tank", "target"} of the latest time-out

    def step(self, now: datetime, tank: float | None, s: dict, price_weight: float,
             pv_surplus: bool, enabled: bool) -> DhwDecision:
        mn, goal = s["dhw_min_temp"], s["dhw_doel_temp"]
        leg_t, leg_days = s["dhw_legionella_temp"], s["dhw_legionella_dagen"]
        max_run = timedelta(minutes=s["dhw_max_looptijd"])

        if not enabled:
            was = self.active
            self._stop()
            return DhwDecision(False if was else None, None, False, "idle", "uit")

        if tank is None:
            if self.active and self.started and now - self.started > max_run:
                self.timeouts += 1
                self._stop()
                return DhwDecision(False, None, False, "idle", "sensor_ontbreekt_timeout")
            return DhwDecision(None, None, self.active, self.mode, "sensor_ontbreekt")

        if self.last_legionella is None:
            self.last_legionella = now  # start counting from first run
        leg_due = now - self.last_legionella >= timedelta(days=leg_days)
        leg_overdue = now - self.last_legionella >= timedelta(days=leg_days + 1)

        if self.active:
            target = leg_t if self.mode == "legionella" else goal
            if tank >= target:
                if self.mode == "legionella":
                    self.last_legionella = now
                self._stop()
                return DhwDecision(False, None, False, "idle", "doel_bereikt")
            if self.started and now - self.started > max_run:
                self._timed_out(now, tank, target)
                return DhwDecision(False, None, False, "idle", "max_looptijd")
            return DhwDecision(True, target, True, self.mode, "bezig")

        # not active: decide whether to start
        if self.retry_after is not None:
            if now < self.retry_after:
                return DhwDecision(None, None, False, "idle", "wachten_na_timeout")
            self.retry_after = None
        # a legionella cycle starts when it is cheap or there is a surplus of solar power; with a neutral price (no
        # price sensor, or price control off) in the afternoon rather than in the middle of the night; and always
        # when it is overdue
        in_window = LEGIONELLA_WINDOW[0] <= now.hour < LEGIONELLA_WINDOW[1]
        leg_ok = pv_surplus or price_weight < 1.0 or (price_weight <= 1.0 and in_window)
        if leg_due and (leg_ok or leg_overdue):
            return self._start(now, "legionella", leg_t, "legionella_cyclus")
        if tank < mn:
            return self._start(now, "normal", goal, "onder_minimum")
        if tank < goal - 5.0 and (price_weight <= 0.8 or pv_surplus):
            return self._start(now, "topup", goal, "goedkoop_bijladen")
        return DhwDecision(None, None, False, "idle", "ok")

    def _timed_out(self, now: datetime, tank: float, target: float) -> None:
        """The run lasted its maximum time without reaching the target: count it, wait before trying again."""
        mode = self.mode
        self.timeouts += 1
        self.last_timeout = {"mode": mode, "at": now.isoformat(), "tank": round(tank, 1), "target": round(target, 1)}
        self.retry_after = now + (COOLDOWN_LEGIONELLA if mode == "legionella" else COOLDOWN_NORMAL)
        self._stop()

    def _start(self, now, mode, target, reason) -> DhwDecision:
        self.active, self.mode, self.started = True, mode, now
        return DhwDecision(True, target, True, mode, reason)

    def _stop(self) -> None:
        self.active, self.mode, self.started = False, "idle", None

    def to_dict(self) -> dict:
        return {"last_legionella": self.last_legionella.isoformat() if self.last_legionella else None,
                "timeouts": self.timeouts, "active": self.active, "mode": self.mode,
                "started": self.started.isoformat() if self.started else None,
                "retry_after": self.retry_after.isoformat() if self.retry_after else None,
                "last_timeout": self.last_timeout}

    def from_dict(self, d: dict) -> None:
        try:
            v = d.get("last_legionella")
            self.last_legionella = datetime.fromisoformat(v) if v else None
            self.timeouts = int(d.get("timeouts", 0))
        except (TypeError, ValueError):
            self.last_legionella = None
        try:
            ra = d.get("retry_after")
            self.retry_after = datetime.fromisoformat(ra) if ra else None
            lt = d.get("last_timeout")
            self.last_timeout = dict(lt) if isinstance(lt, dict) else None
        except (TypeError, ValueError):
            self.retry_after, self.last_timeout = None, None
        # a run that was busy at the restart must still be ended (maximum run time, target reached)
        try:
            st = d.get("started")
            if d.get("active") and st:
                self.active, self.mode, self.started = True, str(d.get("mode") or "normal"), datetime.fromisoformat(st)
        except (TypeError, ValueError):
            self.active, self.mode, self.started = False, "idle", None
