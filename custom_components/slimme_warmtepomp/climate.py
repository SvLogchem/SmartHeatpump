"""Climate platform for Slimme Warmtepomp."""
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode, HVACAction
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

class SlimmeWarmtepompThermostaat(ClimateEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._attr_name = "Slimme Warmtepomp Thermostaat"
        self._attr_unique_id = f"{config_entry.entry_id}_climate"
        
        self._tuya_switch = config_entry.data.get("heatpump_switch")
        self._room_sensor = config_entry.data.get("room_temp_sensor")
        
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        
        self._attr_target_temperature = 21.0
        self._attr_hvac_mode = HVACMode.OFF

    @property
    def current_temperature(self):
        state = self.hass.states.get(self._room_sensor)
        if state and state.state not in ['unknown', 'unavailable']:
            return float(state.state)
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
        if hvac_mode == HVACMode.HEAT:
            await self.hass.services.async_call("switch", "turn_on", {"entity_id": self._tuya_switch})
        elif hvac_mode == HVACMode.OFF:
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": self._tuya_switch})
            
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_update(self):
        state = self.hass.states.get(self._tuya_switch)
        if state:
            self._attr_hvac_mode = HVACMode.HEAT if state.state == "on" else HVACMode.OFF

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([SlimmeWarmtepompThermostaat(hass, config_entry)])
