"""Config flow for Slimme Warmtepomp."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN

class SlimmeWarmtepompConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="Slimme Warmtepomp", data=user_input)

        schema = vol.Schema({
            # Basis temperatuur & frequentie
            vol.Required("room_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Required("outside_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Required("compressor_freq_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Required("flow_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Required("return_temp_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            
            # Vermogen & COP (Optioneel, maar nodig voor de berekeningen)
            vol.Optional("flow_rate_sensor_1"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("flow_rate_sensor_2"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("power_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("voltage_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("current_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            
            # Slimme HEMS logica
            vol.Optional("weather_entity"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["weather"])),
            vol.Optional("electricity_price_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),
            vol.Optional("pv_power_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"])),

            # Doel setpoint en schakelaar (Ondersteunt nu ook input_number / input_boolean helpers)
            vol.Optional("target_setpoint_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["number", "input_number"])
            ),
            vol.Optional("heatpump_switch"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
