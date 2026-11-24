"""Sensor health: unavailable, stale and implausible readings, and two outdoor sensors that disagree (plain Python).

Every problem must last for a while before it is reported (a dropped reading for a minute is normal) and is
cleared again as soon as the reading is fine, so the Repairs page of Home Assistant only shows what is true now.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple

UNAVAILABLE_AFTER = timedelta(minutes=30)
IMPLAUSIBLE_AFTER = timedelta(minutes=10)
OUTSIDE_MISMATCH_AFTER = timedelta(hours=2)
STALE_HOURS = 6.0
OUTSIDE_MISMATCH_K = 8.0

# role -> (min, max) of a believable reading, and whether the sensor should keep reporting
LIMITS = {
    "kamer": (0.0, 40.0), "buiten": (-40.0, 50.0), "aanvoer": (-5.0, 80.0), "retour": (-5.0, 80.0),
    "vloer": (0.0, 50.0), "frequentie": (0.0, 150.0), "vermogen": (0.0, 40000.0),
}
LIVE = ("kamer", "buiten", "aanvoer", "retour", "vloer", "frequentie", "vermogen")
BAD = ("unknown", "unavailable", "none", "")


class Problem(NamedTuple):
    key: str           # issue id, e.g. "unavailable_retour"
    kind: str          # unavailable | stale | implausible | outside
    role: str
    entity: str
    data: dict


class SensorHealth:
    def __init__(self) -> None:
        self._since: dict[str, datetime] = {}

    def _held(self, key: str, active: bool, now: datetime, after: timedelta) -> bool:
        if not active:
            self._since.pop(key, None)
            return False
        first = self._since.setdefault(key, now)
        return now - first >= after

    def check(self, now: datetime, readings: dict[str, dict], unit_outside: float | None = None) -> list[Problem]:
        """readings: role -> {"entity", "state" (str), "value" (float|None), "age_h" (float|None)}."""
        out: list[Problem] = []
        for role, r in readings.items():
            ent, state, val, age = r.get("entity"), str(r.get("state", "")).lower(), r.get("value"), r.get("age_h")
            gone = state in BAD
            if self._held(f"unavailable_{role}", gone, now, UNAVAILABLE_AFTER):
                out.append(Problem(f"unavailable_{role}", "unavailable", role, ent, {}))
            stale = (not gone) and role in LIVE and age is not None and age >= STALE_HOURS
            if self._held(f"stale_{role}", stale, now, timedelta(0)):
                out.append(Problem(f"stale_{role}", "stale", role, ent, {"hours": age}))
            lim = LIMITS.get(role)
            bad_val = (not gone) and lim is not None and val is not None and not (lim[0] <= val <= lim[1])
            if self._held(f"implausible_{role}", bad_val, now, IMPLAUSIBLE_AFTER):
                out.append(Problem(f"implausible_{role}", "implausible", role, ent, {"value": val}))
        outside = readings.get("buiten", {}).get("value")
        mism = (outside is not None and unit_outside is not None and abs(outside - unit_outside) >= OUTSIDE_MISMATCH_K)
        if self._held("outside_mismatch", mism, now, OUTSIDE_MISMATCH_AFTER):
            out.append(Problem("outside_mismatch", "outside", "buiten", readings["buiten"].get("entity"),
                               {"a": outside, "b": unit_outside, "diff": abs(outside - unit_outside)}))
        return out
