"""Config flow for Slimme Warmtepomp: a short wizard instead of one long form.

1. installation (control mode, step size, pump profile, the integration the pump comes from)
2. basics (room(s), outdoor, flow/return/floor)
3. pump (frequency, power, coil, flow rate sensors - any number)
4. control (the pump's setpoint and switch)
5. extras: tick what you have (weather and price, solar and grid, windows, presence, hot water, messages);
   only those get a screen of their own.

The same wizard is used to reconfigure; every field then starts with the current value. When the pump's
integration is chosen the pump fields only list entities of that integration, and every field gets a suggested
entity based on unit and name (see engine/suggest.py) that can be changed.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_CONTROL_MODE, CONF_CURRENT, CONF_EXTRA_ROOMS, CONF_FLOOR, CONF_FLOW, CONF_FLOW_RATES, CONF_FREQ, CONF_GRID,
    CONF_COIL, CONF_DHW_SETPOINT, CONF_DHW_SWITCH, CONF_DHW_TEMP, CONF_HOLIDAY, CONF_NOTIFY, CONF_OPEN_SENSORS,
    CONF_OUTSIDE, CONF_POWER, CONF_PRESENCE, CONF_PRICE, CONF_PUMP_PROFILE, CONF_PUMP_SOURCE, CONF_PV, CONF_RETURN,
    CONF_RETURN_TIME, CONF_ROOM, CONF_ROOM_MODE, CONF_STEP, CONF_SWITCH, CONF_TARGET, CONF_UNIT_OUTSIDE, CONF_VOLTAGE,
    CONF_WEATHER, DOMAIN,
)
from .engine.rooms import MODES as ROOM_MODES
from .engine.suggest import Candidate, suggest

CONF_PUMP_FILTER = "pump_source_filter"
PROFILES = ("alsavo", "algemeen")
IGNORED_PLATFORMS = {DOMAIN, "person", "zone", "sun", "weather", "backup", "hassio", "mobile_app", "homeassistant", "met"}

# extras: tick-box key -> (step id, config keys of that step)
EXTRAS = {
    "extra_weer_prijs": ("weer_prijs", [CONF_WEATHER, CONF_PRICE]),
    "extra_zon_net": ("zon_net", [CONF_PV, CONF_GRID]),
    "extra_ramen": ("ramen", [CONF_OPEN_SENSORS]),
    "extra_aanwezigheid": ("aanwezigheid", [CONF_PRESENCE, CONF_HOLIDAY, CONF_RETURN_TIME]),
    "extra_tapwater": ("tapwater", [CONF_DHW_TEMP, CONF_DHW_SWITCH, CONF_DHW_SETPOINT]),
    "extra_meldingen": ("meldingen", [CONF_NOTIFY]),
}
# suggestion role -> config key
ROLE_KEYS = {
    "kamer": CONF_ROOM, "buiten": CONF_OUTSIDE, "aanvoer": CONF_FLOW, "retour": CONF_RETURN, "vloer": CONF_FLOOR,
    "frequentie": CONF_FREQ, "vermogen": CONF_POWER, "spanning": CONF_VOLTAGE, "stroom": CONF_CURRENT, "coil": CONF_COIL,
    "buiten_unit": CONF_UNIT_OUTSIDE, "pomp_setpoint": CONF_TARGET, "pomp_schakelaar": CONF_SWITCH, "debiet": CONF_FLOW_RATES,
}

SENSOR = ["sensor"]
SETTERS = ["number", "input_number"]
SWITCHES = ["switch", "input_boolean"]


def _select(key: str, options: list[str], *, multiple: bool = False) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=options, translation_key=key, multiple=multiple, mode=selector.SelectSelectorMode.DROPDOWN))


def _entity(domain: list[str], *, multiple: bool = False, integration: str | None = None, **kw) -> selector.EntitySelector:
    cfg: dict[str, Any] = {"domain": domain, "multiple": multiple, **kw}
    if integration:
        cfg["integration"] = integration
    return selector.EntitySelector(selector.EntitySelectorConfig(**cfg))


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in data.items() if v not in (None, "", []) and k not in EXTRAS}
    out[CONF_STEP] = float(out.get(CONF_STEP, 1.0))
    return out


class SlimmeWarmtepompConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._queue: list[str] = []
        self._reconfigure = False
        self._suggest: dict[str, object] | None = None

    # ------------------------------------------------------------------ helpers
    def _platforms(self) -> list[str]:
        try:
            return sorted({e.platform for e in er.async_get(self.hass).entities.values()} - IGNORED_PLATFORMS)
        except (AttributeError, TypeError):
            return []

    def _suggestions(self) -> dict[str, object]:
        """Guess the roles once per flow (from unit and name of the entities that exist)."""
        if self._suggest is None:
            source = self._data.get(CONF_PUMP_SOURCE)
            cands = []
            try:
                reg = er.async_get(self.hass)
                for st in self.hass.states.async_all(["sensor", "number", "switch", "input_number", "input_boolean"]):
                    ent = reg.async_get(st.entity_id)
                    cands.append(Candidate(st.entity_id, str(st.attributes.get("friendly_name") or ""),
                                           st.attributes.get("unit_of_measurement"), st.attributes.get("device_class"),
                                           ent.platform if ent else None))
            except (AttributeError, TypeError):
                cands = []
            self._suggest = suggest(cands, source)
        return self._suggest

    def _default(self, key: str):
        """Current value (reconfigure / going back) or the suggestion."""
        if key in self._data:
            return self._data[key]
        if self._reconfigure:
            return None
        for role, conf in ROLE_KEYS.items():
            if conf == key:
                return self._suggestions().get(role)
        return None

    def _opt(self, key: str) -> vol.Optional:
        return vol.Optional(key, description={"suggested_value": self._default(key)})

    def _pump_filter(self) -> str | None:
        return self._data.get(CONF_PUMP_SOURCE) if self._data.get(CONF_PUMP_FILTER, True) else None

    def _finish(self) -> ConfigFlowResult:
        data = _clean(self._data)
        if self._reconfigure:
            # replace (not merge) so that a cleared optional sensor is really removed
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data=data)
        return self.async_create_entry(title="Slimme Warmtepomp", data=data)

    async def _next(self) -> ConfigFlowResult:
        if self._queue:
            return await getattr(self, f"async_step_{self._queue.pop(0)}")()
        return self._finish()

    # ------------------------------------------------------------------ 1. installation
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self._reconfigure:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_basis()
        platforms = self._platforms()
        fields: dict = {
            vol.Required(CONF_CONTROL_MODE, default=self._data.get(CONF_CONTROL_MODE, "retour")): _select(CONF_CONTROL_MODE, ["retour", "aanvoer"]),
            vol.Required(CONF_STEP, default=str(self._data.get(CONF_STEP, "1.0"))): _select(CONF_STEP, ["0.5", "1.0"]),
            vol.Required(CONF_PUMP_PROFILE, default=self._data.get(CONF_PUMP_PROFILE, "alsavo")): _select(CONF_PUMP_PROFILE, list(PROFILES)),
        }
        if platforms:
            fields[vol.Optional(CONF_PUMP_SOURCE, description={"suggested_value": self._data.get(CONF_PUMP_SOURCE)})] = \
                selector.SelectSelector(selector.SelectSelectorConfig(options=platforms, mode=selector.SelectSelectorMode.DROPDOWN, custom_value=False))
            fields[vol.Required(CONF_PUMP_FILTER, default=self._data.get(CONF_PUMP_FILTER, True))] = bool
        return self.async_show_form(step_id="user", data_schema=vol.Schema(fields))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._reconfigure = True
        entry = self._get_reconfigure_entry()
        self._data = {**entry.data, **entry.options}
        self._data[CONF_STEP] = str(self._data.get(CONF_STEP, "1.0"))
        return await self.async_step_user(user_input)

    # ------------------------------------------------------------------ 2. basics
    async def async_step_basis(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update({k: user_input.get(k) for k in (CONF_ROOM, CONF_EXTRA_ROOMS, CONF_ROOM_MODE, CONF_OUTSIDE, CONF_FLOW, CONF_RETURN, CONF_FLOOR)})
            return await self.async_step_pomp()
        room = self._default(CONF_ROOM)
        out = self._default(CONF_OUTSIDE)
        fields: dict = {
            (vol.Required(CONF_ROOM, default=room) if room else vol.Required(CONF_ROOM)): _entity(SENSOR),
            self._opt(CONF_EXTRA_ROOMS): _entity(SENSOR, multiple=True),
            vol.Required(CONF_ROOM_MODE, default=self._data.get(CONF_ROOM_MODE, "hoofd")): _select(CONF_ROOM_MODE, list(ROOM_MODES)),
            (vol.Required(CONF_OUTSIDE, default=out) if out else vol.Required(CONF_OUTSIDE)): _entity(SENSOR),
            self._opt(CONF_FLOW): _entity(SENSOR, integration=self._pump_filter()),
            self._opt(CONF_RETURN): _entity(SENSOR, integration=self._pump_filter()),
            self._opt(CONF_FLOOR): _entity(SENSOR),
        }
        return self.async_show_form(step_id="basis", data_schema=vol.Schema(fields))

    # ------------------------------------------------------------------ 3. pump
    async def async_step_pomp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update({k: user_input.get(k) for k in (CONF_FREQ, CONF_POWER, CONF_VOLTAGE, CONF_CURRENT, CONF_FLOW_RATES, CONF_COIL, CONF_UNIT_OUTSIDE)})
            return await self.async_step_aansturing()
        src = self._pump_filter()
        fields: dict = {
            self._opt(CONF_FREQ): _entity(SENSOR, integration=src),
            self._opt(CONF_POWER): _entity(SENSOR),
            self._opt(CONF_VOLTAGE): _entity(SENSOR, integration=src),
            self._opt(CONF_CURRENT): _entity(SENSOR, integration=src),
            self._opt(CONF_FLOW_RATES): _entity(SENSOR, multiple=True),
            self._opt(CONF_COIL): _entity(SENSOR, integration=src),
            self._opt(CONF_UNIT_OUTSIDE): _entity(SENSOR, integration=src),
        }
        return self.async_show_form(step_id="pomp", data_schema=vol.Schema(fields))

    # ------------------------------------------------------------------ 4. control
    async def async_step_aansturing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update({k: user_input.get(k) for k in (CONF_TARGET, CONF_SWITCH)})
            return await self.async_step_extras()
        src = self._pump_filter()
        fields = {self._opt(CONF_TARGET): _entity(SETTERS, integration=src), self._opt(CONF_SWITCH): _entity(SWITCHES, integration=src)}
        return self.async_show_form(step_id="aansturing", data_schema=vol.Schema(fields))

    # ------------------------------------------------------------------ 5. extras
    async def async_step_extras(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            chosen = [k for k in EXTRAS if user_input.get(k)]
            for key, (_, conf_keys) in EXTRAS.items():
                if key not in chosen:                       # unticked: forget what was configured there
                    for ck in conf_keys:
                        self._data.pop(ck, None)
            self._queue = [EXTRAS[k][0] for k in chosen]
            return await self._next()
        fields = {vol.Required(k, default=any(self._data.get(ck) for ck in conf)): bool for k, (_, conf) in EXTRAS.items()}
        return self.async_show_form(step_id="extras", data_schema=vol.Schema(fields))

    async def async_step_weer_prijs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update({k: user_input.get(k) for k in (CONF_WEATHER, CONF_PRICE)})
            return await self._next()
        fields = {self._opt(CONF_WEATHER): _entity(["weather"]), self._opt(CONF_PRICE): _entity(SENSOR)}
        return self.async_show_form(step_id="weer_prijs", data_schema=vol.Schema(fields))

    async def async_step_zon_net(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update({k: user_input.get(k) for k in (CONF_PV, CONF_GRID)})
            return await self._next()
        fields = {self._opt(CONF_PV): _entity(SENSOR), self._opt(CONF_GRID): _entity(SENSOR)}
        return self.async_show_form(step_id="zon_net", data_schema=vol.Schema(fields))

    async def async_step_ramen(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_OPEN_SENSORS] = user_input.get(CONF_OPEN_SENSORS)
            return await self._next()
        return self.async_show_form(step_id="ramen", data_schema=vol.Schema({self._opt(CONF_OPEN_SENSORS): _entity(["binary_sensor"], multiple=True)}))

    async def async_step_aanwezigheid(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update({k: user_input.get(k) for k in (CONF_PRESENCE, CONF_HOLIDAY, CONF_RETURN_TIME)})
            return await self._next()
        fields = {
            self._opt(CONF_PRESENCE): _entity(["person", "device_tracker", "binary_sensor", "input_boolean"], multiple=True),
            self._opt(CONF_HOLIDAY): _entity(["input_boolean", "switch"]),
            self._opt(CONF_RETURN_TIME): _entity(["input_datetime", "sensor"]),
        }
        return self.async_show_form(step_id="aanwezigheid", data_schema=vol.Schema(fields))

    async def async_step_tapwater(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update({k: user_input.get(k) for k in (CONF_DHW_TEMP, CONF_DHW_SWITCH, CONF_DHW_SETPOINT)})
            return await self._next()
        fields = {self._opt(CONF_DHW_TEMP): _entity(SENSOR), self._opt(CONF_DHW_SWITCH): _entity(SWITCHES),
                  self._opt(CONF_DHW_SETPOINT): _entity(SETTERS)}
        return self.async_show_form(step_id="tapwater", data_schema=vol.Schema(fields))

    async def async_step_meldingen(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        services = sorted(f"notify.{name}" for name in self.hass.services.async_services().get("notify", {})
                          if name not in ("send_message", "persistent_notification"))
        if user_input is not None:
            self._data[CONF_NOTIFY] = user_input.get(CONF_NOTIFY)
            return await self._next()
        if not services:                    # nothing to choose from: skip the screen
            return await self._next()
        fields = {self._opt(CONF_NOTIFY): selector.SelectSelector(selector.SelectSelectorConfig(
            options=services, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN, custom_value=False))}
        return self.async_show_form(step_id="meldingen", data_schema=vol.Schema(fields))
