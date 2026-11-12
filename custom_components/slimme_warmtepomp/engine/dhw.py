"""Optional domestic hot water (DHW) control: comfort minimum, price/PV-aware
top-up and a periodic legionella cycle.

The integration only *requests* a DHW run (switch and optional target
temperature); the heat pump hardware must handle valve switching itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


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
                self.timeouts += 1
                self._stop()
                return DhwDecision(False, None, False, "idle", "max_looptijd")
            return DhwDecision(True, target, True, self.mode, "bezig")

        # not active: decide whether to start
        if leg_due and (price_weight <= 1.0 or pv_surplus or leg_overdue):
            return self._start(now, "legionella", leg_t, "legionella_cyclus")
        if tank < mn:
            return self._start(now, "normal", goal, "onder_minimum")
        if tank < goal - 5.0 and (price_weight <= 0.8 or pv_surplus):
            return self._start(now, "topup", goal, "goedkoop_bijladen")
        return DhwDecision(None, None, False, "idle", "ok")

    def _start(self, now, mode, target, reason) -> DhwDecision:
        self.active, self.mode, self.started = True, mode, now
        return DhwDecision(True, target, True, mode, reason)

    def _stop(self) -> None:
        self.active, self.mode, self.started = False, "idle", None

    def to_dict(self) -> dict:
        return {"last_legionella": self.last_legionella.isoformat() if self.last_legionella else None,
                "timeouts": self.timeouts}

    def from_dict(self, d: dict) -> None:
        try:
            v = d.get("last_legionella")
            self.last_legionella = datetime.fromisoformat(v) if v else None
            self.timeouts = int(d.get("timeouts", 0))
        except (TypeError, ValueError):
            self.last_legionella = None
