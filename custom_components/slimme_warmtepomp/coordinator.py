"""Coordinator: reads Home Assistant states, runs the engine, applies its decision."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONTROL_MODE, CONF_CURRENT, CONF_GRID, CONF_UNIT_OUTSIDE, CONF_COIL, CONF_HOLIDAY, CONF_OPEN_SENSORS, CONF_PRESENCE, CONF_RETURN_TIME, CONF_DHW_SETPOINT, CONF_DHW_SWITCH, CONF_DHW_TEMP, CONF_FLOOR,
    CONF_FLOW, CONF_FLOW_RATE_1, CONF_FLOW_RATE_2, CONF_FREQ, CONF_OUTSIDE, CONF_POWER, CONF_PRICE,
    CONF_PV, CONF_RETURN, CONF_ROOM, CONF_EXTRA_ROOMS, CONF_ROOM_MODE, CONF_FLOW_RATES, CONF_NOTIFY, CONF_PUMP_PROFILE, CONF_STEP, CONF_SWITCH, CONF_TARGET, CONF_VOLTAGE, CONF_WEATHER,
    DOMAIN, FORECAST_REFRESH_MIN, FORECAST_TYPES, SAVE_INTERVAL_MIN, UPDATE_INTERVAL_MIN, VERSION,
)
from .engine.rooms import combine as combine_rooms
from .engine.health import SensorHealth
from .engine.i18n import lang, msg, role_name
from .engine.controller import Decision, Inputs, PROGRAM_DAY, SmartController
from .engine.prices import parse_price_forecast
from .engine.settings import NUMBER_SPECS, DEFAULTS, PROFILE_PRESETS, SWITCH_DEFAULTS

_LOGGER = logging.getLogger(__name__)
_BAD = ("unknown", "unavailable", "none", "")


class SmartHeatpumpCoordinator(DataUpdateCoordinator[Decision]):
    """Owns the controller, the user settings and the persisted learning state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MIN),
        )
        self.entry = entry
        self.controller = SmartController()
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        # user-facing state, written by the entities
        self.settings: dict[str, float] = {**DEFAULTS, **PROFILE_PRESETS.get(self.cfg.get(CONF_PUMP_PROFILE), {})}
        self.switches: dict[str, bool] = dict(SWITCH_DEFAULTS)
        self.hvac_on = True
        self.preset = PROGRAM_DAY
        self.manual_temp = 21.0
        self.last_setpoint: float | None = None
        self._forecast: list = []
        self._forecast_at: datetime | None = None
        self._forecast_warned = False
        self._forecast_type: str | None = None
        self._last_logged: tuple | None = None
        self._saved_at: datetime | None = None
        self._saved_defrosts = 0.0
        self._coil_samples: list = []
        self.rooms_info: dict = {}
        self.health = SensorHealth()
        self._issues: set[str] = set()
        self._notified: dict[str, datetime] = {}
        self._cold_since: datetime | None = None
        self.week_report: str | None = None
        self.week_data: dict | None = None
        self._week_sent: str | None = None

    # ------------------------------------------------------------------ config
    @property
    def cfg(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    @property
    def has_dhw(self) -> bool:
        return bool(self.cfg.get(CONF_DHW_TEMP))

    def group_enabled(self, group: str) -> bool:
        """Optional entity groups only exist when the matching sensors are configured."""
        cfg = self.cfg
        return {
            "core": True,
            "dhw": bool(cfg.get(CONF_DHW_TEMP)),
            "window": bool(cfg.get(CONF_OPEN_SENSORS)),
            "away": bool(cfg.get(CONF_PRESENCE) or cfg.get(CONF_HOLIDAY)),
            "grid": bool(cfg.get(CONF_GRID)),
            "rooms": bool(cfg.get(CONF_EXTRA_ROOMS)),
            "notify": bool(cfg.get(CONF_NOTIFY)),
        }.get(group, False)

    def flow_rate_entities(self) -> list[str]:
        """The flow sensors (any number); entries from before v2.18 stored two fixed fields."""
        cfg = self.cfg
        lst = cfg.get(CONF_FLOW_RATES)
        if lst is None:
            lst = [cfg.get(CONF_FLOW_RATE_1), cfg.get(CONF_FLOW_RATE_2)]
        return [e for e in (lst if isinstance(lst, list) else [lst]) if e]

    def extra_room_entities(self) -> list[str]:
        rooms = self.cfg.get(CONF_EXTRA_ROOMS) or []
        return [e for e in (rooms if isinstance(rooms, list) else [rooms]) if e]

    # ------------------------------------------------------------------ storage
    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self.controller.import_state(data)
            self._week_sent = (data.get("coordinator") or {}).get("week_sent")

    async def async_save(self) -> None:
        await self._store.async_save({**self.controller.export_state(), "coordinator": {"week_sent": self._week_sent}})
        self._saved_at = dt_util.utcnow()

    # ------------------------------------------------------------------ export / import
    EXPORT_MARK = "slimme_warmtepomp_export"

    def export_bundle(self, include_state: bool = True) -> dict:
        """Settings, switches and (optionally) the learned state: to back up or to share with someone who has the same pump."""
        bundle = {self.EXPORT_MARK: 1, "versie": VERSION, "instellingen": {k: v for k, v in self.settings.items() if k in DEFAULTS},
                  "schakelaars": dict(self.switches)}
        if include_state:
            bundle["leerstatus"] = self.controller.export_state()
        return bundle

    async def import_bundle(self, bundle: dict, include_state: bool = True) -> dict:
        """Apply an export; unknown or invalid entries are skipped and reported."""
        if not isinstance(bundle, dict) or bundle.get(self.EXPORT_MARK) != 1:
            raise HomeAssistantError("Not an export of Slimme Warmtepomp")
        ranges = {s[0]: (s[2], s[3]) for s in NUMBER_SPECS}
        applied, skipped = 0, []
        for key, val in (bundle.get("instellingen") or {}).items():
            try:
                lo, hi = ranges[key]
                self.settings[key] = min(max(float(val), lo), hi)
                applied += 1
            except (KeyError, TypeError, ValueError):
                skipped.append(key)
        for key, val in (bundle.get("schakelaars") or {}).items():
            if key in SWITCH_DEFAULTS and isinstance(val, bool):
                self.switches[key] = val
                applied += 1
            else:
                skipped.append(key)
        learned = False
        if include_state and isinstance(bundle.get("leerstatus"), dict):
            async with self._lock:
                self.controller.import_state(bundle["leerstatus"])
            learned = True
        await self.async_save()
        await self.async_request_refresh()
        return {"toegepast": applied, "overgeslagen": skipped, "leerstatus": learned}

    async def async_reset_model(self, percentage: float = 100.0) -> None:
        async with self._lock:
            self.controller.reset_model(min(100.0, max(1.0, percentage)) / 100.0)
        await self.async_save()
        await self.async_request_refresh()

    # ------------------------------------------------------------------ reading
    def _state(self, entity_id: str | None) -> State | None:
        return self.hass.states.get(entity_id) if entity_id else None

    def _num(self, entity_id: str | None) -> float | None:
        st = self._state(entity_id)
        if st is None or str(st.state).lower() in _BAD:
            return None
        try:
            return float(st.state)
        except ValueError:
            return None

    @callback
    def on_coil_event(self, event) -> None:
        """Remember every change of the coil sensor between two control cycles (event driven, ~1 s resolution)."""
        data = getattr(event, "data", None) or {}
        coil = self.cfg.get(CONF_COIL)
        if not coil or data.get("entity_id") != coil:
            return
        st = data.get("new_state")
        if st is None or str(st.state).lower() in _BAD:
            return
        try:
            self._coil_samples.append((dt_util.now(), float(st.state)))
        except ValueError:
            return
        del self._coil_samples[:-600]

    def _take_coil_samples(self) -> tuple:
        out, self._coil_samples = tuple(self._coil_samples), []
        return out

    def _flow_lh(self, entity_id: str | None) -> float | None:
        val = self._num(entity_id)
        if val is None:
            return None
        unit = str(self._state(entity_id).attributes.get("unit_of_measurement", "")).strip().lower()
        if unit in ("l/s", "liter/seconde", "l/sec"):
            return val * 3600.0
        if unit in ("l/min", "liter/minuut", "l/m"):
            return val * 60.0
        if unit in ("m3/h", "m³/h", "m3/hour"):
            return val * 1000.0
        return val

    def _watts(self, entity_id: str | None) -> float | None:
        val = self._num(entity_id)
        if val is None:
            return None
        unit = str(self._state(entity_id).attributes.get("unit_of_measurement", "")).strip().lower()
        return val * 1000.0 if unit in ("kw", "kilowatt") else val

    def _windows_open(self) -> bool:
        return any(
            (st := self._state(eid)) is not None and st.state in ("on", "open")
            for eid in self.cfg.get(CONF_OPEN_SENSORS) or []
        )

    def _away(self) -> bool:
        """Away = holiday switch on, or presence entities known and none of them 'home'."""
        cfg = self.cfg
        holiday = self._state(cfg.get(CONF_HOLIDAY))
        if holiday is not None and holiday.state == "on":
            return True
        known = [st for eid in cfg.get(CONF_PRESENCE) or []
                 if (st := self._state(eid)) is not None and str(st.state).lower() not in _BAD]
        return bool(known) and not any(st.state in ("home", "on") for st in known)

    def _return_at(self, now: datetime) -> datetime | None:
        st = self._state(self.cfg.get(CONF_RETURN_TIME))
        if st is None or str(st.state).lower() in _BAD:
            return None
        val = str(st.state)
        when = dt_util.parse_datetime(val)
        if when is not None:
            when = when.replace(tzinfo=now.tzinfo) if when.tzinfo is None else dt_util.as_local(when)
        else:
            t = dt_util.parse_time(val)
            if t is None:
                return None
            when = datetime.combine(now.date(), t, tzinfo=now.tzinfo)
        return when if when > now else None

    async def _refresh_forecast(self, now: datetime) -> None:
        entity = self.cfg.get(CONF_WEATHER)
        if not entity:
            return
        if self._forecast_at and now - self._forecast_at < timedelta(minutes=FORECAST_REFRESH_MIN):
            return
        self._forecast_at = now  # also on failure, to avoid hammering the service
        last_err: Exception | None = None
        # not every weather integration serves hourly data: fall back to twice-daily and daily forecasts
        # (coarser, but the planner interpolates) and remember which type works
        types = [self._forecast_type] if self._forecast_type else list(FORECAST_TYPES)
        for ftype in types:
            try:
                resp = await self.hass.services.async_call(
                    "weather", "get_forecasts", {"entity_id": entity, "type": ftype},
                    blocking=True, return_response=True,
                )
                out = self._parse_forecast((resp or {}).get(entity, {}).get("forecast", []), ftype)
            except (HomeAssistantError, KeyError, TypeError, ValueError) as err:
                last_err = err
                continue
            if out:
                if self._forecast_type != ftype:
                    _LOGGER.debug("Weather forecast for %s: using the '%s' forecast", entity, ftype)
                self._forecast_type, self._forecast, self._forecast_warned = ftype, out, False
                return
        self._forecast_type = None      # try all types again next time
        if not self._forecast_warned:
            self._forecast_warned = True
            _LOGGER.warning("Weather forecast unavailable from %s (%s): the planner runs without a forecast until it "
                            "answers a forecast request (hourly, twice daily or daily)", entity, last_err or "empty answer")
        else:
            _LOGGER.debug("Weather forecast unavailable (%s): %s", entity, last_err or "empty answer")

    @staticmethod
    def _parse_forecast(items, ftype: str) -> list:
        out = []
        for it in items or []:
            t = dt_util.parse_datetime(str(it.get("datetime")))
            temp = it.get("temperature")
            if t is None or temp is None:
                continue
            t, temp = dt_util.as_local(t), float(temp)
            if ftype == "daily":
                low = it.get("templow")
                if low is not None:
                    temp = (temp + float(low)) / 2.0          # daily mean, placed at the middle of the day
                t = t.replace(hour=12, minute=0, second=0, microsecond=0)
            out.append((t, temp, it.get("cloud_coverage")))
        return sorted(out, key=lambda x: x[0])

    async def _build_inputs(self) -> Inputs:
        cfg, now = self.cfg, dt_util.now()
        await self._refresh_forecast(now)

        power = self._watts(cfg.get(CONF_POWER))
        if power is None and cfg.get(CONF_VOLTAGE) and cfg.get(CONF_CURRENT):
            v, a = self._num(cfg.get(CONF_VOLTAGE)), self._num(cfg.get(CONF_CURRENT))
            if a is not None:
                power = (v if v is not None else 230.0) * a
        flows = [self._flow_lh(e) for e in self.flow_rate_entities()]
        flow_lh = None if all(f is None for f in flows) else sum(f or 0.0 for f in flows)
        room, self.rooms_info = combine_rooms(
            self._num(cfg.get(CONF_ROOM)), [(e, self._num(e)) for e in self.extra_room_entities()],
            cfg.get(CONF_ROOM_MODE, "hoofd"), self.settings.get("min_extra_kamer", 17.0))

        price_state = self._state(cfg.get(CONF_PRICE))
        forecast = []
        if price_state is not None:
            forecast = parse_price_forecast(dict(price_state.attributes), now)
        pv = self._watts(cfg.get(CONF_PV))

        cloud_now = None
        weather = self._state(cfg.get(CONF_WEATHER))
        if weather is not None:
            try:
                cloud_now = float(weather.attributes.get("cloud_coverage"))
            except (TypeError, ValueError):
                cloud_now = None

        # the outdoor sensor is required; when it is unavailable, fall back to the weather entity's temperature
        outside = self._num(cfg.get(CONF_OUTSIDE))
        if outside is None and weather is not None:
            try:
                outside = float(weather.attributes.get("temperature"))
            except (TypeError, ValueError):
                outside = None

        switch = self._state(cfg.get(CONF_SWITCH))
        sw = switch.state if switch is not None and switch.state in ("on", "off") else None
        target = self._num(cfg.get(CONF_TARGET))

        return Inputs(
            now=now,
            room=room, outside=outside,
            unit_outside=self._num(cfg.get(CONF_UNIT_OUTSIDE)),
            coil_temp=self._num(cfg.get(CONF_COIL)), coil_samples=self._take_coil_samples(),
            flow=self._num(cfg.get(CONF_FLOW)), ret=self._num(cfg.get(CONF_RETURN)),
            floor=self._num(cfg.get(CONF_FLOOR)), freq=self._num(cfg.get(CONF_FREQ)),
            power_w=power, flow_lh=flow_lh, tank=self._num(cfg.get(CONF_DHW_TEMP)),
            price_now=self._num(cfg.get(CONF_PRICE)), price_forecast=forecast, pv_w=pv,
            weather=list(self._forecast), cloud_now=cloud_now,
            lat=self.hass.config.latitude, lon=self.hass.config.longitude,
            control_mode=cfg.get(CONF_CONTROL_MODE, "retour"),
            hvac_on=self.hvac_on, regeling_actief=self.switches["regeling_actief"],
            learning_enabled=self.switches["leren_actief"],
            preheat_enabled=self.switches["voorverwarmen_actief"],
            price_enabled=self.switches["prijssturing_actief"],
            modulation_enabled=self.switches["modulatie_actief"],
            frost_enabled=self.switches["vorstbeveiliging_actief"],
            boost_enabled=self.switches["tekort_boost_actief"],
            cost_fixed_price=self.switches["kosten_vaste_prijs"],
            dhw_enabled=self.has_dhw and self.switches["dhw_actief"],
            preset=self.preset, manual_temp=self.manual_temp, switch_state=sw,
            target_current=target, setpoint_step=float(cfg.get(CONF_STEP, 1.0)),
            windows_open=self._windows_open(), away=self._away(), return_at=self._return_at(now),
            grid_import_w=self._watts(cfg.get(CONF_GRID)),
            settings=dict(self.settings),
        )

    # ------------------------------------------------------------------ acting
    async def _call(self, entity_id: str, domain: str, service: str, data: dict) -> None:
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity_id, **data}, blocking=False)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not call %s.%s on %s: %s", domain, service, entity_id, err)

    async def _set_number(self, entity_id: str, value: float) -> None:
        st = self._state(entity_id)
        if st is not None:
            lo, hi = st.attributes.get("min"), st.attributes.get("max")
            try:
                if lo is not None:
                    value = max(float(lo), value)
                if hi is not None:
                    value = min(float(hi), value)
            except (TypeError, ValueError):
                pass
            try:
                if abs(float(st.state) - value) < 0.05:
                    return  # unchanged: do not spam the device
            except ValueError:
                pass
        await self._call(entity_id, entity_id.split(".")[0], "set_value", {"value": value})

    async def _execute(self, d: Decision) -> None:
        cfg = self.cfg
        if d.revert_manual:
            self.preset = d.program
        if d.setpoint is not None:
            self.last_setpoint = d.setpoint
            if cfg.get(CONF_TARGET) and not d.shadow:
                await self._set_number(cfg[CONF_TARGET], d.setpoint)
        if d.switch and cfg.get(CONF_SWITCH):
            ent = cfg[CONF_SWITCH]
            await self._call(ent, ent.split(".")[0], "turn_on" if d.switch == "on" else "turn_off", {})
        if d.dhw_request is not None and cfg.get(CONF_DHW_SWITCH):
            ent = cfg[CONF_DHW_SWITCH]
            await self._call(ent, ent.split(".")[0], "turn_on" if d.dhw_request else "turn_off", {})
            if d.dhw_request and d.dhw_setpoint and cfg.get(CONF_DHW_SETPOINT):
                await self._set_number(cfg[CONF_DHW_SETPOINT], d.dhw_setpoint)

    # ------------------------------------------------------------------ messages
    @property
    def language(self) -> str:
        return lang(getattr(self.hass.config, "language", "nl"))

    async def _notify(self, kind: str, title: str, message: str, now, *, every_h: float, persistent: bool = False) -> bool:
        """Send a message to the chosen notify services (and optionally as persistent notification), at most
        once per ``every_h`` hours per kind."""
        last = self._notified.get(kind)
        if last is not None and (now - last).total_seconds() < every_h * 3600:
            return False
        self._notified[kind] = now
        if persistent:
            await self.hass.services.async_call("persistent_notification", "create", {
                "title": title, "message": message, "notification_id": f"slimme_warmtepomp_{kind}"}, blocking=False)
        for svc in self.cfg.get(CONF_NOTIFY) or []:
            domain, _, name = str(svc).partition(".")
            if domain and name:
                try:
                    await self.hass.services.async_call(domain, name, {"title": title, "message": message}, blocking=False)
                except HomeAssistantError as err:
                    _LOGGER.warning("Could not send a message through %s: %s", svc, err)
        return True

    async def _notify_frost(self, decision: Decision, now) -> None:
        """Tell the person when the frost protection had to switch the heat pump on."""
        if not decision.frost_forced:
            return
        L = self.language
        why = msg(L, "frost_water" if self.controller.frost_reason == "water" else "frost_outside")
        await self._notify("vorst", msg(L, "frost_title"), msg(L, "frost_body", why=why), now, every_h=6, persistent=True)

    async def _notify_icing(self, decision: Decision, now) -> None:
        """One notification (at most every 12 hours) when the pump seems to be icing up."""
        if decision.ice_level != "ijs":
            return
        L = self.language
        reasons = ", ".join(self._ice_text(r) for r in decision.diag.get("ijsvorming", {}).get("redenen", []))
        await self._notify("ijsvorming", msg(L, "ice_title"), msg(L, "ice_body", reasons=reasons), now, every_h=12, persistent=True)

    def _ice_text(self, reason: str) -> str:
        try:
            return msg(self.language, f"ice_{reason}")
        except KeyError:
            return reason

    async def _notify_cold(self, decision: Decision, inp: Inputs, now) -> None:
        """The room stays colder than wanted for hours: tell the person (the control may be stuck on something)."""
        s = self.settings
        too_cold = (inp.room is not None and self.hvac_on and not decision.summer and not decision.defrost
                    and inp.room < decision.room_setpoint - s.get("melding_te_koud_marge", 1.5))
        if not too_cold:
            self._cold_since = None
            return
        self._cold_since = self._cold_since or now
        hours = (now - self._cold_since).total_seconds() / 3600.0
        if hours >= s.get("melding_te_koud_uren", 3.0):
            L = self.language
            await self._notify("te_koud", msg(L, "cold_title"), msg(
                L, "cold_body", hours=hours, room=inp.room, target=decision.room_setpoint, reason=decision.reason), now, every_h=12)

    # ------------------------------------------------------------------ sensor health (Repairs page)
    def _health_readings(self, now) -> dict:
        cfg, out = self.cfg, {}
        for role, key in (("kamer", CONF_ROOM), ("buiten", CONF_OUTSIDE), ("aanvoer", CONF_FLOW), ("retour", CONF_RETURN),
                          ("vloer", CONF_FLOOR), ("frequentie", CONF_FREQ), ("vermogen", CONF_POWER),
                          ("pomp_setpoint", CONF_TARGET), ("pomp_schakelaar", CONF_SWITCH)):
            ent = cfg.get(key)
            if not ent:
                continue
            st = self._state(ent)
            if st is None:
                out[role] = {"entity": ent, "state": "unavailable", "value": None, "age_h": None}
                continue
            stamp = getattr(st, "last_reported", None) or getattr(st, "last_updated", None)
            age = (now - stamp).total_seconds() / 3600.0 if stamp is not None and hasattr(stamp, "tzinfo") else None
            out[role] = {"entity": ent, "state": st.state,
                         "value": self._watts(ent) if role == "vermogen" else self._num(ent), "age_h": age}
        return out

    async def _check_health(self, now) -> None:
        readings = self._health_readings(now)
        problems = self.health.check(now, readings, self._num(self.cfg.get(CONF_UNIT_OUTSIDE)))
        active = set()
        L = self.language
        for p in problems:
            active.add(p.key)
            text = msg(L, f"health_{p.kind}", entity=p.entity, role=role_name(L, p.role), **p.data)
            if p.key not in self._issues:
                self._issues.add(p.key)
                ir.async_create_issue(
                    self.hass, DOMAIN, p.key, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                    translation_key=p.kind, translation_placeholders={"entity": str(p.entity), "role": role_name(L, p.role),
                    **{k: (f"{v:.1f}" if isinstance(v, float) else str(v)) for k, v in p.data.items()}})
                await self._notify(f"health_{p.key}", msg(L, "health_title"), text, now, every_h=24)
        for key in list(self._issues - active):
            self._issues.discard(key)
            ir.async_delete_issue(self.hass, DOMAIN, key)

    # ------------------------------------------------------------------ weekly report
    async def _weekly_report(self, now_local, decision: Decision) -> None:
        """Monday morning: a summary of the last 7 days (as sensor text, and as message when notify is configured)."""
        key = f"{now_local.isocalendar()[0]}-W{now_local.isocalendar()[1]:02d}"
        rep = self.controller.usage.report(now_local, 7)
        self.week_data = rep
        L = self.language
        if rep:
            cop = f"{rep['kwh_th'] / rep['kwh']:.1f}" if rep["kwh"] > 0.5 and rep["kwh_th"] > 0 else msg(L, "unknown")
            kwh_dd = f"{rep['kwh'] / rep['dd']:.1f}" if rep["dd"] >= 1.0 else msg(L, "unknown")
            comfort = f"{rep['comfort'] * 100:.0f}%" if rep["comfort"] is not None else msg(L, "unknown")
            self.week_report = msg(L, "week_body", days=rep["days"], kwh=rep["kwh"], cost=rep["cost"], cop=cop, kwh_dd=kwh_dd,
                                   comfort=comfort, starts=rep["defrosts"], run_h=rep["run_h"])
        if now_local.weekday() != 0 or now_local.hour < 8 or self._week_sent == key or not rep:
            return
        self._week_sent = key
        if self.switches.get("weekrapport_actief", True) and self.cfg.get(CONF_NOTIFY):
            await self._notify("weekrapport", msg(L, "week_title"), self.week_report, dt_util.utcnow(), every_h=24 * 5)

    # role -> config key: the sensors the user connected (the generated dashboard shows and graphs exactly these)
    _INPUT_ROLES = {
        "kamer": CONF_ROOM, "buiten": CONF_OUTSIDE, "aanvoer": CONF_FLOW, "retour": CONF_RETURN, "vloer": CONF_FLOOR,
        "frequentie": CONF_FREQ, "vermogen": CONF_POWER,
        "spanning": CONF_VOLTAGE, "stroom": CONF_CURRENT, "weer": CONF_WEATHER, "prijs": CONF_PRICE, "zonnepanelen": CONF_PV,
        "net": CONF_GRID, "buiten_unit": CONF_UNIT_OUTSIDE, "coil": CONF_COIL, "tank": CONF_DHW_TEMP,
        "pomp_setpoint": CONF_TARGET, "pomp_schakelaar": CONF_SWITCH,
    }

    def input_entities(self) -> dict[str, str]:
        out = {role: self.cfg[key] for role, key in self._INPUT_ROLES.items() if isinstance(self.cfg.get(key), str) and self.cfg.get(key)}
        for i, ent in enumerate(self.flow_rate_entities(), 1):
            out[f"debiet_{i}"] = ent
        for i, ent in enumerate(self.extra_room_entities(), 2):
            out[f"kamer_{i}"] = ent
        return out

    def _log_changes(self, d: Decision) -> None:
        """One debug line whenever the decision changes in a way that matters (enable with logger: debug)."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        key = (d.reason, d.switch, d.setpoint, d.coasting, d.boost)
        if key != self._last_logged:
            self._last_logged = key
            _LOGGER.debug("Decision: reason=%s setpoint=%s (raw %s) switch=%s coasting=%s limited=%s heating=%s boost=%s room target=%s",
                          d.reason, d.setpoint, d.setpoint_raw, d.switch, d.coasting, d.freq_limited, d.heating, d.boost,
                          d.room_setpoint)

    async def _async_update_data(self) -> Decision:
        try:
            inp = await self._build_inputs()
            async with self._lock:
                decision = await self.hass.async_add_executor_job(self.controller.step, inp)
            if self.extra_room_entities():
                decision.diag["kamers"] = self.rooms_info
            await self._execute(decision)
            self._log_changes(decision)
            now = dt_util.utcnow()
            await self._notify_icing(decision, now)
            await self._notify_frost(decision, now)
            await self._notify_cold(decision, inp, now)
            await self._check_health(now)
            await self._weekly_report(dt_util.now(), decision)
            # save at once when a defrost was counted (so a restart never loses it), else every N minutes
            defrosts = self.controller.usage.cur.get("day", {}).get("defrosts", 0.0)
            new_defrost = defrosts > self._saved_defrosts
            self._saved_defrosts = defrosts
            if new_defrost or self._saved_at is None or now - self._saved_at > timedelta(minutes=SAVE_INTERVAL_MIN):
                await self.async_save()
            return decision
        except Exception as err:  # noqa: BLE001 - keep the loop alive, show the last decision
            _LOGGER.exception("Control cycle failed")
            raise UpdateFailed(str(err)) from err
