"""Switch platform for Slimme Warmtepomp."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import EntityCategory
from .const import DOMAIN

class SlimmeWarmtepompRegelingSwitch(SwitchEntity, RestoreEntity):
    def __init__(self, config_entry):
        self._entry_id = config_entry.entry_id
        self._attr_name = "Slimme Regeling Actief"
        self.entity_id = "switch.slimme_wp_regeling_actief"
        self._attr_unique_id = f"{self._entry_id}_regeling_actief"
        self._attr_icon = "mdi:auto-fix"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_is_on = True

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Slimme Warmtepomp",
            "manufacturer": "Custom HEMS",
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([SlimmeWarmtepompRegelingSwitch(config_entry)])
