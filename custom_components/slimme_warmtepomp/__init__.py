"""The Slimme Warmtepomp integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SERVICE_RESET_MODEL
from .coordinator import SmartHeatpumpCoordinator
from .engine.settings import REMOVED_NUMBER_KEYS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "number", "binary_sensor", "climate", "switch"]

type SlimmeConfigEntry = ConfigEntry[SmartHeatpumpCoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def _reset(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                await coordinator.async_reset_model()

    hass.services.async_register(DOMAIN, SERVICE_RESET_MODEL, _reset)
    return True


def _remove_obsolete_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """v1 had 'dag_start'/'dag_eind' numbers that never influenced anything."""
    registry = er.async_get(hass)
    for key in REMOVED_NUMBER_KEYS:
        entity_id = registry.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_{key}")
        if entity_id:
            registry.async_remove(entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: SlimmeConfigEntry) -> bool:
    _remove_obsolete_entities(hass, entry)
    coordinator = SmartHeatpumpCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    # entities restore their last values (numbers, switches, climate) while being added ...
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # ... so the first control cycle already runs with the user's settings.
    await coordinator.async_config_entry_first_refresh()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SlimmeConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_save()
    return ok
