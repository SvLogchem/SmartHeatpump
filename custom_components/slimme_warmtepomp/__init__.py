"""The Slimme Warmtepomp integration."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, EVENT_STATE_CHANGED
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_COIL, DOMAIN, SERVICE_RESET_MODEL, VERSION
from .coordinator import SmartHeatpumpCoordinator
from .engine.settings import REMOVED_NUMBER_KEYS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "number", "binary_sensor", "climate", "switch", "button"]

type SlimmeConfigEntry = ConfigEntry[SmartHeatpumpCoordinator]


STRATEGY_FILE = "slimme-warmtepomp-strategy.js"
STRATEGY_URL = f"/{DOMAIN}_frontend/{STRATEGY_FILE}"


async def _register_dashboard_strategy(hass: HomeAssistant) -> None:
    """Serve the dashboard strategy (frontend/*.js) and load it in the frontend.

    Afterwards "Slimme Warmtepomp" is offered under Settings > Dashboards > Add dashboard > Community dashboards.
    A failure here must never stop the heat pump control, so everything is caught and logged.
    """
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        folder = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths([StaticPathConfig(f"/{DOMAIN}_frontend", str(folder), False)])
        add_extra_js_url(hass, f"{STRATEGY_URL}?v={VERSION}")
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register the dashboard strategy (%s). The integration itself works; create a dashboard "
                        "manually with 'strategy: type: custom:slimme-warmtepomp' once the file is available", err)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await _register_dashboard_strategy(hass)
    async def _reset(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                await coordinator.async_reset_model(float(call.data.get("percentage", 100)))

    hass.services.async_register(DOMAIN, SERVICE_RESET_MODEL, _reset, schema=vol.Schema(
        {vol.Optional("percentage", default=100): vol.All(vol.Coerce(float), vol.Range(min=1, max=100))}))
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
    # HA does not unload entries on shutdown/restart: save explicitly so nothing since the last periodic save is lost
    async def _save_on_stop(_event) -> None:
        await coordinator.async_save()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _save_on_stop))
    # coil sensor: record every change so a defrost's peak is measured at full resolution
    coil_entity = coordinator.cfg.get(CONF_COIL)
    if coil_entity:
        @callback
        def _only_coil(data) -> bool:
            return data.get("entity_id") == coil_entity

        entry.async_on_unload(hass.bus.async_listen(EVENT_STATE_CHANGED, coordinator.on_coil_event,
                                                    event_filter=_only_coil))
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
