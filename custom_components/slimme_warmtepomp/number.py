"""Number platform: all tunable settings."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .engine.settings import NUMBER_SPECS
from .entity import SlimmeWPEntity


class SlimmeWarmtepompNumber(SlimmeWPEntity, NumberEntity, RestoreEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key, name, lo, hi, step, unit, default) -> None:
        super().__init__(coordinator, key, name, f"number.slimme_wp_{key}")
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit or None
        self._default = default

    @property
    def available(self) -> bool:
        return True  # settings stay editable even when a control cycle fails

    @property
    def native_value(self) -> float:
        return self.coordinator.settings.get(self._key, self._default)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            try:
                value = float(last.state)
            except ValueError:
                value = self._default
            self.coordinator.settings[self._key] = min(max(value, self._attr_native_min_value),
                                                       self._attr_native_max_value)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.settings[self._key] = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        SlimmeWarmtepompNumber(coordinator, key, name, lo, hi, step, unit, default)
        for key, name, lo, hi, step, unit, default, group in NUMBER_SPECS
        if coordinator.group_enabled(group)
    )
