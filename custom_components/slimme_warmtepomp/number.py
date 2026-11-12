"""Number platform for Slimme Warmtepomp."""
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import EntityCategory
from .const import DOMAIN

NUMBERS = [
    ("basis_temperatuur", "Slimme WP Basis Temperatuur", 15.0, 35.0, 0.5, "°C"),
    ("setpoint_offset", "Slimme WP Setpoint Offset", -10.0, 10.0, 0.5, "°C"),
    ("stooklijn", "Slimme WP Stooklijn Helling", 0.1, 1.5, 0.05, ""),
    ("horizon", "Slimme WP Weersverwachting Horizon", 1.0, 12.0, 1.0, "h"),
    ("zon_factor", "Slimme WP Zon Compensatie Factor", 0.0, 5.0, 0.1, ""),
    ("bivalent_temp", "Slimme WP Bivalente Temperatuur", -10.0, 10.0, 0.5, "°C"),
    ("minimum_runtime", "Slimme WP Minimale Draaitijd", 5.0, 60.0, 5.0, "min"),
    ("waakhond_marge", "Slimme WP Waakhond Marge", 0.1, 2.0, 0.1, "°C"),
    ("max_flow_temp", "Slimme WP Max Aanvoertemperatuur", 25.0, 60.0, 1.0, "°C"),
    ("stookgrens", "Slimme WP Zomermodus Stookgrens", 10.0, 25.0, 0.5, "°C"),
    ("max_stroomprijs", "Slimme WP Max Stroomprijs", 0.1, 1.0, 0.01, "€"),
    ("pv_boost", "Slimme WP Zonnepanelen Boost", 0.0, 5.0, 0.5, "°C"),
    ("setpoint_dag", "Slimme WP Setpoint Dag", 15.0, 25.0, 0.1, "°C"),
    ("setpoint_nacht", "Slimme WP Setpoint Nacht", 15.0, 25.0, 0.1, "°C"),
    ("dag_start", "Slimme WP Starttijd Dag", 0.0, 23.0, 1.0, "h"),
    ("dag_eind", "Slimme WP Eindtijd Dag", 0.0, 23.0, 1.0, "h"),
    ("nacht_start", "Slimme WP Starttijd Nacht", 0.0, 23.0, 1.0, "h"),
    ("nacht_eind", "Slimme WP Eindtijd Nacht", 0.0, 23.0, 1.0, "h"),
]

class SlimmeWarmtepompNumber(NumberEntity, RestoreEntity):
    def __init__(self, config_entry, key, name, min_val, max_val, step, unit):
        self._entry_id = config_entry.entry_id
        self._key = key
        self._attr_name = name
        self.entity_id = f"number.slimme_wp_{key}"
        self._attr_unique_id = f"{self._entry_id}_{key}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit if unit else None
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_native_value = min_val

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry_id)}, "name": "Slimme Warmtepomp", "manufacturer": "Custom HEMS"}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ["unknown", "unavailable"]:
            try: self._attr_native_value = float(last_state.state)
            except ValueError: pass

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

async def async_setup_entry(hass, config_entry, async_add_entities):
    entities = [SlimmeWarmtepompNumber(config_entry, *num) for num in NUMBERS]
    async_add_entities(entities)
