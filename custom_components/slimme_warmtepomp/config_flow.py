"""Config flow for Slimme Warmtepomp integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN

class SlimmeWarmtepompConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            # Zet lege optionele velden om naar None zodat validatie slaagt
            cleaned_input = {k: (v if v != "" else None) for k, v in user_input.items()}
            return self.async_create_entry(title="Slimme Warmtepomp", data=cleaned_input)

        return self.async_show_form(
            step_id="user", data_schema=self._get_schema(), errors=errors
        )

    async def async_step_reconfigure(self, user_input=None):
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            cleaned_input = {k: (v if v != "" else None) for k, v in user_input.items()}
            return self.async_update_reload_and_abort(
                entry,
                data=cleaned_input,
            )

        current_data = {**entry.data, **entry.options}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._get_schema(current_data),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return SlimmeWarmtepompOptionsFlowHandler(config_entry)

    def _get_schema(self, defaults=None):
        if defaults is None:
            defaults = {}
        return vol.Schema({
            vol.Required("control_mode", default=defaults.get("control_mode", "retour")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "retour", "label": "Sturen op Retourtemperatuur"},
                        {"value": "aanvoer", "label": "Sturen op Aanvoertemperatuur"}
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required("target_setpoint_entity", default=defaults.get("target_setpoint_entity", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="number")
            ),
            vol.Required("heatpump_switch", default=defaults.get("heatpump_switch", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional("flow_rate_sensor_1", default=defaults.get("flow_rate_sensor_1", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("flow_rate_sensor_2", default=defaults.get("flow_rate_sensor_2", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("power_sensor", default=defaults.get("power_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("voltage_sensor", default=defaults.get("voltage_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("current_sensor", default=defaults.get("current_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("electricity_price_sensor", default=defaults.get("electricity_price_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("pv_power_sensor", default=defaults.get("pv_power_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("dhw_status_sensor", default=defaults.get("dhw_status_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required("room_temp_sensor", default=defaults.get("room_temp_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("outside_temp_sensor", default=defaults.get("outside_temp_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("weather_entity", default=defaults.get("weather_entity", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional("flow_temp_sensor", default=defaults.get("flow_temp_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("return_temp_sensor", default=defaults.get("return_temp_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("compressor_freq_sensor", default=defaults.get("compressor_freq_sensor", "")): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
        })


class SlimmeWarmtepompOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            cleaned_input = {k: (v if v != "" else None) for k, v in user_input.items()}
            return self.async_create_entry(title="", data=cleaned_input)

        data = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("control_mode", default=data.get("control_mode", "retour")): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "retour", "label": "Sturen op Retourtemperatuur"},
                            {"value": "aanvoer", "label": "Sturen op Aanvoertemperatuur"}
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required("target_setpoint_entity", default=data.get("target_setpoint_entity", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Required("heatpump_switch", default=data.get("heatpump_switch", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional("flow_rate_sensor_1", default=data.get("flow_rate_sensor_1", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("flow_rate_sensor_2", default=data.get("flow_rate_sensor_2", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("power_sensor", default=data.get("power_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("voltage_sensor", default=data.get("voltage_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("current_sensor", default=data.get("current_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("electricity_price_sensor", default=data.get("electricity_price_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("pv_power_sensor", default=data.get("pv_power_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("dhw_status_sensor", default=data.get("dhw_status_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("room_temp_sensor", default=data.get("room_temp_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional("outside_temp_sensor", default=data.get("outside_temp_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional("weather_entity", default=data.get("weather_entity", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Optional("flow_temp_sensor", default=data.get("flow_temp_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional("return_temp_sensor", default=data.get("return_temp_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional("compressor_freq_sensor", default=data.get("compressor_freq_sensor", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            })
        )
