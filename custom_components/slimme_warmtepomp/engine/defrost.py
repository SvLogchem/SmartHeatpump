"""Learns how long a defrost cycle lasts, how often it happens and how long the water needs
to settle afterwards.

Detection of a defrost itself stays in the controller (flow colder than return while the
compressor runs). This class only watches those episodes:

* ``dur``      typical length of the reversed-flow phase (minutes)
* ``interval`` typical time between two defrost starts (minutes)
* ``recovery`` time after a defrost until flow minus return is back within 25 % of the value
               it had before (minutes). While the water is still settling, COP and learning
               are suspended, so this decides how long that pause has to be.
"""
from __future__ import annotations

from datetime import datetime, timedelta

MIN_EVENTS = 3          # recoveries needed before the learned value replaces the setting
RECOVERY_CAP = 10.0     # never wait longer than this (minutes)
TOLERANCE = 0.25


def _ew(old: float | None, new: float, n: int) -> float:
    return new if old is None else old + max(0.2, 1.0 / max(n, 1)) * (new - old)


class DefrostLearner:
    def __init__(self) -> None:
        self.n = 0                 # defrosts seen
        self.rec_n = 0             # recoveries measured
        self.dur: float | None = None
        self.interval: float | None = None
        self.recovery: float | None = None
        self.unit_t: float | None = None     # heat pump's own outdoor sensor at the start of a defrost
        self.last_start: datetime | None = None
        self.last_end: datetime | None = None
        self.last_interval: float | None = None
        self._start: datetime | None = None
        self._recov_start: datetime | None = None
        self._pre_dtw: float | None = None

    def update(self, now: datetime, defrost: bool, dtw: float | None, heating: bool,
               unit_temp: float | None = None) -> None:
        if defrost and self._start is None:
            self._start, self._recov_start = now, None
            if self.last_start is not None:
                gap = (now - self.last_start).total_seconds() / 60.0
                if 5.0 <= gap <= 360.0:
                    self.interval = _ew(self.interval, gap, self.n)
                    self.last_interval = gap
            self.last_start = now
            if unit_temp is not None:
                self.unit_t = _ew(self.unit_t, unit_temp, self.n)
        elif not defrost and self._start is not None:
            length = (now - self._start).total_seconds() / 60.0
            self._start = None
            self.last_end = now
            if 0.3 <= length <= 20.0:
                self.dur = _ew(self.dur, length, self.n)
                self.n += 1
                self._recov_start = now
        if defrost:
            return
        if self._recov_start is not None:
            waited = (now - self._recov_start).total_seconds() / 60.0
            stable = (dtw is not None and self._pre_dtw is not None
                      and abs(dtw - self._pre_dtw) <= TOLERANCE * self._pre_dtw)
            if stable or waited > RECOVERY_CAP:
                self.rec_n += 1
                self.recovery = _ew(self.recovery, min(waited, RECOVERY_CAP), self.rec_n)
                self._recov_start = None
            return
        if heating and dtw is not None and dtw > 1.0 and self._start is None:
            self._pre_dtw = dtw if self._pre_dtw is None else self._pre_dtw + 0.05 * (dtw - self._pre_dtw)

    def wait_minutes(self, default: float) -> float:
        if self.rec_n >= MIN_EVENTS and self.recovery is not None:
            return min(RECOVERY_CAP, max(1.0, 1.25 * self.recovery + 0.5))
        return default

    def minutes_until_next(self, now: datetime) -> float | None:
        """Expected minutes until the next defrost (negative = overdue); None until 3 cycles are known."""
        if self.n < 3 or self.interval is None or self.last_start is None:
            return None
        return round((self.last_start + timedelta(minutes=self.interval) - now).total_seconds() / 60.0, 1)

    def minutes_since_last(self, now: datetime) -> float | None:
        return None if self.last_start is None else (now - self.last_start).total_seconds() / 60.0

    def summary(self) -> dict:
        r = lambda x: None if x is None else round(x, 1)
        return {"aantal": self.n, "duur_min": r(self.dur), "interval_min": r(self.interval),
                "herstel_min": r(self.recovery), "unit_buiten_temp": r(self.unit_t)}

    def to_dict(self) -> dict:
        return {"n": self.n, "rec_n": self.rec_n, "dur": self.dur, "interval": self.interval,
                "recovery": self.recovery, "unit_t": self.unit_t,
                "last_start": self.last_start.isoformat() if self.last_start else None,
                "last_end": self.last_end.isoformat() if self.last_end else None,
                "last_interval": self.last_interval}

    def from_dict(self, d: dict) -> None:
        d = d or {}
        self.n, self.rec_n = int(d.get("n", 0)), int(d.get("rec_n", 0))
        self.dur, self.interval = d.get("dur"), d.get("interval")
        self.recovery, self.unit_t = d.get("recovery"), d.get("unit_t")
        ls = d.get("last_start")
        self.last_start = datetime.fromisoformat(ls) if ls else None
        le = d.get("last_end")
        self.last_end = datetime.fromisoformat(le) if le else None
        self.last_interval = d.get("last_interval")
