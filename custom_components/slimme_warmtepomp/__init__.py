"""The Slimme Warmtepomp integration."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, EVENT_STATE_CHANGED
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import CONF_COIL, CONF_FLOW_RATE_1, CONF_FLOW_RATE_2, CONF_FLOW_RATES, DOMAIN, SERVICE_RESET_MODEL, VERSION
from .coordinator import SmartHeatpumpCoordinator
from .engine.settings import REMOVED_NUMBER_KEYS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "number", "binary_sensor", "climate", "switch", "button"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SlimmeConfigEntry = ConfigEntry[SmartHeatpumpCoordinator]


EXPORT_FILE = "slimme_warmtepomp_export.json"
SERVICE_EXPORT = "exporteer"
SERVICE_IMPORT = "importeer"
STRATEGY_FILE = "slimme-warmtepomp-strategy.js"
STRATEGY_URL = f"/{DOMAIN}_frontend/{STRATEGY_FILE}"


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as err:
        raise HomeAssistantError(f"Could not read {EXPORT_FILE}: {err}") from err


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
    async def _reset(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                await coordinator.async_reset_model(float(call.data.get("percentage", 100)))

    hass.services.async_register(DOMAIN, SERVICE_RESET_MODEL, _reset, schema=vol.Schema(
        {vol.Optional("percentage", default=100): vol.All(vol.Coerce(float), vol.Range(min=1, max=100))}))

    def _coordinator():
        for entry in hass.config_entries.async_entries(DOMAIN):
            if getattr(entry, "runtime_data", None) is not None:
                return entry.runtime_data
        raise HomeAssistantError("Slimme Warmtepomp is not set up")

    async def _export(call: ServiceCall) -> dict:
        bundle = _coordinator().export_bundle(bool(call.data.get("leerstatus", True)))
        path = hass.config.path(EXPORT_FILE)
        await hass.async_add_executor_job(_write_json, path, bundle)
        return {"bestand": EXPORT_FILE, **bundle}

    async def _import(call: ServiceCall) -> dict:
        bundle = call.data.get("data")
        if not bundle:
            path = hass.config.path(EXPORT_FILE)
            bundle = await hass.async_add_executor_job(_read_json, path)
        return await _coordinator().import_bundle(bundle, bool(call.data.get("leerstatus", True)))

    hass.services.async_register(DOMAIN, SERVICE_EXPORT, _export, schema=vol.Schema(
        {vol.Optional("leerstatus", default=True): bool}), supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_IMPORT, _import, schema=vol.Schema(
        {vol.Optional("leerstatus", default=True): bool, vol.Optional("data"): dict}),
        supports_response=SupportsResponse.OPTIONAL)
    await _register_dashboard_strategy(hass)
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v1 -> v2 (integration 2.18): the two fixed flow-rate fields became one list of any length."""
    if entry.version == 1:
        data = dict(entry.data)
        flows = [data.pop(CONF_FLOW_RATE_1, None), data.pop(CONF_FLOW_RATE_2, None)]
        flows = [f for f in flows if f]
        if flows and CONF_FLOW_RATES not in data:
            data[CONF_FLOW_RATES] = flows
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SlimmeConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_save()
    return ok
