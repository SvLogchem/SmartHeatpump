"""Sensor platform."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature, UnitOfTime

from .entity import SlimmeWPEntity


class SetpointSensor(SlimmeWPEntity, SensorEntity):
    """The water setpoint the controller last wrote (same entity as in v1)."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "setpoint", "Slimme WP Berekend Setpoint", "sensor.slimme_wp_setpoint")

    @property
    def native_value(self):
        return self.coordinator.last_setpoint

    @property
    def extra_state_attributes(self) -> dict:
        d = self.decision
        if d is None:
            return {}
        return {
            "reden": d.reason,
            "actief_programma": d.program,
            "kamer_setpoint": d.room_setpoint,
            "setpoint_ongerond": d.setpoint_raw,
            "sturing_actief": self.coordinator.switches["regeling_actief"],
            "ontdooi_actief": d.defrost,
            "zomermodus_actief": d.summer,
            "dure_stroom_actief": d.expensive,
            **d.diag,
        }


class DecisionSensor(SlimmeWPEntity, SensorEntity):
    """Generic read-out of one value from the latest decision."""

    def __init__(self, coordinator, key, name, getter, unit=None, device_class=None, state_class=None,
                 category=None, icon=None, entity_suffix=None) -> None:
        super().__init__(coordinator, key, name, f"sensor.slimme_wp_{entity_suffix or key}")
        self._getter = getter
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = category
        if icon:
            self._attr_icon = icon

    @property
    def native_value(self):
        d = self.decision
        return None if d is None else self._getter(d)


def _diag(name):
    return lambda d: d.diag.get(name)


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    M, D = SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC
    TEMP, KWH = UnitOfTemperature.CELSIUS, UnitOfEnergy.KILO_WATT_HOUR
    entities = [
        SetpointSensor(c),
        # --- v1 entities (same unique ids)
        DecisionSensor(c, "thermisch_vermogen", "Slimme WP Thermisch Vermogen", lambda d: d.thermal_kw,
                       UnitOfPower.KILO_WATT, SensorDeviceClass.POWER, M, entity_suffix="thermisch_vermogen"),
        DecisionSensor(c, "cop", "Slimme WP Huidige COP", lambda d: d.cop, None, None, M, entity_suffix="cop"),
        DecisionSensor(c, "elektrisch_vermogen", "Slimme WP Elektrisch Verbruik", lambda d: d.electric_w,
                       UnitOfPower.WATT, SensorDeviceClass.POWER, M, entity_suffix="elektrisch_vermogen"),
        DecisionSensor(c, "voorspelde_buiten_temp", "Slimme WP Verwachte Buitentemp",
                       _diag("verwacht_buiten"), TEMP, SensorDeviceClass.TEMPERATURE, M, D,
                       entity_suffix="voorspelde_buiten_temp"),
        DecisionSensor(c, "voorspelde_afkoeling", "Slimme WP Voorspelde Afkoeling",
                       lambda d: d.diag.get("voorspeld_kamer_min"), TEMP, SensorDeviceClass.TEMPERATURE, M, D,
                       entity_suffix="voorspelde_afkoeling"),
        DecisionSensor(c, "zon_reductie", "Slimme WP Verwachte Zon Reductie", _diag("zon_reductie_k"), TEMP,
                       SensorDeviceClass.TEMPERATURE, M, D, entity_suffix="zon_reductie"),
        # --- new in v2
        DecisionSensor(c, "reden", "Slimme WP Reden", lambda d: d.reason, category=D, icon="mdi:comment-text",
                       entity_suffix="reden"),
        DecisionSensor(c, "plan", "Slimme WP Plan", lambda d: d.diag.get("plan_reden") or d.diag.get("plan"),
                       category=D, icon="mdi:calendar-clock", entity_suffix="plan"),
        DecisionSensor(c, "modelvertrouwen", "Slimme WP Modelvertrouwen",
                       lambda d: round(100 * d.diag.get("model_vertrouwen", 0)), PERCENTAGE, None, M, D,
                       "mdi:brain", "modelvertrouwen"),
        DecisionSensor(c, "tijdconstante_huis", "Slimme WP Geleerde Afkoeltijd Huis", _diag("huis_tijdconstante_u"),
                       UnitOfTime.HOURS, None, M, D, "mdi:home-thermometer", "tijdconstante_huis"),
        DecisionSensor(c, "tijdconstante_vloer", "Slimme WP Geleerde Afkoeltijd Vloer",
                       _diag("vloer_tijdconstante_u"), UnitOfTime.HOURS, None, M, D, "mdi:radiator",
                       "tijdconstante_vloer"),
        DecisionSensor(c, "vloer_geschat", "Slimme WP Vloertemperatuur (geschat)", _diag("vloer_geschat"), TEMP,
                       SensorDeviceClass.TEMPERATURE, M, D, entity_suffix="vloer_geschat"),
        DecisionSensor(c, "vloer_gemeten", "Slimme WP Vloertemperatuur (gemeten)", _diag("vloer_gemeten"), TEMP,
                       SensorDeviceClass.TEMPERATURE, M, D, entity_suffix="vloer_gemeten"),
        DecisionSensor(c, "vloer_bron", "Slimme WP Vloer Bron", _diag("vloer_bron"), category=D,
                       icon="mdi:thermometer-check", entity_suffix="vloer_bron"),
        DecisionSensor(c, "kamer_na_bedtijd", "Slimme WP Voorspelde Kamer 1u Na Bedtijd",
                       _diag("voorspeld_kamer_na_bedtijd"), TEMP, SensorDeviceClass.TEMPERATURE, M, D,
                       entity_suffix="kamer_na_bedtijd"),
        DecisionSensor(c, "avond_bias", "Slimme WP Avond Correctie", _diag("avond_bias_k"), TEMP, None, M, D,
                       "mdi:weather-sunset-down", "avond_bias"),
        DecisionSensor(c, "energie_thermisch", "Slimme WP Thermische Energie", lambda d: d.energy_thermal_kwh, KWH,
                     SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, entity_suffix="energie_thermisch"),
        DecisionSensor(c, "energie_elektrisch", "Slimme WP Elektrische Energie", lambda d: d.energy_electric_kwh,
                     KWH, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING,
                     entity_suffix="energie_elektrisch"),
        DecisionSensor(c, "cop_seizoen", "Slimme WP Gemiddelde COP",
                       lambda d: round(d.energy_thermal_kwh / d.energy_electric_kwh, 2)
                       if d.energy_electric_kwh > 1.0 else None, None, None, M, entity_suffix="cop_seizoen"),
    ]
    entities += [
        DecisionSensor(c, "cop_vandaag", "Slimme WP COP Vandaag", lambda d: d.cop_today, None, None, M,
                       icon="mdi:chart-line", entity_suffix="cop_vandaag"),
        DecisionSensor(c, "cop_gisteren", "Slimme WP COP Gisteren", lambda d: d.cop_yesterday, None, None, None,
                       icon="mdi:chart-line", entity_suffix="cop_gisteren"),
        DecisionSensor(c, "starts_vandaag", "Slimme WP Compressorstarts Vandaag", lambda d: d.starts_today, None,
                       None, SensorStateClass.TOTAL_INCREASING, icon="mdi:counter", entity_suffix="starts_vandaag"),
        DecisionSensor(c, "starts_gisteren", "Slimme WP Compressorstarts Gisteren", lambda d: d.starts_yesterday,
                       None, None, None, icon="mdi:counter", entity_suffix="starts_gisteren"),
        DecisionSensor(c, "ijsvorming", "Slimme WP Ijsvorming", lambda d: d.ice_level, None, None, None,
                       icon="mdi:snowflake-alert", entity_suffix="ijsvorming"),
        DecisionSensor(c, "ontdooi_piek", "Slimme WP Ontdooipiek Coil (Laatste Ontdooi)", _diag("ontdooi_piek"), TEMP,
                       SensorDeviceClass.TEMPERATURE, None, D, icon="mdi:snowflake-thermometer",
                       entity_suffix="ontdooi_piek"),
        DecisionSensor(c, "volgende_ontdooi", "Slimme WP Volgende Ontdooicyclus (Verwacht)",
                       lambda d: d.next_defrost_min, UnitOfTime.MINUTES, None, None, D,
                       icon="mdi:snowflake-melt", entity_suffix="volgende_ontdooi"),
    ]
    if c.has_dhw:
        entities.append(DecisionSensor(c, "tapwater_modus", "Slimme WP Tapwater Modus", _diag("tapwater_modus"),
                                       category=D, icon="mdi:water-boiler", entity_suffix="tapwater_modus"))
    async_add_entities(entities)
