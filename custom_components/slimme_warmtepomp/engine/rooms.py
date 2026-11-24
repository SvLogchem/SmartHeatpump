"""Several room temperature sensors -> the one temperature the controller regulates on (plain Python).

The heat pump has a single water circuit, so rooms cannot be heated separately. What can be done is choosing how
the rooms count:

* ``hoofd``      the main room leads; every other room only has a minimum (guard rooms): when one is colder than
                 that minimum the controller sees a shortfall of the same size (at most MAX_GUARD_K), so the
                 heating works until the guard room is back above its minimum.
* ``gemiddelde`` the mean of all rooms.
* ``koudste``    the coldest room decides.

A sensor that drops out never stops the control: the remaining sensors are used.
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
    if main is None and not known:
        info["gebruikt"] = None
        return None, info
    if not extras:
        info["gebruikt"] = main
        return main, info
    allv = ([main] if main is not None else []) + known
    if mode == "gemiddelde":
        value = sum(allv) / len(allv)
    elif mode == "koudste":
        value = min(allv)
    else:
        base = main if main is not None else sum(known) / len(known)
        short = max([guard_min - v for v in known] + [0.0])
        value = base - min(short, MAX_GUARD_K)
        info["tekort_bewaakt"] = round(min(short, MAX_GUARD_K), 2)
    info["gebruikt"] = round(value, 2)
    return value, info
