"""Climate platform for Slimme Warmtepomp."""
import logging
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PRESET_DAY = "Dag"
PRESET_NIGHT = "Nacht"
PRESET_MANUAL = "Handmatig"

class SlimmeWarmtepompThermostaat(ClimateEntity, RestoreEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_name = "Slimme WP Thermostaat"
        self.entity_id = "climate.slimme_wp_thermostaat"
        self._attr_unique_id = f"{config_entry.entry_id}_climate"
        
        config = {**config_entry.data, **config_entry.options}
        self._tuya_switch = config.get("heatpump_switch")
        self._room_sensor = config.get("room_temp_sensor")
        
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attr_preset_modes = [PRESET_DAY, PRESET_NIGHT, PRESET_MANUAL]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        
        self._attr_precision = 0.1
        self._attr_target_temperature_step = 0.1
        self._attr_min_temp = 15.0
        self._attr_max_temp = 25.0
        
        self._attr_target_temperature = 21.0
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_preset_mode = PRESET_DAY

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            if last_state.state in [HVACMode.HEAT, HVACMode.OFF]:
                self._attr_hvac_mode = last_state.state
            if "temperature" in last_state.attributes and last_state.attributes["temperature"] is not None:
                try: self._attr_target_temperature = float(last_state.attributes["temperature"])
                except ValueError: pass
            if "preset_mode" in last_state.attributes and last_state.attributes["preset_mode"] in self._attr_preset_modes:
                self._attr_preset_mode = last_state.attributes["preset_mode"]

    @property
    def precision(self) -> float: return 0.1
    @property
    def target_temperature_step(self) -> float: return 0.1
    
    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._config_entry.entry_id)}, "name": "Slimme Warmtepomp", "manufacturer": "Custom HEMS"}

    @property
    def native_current_temperature(self):
        if not self._room_sensor: return None
        state = self.hass.states.get(self._room_sensor)
        if state and state.state not in ['unknown', 'unavailable']:
            try: return float(state.state)
            except ValueError: return None
        return None

    @property
    def hvac_action(self):
        if self._attr_hvac_mode == HVACMode.OFF: 
            return HVACAction.OFF
            
        config = {**self._config_entry.data, **self._config_entry.options}
        tuya_switch = config.get("heatpump_switch")
        freq_sensor = config.get("compressor_freq_sensor")
        
        switch_is_on = False
        if tuya_switch:
            state = self.hass.states.get(tuya_switch)
            if state and state.state == "on":
                switch_is_on = True

        if not switch_is_on and tuya_switch:
            return HVACAction.IDLE 
            
        freq = 0.0
        if freq_sensor:
            freq_state = self.hass.states.get(freq_sensor)
            if freq_state and freq_state.state not in ['unknown', 'unavailable']:
                try: freq = float(freq_state.state)
                except ValueError: pass

        if freq > 2.0:
            return HVACAction.HEATING
        return HVACAction.FAN

    async def async_set_temperature(self, **kwargs):
        if ATTR_TEMPERATURE in kwargs:
            self._attr_target_temperature = kwargs[ATTR_TEMPERATURE]
            self._attr_preset_mode = PRESET_MANUAL
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str):
        self._attr_preset_mode = preset_mode
        if preset_mode == PRESET_DAY:
            state = self.hass.states.get("number.slimme_wp_setpoint_dag")
            if state: self._attr_target_temperature = float(state.state)
        elif preset_mode == PRESET_NIGHT:
            state = self.hass.states.get("number.slimme_wp_setpoint_nacht")
            if state: self._attr_target_temperature = float(state.state)
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        self._attr_hvac_mode = hvac_mode
        regeling_switch = self.hass.states.get("switch.slimme_wp_regeling_actief")
        mag_aansturen = False if (regeling_switch and regeling_switch.state == "off") else True

        if mag_aansturen and hvac_mode == HVACMode.OFF and self._tuya_switch and not self._tuya_switch.startswith("virtual_"):
            svc = "input_boolean" if self._tuya_switch.startswith("input_boolean") else "switch"
            await self.hass.services.async_call(svc, "turn_off", {"entity_id": self._tuya_switch})
        self.async_write_ha_state()

    async def async_update(self):
        if self._attr_preset_mode != PRESET_MANUAL:
            sensor_state = self.hass.states.get("sensor.slimme_wp_setpoint")
            if sensor_state and "actief_programma" in sensor_state.attributes:
                auto_prog = sensor_state.attributes["actief_programma"]
                if auto_prog in [PRESET_DAY, PRESET_NIGHT]:
                    self._attr_preset_mode = auto_prog
                    if auto_prog == PRESET_DAY:
                        dag_s = self.hass.states.get("number.slimme_wp_setpoint_dag")
                        if dag_s: self._attr_target_temperature = float(dag_s.state)
                    elif auto_prog == PRESET_NIGHT:
                        nacht_s = self.hass.states.get("number.slimme_wp_setpoint_nacht")
                        if nacht_s: self._attr_target_temperature = float(nacht_s.state)

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([SlimmeWarmtepompThermostaat(hass, config_entry)])
