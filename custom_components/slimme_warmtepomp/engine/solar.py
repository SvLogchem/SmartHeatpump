"""Approximate solar elevation (NOAA formulas) and a simple sun-gain proxy."""
from __future__ import annotations

import math
from datetime import datetime, timezone


def solar_elevation(when: datetime, lat: float, lon: float) -> float:
    """Elevation of the sun above the horizon in degrees."""
    utc = when.astimezone(timezone.utc)
    doy = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    g = 2.0 * math.pi / 365.0 * (doy - 1 + (hour - 12.0) / 24.0)
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g)
    )
    decl = (
        0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g)
    )
    tst = hour * 60.0 + eqtime + 4.0 * lon
    ha = math.radians(tst / 4.0 - 180.0)
    la = math.radians(lat)
    cos_zen = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    cos_zen = min(1.0, max(-1.0, cos_zen))
    return 90.0 - math.degrees(math.acos(cos_zen))


def sun_gain(when: datetime, lat: float, lon: float, cloud_pct: float | None) -> float:
    """Dimensionless 0..1 proxy for solar heat gain (the model learns the scale)."""
    elev = solar_elevation(when, lat, lon)
    if elev <= 0:
        return 0.0
    cloud = 50.0 if cloud_pct is None else min(100.0, max(0.0, cloud_pct))
    return math.sin(math.radians(elev)) * (1.0 - 0.75 * cloud / 100.0)
