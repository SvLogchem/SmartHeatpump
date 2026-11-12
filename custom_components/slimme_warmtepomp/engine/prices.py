"""Electricity price handling: parse forecast attributes, relative price weights.

Parsing is deliberately tolerant: many price integrations (Nordpool, EPEX
Spot, Frank Energie, ENTSO-E, ...) expose a list of {start, price} dicts as
a state attribute, only with different key names.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, tzinfo

TIME_KEYS = ("start", "start_time", "from", "time", "datetime", "begin", "date")
PRICE_KEYS = ("value", "price", "price_per_kwh", "total", "marketPrice", "energy", "amount")
FLAT_KEYS = ("today", "tomorrow", "prices_today", "prices_tomorrow")


def _to_dt(value, tz: tzinfo) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=tz)
    return None


def _slots_from_dicts(items, tz: tzinfo) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    for it in items:
        if not isinstance(it, dict):
            return []
        t = next((_to_dt(it[k], tz) for k in TIME_KEYS if k in it and _to_dt(it[k], tz)), None)
        p = next((it[k] for k in PRICE_KEYS if k in it and isinstance(it[k], (int, float))), None)
        if t is None or p is None:
            return []
        out.append((t, float(p)))
    return out


def parse_price_forecast(attributes: dict, now: datetime) -> list[tuple[datetime, float]]:
    """Return a sorted list of (slot start, price) from a sensor's attributes."""
    tz = now.tzinfo
    slots: dict[datetime, float] = {}
    for key, val in (attributes or {}).items():
        if isinstance(val, (list, tuple)) and val:
            if isinstance(val[0], dict):
                for t, p in _slots_from_dicts(val, tz):
                    slots.setdefault(t, p)
            elif key in FLAT_KEYS and all(isinstance(v, (int, float)) for v in val):
                day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if "tomorrow" in key:
                    day += timedelta(days=1)
                step = timedelta(hours=24) / len(val)
                for i, p in enumerate(val):
                    slots.setdefault(day + step * i, float(p))
    return sorted(slots.items())


class PriceCurve:
    """Piecewise-constant price curve with relative weights around a reference."""

    def __init__(self, slots, ref: float | None, sensitivity: float = 1.0):
        self.slots = list(slots)
        self.step = timedelta(hours=1)
        if len(self.slots) > 1:
            gaps = [(b[0] - a[0]) for a, b in zip(self.slots, self.slots[1:])]
            self.step = min(gaps) if min(gaps) > timedelta(0) else self.step
        prices = [p for _, p in self.slots]
        self.ref = ref if ref is not None else (statistics.median(prices) if prices else None)
        self.sensitivity = sensitivity
        self._idx = [t for t, _ in self.slots]

    def covers(self, t: datetime) -> bool:
        return bool(self.slots) and self.slots[0][0] <= t < self.slots[-1][0] + self.step

    def price_at(self, t: datetime) -> float | None:
        if not self.covers(t):
            return None
        lo, hi = 0, len(self._idx) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._idx[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return self.slots[lo][1]

    def weight(self, t: datetime) -> float:
        """Relative cost of one unit of electricity at time t (1.0 = typical)."""
        p = self.price_at(t)
        return weight_for(p, self.ref, self.sensitivity)


def weight_for(price: float | None, ref: float | None, sensitivity: float = 1.0) -> float:
    if price is None or ref is None:
        return 1.0
    spread = max(abs(ref), 0.10)
    w = 1.0 + sensitivity * (price - ref) / spread
    return min(4.0, max(0.2, w))


class PriceStats:
    """Rolling 48h price history (used when no forecast is available)."""

    def __init__(self) -> None:
        self.samples: list[tuple[float, float]] = []  # (unix ts, price)

    def add(self, ts: float, price: float) -> None:
        if not self.samples or ts - self.samples[-1][0] >= 600:
            self.samples.append((ts, price))
        cutoff = ts - 48 * 3600
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.pop(0)

    def reference(self) -> float | None:
        if len(self.samples) < 12:
            return None
        return statistics.median(p for _, p in self.samples)

    def to_dict(self) -> dict:
        return {"samples": self.samples[-300:]}

    def from_dict(self, d: dict) -> None:
        try:
            self.samples = [(float(a), float(b)) for a, b in d.get("samples", [])]
        except (TypeError, ValueError):
            self.samples = []
