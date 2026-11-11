"""Config flow for Slimme Warmtepomp."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN

class SlimmeWarmtepompConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def _get_schema(self, current_data=None):
        if current_data is None:
            current_data = {}

        def req_key(key):
            if key in current_data:
                return vol.Required(key, default=current_data[key])
            return vol.Required(key)

        return vol.Schema({
            req_key("room_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            req_key("outside_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            req_key("compressor_freq_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            req_key("flow_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            req_key("return_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            
            vol.Optional("flow_rate_sensor_1", description={"suggested_value": current_data.get("flow_rate_sensor_1")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("flow_rate_sensor_2", description={"suggested_value": current_data.get("flow_rate_sensor_2")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("power_sensor", description={"suggested_value": current_data.get("power_sensor")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("voltage_sensor", description={"suggested_value": current_data.get("voltage_sensor")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("current_sensor", description={"suggested_value": current_data.get("current_sensor")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            
            vol.Optional("weather_entity", description={"suggested_value": current_data.get("weather_entity")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["weather"])),
            vol.Optional("electricity_price_sensor", description={"suggested_value": current_data.get("electricity_price_sensor")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("pv_power_sensor", description={"suggested_value": current_data.get("pv_power_sensor")}): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),

            vol.Optional("target_setpoint_entity", description={"suggested_value": current_data.get("target_setpoint_entity")}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["number", "input_number"])
            ),
            vol.Optional("heatpump_switch", description={"suggested_value": current_data.get("heatpump_switch")}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
        })

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="Slimme Warmtepomp", data=user_input)

        return self.async_show_form(step_id="user", data_schema=self._get_schema(), errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data={**entry.data, **user_input},
                reason="reconfigure_successful",
            )

        return self.async_show_form(
            step_id="reconfigure", 
            data_schema=self._get_schema(entry.data), 
            errors=errors
        )
