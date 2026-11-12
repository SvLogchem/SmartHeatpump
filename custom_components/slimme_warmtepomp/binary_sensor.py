"""Binary sensor platform."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import SlimmeWPEntity

# key (= unique_id suffix), entity_id suffix, name, decision field, device class
SPECS = [
    ("defrost", "defrost", "Slimme WP Ontdooi Actief", "defrost", BinarySensorDeviceClass.HEAT),
    ("dure_stroom", "dure_stroom", "Slimme WP Blokkering Dure Stroom", "expensive", None),
    ("zomermodus", "zomermodus", "Slimme WP Zomermodus (Stookgrens)", "summer", None),
    ("voorverwarmen", "voorverwarmen", "Slimme WP Voorverwarmen Bezig", "preheating", None),
    ("uitlopen", "uitlopen", "Slimme WP Uitlopen (Niet Verwarmen)", "coasting", None),
    ("bivalent", "bivalent", "Slimme WP Onder Bivalent Punt", "bivalent", None),
    ("zacht_draaien", "zacht_draaien", "Slimme WP Zacht Draaien (Laag Vermogen)", "soft", None),
    ("sensor_probleem", "sensor_probleem", "Slimme WP Sensorprobleem", "sensor_problem",
     BinarySensorDeviceClass.PROBLEM),
]


class SlimmeWarmtepompBinary(SlimmeWPEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key, suffix, name, field, device_class) -> None:
        super().__init__(coordinator, key, name, f"binary_sensor.slimme_wp_{suffix}")
        self._field = field
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        d = self.decision
        return None if d is None else bool(getattr(d, self._field))


OPTIONAL = [
    ("window", "raam_open", "raam_open", "Slimme WP Raam Of Deur Open", "window_open", BinarySensorDeviceClass.WINDOW),
    ("away", "afwezig", "afwezig", "Slimme WP Afwezig", "away", None),
    ("grid", "netlimiet", "netlimiet", "Slimme WP Netlimiet Actief", "grid_limited", None),
]


class SlimmeWarmtepompDhwBusy(SlimmeWarmtepompBinary):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "dhw_bezig", "dhw_bezig", "Slimme WP Tapwater Bezig", "dhw_active", None)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [SlimmeWarmtepompBinary(coordinator, *spec) for spec in SPECS]
    if coordinator.has_dhw:
        entities.append(SlimmeWarmtepompDhwBusy(coordinator))
    entities += [SlimmeWarmtepompBinary(coordinator, *spec[1:]) for spec in OPTIONAL
                 if coordinator.group_enabled(spec[0])]
    async_add_entities(entities)
