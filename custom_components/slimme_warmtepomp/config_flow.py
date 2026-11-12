"""Config flow for Slimme Warmtepomp."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CONTROL_MODE, CONF_CURRENT, CONF_DHW_SETPOINT, CONF_DHW_SWITCH, CONF_DHW_TEMP, CONF_FLOOR,
    CONF_FLOW, CONF_FLOW_RATE_1, CONF_FLOW_RATE_2, CONF_FREQ, CONF_OUTSIDE, CONF_POWER, CONF_PRICE,
    CONF_PV, CONF_RETURN, CONF_ROOM, CONF_STEP, CONF_SWITCH, CONF_TARGET, CONF_VOLTAGE, CONF_WEATHER,
    DOMAIN,
)

SENSOR = selector.EntitySelectorConfig(domain=["sensor"])
SETTERS = selector.EntitySelectorConfig(domain=["number", "input_number"])
SWITCHES = selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
WEATHER = selector.EntitySelectorConfig(domain=["weather"])

REQUIRED = [CONF_ROOM, CONF_OUTSIDE]
OPTIONAL_SENSORS = [
    CONF_RETURN, CONF_FLOW, CONF_FLOOR, CONF_FREQ, CONF_POWER, CONF_VOLTAGE, CONF_CURRENT,
    CONF_FLOW_RATE_1, CONF_FLOW_RATE_2, CONF_PRICE, CONF_PV, CONF_DHW_TEMP,
]


def _select(key: str, options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=options, translation_key=key, mode=selector.SelectSelectorMode.DROPDOWN))


def _schema(cur: dict[str, Any] | None = None) -> vol.Schema:
    cur = cur or {}

    def opt(key):
        return vol.Optional(key, description={"suggested_value": cur.get(key)})

    fields: dict = {}
    for key in REQUIRED:
        fields[vol.Required(key, default=cur[key]) if key in cur else vol.Required(key)] = \
            selector.EntitySelector(SENSOR)
    fields[opt(CONF_TARGET)] = selector.EntitySelector(SETTERS)
    fields[opt(CONF_SWITCH)] = selector.EntitySelector(SWITCHES)
    fields[vol.Required(CONF_CONTROL_MODE, default=cur.get(CONF_CONTROL_MODE, "retour"))] = \
        _select(CONF_CONTROL_MODE, ["retour", "aanvoer"])
    fields[vol.Required(CONF_STEP, default=str(cur.get(CONF_STEP, "1.0")))] = _select(CONF_STEP, ["0.5", "1.0"])
    for key in OPTIONAL_SENSORS[:-1]:
        fields[opt(key)] = selector.EntitySelector(SENSOR)
    fields[opt(CONF_WEATHER)] = selector.EntitySelector(WEATHER)
    fields[opt(CONF_DHW_TEMP)] = selector.EntitySelector(SENSOR)
    fields[opt(CONF_DHW_SWITCH)] = selector.EntitySelector(SWITCHES)
    fields[opt(CONF_DHW_SETPOINT)] = selector.EntitySelector(SETTERS)
    return vol.Schema(fields)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {k: v for k, v in user_input.items() if v not in (None, "")}
    data[CONF_STEP] = float(data.get(CONF_STEP, 1.0))
    return data


class SlimmeWarmtepompConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Slimme Warmtepomp", data=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema())

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            # replace (not merge) so that a cleared optional sensor is really removed
            return self.async_update_reload_and_abort(entry, data=_clean(user_input))
        return self.async_show_form(step_id="reconfigure", data_schema=_schema({**entry.data, **entry.options}))
