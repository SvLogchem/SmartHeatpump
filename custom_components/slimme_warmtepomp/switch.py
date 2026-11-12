"""Switch platform: feature toggles."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .engine.settings import SWITCH_SPECS
from .entity import SlimmeWPEntity


class SlimmeWarmtepompSwitch(SlimmeWPEntity, SwitchEntity, RestoreEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key, name, default, icon) -> None:
        super().__init__(coordinator, key, name, f"switch.slimme_wp_{key}")
        self._attr_icon = icon
        self._default = default

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.switches.get(self._key, self._default)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self.coordinator.switches[self._key] = last.state == "on"

    async def _set(self, value: bool) -> None:
        self.coordinator.switches[self._key] = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        SlimmeWarmtepompSwitch(coordinator, key, name, default, icon)
        for key, name, default, icon, group in SWITCH_SPECS
        if group == "core" or coordinator.has_dhw
    )
