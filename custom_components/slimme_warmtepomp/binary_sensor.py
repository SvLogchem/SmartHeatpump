"""Binary Sensor platform for Slimme Warmtepomp."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from .const import DOMAIN

class SlimmeWarmtepompDefrostSensor(BinarySensorEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._entry_id = config_entry.entry_id
        self._attr_name = "Slimme WP Ontdooi Actief"
        self.entity_id = "binary_sensor.slimme_wp_defrost"
        self._attr_unique_id = f"{self._entry_id}_defrost"
        self._attr_device_class = BinarySensorDeviceClass.HEAT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry_id)}, "name": "Slimme Warmtepomp", "manufacturer": "Custom HEMS"}

    @property
    def is_on(self):
        state = self.hass.states.get("sensor.slimme_wp_setpoint")
        return state.attributes.get("ontdooi_actief", False) if state else False

class SlimmeWarmtepompDureStroomSensor(BinarySensorEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._entry_id = config_entry.entry_id
        self._attr_name = "Slimme WP Blokkering Dure Stroom"
        self.entity_id = "binary_sensor.slimme_wp_dure_stroom"
        self._attr_unique_id = f"{self._entry_id}_dure_stroom"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry_id)}, "name": "Slimme Warmtepomp", "manufacturer": "Custom HEMS"}

    @property
    def is_on(self):
        state = self.hass.states.get("sensor.slimme_wp_setpoint")
        return state.attributes.get("dure_stroom_actief", False) if state else False

class SlimmeWarmtepompZomermodusSensor(BinarySensorEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._entry_id = config_entry.entry_id
        self._attr_name = "Slimme WP Zomermodus (Stookgrens)"
        self.entity_id = "binary_sensor.slimme_wp_zomermodus"
        self._attr_unique_id = f"{self._entry_id}_zomermodus"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry_id)}, "name": "Slimme Warmtepomp", "manufacturer": "Custom HEMS"}

    @property
    def is_on(self):
        state = self.hass.states.get("sensor.slimme_wp_setpoint")
        return state.attributes.get("zomermodus_actief", False) if state else False

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([
        SlimmeWarmtepompDefrostSensor(hass, config_entry),
        SlimmeWarmtepompDureStroomSensor(hass, config_entry),
        SlimmeWarmtepompZomermodusSensor(hass, config_entry)
    ])
