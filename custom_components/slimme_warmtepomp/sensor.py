"""Sensor platform."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import MATCH_ALL, PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature, UnitOfTime

from .entity import SlimmeWPEntity


class SetpointSensor(SlimmeWPEntity, SensorEntity):
    """The water setpoint the controller last wrote (same entity as in v1)."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    # ~4 KB of attributes change every cycle: show them live, but keep them out of the recorder database
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "setpoint", "Slimme WP Berekend Setpoint", "sensor.slimme_wp_setpoint")

    @property
    def native_value(self):
        return self.coordinator.last_setpoint

    @property
    def extra_state_attributes(self) -> dict:
        d = self.decision
        inputs = {"invoer_sensoren": self.coordinator.input_entities()}      # read by the generated dashboard
        if d is None:
            return inputs
        return {
            **inputs,
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


class WeekReportSensor(SlimmeWPEntity, SensorEntity):
    """kWh of the last 7 days as state, the readable weekly report in the attribute ``rapport``."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:file-chart-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "weekrapport", "Slimme WP Weekrapport", "sensor.slimme_wp_weekrapport")

    @property
    def native_value(self):
        rep = self.coordinator.week_data
        return round(rep["kwh"], 1) if rep else None

    @property
    def extra_state_attributes(self) -> dict:
        rep = self.coordinator.week_data or {}
        return {"rapport": self.coordinator.week_report, "dagen": rep.get("days"),
                "kosten": round(rep["cost"], 2) if rep else None,
                "comfort_percentage": round(rep["comfort"] * 100) if rep.get("comfort") is not None else None}


def _diag(name):
    return lambda d: d.diag.get(name)


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    M, D = SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC
    TEMP, KWH = UnitOfTemperature.CELSIUS, UnitOfEnergy.KILO_WATT_HOUR
    entities = [
        SetpointSensor(c),
        WeekReportSensor(c),
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
        # a correction and a shortfall are temperature differences (K), not temperatures: with the temperature class
        # Home Assistant would convert them with an offset for a user who shows degrees Fahrenheit
        DecisionSensor(c, "stooklijn_correctie", "Slimme WP Stooklijn Correctie (Geleerd)", _diag("stooklijn_correctie"),
                       "K", None, None, D, icon="mdi:chart-bell-curve-cumulative", entity_suffix="stooklijn_correctie"),
        DecisionSensor(c, "vloer_tekort", "Slimme WP Vloer Warmtetekort", _diag("vloer_tekort"), "K",
                       None, None, D, icon="mdi:heating-coil", entity_suffix="vloer_tekort"),
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
        DecisionSensor(c, "cop_gisteren", "Slimme WP COP Gisteren", lambda d: d.cop_yesterday, None, None, M,
                       icon="mdi:chart-line", entity_suffix="cop_gisteren"),
        DecisionSensor(c, "starts_vandaag", "Slimme WP Compressorstarts Vandaag", lambda d: d.starts_today, None,
                       None, SensorStateClass.TOTAL_INCREASING, icon="mdi:counter", entity_suffix="starts_vandaag"),
        DecisionSensor(c, "starts_gisteren", "Slimme WP Compressorstarts Gisteren", lambda d: d.starts_yesterday,
                       None, None, M, icon="mdi:counter", entity_suffix="starts_gisteren"),
        DecisionSensor(c, "graaddagen_dag", "Slimme WP Graaddagen Vandaag", _diag("graaddagen_dag"), "°Cd", None, M,
                       icon="mdi:thermometer-minus", entity_suffix="graaddagen_dag"),
        DecisionSensor(c, "graaddagen_week", "Slimme WP Graaddagen Week", _diag("graaddagen_week"), "°Cd", None, M,
                       icon="mdi:thermometer-minus", entity_suffix="graaddagen_week"),
        DecisionSensor(c, "graaddagen_maand", "Slimme WP Graaddagen Maand", _diag("graaddagen_maand"), "°Cd", None, M,
                       icon="mdi:thermometer-minus", entity_suffix="graaddagen_maand"),
        DecisionSensor(c, "kwh_per_graaddag", "Slimme WP kWh Per Graaddag", _diag("kwh_per_graaddag_dag"), "kWh/°Cd",
                       None, M, icon="mdi:chart-timeline-variant", entity_suffix="kwh_per_graaddag"),
        DecisionSensor(c, "kwh_per_graaddag_gisteren", "Slimme WP kWh Per Graaddag Gisteren",
                       _diag("kwh_per_graaddag_gisteren"), "kWh/°Cd", None, M, icon="mdi:chart-timeline-variant",
                       entity_suffix="kwh_per_graaddag_gisteren"),
        DecisionSensor(c, "kwh_per_graaddag_week", "Slimme WP kWh Per Graaddag Week", _diag("kwh_per_graaddag_week"),
                       "kWh/°Cd", None, M, icon="mdi:chart-timeline-variant", entity_suffix="kwh_per_graaddag_week"),
        DecisionSensor(c, "energie_dag", "Slimme WP Verbruik Vandaag", _diag("energie_dag"), UnitOfEnergy.KILO_WATT_HOUR,
                       None, M, icon="mdi:flash", entity_suffix="energie_dag"),
        DecisionSensor(c, "energie_week", "Slimme WP Verbruik Week", _diag("energie_week"), UnitOfEnergy.KILO_WATT_HOUR,
                       None, M, icon="mdi:flash", entity_suffix="energie_week"),
        DecisionSensor(c, "energie_maand", "Slimme WP Verbruik Maand", _diag("energie_maand"), UnitOfEnergy.KILO_WATT_HOUR,
                       None, M, icon="mdi:flash", entity_suffix="energie_maand"),
        DecisionSensor(c, "thermisch_dag", "Slimme WP Thermisch Vandaag", _diag("thermisch_dag"),
                       UnitOfEnergy.KILO_WATT_HOUR, None, M, icon="mdi:fire", entity_suffix="thermisch_dag"),
        DecisionSensor(c, "thermisch_week", "Slimme WP Thermisch Week", _diag("thermisch_week"),
                       UnitOfEnergy.KILO_WATT_HOUR, None, M, icon="mdi:fire", entity_suffix="thermisch_week"),
        DecisionSensor(c, "thermisch_maand", "Slimme WP Thermisch Maand", _diag("thermisch_maand"),
                       UnitOfEnergy.KILO_WATT_HOUR, None, M, icon="mdi:fire", entity_suffix="thermisch_maand"),
        DecisionSensor(c, "kosten_dag", "Slimme WP Kosten Vandaag", _diag("kosten_dag"), "€", None, M,
                       icon="mdi:cash", entity_suffix="kosten_dag"),
        DecisionSensor(c, "kosten_week", "Slimme WP Kosten Week", _diag("kosten_week"), "€", None, M,
                       icon="mdi:cash", entity_suffix="kosten_week"),
        DecisionSensor(c, "kosten_maand", "Slimme WP Kosten Maand", _diag("kosten_maand"), "€", None, M,
                       icon="mdi:cash-multiple", entity_suffix="kosten_maand"),
        DecisionSensor(c, "kosten_jaar", "Slimme WP Kosten Jaar", _diag("kosten_jaar"), "€", None, M,
                       icon="mdi:cash-multiple", entity_suffix="kosten_jaar"),
        DecisionSensor(c, "draaitijd_vandaag", "Slimme WP Draaitijd Vandaag", _diag("draaitijd_vandaag"),
                       UnitOfTime.MINUTES, None, M, icon="mdi:timer-play", entity_suffix="draaitijd_vandaag"),
        DecisionSensor(c, "draaitijd_per_start", "Slimme WP Gemiddelde Draaitijd Per Start",
                       _diag("draaitijd_per_start"), UnitOfTime.MINUTES, None, M, icon="mdi:timer-outline",
                       entity_suffix="draaitijd_per_start"),
        DecisionSensor(c, "ontdooien_vandaag", "Slimme WP Ontdooicycli Vandaag", _diag("ontdooien_vandaag"), None,
                       None, M, icon="mdi:snowflake-melt", entity_suffix="ontdooien_vandaag"),
        DecisionSensor(c, "ontdooien_7_dagen", "Slimme WP Ontdooicycli 7 Dagen", _diag("ontdooien_7_dagen"), None,
                       None, M, icon="mdi:snowflake-melt", entity_suffix="ontdooien_7_dagen"),
        DecisionSensor(c, "kwh_graaddag_regeling", "Slimme WP kWh Per Graaddag (Regeling Aan)",
                       _diag("kwh_per_graaddag_regeling"), "kWh/°Cd", None, M, icon="mdi:brain",
                       entity_suffix="kwh_graaddag_regeling"),
        DecisionSensor(c, "kwh_graaddag_schaduw", "Slimme WP kWh Per Graaddag (Regeling Uit)",
                       _diag("kwh_per_graaddag_schaduw"), "kWh/°Cd", None, M, icon="mdi:brain",
                       entity_suffix="kwh_graaddag_schaduw"),
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
