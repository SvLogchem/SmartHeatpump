"""The Slimme Warmtepomp integration."""
from __namespace__ import logging  # (optioneel, of import logging)
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# De platforms die jouw integratie laadt
PLATFORMS: list[str] = ["sensor", "number", "climate"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Zet de integratie op vanuit de UI (Config Flow)."""
    hass.data.setdefault(DOMAIN, {})
    
    # Sla de configuratie op in hass.data zodat de platforms (sensor.py, etc.) hierbij kunnen
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Laad alle platforms tegelijk (sensor, number, climate)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Verwijder de integratie netjes als de gebruiker deze wist."""
    # Unload alle platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
