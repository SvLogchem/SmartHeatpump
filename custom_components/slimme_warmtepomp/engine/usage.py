"""Usage statistics: degree days, kWh per degree day, cost, run time and defrosts per period.

Replaces the hand-made YAML package (template sensors, utility meters, history_stats). Everything
is accumulated here from the same measurements as the energy sensors, persisted with the model and
compared per day for smart control on / off (shadow mode).
"""
from __future__ import annotations

from datetime import datetime, timedelta

HISTORY_DAYS = 400
MIN_DD_DAY = 0.5      # below this a day is too mild to say anything about kWh per degree day
MIN_DD_WEEK = 1.0
COMPARE_DAYS = 28
DEFROST_GAP = timedelta(minutes=5)

_FIELDS = ("dd", "kwh", "kwh_th", "cost", "run_min", "defrosts", "reg_s", "tot_s")


def _blank() -> dict:
    return {f: 0.0 for f in _FIELDS}


def _keys(now: datetime) -> dict:
    iso = now.isocalendar()
    return {"day": now.date().isoformat(), "week": f"{iso[0]}-W{iso[1]:02d}",
            "month": now.strftime("%Y-%m"), "year": now.strftime("%Y")}


class UsageStats:
    def __init__(self) -> None:
        self.cur: dict[str, dict] = {}          # period -> {"key": str, **sums}
        self.history: dict[str, dict] = {}      # iso date -> finished day
        self._was_defrost = False
        self._last_defrost: datetime | None = None

    # ------------------------------------------------------------------ update
    def update(self, now: datetime, *, dt_h: float, e_dt: float, outside: float | None, base: float,
               el_kwh: float, th_kwh: float, price: float | None, heating: bool, defrost: bool,
               regeling_actief: bool) -> None:
        keys = _keys(now)
        for period, key in keys.items():
            c = self.cur.get(period)
            if c is None or c["key"] != key:
                if period == "day" and c is not None:
                    self._close_day(c)
                self.cur[period] = {"key": key, **_blank()}
        add = {"kwh": el_kwh, "kwh_th": th_kwh, "tot_s": dt_h * 3600.0,
               "reg_s": dt_h * 3600.0 if regeling_actief else 0.0,
               "run_min": e_dt * 60.0 if heating else 0.0,
               "cost": el_kwh * price if price is not None else 0.0}
        if outside is not None:
            add["dd"] = max(0.0, base - outside) * dt_h / 24.0
        if defrost and not self._was_defrost and (self._last_defrost is None
                                                  or now - self._last_defrost >= DEFROST_GAP):
            add["defrosts"] = 1.0
            self._last_defrost = now
        self._was_defrost = defrost
        for c in self.cur.values():
            for f, v in add.items():
                c[f] += v

    def _close_day(self, c: dict) -> None:
        self.history[c["key"]] = {f: round(c[f], 4) for f in _FIELDS}
        for k in sorted(self.history)[:-HISTORY_DAYS]:
            del self.history[k]

    # ----------------------------------------------------------------- read-out
    def summary(self, starts_today: int = 0) -> dict:
        g = lambda p, f: self.cur.get(p, {}).get(f, 0.0)
        out: dict = {}
        for p, nm in (("day", "dag"), ("week", "week"), ("month", "maand")):
            out[f"graaddagen_{nm}"] = round(g(p, "dd"), 2)
        for p, nm in (("day", "dag"), ("week", "week"), ("month", "maand"), ("year", "jaar")):
            out[f"kosten_{nm}"] = round(g(p, "cost"), 2)
        out["kwh_per_graaddag_dag"] = round(g("day", "kwh") / g("day", "dd"), 2) if g("day", "dd") >= MIN_DD_DAY else None
        out["kwh_per_graaddag_week"] = round(g("week", "kwh") / g("week", "dd"), 2) if g("week", "dd") >= MIN_DD_WEEK else None
        out["draaitijd_vandaag"] = round(g("day", "run_min"))
        out["draaitijd_per_start"] = round(g("day", "run_min") / starts_today) if starts_today else None
        out["ontdooien_vandaag"] = int(g("day", "defrosts"))
        week_back = (datetime.fromisoformat(self.cur["day"]["key"]) - timedelta(days=6)).date().isoformat() \
            if "day" in self.cur else None
        past = sum(v["defrosts"] for k, v in self.history.items() if week_back and k >= week_back)
        out["ontdooien_7_dagen"] = int(past + g("day", "defrosts"))
        out.update(self._compare())
        return out

    def _compare(self) -> dict:
        """Average kWh per degree day on days the smart control was mostly on, against mostly off."""
        today = self.cur.get("day", {}).get("key")
        days = [(k, v) for k, v in sorted(self.history.items())[-COMPARE_DAYS:]
                if k != today and v["dd"] >= MIN_DD_DAY and v["tot_s"] > 0]
        on = [v["kwh"] / v["dd"] for _, v in days if v["reg_s"] / v["tot_s"] >= 0.5]
        off = [v["kwh"] / v["dd"] for _, v in days if v["reg_s"] / v["tot_s"] < 0.5]
        avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
        return {"kwh_per_graaddag_regeling": avg(on), "kwh_per_graaddag_schaduw": avg(off),
                "dagen_regeling": len(on), "dagen_schaduw": len(off)}

    # ------------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        return {"cur": self.cur, "history": self.history}

    def from_dict(self, d: dict) -> None:
        d = d or {}
        self.cur = {p: {"key": str(c["key"]), **{f: float(c.get(f, 0.0)) for f in _FIELDS}}
                    for p, c in (d.get("cur") or {}).items()}
        self.history = {k: {f: float(v.get(f, 0.0)) for f in _FIELDS} for k, v in (d.get("history") or {}).items()}
