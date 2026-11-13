"""Defrost quality from the heat pump's own coil (evaporator) temperature.

The coil temperature (e.g. the Tuya datapoint 'pg_temp') jumps by tens of kelvin during a defrost.
That makes it a faster and more reliable defrost detector than the water temperatures, and its
peak tells whether the defrost actually melted the ice:

  * healthy defrost  : coil peaks at 25-45 degC
  * ineffective      : coil peaks at 0-12 degC; ice stays and builds up cycle after cycle

Observed on a real installation: with a too short defrost time and too low end temperature
every defrost peaked at 0.6-3 degC and the unit iced up within hours. The reference is learned
(`peak_ref`), the absolute floor is WEAK_PEAK.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

RISE_K = 6.0            # coil rise within RISE_S that marks the start of a defrost
RISE_S = 100
EVENT_MIN = 5.0         # minutes after the start in which the peak is taken
PRE_MIN = 12.0          # minutes before the start in which the minimum (ice load) is taken
WEAK_PEAK = 15.0        # absolute: below this a defrost has not melted the ice
COLD_PRE = -12.0        # coil colder than this right before a defrost = heavily iced


class CoilTracker:
    def __init__(self) -> None:
        self._hist: deque = deque()
        self._start: datetime | None = None
        self._peak: float | None = None
        self._pre: float | None = None
        self._cool_until: datetime | None = None
        self.peak_ref: float | None = None
        self.last_peak: float | None = None
        self.last_pre: float | None = None
        self.last_start: datetime | None = None
        self.weak_streak = 0
        self.n = 0

    # ---------------------------------------------------------------- update
    def update(self, now: datetime, coil: float | None, heating: bool) -> bool:
        """Feed one sample; returns True while a defrost is in progress according to the coil."""
        if coil is None:
            return False
        self._hist.append((now, coil))
        while self._hist and now - self._hist[0][0] > timedelta(minutes=PRE_MIN + 4):
            self._hist.popleft()

        if self._start is None:
            if heating and (self._cool_until is None or now >= self._cool_until):
                old = [c for t, c in self._hist if timedelta(seconds=20) <= now - t <= timedelta(seconds=RISE_S)]
                if old and coil - min(old) >= RISE_K:
                    self._start, self._peak = now, coil
                    before = [c for t, c in self._hist if now - t >= timedelta(seconds=RISE_S)
                              and now - t <= timedelta(minutes=PRE_MIN + 2)]
                    self._pre = min(before) if before else None
            return self._start is not None

        self._peak = max(self._peak, coil)
        if now - self._start >= timedelta(minutes=EVENT_MIN):
            self._finish(now)
            return False
        # the defrost is over when the coil falls well off its peak again
        return not (self._peak - coil >= 8.0 and now - self._start >= timedelta(minutes=1))

    def _finish(self, now: datetime) -> None:
        peak = self._peak
        weak = peak < WEAK_PEAK or (self.peak_ref is not None and self.n >= 3 and peak < 0.5 * self.peak_ref)
        self.last_peak, self.last_pre, self.last_start = peak, self._pre, self._start
        self.n += 1
        if weak:
            self.weak_streak += 1
        else:
            self.weak_streak = 0
            self.peak_ref = peak if self.peak_ref is None else self.peak_ref + 0.2 * (peak - self.peak_ref)
        self._start = self._peak = self._pre = None
        self._cool_until = now + timedelta(minutes=10)

    # ---------------------------------------------------------------- read-out
    @property
    def cold(self) -> bool:
        return self.last_pre is not None and self.last_pre < COLD_PRE

    def summary(self) -> dict:
        r = lambda x: None if x is None else round(x, 1)
        return {"laatste_piek": r(self.last_peak), "voor_ontdooien_min": r(self.last_pre),
                "referentie_piek": r(self.peak_ref), "zwakke_reeks": self.weak_streak, "aantal": self.n}

    def to_dict(self) -> dict:
        return {"peak_ref": self.peak_ref, "n": self.n, "weak": self.weak_streak,
                "last_peak": self.last_peak, "last_pre": self.last_pre}

    def from_dict(self, d: dict) -> None:
        d = d or {}
        self.peak_ref, self.n = d.get("peak_ref"), int(d.get("n", 0))
        self.weak_streak = int(d.get("weak", 0))
        self.last_peak, self.last_pre = d.get("last_peak"), d.get("last_pre")
