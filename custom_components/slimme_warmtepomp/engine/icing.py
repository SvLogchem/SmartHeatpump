"""Watches for a heat pump that cannot get rid of its ice.

A clean evaporator gives a certain COP right after each defrost. Ice builds up between
defrosts and the COP sags; a good defrost brings it back. When defrosts stop restoring the
COP, come ever more often, do not happen when they should, or the COP collapses, the unit is
icing up (wrong defrost settings: interval, start/stop temperature, maximum time). We cannot
change the pump's own settings, but we can see it early and say so.

Signals (each is learned relative to this installation, no fixed physics):
  cop_zakt         COP now < 70 % of the COP right after the last defrosts
  herstelt_niet    the post-defrost COP itself dropped > 20 % versus its long-term level
  vaker            time between defrosts fell below 60 % of the usual interval
  ontdooit_te_laat no defrost for > 2.2 x the usual interval although it is cold and heating
  pomp_sensor_koud the pump's own outdoor sensor is > 4 K colder (relative to the real outside
                   temperature) than right after a defrost
  kritiek          COP below 1.6 for 15 minutes while the compressor runs
"""
from __future__ import annotations

from datetime import datetime, timedelta

POST_WINDOW_MIN = 12.0
LEVELS = ("ok", "let_op", "ijs")


def _ew(old, new, a):
    return new if old is None else old + a * (new - old)


class IcingMonitor:
    def __init__(self) -> None:
        self.cop_ref: float | None = None
        self.cop_slow: float | None = None
        self.ref_n = 0
        self.unit_ref: float | None = None
        self.ema: float | None = None
        self.ema_n = 0
        self.level = "ok"
        self.reasons: list[str] = []
        self._seen_end: datetime | None = None
        self._post_cops: list[float] = []
        self._post_units: list[float] = []
        self._low_since: datetime | None = None
        self._hold_until: datetime | None = None

    def update(self, now: datetime, *, cop: float, heating: bool, settling: bool, defrost: bool,
               unit_diff: float | None, outside: float | None, freq_running: bool,
               last_end: datetime | None, last_interval: float | None, mean_interval: float | None,
               n_defrosts: int, since_last_min: float | None) -> None:
        # a new defrost just ended: open the window in which the clean-coil COP is measured
        if last_end is not None and last_end != self._seen_end:
            self._close_post_window()
            self._seen_end = last_end
            self.ema, self.ema_n = None, 0
        in_post = last_end is not None and (now - last_end) <= timedelta(minutes=POST_WINDOW_MIN)
        steady = heating and not settling and not defrost and cop > 0
        if steady:
            if in_post:
                self._post_cops.append(cop)
                if unit_diff is not None:
                    self._post_units.append(unit_diff)
            else:
                self.ema = cop if self.ema is None else self.ema + 0.15 * (cop - self.ema)
                self.ema_n += 1
        elif not in_post:
            self._close_post_window()

        reasons: list[str] = []
        if (self.ema is not None and self.cop_ref and self.ref_n >= 2 and self.ema_n >= 8
                and self.ema < 0.7 * self.cop_ref):
            reasons.append("cop_zakt")
        if self.ref_n >= 5 and self.cop_ref and self.cop_slow and self.cop_ref < 0.8 * self.cop_slow:
            reasons.append("herstelt_niet")
        if n_defrosts >= 5 and last_interval and mean_interval and last_interval < 0.6 * mean_interval:
            reasons.append("vaker")
        if (n_defrosts >= 5 and mean_interval and since_last_min is not None and heating
                and outside is not None and outside < 5.0 and since_last_min > 2.2 * mean_interval):
            reasons.append("ontdooit_te_laat")
        if (unit_diff is not None and self.unit_ref is not None and not in_post and not defrost
                and unit_diff < self.unit_ref - 4.0):
            reasons.append("pomp_sensor_koud")
        critical = False
        if self.ema is not None and self.ema < 1.6 and freq_running and heating and not settling:
            self._low_since = self._low_since or now
            critical = now - self._low_since >= timedelta(minutes=15)
        else:
            self._low_since = None
        if critical:
            reasons.append("kritiek")

        new = "ijs" if critical or len(reasons) >= 2 else "let_op" if reasons else "ok"
        if LEVELS.index(new) >= LEVELS.index(self.level):
            self.level, self.reasons = new, reasons
            self._hold_until = now + timedelta(minutes=30)
        elif self._hold_until is not None and now >= self._hold_until:
            self.level, self.reasons = new, reasons

    def _close_post_window(self) -> None:
        if len(self._post_cops) >= 3:
            ref = sum(self._post_cops) / len(self._post_cops)
            self.ref_n += 1
            self.cop_ref = _ew(self.cop_ref, ref, 0.3)
            if self.ref_n >= 2:
                self.cop_slow = _ew(self.cop_slow, ref, 0.1 if self.cop_slow is not None else 1.0)
            if self._post_units:
                self.unit_ref = _ew(self.unit_ref, sum(self._post_units) / len(self._post_units), 0.3)
        self._post_cops, self._post_units = [], []

    def summary(self) -> dict:
        r = lambda x: None if x is None else round(x, 2)
        return {"niveau": self.level, "redenen": list(self.reasons), "cop_na_ontdooien": r(self.cop_ref),
                "cop_nu": r(self.ema)}

    def to_dict(self) -> dict:
        return {"cop_ref": self.cop_ref, "cop_slow": self.cop_slow, "ref_n": self.ref_n,
                "unit_ref": self.unit_ref}

    def from_dict(self, d: dict) -> None:
        d = d or {}
        self.cop_ref, self.cop_slow = d.get("cop_ref"), d.get("cop_slow")
        self.ref_n, self.unit_ref = int(d.get("ref_n", 0)), d.get("unit_ref")
