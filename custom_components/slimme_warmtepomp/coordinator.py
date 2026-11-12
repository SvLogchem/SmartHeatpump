"""Coordinator: reads Home Assistant states, runs the engine, applies its decision."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONTROL_MODE, CONF_CURRENT, CONF_GRID, CONF_HOLIDAY, CONF_OPEN_SENSORS, CONF_PRESENCE, CONF_RETURN_TIME, CONF_DHW_SETPOINT, CONF_DHW_SWITCH, CONF_DHW_TEMP, CONF_FLOOR,
    CONF_FLOW, CONF_FLOW_RATE_1, CONF_FLOW_RATE_2, CONF_FREQ, CONF_OUTSIDE, CONF_POWER, CONF_PRICE,
    CONF_PV, CONF_RETURN, CONF_ROOM, CONF_STEP, CONF_SWITCH, CONF_TARGET, CONF_VOLTAGE, CONF_WEATHER,
    DOMAIN, FORECAST_REFRESH_MIN, SAVE_INTERVAL_MIN, UPDATE_INTERVAL_MIN,
)
from .engine.controller import Decision, Inputs, PROGRAM_DAY, SmartController
from .engine.prices import parse_price_forecast
from .engine.settings import DEFAULTS, SWITCH_DEFAULTS

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
        self.settings: dict[str, float] = dict(DEFAULTS)
        self.switches: dict[str, bool] = dict(SWITCH_DEFAULTS)
        self.hvac_on = True
        self.preset = PROGRAM_DAY
        self.manual_temp = 21.0
        self.last_setpoint: float | None = None
        self._forecast: list = []
        self._forecast_at: datetime | None = None
        self._saved_at: datetime | None = None

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
        }.get(group, False)

    # ------------------------------------------------------------------ storage
    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self.controller.import_state(data)

    async def async_save(self) -> None:
        await self._store.async_save(self.controller.export_state())
        self._saved_at = dt_util.utcnow()

    async def async_reset_model(self) -> None:
        async with self._lock:
            self.controller.reset_model()
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
        try:
            resp = await self.hass.services.async_call(
                "weather", "get_forecasts", {"entity_id": entity, "type": "hourly"},
                blocking=True, return_response=True,
            )
            items = (resp or {}).get(entity, {}).get("forecast", [])
            out = []
            for it in items:
                t = dt_util.parse_datetime(str(it.get("datetime")))
                temp = it.get("temperature")
                if t is None or temp is None:
                    continue
                out.append((dt_util.as_local(t), float(temp), it.get("cloud_coverage")))
            self._forecast = sorted(out, key=lambda x: x[0])
        except (HomeAssistantError, KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Weather forecast unavailable (%s): %s", entity, err)

    async def _build_inputs(self) -> Inputs:
        cfg, now = self.cfg, dt_util.now()
        await self._refresh_forecast(now)

        power = self._watts(cfg.get(CONF_POWER))
        if power is None and cfg.get(CONF_VOLTAGE) and cfg.get(CONF_CURRENT):
            v, a = self._num(cfg.get(CONF_VOLTAGE)), self._num(cfg.get(CONF_CURRENT))
            if a is not None:
                power = (v if v is not None else 230.0) * a
        f1, f2 = self._flow_lh(cfg.get(CONF_FLOW_RATE_1)), self._flow_lh(cfg.get(CONF_FLOW_RATE_2))
        flow_lh = None if f1 is None and f2 is None else (f1 or 0.0) + (f2 or 0.0)

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

        switch = self._state(cfg.get(CONF_SWITCH))
        sw = switch.state if switch is not None and switch.state in ("on", "off") else None
        target = self._num(cfg.get(CONF_TARGET))

        return Inputs(
            now=now,
            room=self._num(cfg.get(CONF_ROOM)), outside=self._num(cfg.get(CONF_OUTSIDE)),
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

    async def _async_update_data(self) -> Decision:
        try:
            inp = await self._build_inputs()
            async with self._lock:
                decision = await self.hass.async_add_executor_job(self.controller.step, inp)
            await self._execute(decision)
            now = dt_util.utcnow()
            if self._saved_at is None or now - self._saved_at > timedelta(minutes=SAVE_INTERVAL_MIN):
                await self.async_save()
            return decision
        except Exception as err:  # noqa: BLE001 - keep the loop alive, show the last decision
            _LOGGER.exception("Control cycle failed")
            raise UpdateFailed(str(err)) from err
