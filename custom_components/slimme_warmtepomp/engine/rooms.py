"""Several room temperature sensors -> the one temperature the controller regulates on (plain Python).

The heat pump has a single water circuit, so rooms cannot be heated separately. What can be done is choosing how
the rooms count:

* ``hoofd``      the main room leads; every other room only has a minimum (guard rooms): when one is colder than
                 that minimum the controller gets a shortfall of the same size (at most MAX_GUARD_K) as extra
                 heat demand, so the heating works until the guard room is back above its minimum. The shortfall
                 is reported separately (``tekort_bewaakt``): the temperature itself stays the main room's real
                 temperature, because that is what the learned house model, the evening correction and the
                 heating-curve correction must see.
* ``gemiddelde`` the mean of all rooms.
* ``koudste``    the coldest room decides.

A guard room (or any other extra room) that drops out is simply left out. Without the main sensor the result is
None: the setpoint is a target for the main room, so the other rooms must not take its place (the controller
then holds its last state, as for any missing room sensor).
"""
from __future__ import annotations

MODES = ("hoofd", "gemiddelde", "koudste")
DEFAULT_MODE = "hoofd"
MAX_GUARD_K = 3.0


def combine(main: float | None, extras: list[tuple[str, float | None]], mode: str, guard_min: float) -> tuple[float | None, dict]:
    """Return (temperature to regulate on, details for the diagnostics)."""
    mode = mode if mode in MODES else DEFAULT_MODE
    known = [v for _, v in extras if v is not None]
    info = {"modus": mode, "hoofd": main, "extra": {name: v for name, v in extras}}
    if main is None:
        info["gebruikt"] = None
        info["reden"] = "hoofdsensor_weg"
        return None, info
    if not extras:
        info["gebruikt"] = main
        return main, info
    allv = [main] + known
    if mode == "gemiddelde":
        value = sum(allv) / len(allv)
    elif mode == "koudste":
        value = min(allv)
    else:
        value = main
        info["tekort_bewaakt"] = round(min(max([guard_min - v for v in known] + [0.0]), MAX_GUARD_K), 2)
    info["gebruikt"] = round(value, 2)
    return value, info
