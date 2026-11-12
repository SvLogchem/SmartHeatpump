"""Shared base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import SmartHeatpumpCoordinator


class SlimmeWPEntity(CoordinatorEntity[SmartHeatpumpCoordinator]):
    """Entity bound to the coordinator.

    unique_ids are ``<entry_id>_<key>`` exactly like v1, and entity_ids keep
    their v1 names, so existing dashboards and automations keep working.
    """

    _attr_has_entity_name = False

    def __init__(self, coordinator: SmartHeatpumpCoordinator, key: str, name: str, entity_id: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self.entity_id = entity_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Slimme Warmtepomp",
            manufacturer="Custom HEMS",
            model="Zelflerende Regeling",
            sw_version=VERSION,
        )

    @property
    def decision(self):
        return self.coordinator.data
