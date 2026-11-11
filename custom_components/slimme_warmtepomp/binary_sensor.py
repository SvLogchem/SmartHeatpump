"""Binary Sensor platform for Slimme Warmtepomp."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from .const import DOMAIN

class SlimmeWarmtepompBaseBinarySensor(BinarySensorEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._entry_id = config_entry.entry_id
        self._config_entry = config_entry
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Slimme Warmtepomp",
            "manufacturer": "Custom HEMS",
        }

class OntdooiBinarySensor(SlimmeWarmtepompBaseBinarySensor):
    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        self._attr_name = "Warmtepomp Ontdooit (Defrost)"
        self._attr_unique_id = f"{self._entry_id}_defrost"
        self._attr_device_class = BinarySensorDeviceClass.COLD

    @property
    def is_on(self):
        state = self.hass.states.get("sensor.slimme_wp_setpoint")
        if state and "ontdooi_actief" in state.attributes:
            return state.attributes["ontdooi_actief"]
        return False

class DureStroomBinarySensor(SlimmeWarmtepompBaseBinarySensor):
    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        self._attr_name = "Warmtepomp Geblokkeerd (Dure Stroom)"
        self._attr_unique_id = f"{self._entry_id}_dure_stroom"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        state = self.hass.states.get("sensor.slimme_wp_setpoint")
        if state and "dure_stroom_actief" in state.attributes:
            return state.attributes["dure_stroom_actief"]
        return False

class ZomerModusBinarySensor(SlimmeWarmtepompBaseBinarySensor):
    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        self._attr_name = "Zomermodus Actief (Stookgrens)"
        self._attr_unique_id = f"{self._entry_id}_zomermodus"
        self._attr_icon = "mdi:sun-thermometer"

    @property
    def is_on(self):
        state = self.hass.states.get("sensor.slimme_wp_setpoint")
        if state and "zomermodus_actief" in state.attributes:
            return state.attributes["zomermodus_actief"]
        return False

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([
        OntdooiBinarySensor(hass, config_entry),
        DureStroomBinarySensor(hass, config_entry),
        ZomerModusBinarySensor(hass, config_entry)
    ], update_before_add=True)
