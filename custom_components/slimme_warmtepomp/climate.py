"""Climate platform for Slimme Warmtepomp."""
import logging
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class SlimmeWarmtepompThermostaat(ClimateEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_name = "Slimme Warmtepomp Thermostaat"
        self._attr_unique_id = f"{config_entry.entry_id}_climate"
        
        config = {**config_entry.data, **config_entry.options}
        
        self._tuya_switch = config.get("heatpump_switch")
        self._room_sensor = config.get("room_temp_sensor")
        
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        
        self._attr_precision = 0.1
        self._attr_target_temp_step = 0.1
        
        self._attr_min_temp = 15.0
        self._attr_max_temp = 25.0
        
        self._attr_target_temperature = 21.0
        self._attr_hvac_mode = HVACMode.OFF

    @property
    def precision(self) -> float:
        return 0.1

    @property
    def target_temp_step(self) -> float:
        return 0.1

    @property
    def extra_state_attributes(self):
        return {
            "target_temp_step": 0.1,
            "precision": 0.1,
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": "Slimme Warmtepomp",
            "manufacturer": "Custom HEMS",
            "model": "Zelflerende Regeling",
            "sw_version": "1.0.0",
        }

    @property
    def current_temperature(self):
        if not self._room_sensor:
            return None
        state = self.hass.states.get(self._room_sensor)
        if state and state.state not in ['unknown', 'unavailable']:
            try:
                return float(state.state)
            except ValueError:
                return None
        return None

    @property
    def hvac_action(self):
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return HVACAction.HEATING

    async def async_set_temperature(self, **kwargs):
        if ATTR_TEMPERATURE in kwargs:
            self._attr_target_temperature = kwargs[ATTR_TEMPERATURE]
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        if self._tuya_switch and not self._tuya_switch.startswith("virtual_"):
            if hvac_mode == HVACMode.HEAT:
                await self.hass.services.async_call("switch", "turn_on", {"entity_id": self._tuya_switch})
            elif hvac_mode == HVACMode.OFF:
                await self.hass.services.async_call("switch", "turn_off", {"entity_id": self._tuya_switch})
            
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_update(self):
        config = {**self._config_entry.data, **self._config_entry.options}
        self._room_sensor = config.get("room_temp_sensor")
        self._tuya_switch = config.get("heatpump_switch")

        if self._tuya_switch and not self._tuya_switch.startswith("virtual_"):
            state = self.hass.states.get(self._tuya_switch)
            if state:
                self._attr_hvac_mode = HVACMode.HEAT if state.state == "on" else HVACMode.OFF

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([SlimmeWarmtepompThermostaat(hass, config_entry)])
