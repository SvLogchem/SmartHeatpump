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
            vol.Required("room_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor"])
            ),
            vol.Required("outside_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor"])
            ),
            vol.Required("compressor_freq_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor"])
            ),
            vol.Required("flow_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor"])
            ),
            vol.Required("return_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor"])
            ),
            vol.Optional("simulation_mode", default=False): selector.BooleanSelector(),
            vol.Optional("target_setpoint_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["number", "input_number"])
            ),
            vol.Optional("heatpump_switch"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
            ),
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
