"""Guess which of the user's entities play which role (plain Python, no Home Assistant imports).

Used by the setup wizard to pre-fill the selectors; every suggestion can be changed. The guess looks at the unit of
measurement and at words in the name or entity id, Dutch and English: a sensor in °C called "..._retour_temp" is
the return temperature, one in Hz is the compressor frequency, a number called "..._setpoint" is the pump's setpoint.
"""
from __future__ import annotations

import re
from typing import NamedTuple


class Candidate(NamedTuple):
    entity_id: str
    name: str
    unit: str | None = None
    device_class: str | None = None
    platform: str | None = None


TEMP = ("°c", "c")
FLOW_UNITS = ("l/min", "l/h", "l/s", "m3/h", "m³/h", "lph", "l/m")

# role: (domains, units, keywords, avoid)
RULES: dict[str, tuple] = {
    "retour": (("sensor",), TEMP, ("retour", "return", "inlet", "terug"), ("rate", "debiet", "setpoint")),
    "aanvoer": (("sensor",), TEMP, ("aanvoer", "supply", "outlet", "vertrek", "uitlaat"), ("rate", "debiet", "setpoint")),
    "vloer": (("sensor",), TEMP, ("vloer", "floor", "screed", "dekvloer"), ()),
    "coil": (("sensor",), TEMP, ("coil", "pg", "verdamper", "evaporator"), ()),
    "buiten": (("sensor",), TEMP, ("buiten", "outside", "outdoor", "ambient", "omgeving"), ("unit", "pomp", "pg", "coil")),
    "buiten_unit": (("sensor",), TEMP, ("buiten", "outside", "outdoor", "ambient", "omgeving", "unit"), ()),
    "kamer": (("sensor",), TEMP, ("woonkamer", "living", "room", "kamer", "lounge"), ("buiten", "outside", "outdoor", "slaap")),
    "frequentie": (("sensor",), ("hz",), ("frequentie", "frequency", "compressor", "freq"), ()),
    "vermogen": (("sensor",), ("w", "kw"), ("vermogen", "power", "verbruik", "watt"), ("thermisch", "thermal", "cop", "delta")),
    "spanning": (("sensor",), ("v",), ("spanning", "voltage", "volt"), ("dc",)),
    "stroom": (("sensor",), ("a",), ("stroom", "current", "ampere", "amp"), ()),
    "debiet": (("sensor",), FLOW_UNITS, ("flow", "debiet", "doorstroming", "rate", "lph"), ("temp",)),
    "pomp_setpoint": (("number", "input_number"), None, ("setpoint", "target", "doel", "instelwaarde"), ("dhw", "tap", "freq", "defrost")),
    "pomp_schakelaar": (("switch", "input_boolean"), None, ("schakelaar", "switch", "aan", "power", "onoff", "on"), ("dhw", "tap")),
}


def _tokens(c: Candidate) -> set[str]:
    text = f"{c.name} {c.entity_id.split('.', 1)[-1]}".lower()
    return set(t for t in re.split(r"[^a-z0-9]+", text) if t)


def score(role: str, c: Candidate) -> int:
    domains, units, keywords, avoid = RULES[role]
    if c.entity_id.split(".", 1)[0] not in domains:
        return 0
    toks = _tokens(c)
    text = " ".join(sorted(toks))
    unit = (c.unit or "").strip().lower()
    if units is not None and unit not in units:
        return 0
    if any(a in toks or (len(a) > 3 and a in text) for a in avoid):
        return 0
    hits = sum(1 for k in keywords if k in toks or (len(k) > 3 and k in text))
    if hits == 0:
        return 0
    return hits + (1 if units is not None else 0)


def suggest(cands: list[Candidate], pump_platform: str | None = None) -> dict[str, object]:
    """role -> entity_id (``debiet`` -> list). Pump-only roles prefer the pump's integration when one was chosen;
    the controller's own outdoor temperature (``buiten``) and the room sensor deliberately do not come from it."""
    pump_roles = {"retour", "aanvoer", "coil", "frequentie", "spanning", "stroom", "buiten_unit", "pomp_setpoint", "pomp_schakelaar"}
    own_roles = {"buiten", "kamer"}
    out: dict[str, object] = {}
    used: set[str] = set()
    ranked: list[tuple[int, int, str, Candidate]] = []
    for role in RULES:
        for c in cands:
            s = score(role, c)
            if s <= 0:
                continue
            from_pump = pump_platform is not None and c.platform == pump_platform
            if pump_platform and role in pump_roles and not from_pump:
                s -= 2
            if pump_platform and role in own_roles and from_pump:
                s -= 2
            if s > 0:
                ranked.append((s, -len(c.entity_id), role, c))
    ranked.sort(key=lambda x: (-x[0], x[1], x[3].entity_id))
    for s, _, role, c in ranked:
        if c.entity_id in used:
            continue
        if role == "debiet":
            out.setdefault("debiet", [])
            out["debiet"].append(c.entity_id)           # type: ignore[union-attr]
            used.add(c.entity_id)
        elif role not in out:
            out[role] = c.entity_id
            used.add(c.entity_id)
    return out
