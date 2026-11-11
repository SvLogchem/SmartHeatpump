"""Number platform for Slimme Warmtepomp config parameters."""
from homeassistant.components.number import RestoreNumber, NumberMode
from homeassistant.const import EntityCategory
from .const import DOMAIN

CONFIG_NUMBERS = {
    "slimme_wp_basis_temperatuur": ("Stooklijn: Basis Temperatuur", 15, 35, 0.5, 22.0, "°C", "mdi:thermometer"),
    "slimme_wp_setpoint_offset": ("Stooklijn: Setpoint Offset", -5, 5, 0.5, 0.0, "°C", "mdi:thermometer-plus"),
    "slimme_wp_stooklijn": ("Stooklijn: Helling", 0.1, 1.0, 0.1, 0.4, "", "mdi:chart-line"),
    
    "slimme_wp_setpoint_dag": ("Klokprogramma: Setpoint Dag", 15, 25, 0.1, 21.0, "°C", "mdi:sun-compass"),
    "slimme_wp_setpoint_nacht": ("Klokprogramma: Setpoint Nacht", 15, 25, 0.1, 20.4, "°C", "mdi:weather-night"),
    "slimme_wp_dag_start": ("Klokprogramma: Starttijd Dag", 0, 23, 1, 9.0, "h", "mdi:clock-start"),
    "slimme_wp_dag_eind": ("Klokprogramma: Eindtijd Dag", 0, 23, 1, 21.0, "h", "mdi:clock-end"),
    "slimme_wp_nacht_start": ("Klokprogramma: Starttijd Nacht", 0, 23, 1, 23.0, "h", "mdi:clock-start"),
    "slimme_wp_nacht_eind": ("Klokprogramma: Eindtijd Nacht", 0, 23, 1, 7.0, "h", "mdi:clock-end"),
    
    "slimme_wp_horizon": ("Anticipatie: Weersverwachting Horizon", 1, 12, 1, 4.0, "h", "mdi:weather-partly-cloudy"),
    "slimme_wp_zon_factor": ("Anticipatie: Zon Compensatie Factor", 0.0, 5.0, 0.1, 2.0, "", "mdi:white-balance-sunny"),
    "slimme_wp_bivalent_temp": ("Anticipatie: Bivalente Temperatuur", -20, 10, 1, -7.0, "°C", "mdi:snowflake"),
    
    "slimme_wp_minimum_runtime": ("Systeem: Minimale Draaitijd", 0, 60, 5, 15.0, "min", "mdi:timer"),
    "slimme_wp_waakhond_marge": ("Systeem: Waakhond Marge", 0.1, 2.0, 0.1, 0.5, "°C", "mdi:shield-check"),
    "slimme_wp_max_flow_temp": ("Systeem: Max Aanvoertemperatuur", 20, 60, 1, 40.0, "°C", "mdi:thermometer-high"),
    "slimme_wp_stookgrens": ("Systeem: Zomermodus Stookgrens", 10, 25, 0.5, 18.0, "°C", "mdi:sun-thermometer"),
    
    "slimme_wp_max_stroomprijs": ("Kosten: Max Stroomprijs", 0.0, 1.0, 0.01, 0.35, "€/kWh", "mdi:cash"),
    "slimme_wp_pv_boost": ("Kosten: Zonnepanelen Boost", 0.0, 5.0, 0.5, 1.0, "°C", "mdi:solar-power"),
}

class SlimmeWarmtepompConfigNumber(RestoreNumber):
    def __init__(self, hass, config_entry, key, name, min_v, max_v, step, default, unit, icon):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_name = name
        self.entity_id = f"number.{key}"
        self._attr_unique_id = f"{config_entry.entry_id}_{key}"
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_native_step = step
        self._attr_native_value = default
        self._attr_mode = NumberMode.BOX
        self._attr_entity_category = EntityCategory.CONFIG
        
        if unit: self._attr_native_unit_of_measurement = unit
        if icon: self._attr_icon = icon

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": "Slimme Warmtepomp",
            "manufacturer": "Custom HEMS",
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_number_data()
        if last_state is not None and last_state.native_value is not None:
            self._attr_native_value = last_state.native_value

    async def async_set_native_value(self, value: float):
        self._attr_native_value = value
        self.async_write_ha_state()

async def async_setup_entry(hass, config_entry, async_add_entities):
    entities = []
    for key, (name, min_v, max_v, step, default, unit, icon) in CONFIG_NUMBERS.items():
        entities.append(SlimmeWarmtepompConfigNumber(hass, config_entry, key, name, min_v, max_v, step, default, unit, icon))
    async_add_entities(entities)
