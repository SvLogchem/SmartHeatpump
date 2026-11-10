"""Number platform for Slimme Warmtepomp."""
from homeassistant.components.number import NumberEntity
from .const import DOMAIN

class WarmtepompInstelling(NumberEntity):
    def __init__(self, hass, config_entry, name, entity_id_suffix, default_val, min_val, max_val, step, unit):
        self.hass = hass
        self._attr_name = name
        self.entity_id = f"number.slimme_wp_{entity_id_suffix}"
        self._attr_unique_id = f"{config_entry.entry_id}_{entity_id_suffix}"
        self._attr_native_value = default_val
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

async def async_setup_entry(hass, config_entry, async_add_entities):
    control_mode = config_entry.data.get("control_mode", "retour")
    
    if control_mode == "aanvoer":
        basis_naam = "Basis Aanvoertemperatuur"
        basis_default = 28.0
    else:
        basis_naam = "Basis Retourtemperatuur"
        basis_default = 22.0

    entiteiten = [
        WarmtepompInstelling(hass, config_entry, basis_naam, "basis_temperatuur", basis_default, 15.0, 45.0, 0.1, "°C"),
        WarmtepompInstelling(hass, config_entry, "Stooklijn Helling", "stooklijn", 0.4, 0.1, 1.5, 0.05, ""),
        WarmtepompInstelling(hass, config_entry, "Gewenste Kamertemperatuur Dag", "setpoint_dag", 21.0, 15.0, 25.0, 0.1, "°C"),
        WarmtepompInstelling(hass, config_entry, "Gewenste Kamertemperatuur Nacht", "setpoint_nacht", 20.4, 15.0, 25.0, 0.1, "°C"),
        
        # Tijd- en overige instellingen
        WarmtepompInstelling(hass, config_entry, "Dag Start Uur", "dag_start", 9.0, 0.0, 23.0, 1.0, "uur"),
        WarmtepompInstelling(hass, config_entry, "Dag Eind Uur", "dag_eind", 21.0, 0.0, 23.0, 1.0, "uur"),
        WarmtepompInstelling(hass, config_entry, "Nacht Start Uur", "nacht_start", 23.0, 0.0, 23.0, 1.0, "uur"),
        WarmtepompInstelling(hass, config_entry, "Nacht Eind Uur", "nacht_eind", 7.0, 0.0, 23.0, 1.0, "uur"),
        WarmtepompInstelling(hass, config_entry, "Max Stroomprijs voor Verwarmen", "max_stroomprijs", 0.35, 0.05, 1.00, 0.01, "€/kWh"),
        WarmtepompInstelling(hass, config_entry, "Anticipatie Horizon", "horizon", 4.0, 1.0, 12.0, 1.0, "uur"),
        WarmtepompInstelling(hass, config_entry, "Zon Compensatie (Max)", "zon_factor", 2.0, 0.0, 5.0, 0.1, "°C"),
        WarmtepompInstelling(hass, config_entry, "Minimum Run-Time", "minimum_runtime", 15.0, 5.0, 45.0, 1.0, "min"),
        WarmtepompInstelling(hass, config_entry, "Waakhond Marge", "waakhond_marge", 0.5, 0.1, 2.0, 0.1, "°C"),
        
        # Veiligheid en Pro-instellingen
        WarmtepompInstelling(hass, config_entry, "Maximale Aanvoer/Vloer Temp", "max_flow_temp", 40.0, 30.0, 55.0, 0.5, "°C"),
        WarmtepompInstelling(hass, config_entry, "PV-Overschot Boost", "pv_boost", 1.0, 0.0, 3.0, 0.1, "°C"),
        WarmtepompInstelling(hass, config_entry, "Bivalente Vorst-waarschuwing", "bivalent_temp", -7.0, -15.0, 0.0, 0.5, "°C"),
    ]
    async_add_entities(entiteiten)
