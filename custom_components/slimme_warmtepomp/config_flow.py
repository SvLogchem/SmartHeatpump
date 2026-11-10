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
            cleaned_input = {k: (v if v else None) for k, v in user_input.items()}
            return self.async_create_entry(title="Slimme Warmtepomp", data=cleaned_input)

        return self.async_show_form(
            step_id="user", data_schema=self._get_schema(), errors=errors
        )

    async def async_step_reconfigure(self, user_input=None):
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            cleaned_input = {k: (v if v else None) for k, v in user_input.items()}
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
            
        schema = {
            vol.Required("control_mode", default=defaults.get("control_mode", "retour")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "retour", "label": "Sturen op Retourtemperatuur"},
                        {"value": "aanvoer", "label": "Sturen op Aanvoertemperatuur"}
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
        }

        req_fields = [
            ("target_setpoint_entity", "number", None),
            ("heatpump_switch", "switch", None),
            ("room_temp_sensor", "sensor", "temperature"),
        ]
        for key, domain, dev_class in req_fields:
            opt_config = {"domain": domain}
            if dev_class:
                opt_config["device_class"] = dev_class
            val = defaults.get(key)
            if val:
                schema[vol.Required(key, default=val)] = selector.EntitySelector(selector.EntitySelectorConfig(**opt_config))
            else:
                schema[vol.Required(key)] = selector.EntitySelector(selector.EntitySelectorConfig(**opt_config))

        optional_sensors = [
            ("flow_rate_sensor_1", "sensor", None),
            ("flow_rate_sensor_2", "sensor", None),
            ("power_sensor", "sensor", None),
            ("voltage_sensor", "sensor", None),
            ("current_sensor", "sensor", None),
            ("electricity_price_sensor", "sensor", None),
            ("pv_power_sensor", "sensor", None),
            ("dhw_status_sensor", "sensor", None),
            ("outside_temp_sensor", "sensor", "temperature"),
            ("weather_entity", "weather", None),
            ("flow_temp_sensor", "sensor", "temperature"),
            ("return_temp_sensor", "sensor", "temperature"),
            ("compressor_freq_sensor", "sensor", None),
        ]

        for key, domain, dev_class in optional_sensors:
            opt_config = {"domain": domain}
            if dev_class:
                opt_config["device_class"] = dev_class
            val = defaults.get(key)
            if val:
                schema[vol.Optional(key, default=val)] = selector.EntitySelector(selector.EntitySelectorConfig(**opt_config))
            else:
                schema[vol.Optional(key)] = selector.EntitySelector(selector.EntitySelectorConfig(**opt_config))

        return vol.Schema(schema)


class SlimmeWarmtepompOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            cleaned_input = {k: (v if v else None) for k, v in user_input.items()}
            return self.async_create_entry(title="", data=cleaned_input)

        data = {**self.config_entry.data, **self.config_entry.options}
        flow = SlimmeWarmtepompConfigFlow()
        flow.hass = self.hass
        return self.async_show_form(
            step_id="init",
            data_schema=flow._get_schema(data)
        )
