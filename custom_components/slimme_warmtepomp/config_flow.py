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
            return self.async_create_entry(title="Slimme Warmtepomp", data=user_input)

        data_schema = vol.Schema({
            vol.Required("control_mode", default="retour"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "retour", "label": "Sturen op Retourtemperatuur"},
                        {"value": "aanvoer", "label": "Sturen op Aanvoertemperatuur"}
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required("target_setpoint_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="number")
            ),
            vol.Required("heatpump_switch"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional("flow_rate_sensor_1"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("flow_rate_sensor_2"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            # Directe vermogenssensor (optioneel)
            vol.Optional("power_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            # Alternatief: Volt en Stroom
            vol.Optional("voltage_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("current_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("electricity_price_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("pv_power_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("dhw_status_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required("room_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("outside_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("weather_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional("flow_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("return_temp_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional("compressor_freq_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
